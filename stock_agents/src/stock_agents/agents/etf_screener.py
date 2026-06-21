"""ETF screener agent — turns a theme into a focused candidate list."""

from __future__ import annotations

from stock_agents.agents.base import AgentResult, AgentRunner
from stock_agents.config import AGENT_MODELS
from stock_agents.models.company import CandidateList
from stock_agents.tools import definitions as d
from stock_agents.tools import get_handlers
from stock_agents.tools.handlers import ToolContext

NAME = "etf_screener"

TOOLS = [d.SEARCH_THEMATIC_ETFS, d.GET_ETF_HOLDINGS, d.GET_COMPANY_PROFILE]

SYSTEM = """You are an equity research analyst specializing in thematic ETF screening. Your job is to take a theme or sector and produce a focused list of stocks worth deeper analysis.

Process:
1. Identify 5-10 ETFs matching the theme. Include both mainstream (e.g., SMH for semis) and specialist (e.g., BOTZ for robotics) options. Use search_thematic_etfs to find candidates.
2. Retrieve top 25 holdings of each.
3. Score each stock by: cumulative weighting across ETFs, number of ETF appearances, market cap.
4. Filter aggressively. Exclude:
   - Mega-caps over $500B unless the theme specifically requires them
   - Sub-$500M market cap (illiquid)
   - Stocks whose business does not actually match the theme (look at company profile)
5. Return JSON conforming to the CandidateList schema. Target 15-25 candidates.

Quality over quantity. Be ruthless. A focused list of 15 strong candidates beats 40 mediocre ones. Populate etf_appearances and aggregate_weight from the holdings data, and record what you excluded and why in the excluded field."""


def run(theme: str, *, ctx: ToolContext | None = None, constraints: str = "") -> AgentResult:
    runner = AgentRunner(
        model=AGENT_MODELS[NAME],
        tools=TOOLS,
        handlers=get_handlers([t["name"] for t in TOOLS]),
        agent_name=NAME,
        max_tokens=8192,  # candidate lists can be long
    )
    extra = f"\n\nUNIVERSE CONSTRAINTS (hard — only include names that satisfy these): {constraints}" if constraints else ""
    return runner.run(
        system=SYSTEM,
        user_message=(
            f"Build a candidate list for the investment theme: {theme!r}. "
            f"Return a CandidateList.{extra}"
        ),
        output_schema=CandidateList,
        ctx=ctx,
        max_iters=20,  # many ETF holdings calls
    )
