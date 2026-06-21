"""Peer Comparison agent (v2 Phase 2).

Forces the question "why this one and not the closest alternative" before the
synthesizer locks in conviction. Runs after Stress Test, before Synthesizer,
per analyzed candidate.
"""

from __future__ import annotations

from stock_agents.agents.base import AgentResult, AgentRunner
from stock_agents.config import AGENT_MODELS
from stock_agents.models.analysis import PeerComparisonReport
from stock_agents.tools import definitions as d
from stock_agents.tools import get_handlers
from stock_agents.tools.handlers import ToolContext

NAME = "peer_comparison"

TOOLS = [
    d.GET_COMPANY_PROFILE,
    d.GET_INCOME_STATEMENT,
    d.GET_BALANCE_SHEET,
    d.GET_KEY_METRICS,
    d.GET_PEER_COMPARISON,
]

SYSTEM = """You are a relative-value analyst. Your single job: decide whether the subject company is genuinely the best way to express this thesis, versus its closest comparable alternatives. The synthesizer reads your verdict before setting conviction.

Process:
1. Identify the 3 closest comparable companies: same sector / sub-industry, similar market-cap band (roughly 0.3x to 3x of the subject), publicly traded, with available financials. Use get_peer_comparison and get_company_profile to find and validate them.
2. Pull key metrics for the subject and each peer: revenue growth, gross margin, operating margin, FCF margin, ROE, net debt/EBITDA, EV/Revenue, EV/EBITDA, P/E. Use the most recent available data.
3. Build a comparison matrix. For each metric, record the subject's value, each peer's value, and the subject's rank (1 = best) across the group.
4. Identify where the subject is materially better, materially worse, and roughly equal.
5. For EACH dimension where the subject is materially worse, state the question explicitly: "Why hold {subject} instead of {peer} given this?" Then answer it honestly — give the real reason the subject is still preferable, OR admit there isn't a good answer. A rebuttal that is just "but {subject} is the leader" is not an answer.
6. Score 1-10 on preference strength: how confidently the subject is the right pick versus the alternatives. 9-10 = clearly the best vehicle on most axes; 5-6 = a coin-flip versus a named peer; 1-3 = a peer is plainly better and the subject is being held on narrative.

Numbers, not adjectives. Be willing to conclude that a peer is the better buy — that is a useful finding, not a failure.

Output: valid JSON conforming to PeerComparisonReport. Populate metrics with the comparison matrix, and make subject_disadvantages and rebuttals correspond one-to-one."""


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
            f"Compare {ticker.upper()} against its 3 closest investable peers and decide "
            "whether it is the best vehicle for the thesis. Return a PeerComparisonReport."
        ),
        output_schema=PeerComparisonReport,
        ctx=ctx,
        ticker=ticker.upper(),
    )
