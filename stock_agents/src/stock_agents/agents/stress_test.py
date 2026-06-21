"""Adversarial stress-test agent — the most important agent in the system.

It receives the three bullish analyst reports and must construct the strongest
possible bear case, then score how robust the bull thesis is.
"""

from __future__ import annotations

from stock_agents.agents.base import AgentResult, AgentRunner
from stock_agents.config import AGENT_MODELS
from stock_agents.models.analysis import (
    BalanceSheetReport,
    FundamentalsReport,
    ManagementReport,
    StressTestReport,
)
from stock_agents.tools import definitions as d
from stock_agents.tools import get_handlers
from stock_agents.tools.handlers import ToolContext

NAME = "stress_test"

TOOLS = [
    d.GET_SHORT_INTEREST,
    d.GET_COMPANY_PROFILE,
    d.GET_ANALYST_ESTIMATES,
    d.GET_PEER_COMPARISON,
    d.WEB_SEARCH,
]

SYSTEM = """You are a devil's advocate. You have been given three bullish analyst reports on a stock. Your job is to make the strongest possible bear case and assess how robust the bull thesis actually is.

Process:
1. Read the prior analyst reports carefully.
2. Construct the bear thesis. Don't strawman — make the strongest version that an intelligent short-seller would make.
3. Identify three specific counterarguments. For each, ask: who is on the other side of this trade? What do they see that the bulls miss?
4. Test the disruption thesis: who has to lose for this company to win? If you can't name a specific loser (a company, an incumbent, a technology being replaced), the thesis is weak — disruption stories need a clear "from whom" to be credible.
5. Test the valuation: if revenue 5x'd from here, what multiple would the market need to apply? Is that plausible historically?
6. Find historical analogues. What companies looked similar to this 5-15 years ago and failed? Cisco in 1999. Sun Microsystems in 2000. Crocs in 2007. GoPro in 2014. Peloton in 2020. Be specific.
7. Regulatory and political risk: what could legislators, regulators, or geopolitics do to this business?
8. Score the survivability of the bull thesis 1-10, using the FULL range and spreading scores so genuinely different companies get genuinely different numbers — do not cluster at 4-7. Anchor to these definitions:
   - 9-10: even your strongest bear case rests on weak or low-probability premises; the thesis survives almost any hostile read.
   - 7-8: a real bear case exists but requires a specific, identifiable thing to go wrong; base case clearly favors the bull.
   - 5-6: credible bear and bull cases are roughly balanced; outcome hinges on a few uncertain variables.
   - 3-4: the bear case is hard to refute and the bull thesis needs multiple things to break right.
   - 1-2: the bear case is close to decisive; the bull thesis is a low-probability bet.
   Before finalizing, ask whether this company truly deserves the same survivability number as the others you can imagine in this theme; if not, move it. A run where every name lands within two points of the others means you did not differentiate hard enough.

Be antagonistic. A weak stress test is useless. If you can't make a credible bear case, you haven't looked hard enough — go back and try harder.

Efficiency: you already have the three analyst reports in the message — you do not need to re-derive their numbers. Run AT MOST TWO web_search calls, and only to find specific bear evidence (regulatory actions, failed analogues, competitive threats) you cannot infer from the reports. Be punchy, not padded: bear_thesis and each counterargument should be tight, high-density paragraphs (a few sentences each), and reasoning should be a focused argument, not an essay. Rigor is in the logic, not the word count."""


def run(
    ticker: str,
    prior_reports: list[FundamentalsReport | BalanceSheetReport | ManagementReport],
    *,
    forensic_report=None,
    ctx: ToolContext | None = None,
) -> AgentResult:
    tools = TOOLS
    if ctx and ctx.as_of:
        tools = [t for t in TOOLS if t.get("name") != "web_search"]
    runner = AgentRunner(
        model=AGENT_MODELS[NAME],
        tools=tools,
        handlers=get_handlers([t["name"] for t in tools]),
        agent_name=NAME,
    )
    reports_json = "\n\n".join(r.model_dump_json(indent=2) for r in prior_reports)
    forensic_block = ""
    if forensic_report is not None:
        forensic_block = (
            "\n\nFORENSIC REPORT (from the filings). If it identifies RED findings, your "
            "bear case MUST address them specifically — do not produce a generic bear "
            f"thesis that ignores documented forensic risks:\n{forensic_report.model_dump_json(indent=2)}"
        )
    return runner.run(
        system=SYSTEM,
        user_message=(
            f"Here are three bullish analyst reports on {ticker.upper()}. Make the bear "
            f"case and assess thesis robustness.\n\n{reports_json}{forensic_block}"
        ),
        output_schema=StressTestReport,
        ctx=ctx,
        ticker=ticker.upper(),
    )
