"""Management quality analyst agent."""

from __future__ import annotations

from stock_agents.agents.base import AgentResult, AgentRunner
from stock_agents.config import AGENT_MODELS
from stock_agents.models.analysis import ManagementReport
from stock_agents.tools import definitions as d
from stock_agents.tools import get_handlers
from stock_agents.tools.handlers import ToolContext

NAME = "management"

# web_search is a server-side tool; the handler registry ignores it.
TOOLS = [
    d.GET_INSIDER_TRANSACTIONS,
    d.SEARCH_EDGAR_FILINGS,
    d.FETCH_FILING_CONTENT,
    d.GET_COMPANY_PROFILE,
    d.WEB_SEARCH,
]

SYSTEM = """You are evaluating management quality. Founder-led businesses with high insider ownership and consistent execution warrant premium consideration. Frequent executive turnover, weak governance, and insider selling are negative signals.

Process:
1. Pull insider transactions first (get_insider_transactions). The tool already nets open-market vs. all transactions — use those numbers directly; do not recompute.
2. Pull ONLY the most recent DEF 14A proxy statement, and fetch it with section="exec_comp". Extract CEO compensation, ownership stakes, board composition, and related-party transactions from that section.
3. Use the company profile for CEO name, founder status, and tenure.
4. If an earnings transcript / press release is included in your input, read it closely for management QUALITY signals — not the financials. Specifically assess: (a) Q&A vagueness — do executives give specific, quantified answers or deflect with platitudes? (b) evasion — are pointed analyst questions answered directly or dodged? (c) consistency — does the strategy and tone match prior quarters, or is there an unexplained pivot? A vague, evasive, or inconsistent call is a negative signal and should pull earnings_call_quality toward "evasive" and lower the score. A crisp, specific, self-critical call is a positive signal. If no transcript is provided, set earnings_call_quality on the rest of the evidence and say so in reasoning.
5. Optionally run AT MOST ONE web_search if you need to confirm CEO background, a known controversy, or a recent executive departure. Skip it entirely if the filing and profile already answer the question.
6. Score 1-10.

Green signals: founder still active with 5%+ ownership, open-market insider buying, multi-year strategic consistency, specific acknowledgment of past mistakes, low CEO compensation relative to performance.

Red signals: heavy insider selling at lows, mass C-suite turnover, vague or evasive earnings call Q&A, governance concerns (split CEO/Chair contested, related-party transactions, classified boards), recent SEC investigations.

Be honest. Charisma is not the same as capital allocation skill. Do NOT manufacture governance concerns from thin web noise — a concern belongs in the report only if a filing or a credible source substantiates it; otherwise leave governance_concerns empty.

Tool-cost discipline (important): you are one of several agents analyzing this company and you share a cost budget. Do NOT fetch 10-K, 10-Q, or 8-K filings — those are financial filings other agents own; you only need the DEF 14A exec_comp section. Fetch at most ONE filing. Each full filing you pull costs real money, so be surgical. Keep shareholder_letter_summary and reasoning concise (a few sentences each)."""


def _fetch_transcript_block(ticker: str, ctx: ToolContext | None) -> str:
    """Pre-fetch the latest earnings transcript/press release for the user message.

    Skipped in backtest mode for non-8-K sources (no point-in-time web/IR); the
    8-K source is filtered to filings before the as-of date when ``ctx.as_of`` is set.
    Returns an empty string when nothing is available (the agent then relies on
    filings + insider data alone).
    """
    from stock_agents.data import transcripts

    try:
        result = transcripts.get_earnings_transcript(ticker, before=ctx.as_of if ctx else None)
    except transcripts.TranscriptUnavailable:
        return ""
    return (
        f"\n\nMOST RECENT EARNINGS TRANSCRIPT / PRESS RELEASE "
        f"(source: {result['source']}, quarter: {result['quarter']}). Read it for Q&A "
        f"vagueness, executive evasion, and consistency with prior quarters:\n\n{result['text']}"
    )


def run(ticker: str, *, ctx: ToolContext | None = None) -> AgentResult:
    # In point-in-time / backtest mode, drop web search (no historical web).
    tools = TOOLS
    if ctx and ctx.as_of:
        tools = [t for t in TOOLS if t.get("name") != "web_search"]
    runner = AgentRunner(
        model=AGENT_MODELS[NAME],
        tools=tools,
        handlers=get_handlers([t["name"] for t in tools]),
        agent_name=NAME,
    )
    transcript_block = _fetch_transcript_block(ticker, ctx)
    return runner.run(
        system=SYSTEM,
        user_message=(
            f"Evaluate the management quality of {ticker.upper()}. Return a ManagementReport."
            f"{transcript_block}"
        ),
        output_schema=ManagementReport,
        ctx=ctx,
        ticker=ticker.upper(),
    )
