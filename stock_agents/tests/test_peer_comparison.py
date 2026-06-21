"""Peer Comparison agent + its orchestrator integration (offline)."""

from __future__ import annotations

from stock_agents.agents import base, orchestrator, peer_comparison
from stock_agents.agents.base import AgentResult, Usage
from stock_agents.models.analysis import (
    BalanceSheetReport,
    FundamentalsReport,
    ManagementReport,
    PeerComparisonReport,
    StressTestReport,
)
from stock_agents.models.thesis import InvestmentThesis
from tests.conftest import fake_anthropic_returning

_VALID = PeerComparisonReport(
    ticker="NVDA", peers=["AMD", "AVGO", "TSM"],
    metrics=[], subject_advantages=["gross margin"], subject_disadvantages=["valuation"],
    rebuttals=["growth justifies the multiple"], preference_strength_1_to_10=8, reasoning="r",
).model_dump_json()


def test_peer_agent_returns_valid_report(monkeypatch, tmp_path):
    monkeypatch.setattr(base.settings, "audit_log_dir", tmp_path)
    monkeypatch.setattr(base, "Anthropic", fake_anthropic_returning(_VALID))
    res = peer_comparison.run("NVDA")
    assert isinstance(res.output, PeerComparisonReport)
    assert res.output.preference_strength_1_to_10 == 8
    assert res.error is None


def _r(model, **kw):
    return AgentResult(output=model, cost_usd=0.1, usage=Usage(), model="m")


def _fund():
    return FundamentalsReport(ticker="NVDA", revenue_cagr_3y=40, revenue_cagr_5y=40,
        gross_margin_latest=70, gross_margin_trend="expanding", operating_margin_latest=50,
        fcf_conversion=0.9, rule_of_40_score=80, segment_analysis="x", peer_comparison="y",
        red_flags=[], yellow_flags=[], score_1_to_10=8, reasoning="r")


def _bal():
    return BalanceSheetReport(ticker="NVDA", current_ratio=3.0, shares_outstanding_cagr_3y=1.0,
        sbc_pct_revenue=5.0, fcf_vs_netincome_gap_pct=5.0, goodwill_pct_assets=2.0,
        debt_maturity_risk="low", capital_allocation_grade="A", red_flags=[], yellow_flags=[],
        score_1_to_10=9, reasoning="r")


def _mgmt():
    return ManagementReport(ticker="NVDA", ceo_name="Jensen", ceo_tenure_years=30,
        is_founder_led=True, insider_ownership_pct=3.5, insider_net_buying_24mo=0.0,
        shareholder_letter_summary="s", governance_concerns=[], capital_allocation_track_record="t",
        earnings_call_quality="strong", score_1_to_10=8, reasoning="r")


def _stress():
    return StressTestReport(ticker="NVDA", bear_thesis="b", counterargument_1="1",
        counterargument_2="2", counterargument_3="3", who_has_to_lose="x", regulatory_risk="r",
        valuation_check="v", historical_analogues=["a"], survivability_score_1_to_10=6, reasoning="r")


def _thesis(**over):
    base_ = dict(ticker="NVDA", name="NVIDIA", one_paragraph_summary="s", bull_case=["b"],
        bear_case=["x"], what_would_change_my_mind="w", conviction_score=70.0,
        conviction_label="high", fundamentals_score=8, balance_sheet_score=9,
        management_score=8, stress_test_score=6)
    base_.update(over)
    return InvestmentThesis(**base_)


def test_peer_wired_into_pipeline(monkeypatch):
    """analyze_single_detailed runs peer comparison and carries it + backfills the thesis."""
    monkeypatch.setattr(orchestrator.fundamentals, "run", lambda t, **k: _r(_fund()))
    monkeypatch.setattr(orchestrator.balance_sheet, "run", lambda t, **k: _r(_bal()))
    monkeypatch.setattr(orchestrator.management, "run", lambda t, **k: _r(_mgmt()))
    monkeypatch.setattr(orchestrator.stress_test, "run", lambda t, reps, **k: _r(_stress()))
    peer = PeerComparisonReport(ticker="NVDA", peers=["AMD"], metrics=[], subject_advantages=[],
        subject_disadvantages=[], rebuttals=[], preference_strength_1_to_10=7, reasoning="r")
    monkeypatch.setattr(orchestrator.peer_comparison, "run", lambda t, **k: _r(peer))

    captured = {}

    def fake_synth(ticker, reports, *, peer_report=None, macro=None, forensic_report=None, ctx=None):
        captured["peer"] = peer_report
        captured["macro"] = macro
        # synthesizer omits peer_preference_strength -> orchestrator should backfill
        return _r(_thesis(peer_preference_strength=None))

    monkeypatch.setattr(orchestrator.synthesizer, "run", fake_synth)

    from stock_agents.models.company import Candidate
    result = orchestrator.analyze_single_detailed(Candidate(ticker="NVDA", name="NVIDIA",
        market_cap_usd=1e12, sector="Tech", industry="Semis"))

    assert result.peer_comparison is peer
    assert captured["peer"] is peer  # synthesizer received it
    assert result.thesis.peer_preference_strength == 7  # backfilled from peer report
