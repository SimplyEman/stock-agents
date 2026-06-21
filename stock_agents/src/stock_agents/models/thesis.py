"""Synthesizer and final-report schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from stock_agents.models.analysis import MacroContext


class InvestmentThesis(BaseModel):
    ticker: str
    name: str
    one_paragraph_summary: str
    bull_case: list[str] = Field(description="3 bullets max")
    bear_case: list[str] = Field(description="3 bullets max")
    what_would_change_my_mind: str
    catalysts: list[str] = Field(default_factory=list)
    conviction_score: float = Field(ge=0, le=100, description="0-100 weighted composite")
    conviction_label: Literal["low", "medium", "high", "very high"]
    fundamentals_score: int = Field(ge=1, le=10)
    balance_sheet_score: int = Field(ge=1, le=10)
    management_score: int = Field(ge=1, le=10)
    stress_test_score: int = Field(ge=1, le=10)
    # v2 Phase 2: references to the peer-comparison and macro-overlay agents.
    # Informative only — they do NOT enter the conviction composite (unchanged).
    peer_preference_strength: int | None = Field(
        default=None, ge=1, le=10,
        description="Peer-comparison agent's confidence the subject beats its closest alternatives",
    )
    macro_fit: str = Field(
        default="",
        description="One phrase on whether the candidate fits the regime winners or losers profile",
    )
    forensic_risk_score: int | None = Field(
        default=None, ge=1, le=10,
        description="Forensic agent's filings-risk score (forensic mode only); higher = riskier",
    )
    sources: list[str] = Field(
        default_factory=list, description="URLs / filing accession numbers cited"
    )


class FinalReport(BaseModel):
    theme: str
    run_timestamp: datetime
    candidates_analyzed: int
    api_cost_usd: float
    market_commentary: str = ""
    macro_context: MacroContext | None = None  # v2 Phase 2: regime context for the run
    filter_note: str = ""  # addendum: asymmetric universe filter thresholds + exclusions
    top_picks: list[InvestmentThesis] = Field(default_factory=list)
    full_results: list[InvestmentThesis] = Field(default_factory=list)
