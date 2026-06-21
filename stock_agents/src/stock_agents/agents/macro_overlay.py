"""Macro/Sector Overlay agent (v2 Phase 2).

Places the theme in cycle/regime context so the synthesizer doesn't read every
company in a vacuum. Runs ONCE per `analyze` invocation, before screening; its
output is passed to the synthesizer for every candidate in that run.
"""

from __future__ import annotations

from stock_agents.agents.base import AgentResult, AgentRunner
from stock_agents.config import AGENT_MODELS
from stock_agents.models.analysis import MacroContext
from stock_agents.tools import definitions as d
from stock_agents.tools import get_handlers
from stock_agents.tools.handlers import ToolContext

NAME = "macro_overlay"

TOOLS = [d.GET_COMPANY_PROFILE, d.WEB_SEARCH]

SYSTEM = """You are a macro/sector strategist. Given an investment theme, place it in current cycle and regime context. Your output is read by the portfolio manager for every candidate in this run, so be specific and current — not a textbook summary.

Process:
1. Identify the dominant sector(s) the theme touches.
2. Identify the relevant cycle for those sectors: interest rates (financials, long-duration growth), capex cycle (semis, energy, industrials), patent cliff (pharma), regulatory regime (defense, healthcare, big tech).
3. Find the current placement in that cycle from public data (Fed path, hyperscaler/industrial capex guidance, regulatory calendar, commodity cycle). Use web_search when available to ground this in the present, not your training cutoff.
4. Identify 2-3 specific tailwinds and 2-3 specific headwinds for this theme in the regime right now.
5. Characterize which company TYPES in this theme benefit and which suffer under the current regime. Be concrete, e.g. "in a higher-for-longer rate regime, negative-FCF software names dependent on cheap capital are penalized more than capital-light cash-generative incumbents with pricing power."

Cite sources for any current-state claims. If web_search is unavailable (historical/backtest mode), say so in cycle_position and reason from durable structural features rather than inventing current data points.

Output: valid JSON conforming to MacroContext."""


def run(theme: str, *, ctx: ToolContext | None = None) -> AgentResult:
    # In point-in-time / backtest mode there is no reliable historical web; drop it.
    tools = TOOLS
    if ctx and ctx.as_of:
        tools = [t for t in TOOLS if t.get("name") != "web_search"]
    runner = AgentRunner(
        model=AGENT_MODELS[NAME],
        tools=tools,
        handlers=get_handlers([t["name"] for t in tools]),
        agent_name=NAME,
    )
    return runner.run(
        system=SYSTEM,
        user_message=(
            f"Provide current cycle/regime context for the investment theme: {theme!r}. "
            "Return a MacroContext."
        ),
        output_schema=MacroContext,
        ctx=ctx,
    )
