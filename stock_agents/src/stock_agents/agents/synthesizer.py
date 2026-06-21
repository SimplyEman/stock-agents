"""Synthesizer agent — the lead PM.

Weighs the four analyst reports and writes the final thesis. The conviction
score is computed deterministically in Python (not left to the model) so the
weighting formula is exact and auditable; the agent supplies the narrative and
the component scores it read from the reports.
"""

from __future__ import annotations

from typing import Literal

from stock_agents.agents.base import AgentResult, AgentRunner
from stock_agents.config import AGENT_MODELS
from stock_agents.models.analysis import (
    BalanceSheetReport,
    FundamentalsReport,
    MacroContext,
    ManagementReport,
    PeerComparisonReport,
    StressTestReport,
)
from stock_agents.models.thesis import InvestmentThesis
from stock_agents.tools.handlers import ToolContext

NAME = "synthesizer"

WEIGHTS = {"fundamentals": 0.25, "balance_sheet": 0.20, "management": 0.25, "stress_test": 0.30}

SYSTEM = """You are the lead portfolio manager. Specialist analysts have submitted reports on this stock — four core analysts (fundamentals, balance sheet, management, stress test) plus, when provided, a Peer Comparison report and a Macro/Sector Overlay for the whole run. Your job is to weigh their inputs, resolve conflicts, and produce a final investment thesis.

Process:
1. Read all reports.
2. Identify conflicting signals. A great balance sheet does not save bad management. Strong fundamentals can be undermined by a fragile bear case. Be explicit about tensions.
3. Carry forward the four core component scores exactly as reported: fundamentals_score, balance_sheet_score, management_score, and stress_test_score (the stress test's survivability score). These four (and ONLY these four) drive the conviction composite, which is recomputed downstream — do not try to fold peer/macro into the four scores.
3b. If a Peer Comparison report is provided: set peer_preference_strength to its preference_strength_1_to_10, and let a weak peer verdict temper your bull case / narrative (if a named peer is plainly better, say so in the bear case). If absent, leave peer_preference_strength null.
3c. If a Macro/Sector Overlay is provided: set macro_fit to one phrase stating whether this candidate matches the regime winners profile or the losers profile, and reflect that in your reasoning. If absent, leave macro_fit empty.
3d. If a Forensic Report is provided: set forensic_risk_score to its forensic_risk_score_1_to_10, and weight its findings in your reasoning — red forensic findings (restatement risk, auditor concerns, hostile insider activity, governance issues) should materially temper conviction and surface in the bear case. The composite conviction is recomputed downstream with forensic risk at 15% weight (higher forensic risk lowers conviction), so carry the score accurately.
4. Write the thesis:
   - One paragraph summary (4-6 sentences, no jargon)
   - Bull case: exactly 3 bullets, each one sentence
   - Bear case: exactly 3 bullets, each one sentence
   - What would change your mind: one paragraph identifying specific falsifiers
   - Catalysts: 2-4 specific events with rough timeline
5. Cite sources: list URLs and filing accession numbers referenced across the reports.

Note: the conviction_score and conviction_label fields are recomputed downstream from the component scores using a fixed weighting, so set conviction_score to your best estimate but focus your effort on the narrative and on carrying the four component scores accurately.

Calibration matters more than precision. A medium-conviction call you're honest about beats a high-conviction call you can't defend. The goal is finding 1-2 Nvidias, not 30 mediocre ideas. Be willing to score most candidates low — that's correct, because most stocks are not Nvidia-2021.

Use the full 0-100 conviction range. A weak, expensive, or fragile-thesis name should land 25-40; a merely fine business at a full price 45-60; reserve 75+ for a durable compounder with a defensible moat, clean balance sheet, aligned management, and a bear case that requires multiple things to go right. Do not cluster everything at 55-70.

Be concise: the one-paragraph summary is 4-6 sentences, bull/bear bullets are one sentence each, and you are writing over reports you already have — do not restate every figure."""


def compute_conviction(
    fundamentals: int, balance_sheet: int, management: int, stress_test: int,
    *, forensic_risk: int | None = None,
) -> tuple[float, Literal["low", "medium", "high", "very high"]]:
    if forensic_risk is None:
        score = (
            fundamentals * WEIGHTS["fundamentals"]
            + balance_sheet * WEIGHTS["balance_sheet"]
            + management * WEIGHTS["management"]
            + stress_test * WEIGHTS["stress_test"]
        ) * 10.0
    else:
        # Forensic mode (addendum): forensic risk takes 15% weight (redistributed
        # from fundamentals and balance sheet). Inverted so higher risk LOWERS conviction.
        score = (
            fundamentals * 0.20
            + balance_sheet * 0.15
            + management * 0.20
            + stress_test * 0.30
            + (11 - forensic_risk) * 0.15
        ) * 10.0
    if score < 40:
        label: Literal["low", "medium", "high", "very high"] = "low"
    elif score < 60:
        label = "medium"
    elif score < 80:
        label = "high"
    else:
        label = "very high"
    return round(score, 1), label


def run(
    ticker: str,
    reports: list[
        FundamentalsReport | BalanceSheetReport | ManagementReport | StressTestReport
    ],
    *,
    peer_report: PeerComparisonReport | None = None,
    macro: MacroContext | None = None,
    forensic_report=None,
    ctx: ToolContext | None = None,
) -> AgentResult:
    runner = AgentRunner(
        model=AGENT_MODELS[NAME],
        tools=[],
        handlers={},
        agent_name=NAME,
    )
    reports_json = "\n\n".join(r.model_dump_json(indent=2) for r in reports)
    extra = ""
    if peer_report is not None:
        extra += f"\n\nPEER COMPARISON REPORT:\n{peer_report.model_dump_json(indent=2)}"
    if macro is not None:
        extra += f"\n\nMACRO / SECTOR OVERLAY (applies to the whole run):\n{macro.model_dump_json(indent=2)}"
    if forensic_report is not None:
        extra += (
            "\n\nFORENSIC REPORT (filings-based risk signals). Set forensic_risk_score to "
            "its forensic_risk_score_1_to_10, and let red findings weigh on the thesis "
            f"(higher forensic risk = lower conviction):\n{forensic_report.model_dump_json(indent=2)}"
        )
    result = runner.run(
        system=SYSTEM,
        user_message=(
            f"Synthesize a final investment thesis for {ticker.upper()} from the analyst "
            f"reports below.\n\n{reports_json}{extra}"
        ),
        output_schema=InvestmentThesis,
        ctx=ctx,
        ticker=ticker.upper(),
    )

    # Enforce the deterministic conviction formula on top of the model's narrative.
    if isinstance(result.output, InvestmentThesis):
        t = result.output
        score, label = compute_conviction(
            t.fundamentals_score, t.balance_sheet_score, t.management_score, t.stress_test_score
        )
        t.conviction_score = score
        t.conviction_label = label
    return result
