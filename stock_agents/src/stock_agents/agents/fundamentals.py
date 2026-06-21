"""Fundamentals analyst agent.

Scores a single ticker on revenue quality, margin trends, and growth durability.
"""

from __future__ import annotations

from stock_agents.agents.base import AgentResult, AgentRunner
from stock_agents.config import AGENT_MODELS
from stock_agents.models.analysis import FundamentalsReport
from stock_agents.tools import definitions as d
from stock_agents.tools import get_handlers
from stock_agents.tools.handlers import ToolContext

NAME = "fundamentals"

TOOLS = [
    d.GET_INCOME_STATEMENT,
    d.GET_CASH_FLOW_STATEMENT,
    d.GET_KEY_METRICS,
    d.GET_COMPANY_PROFILE,
    d.GET_PEER_COMPARISON,
]

SYSTEM = """You are a fundamental equity analyst evaluating revenue quality, margins, and growth durability for a single company.

Process:
1. Pull 5 years of income statement data.
2. Compute: 3-year and 5-year revenue CAGR, gross margin trend, operating margin trend, FCF conversion ratio, Rule of 40 score (revenue growth % + FCF margin %).
3. Identify segment-level growth. Which business unit is driving growth? What's the marginal economics?
4. Flag concentration: top customer %, geographic concentration, single-product reliance.
5. Compare to top 5 sector peers by market cap.
6. Score 1-10 where 10 = Nvidia-2021 quality (>40% revenue growth, expanding margins, segment with massive runway).

Numbers, not adjectives. "Revenue grew 47% YoY" not "strong growth." "Gross margin expanded from 62% to 73% over 3 years" not "improving margins."

Be skeptical of accounting. Flag: pulled-forward revenue, unusual receivables growth relative to revenue, deferred revenue changes, capitalized software costs as % of R&D.

The tools return pre-computed derived metrics (CAGRs, margins, Rule of 40) alongside raw statements — use those figures directly and cite the raw periods that produced them."""


def run(ticker: str, *, ctx: ToolContext | None = None) -> AgentResult:
    runner = AgentRunner(
        model=AGENT_MODELS[NAME],
        tools=TOOLS,
        handlers=get_handlers([t["name"] for t in TOOLS]),
        agent_name=NAME,
    )
    return runner.run(
        system=SYSTEM,
        user_message=(
            f"Analyze the fundamentals of {ticker.upper()}. Gather the data, compute the "
            "metrics, and return a FundamentalsReport."
        ),
        output_schema=FundamentalsReport,
        ctx=ctx,
        ticker=ticker.upper(),
    )
