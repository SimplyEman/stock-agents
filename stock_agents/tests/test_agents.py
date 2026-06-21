"""AgentRunner tests with a fully mocked Anthropic client.

These cover the parts most likely to break: the tool-use loop, JSON extraction,
schema validation, the one-shot correction retry, cost accounting, and the
audit log. No network, no real model.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from stock_agents.agents import base

# --- fake Anthropic primitives ---------------------------------------------


class _Usage:
    def __init__(self, i=100, o=50, cw=0, cr=0):
        self.input_tokens = i
        self.output_tokens = o
        self.cache_creation_input_tokens = cw
        self.cache_read_input_tokens = cr


class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _ToolUse:
    type = "tool_use"

    def __init__(self, name, inp, id="tu_1"):
        self.name = name
        self.input = inp
        self.id = id


class _Resp:
    def __init__(self, content, stop_reason, usage=None):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage or _Usage()


class _Messages:
    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return self._script.pop(0)


class _FakeClient:
    def __init__(self, script):
        self.messages = _Messages(script)


class Demo(BaseModel):
    ticker: str
    score: int


def _runner(script, handlers=None, tools=None):
    return base.AgentRunner(
        model="claude-sonnet-4-6",
        tools=tools or [],
        handlers=handlers or {},
        agent_name="test",
        client=_FakeClient(script),
    )


# --- tests -------------------------------------------------------------------


def test_happy_path_with_tool_call(tmp_path, monkeypatch):
    monkeypatch.setattr(base.settings, "audit_log_dir", tmp_path)
    calls = []

    def handler(inp, ctx):
        calls.append(inp)
        return json.dumps({"ok": True})

    script = [
        _Resp([_ToolUse("get_thing", {"ticker": "NVDA"})], "tool_use"),
        _Resp([_Text(json.dumps({"ticker": "NVDA", "score": 9}))], "end_turn"),
    ]
    runner = _runner(script, handlers={"get_thing": handler})
    result = runner.run("sys", "analyze NVDA", Demo, ticker="NVDA")

    assert result.output == Demo(ticker="NVDA", score=9)
    assert result.error is None
    assert calls == [{"ticker": "NVDA"}]
    assert result.cost_usd > 0
    # audit log written
    assert any(e.get("tool") == "get_thing" for e in result.audit_log)
    assert (tmp_path / "tool_calls.jsonl").exists()


def test_bad_json_then_correction(tmp_path, monkeypatch):
    monkeypatch.setattr(base.settings, "audit_log_dir", tmp_path)
    script = [
        _Resp([_Text("here you go: not json at all")], "end_turn"),
        _Resp([_Text(json.dumps({"ticker": "AAPL", "score": 7}))], "end_turn"),
    ]
    runner = _runner(script)
    result = runner.run("sys", "go", Demo)
    assert result.output == Demo(ticker="AAPL", score=7)
    assert runner.client.messages.calls == 2


def test_validation_failure_after_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(base.settings, "audit_log_dir", tmp_path)
    script = [
        _Resp([_Text("garbage")], "end_turn"),
        _Resp([_Text('{"ticker": "X"}')], "end_turn"),  # missing required `score`
    ]
    runner = _runner(script)
    result = runner.run("sys", "go", Demo)
    assert result.output is None
    assert result.error and "validation failed" in result.error


def test_json_extraction_from_fenced_block(tmp_path, monkeypatch):
    monkeypatch.setattr(base.settings, "audit_log_dir", tmp_path)
    fenced = "```json\n{\"ticker\": \"MSFT\", \"score\": 8}\n```"
    script = [_Resp([_Text(fenced)], "end_turn")]
    result = _runner(script).run("sys", "go", Demo)
    assert result.output == Demo(ticker="MSFT", score=8)


def test_pause_turn_is_continued(tmp_path, monkeypatch):
    monkeypatch.setattr(base.settings, "audit_log_dir", tmp_path)
    script = [
        _Resp([_Text("searching...")], "pause_turn"),
        _Resp([_Text(json.dumps({"ticker": "GOOG", "score": 6}))], "end_turn"),
    ]
    result = _runner(script).run("sys", "go", Demo)
    assert result.output == Demo(ticker="GOOG", score=6)


def test_tool_handler_error_is_surfaced_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(base.settings, "audit_log_dir", tmp_path)

    def boom(inp, ctx):
        raise RuntimeError("api down")

    script = [
        _Resp([_ToolUse("boom", {})], "tool_use"),
        _Resp([_Text(json.dumps({"ticker": "T", "score": 1}))], "end_turn"),
    ]
    runner = _runner(script, handlers={"boom": boom})
    result = runner.run("sys", "go", Demo)
    assert result.output == Demo(ticker="T", score=1)
    assert any(e.get("error") == "api down" for e in result.audit_log)


def test_cost_accounting():
    u = base.Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    # sonnet: $3 in + $15 out per 1M
    assert u.cost("claude-sonnet-4-6") == pytest.approx(18.0)


def test_extract_json_helper():
    assert base._extract_json('{"a": 1}') == '{"a": 1}'
    assert base._extract_json('prefix {"a": 1} suffix') == '{"a": 1}'
    with pytest.raises(ValueError):
        base._extract_json("no json here")
