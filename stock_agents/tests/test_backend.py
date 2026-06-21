"""Tests for the Claude Code backend selector and tool bridging (offline)."""

from __future__ import annotations

import json

from stock_agents.agents import base, claude_code_backend
from stock_agents.tools.handlers import ToolContext


def test_cc_model_alias():
    assert base._cc_model_alias("claude-opus-4-7") == "opus"
    assert base._cc_model_alias("claude-sonnet-4-6") == "sonnet"
    assert base._cc_model_alias("claude-haiku-4-5-20251001") == "haiku"
    assert base._cc_model_alias("something-else") == "sonnet"


def test_is_web_search_detection():
    assert claude_code_backend._is_web_search({"type": "web_search_20250305", "name": "web_search"})
    assert not claude_code_backend._is_web_search({"name": "get_income_statement"})


def test_subprocess_env_strips_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-stripped")
    monkeypatch.setenv("FMP_API_KEY", "keep-me")
    env = claude_code_backend._subprocess_env()
    assert "ANTHROPIC_API_KEY" not in env  # forces subscription auth, not API billing
    assert env.get("FMP_API_KEY") == "keep-me"


def test_build_sdk_tools_bridges_handlers_and_skips_web_search():
    audit: list[dict] = []
    tool_defs = [
        {"name": "get_company_profile", "description": "d", "input_schema": {"type": "object"}},
        {"type": "web_search_20250305", "name": "web_search"},
    ]
    handlers = {"get_company_profile": lambda inp, ctx: json.dumps({"ok": True})}
    sdk_tools = claude_code_backend._build_sdk_tools(
        tool_defs, handlers, ToolContext(), audit, "rid", "test", "AAPL"
    )
    # web_search has no handler -> not turned into an MCP tool; only the profile tool is.
    assert len(sdk_tools) == 1
