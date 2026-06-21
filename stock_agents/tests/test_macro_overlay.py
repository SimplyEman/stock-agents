"""Macro/Sector Overlay agent + backtest web-search gating (offline)."""

from __future__ import annotations

from stock_agents.agents import base, macro_overlay
from stock_agents.models.analysis import MacroContext
from stock_agents.tools.handlers import ToolContext
from tests.conftest import fake_anthropic_returning

_VALID = MacroContext(
    theme="AI infrastructure",
    sectors_covered=["Semiconductors"],
    cycle_position="Mid capex cycle.",
    tailwinds=["hyperscaler capex"],
    headwinds=["concentration"],
    regime_winners_profile="cash-generative incumbents",
    regime_losers_profile="negative-FCF names",
    sources=["https://example.com"],
).model_dump_json()


def test_macro_agent_returns_valid_context(monkeypatch, tmp_path):
    monkeypatch.setattr(base.settings, "audit_log_dir", tmp_path)
    monkeypatch.setattr(base, "Anthropic", fake_anthropic_returning(_VALID))
    res = macro_overlay.run("AI infrastructure")
    assert isinstance(res.output, MacroContext)
    assert "Semiconductors" in res.output.sectors_covered


def test_macro_drops_web_search_in_backtest(monkeypatch, tmp_path):
    monkeypatch.setattr(base.settings, "audit_log_dir", tmp_path)
    monkeypatch.setattr(base, "Anthropic", fake_anthropic_returning(_VALID))

    captured = {}
    orig_init = base.AgentRunner.__init__

    def spy_init(self, model, tools, handlers, **kw):
        captured["tool_names"] = [t.get("name") for t in tools]
        orig_init(self, model, tools, handlers, **kw)

    monkeypatch.setattr(base.AgentRunner, "__init__", spy_init)

    # Live mode: web search present.
    macro_overlay.run("AI infrastructure")
    assert "web_search" in captured["tool_names"]

    # Backtest mode: web search dropped.
    macro_overlay.run("AI infrastructure", ctx=ToolContext(as_of="2018-01-01", allow_web=False))
    assert "web_search" not in captured["tool_names"]
