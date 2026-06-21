"""Per-agent structured output schemas for the four analyst agents.

Each analyst returns exactly one of these. The agent runner forces the model to
emit JSON matching the schema and validates it with ``model_validate_json``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FundamentalsReport(BaseModel):
    ticker: str
    revenue_cagr_3y: float
    revenue_cagr_5y: float
    gross_margin_latest: float
    gross_margin_trend: Literal["expanding", "stable", "compressing"]
    operating_margin_latest: float
    fcf_conversion: float = Field(description="Free cash flow / net income")
    rule_of_40_score: float = Field(description="Revenue growth % + FCF margin %")
    segment_analysis: str
    peer_comparison: str
    red_flags: list[str] = Field(default_factory=list)
    yellow_flags: list[str] = Field(default_factory=list)
    score_1_to_10: int = Field(ge=1, le=10)
    reasoning: str


class BalanceSheetReport(BaseModel):
    ticker: str
    net_debt_to_ebitda: float | None = None
    interest_coverage: float | None = None
    current_ratio: float
    shares_outstanding_cagr_3y: float
    sbc_pct_revenue: float = Field(description="Stock-based comp as % of revenue")
    fcf_vs_netincome_gap_pct: float
    goodwill_pct_assets: float
    debt_maturity_risk: Literal["low", "medium", "high"]
    capital_allocation_grade: Literal["A", "B", "C", "D", "F"]
    red_flags: list[str] = Field(default_factory=list)
    yellow_flags: list[str] = Field(default_factory=list)
    score_1_to_10: int = Field(ge=1, le=10)
    reasoning: str


class ManagementReport(BaseModel):
    ticker: str
    ceo_name: str
    ceo_tenure_years: float
    is_founder_led: bool
    insider_ownership_pct: float
    insider_net_buying_24mo: float = Field(description="USD; negative = net selling")
    shareholder_letter_summary: str
    governance_concerns: list[str] = Field(default_factory=list)
    capital_allocation_track_record: str
    earnings_call_quality: Literal["strong", "adequate", "evasive"]
    score_1_to_10: int = Field(ge=1, le=10)
    reasoning: str


class PeerMetric(BaseModel):
    name: str  # e.g. "Gross margin"
    subject_value: float
    peer_values: dict[str, float] = Field(default_factory=dict)  # {"AMD": 47.2, ...}
    subject_rank: int  # 1 = best in the group


class PeerComparisonReport(BaseModel):
    ticker: str
    peers: list[str] = Field(default_factory=list)
    metrics: list[PeerMetric] = Field(default_factory=list)
    subject_advantages: list[str] = Field(default_factory=list)
    subject_disadvantages: list[str] = Field(default_factory=list)
    rebuttals: list[str] = Field(
        default_factory=list,
        description="For each disadvantage, why the subject is still preferred (or an admission it isn't)",
    )
    preference_strength_1_to_10: int = Field(ge=1, le=10)
    reasoning: str


class MacroContext(BaseModel):
    theme: str
    sectors_covered: list[str] = Field(default_factory=list)
    cycle_position: str  # ~3 sentences
    tailwinds: list[str] = Field(default_factory=list)  # 2-3 bullets
    headwinds: list[str] = Field(default_factory=list)  # 2-3 bullets
    regime_winners_profile: str
    regime_losers_profile: str
    sources: list[str] = Field(default_factory=list)


class ForensicFinding(BaseModel):
    category: Literal[
        "risk_factor_delta", "footnote", "working_capital",
        "auditor_or_restatement", "insider_pattern",
        "proxy_governance", "recent_8k",
    ]
    finding: str  # one paragraph describing the signal
    severity: Literal["green", "yellow", "red"]
    citation: str  # accession number + section
    source_url: str | None = None


class ForensicReport(BaseModel):
    ticker: str
    findings: list[ForensicFinding] = Field(default_factory=list)
    risk_factor_delta_summary: str
    no_notable_findings_categories: list[str] = Field(default_factory=list)
    forensic_risk_score_1_to_10: int = Field(ge=1, le=10)
    reasoning: str
    sources: list[str] = Field(default_factory=list)  # all accession numbers cited


class StressTestReport(BaseModel):
    ticker: str
    bear_thesis: str
    counterargument_1: str
    counterargument_2: str
    counterargument_3: str
    who_has_to_lose: str
    regulatory_risk: str
    valuation_check: str
    historical_analogues: list[str] = Field(default_factory=list)
    survivability_score_1_to_10: int = Field(ge=1, le=10)
    reasoning: str
