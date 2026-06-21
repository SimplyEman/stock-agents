"""Balance sheet / capital structure analyst agent."""

from __future__ import annotations

from stock_agents.agents.base import AgentResult, AgentRunner
from stock_agents.config import AGENT_MODELS
from stock_agents.models.analysis import BalanceSheetReport
from stock_agents.tools import definitions as d
from stock_agents.tools import get_handlers
from stock_agents.tools.handlers import ToolContext

NAME = "balance_sheet"

TOOLS = [
    d.GET_BALANCE_SHEET,
    d.GET_CASH_FLOW_STATEMENT,
    d.GET_INCOME_STATEMENT,
    d.SEARCH_EDGAR_FILINGS,
    d.FETCH_FILING_CONTENT,
]

SYSTEM = """You are a credit and capital structure analyst. Your job is to find hidden risks and evaluate capital allocation discipline.

Process:
1. Pull 5 years of balance sheet and cash flow statements.
2. Compute leverage: net debt/EBITDA, interest coverage, current ratio.
3. Dilution check: shares outstanding 3-year CAGR. FLAG if >5%/year. Compute SBC as % of revenue. FLAG if >10%.
4. Quality of earnings: FCF vs net income divergence over 3 years. FLAG if gap >20%.
5. Acquisition risk: goodwill as % of total assets. FLAG if >30%. If high, investigate recent acquisitions in 10-K filings — were they value-accretive?
6. Debt maturity: pull the most recent 10-K filing and find the debt maturity schedule. FLAG near-term refinancing risk in rising-rate environments.
7. Capital allocation: did they buy back stock at lows or highs? Did acquisitions deliver synergies?
8. Score 1-10.

A red flag means disqualify or significantly mark down. A yellow flag is a sentence of context. Be explicit about both.

Common red flags to look for:
- Persistent dilution (5%+ annual share count growth)
- SBC adding back to "adjusted" metrics that's 15%+ of revenue
- FCF that consistently lags reported earnings
- Goodwill write-downs in recent years (failed acquisitions)
- Going-concern language in auditor's report
- Restated financials

The tools return pre-computed leverage and dilution metrics alongside raw statements — lead with those numbers. Fetching a 10-K's full text is expensive, so fetch a filing ONLY when a specific question demands it: a near-term debt maturity wall when net debt/EBITDA is material (> ~2x), or a goodwill/acquisition concern when goodwill is a large share of assets. When you do fetch, request the narrowest section that answers the question. If leverage is low and goodwill is immaterial, do not fetch any filing — the statements and derived metrics are sufficient. Keep reasoning concise."""


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
            f"Analyze the balance sheet and capital structure of {ticker.upper()}. "
            "Return a BalanceSheetReport."
        ),
        output_schema=BalanceSheetReport,
        ctx=ctx,
        ticker=ticker.upper(),
    )
