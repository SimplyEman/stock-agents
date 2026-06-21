"""Material-change diff logic (offline, no DB, no model calls)."""

from __future__ import annotations

from stock_agents.models.analysis import BalanceSheetReport, FundamentalsReport
from stock_agents.models.thesis import InvestmentThesis
from stock_agents.track import diff as D
from stock_agents.track.models import ThesisSnapshot


def _thesis(**over) -> InvestmentThesis:
    base = dict(
        ticker="NVDA",
        name="NVIDIA",
        one_paragraph_summary="s",
        bull_case=["b1", "b2", "b3"],
        bear_case=["x1", "x2", "x3"],
        what_would_change_my_mind="data center revenue growth decelerating below 20 percent",
        conviction_score=70.0,
        conviction_label="high",
        fundamentals_score=8,
        balance_sheet_score=8,
        management_score=7,
        stress_test_score=6,
    )
    base.update(over)
    return InvestmentThesis(**base)


def _snap(thesis, sid="S1", **reports) -> ThesisSnapshot:
    return ThesisSnapshot(
        id=sid,
        ticker=thesis.ticker,
        run_id="R1",
        taken_at="2026-01-01T00:00:00+00:00",
        thesis=thesis,
        **reports,
    )


def test_quiet_diff_not_material():
    entry = _snap(_thesis(conviction_score=70.0), "S1")
    new = _snap(_thesis(conviction_score=72.0), "S2")  # +2, no component move
    d = D.compute_diff(entry, new)
    assert not d.is_material
    assert d.conviction_delta == 2.0
    assert d.material_reasons == []


def test_conviction_move_material():
    entry = _snap(_thesis(conviction_score=70.0), "S1")
    new = _snap(_thesis(conviction_score=52.0), "S2")  # -18 >= 15
    d = D.compute_diff(entry, new)
    assert d.is_material
    assert any("conviction moved" in r for r in d.material_reasons)


def test_component_move_material():
    entry = _snap(_thesis(stress_test_score=6), "S1")
    new = _snap(_thesis(stress_test_score=3, conviction_score=70.0), "S2")  # -3
    d = D.compute_diff(entry, new)
    assert d.component_deltas["stress_test"] == -3
    assert d.is_material
    assert any("stress_test score moved -3" in r for r in d.material_reasons)


def test_new_red_flag_detected_when_reports_present():
    entry = _snap(
        _thesis(),
        "S1",
        fundamentals=FundamentalsReport(
            ticker="NVDA",
            revenue_cagr_3y=40,
            revenue_cagr_5y=40,
            gross_margin_latest=70,
            gross_margin_trend="expanding",
            operating_margin_latest=50,
            fcf_conversion=0.9,
            rule_of_40_score=80,
            segment_analysis="x",
            peer_comparison="y",
            red_flags=[],
            yellow_flags=[],
            score_1_to_10=8,
            reasoning="r",
        ),
    )
    new = _snap(
        _thesis(conviction_score=70.0),
        "S2",
        balance_sheet=BalanceSheetReport(
            ticker="NVDA",
            current_ratio=3.0,
            shares_outstanding_cagr_3y=1.0,
            sbc_pct_revenue=5.0,
            fcf_vs_netincome_gap_pct=5.0,
            goodwill_pct_assets=2.0,
            debt_maturity_risk="low",
            capital_allocation_grade="A",
            red_flags=["Customer concentration rising"],
            yellow_flags=[],
            score_1_to_10=7,
            reasoning="r",
        ),
    )
    d = D.compute_diff(entry, new)
    assert d.red_flags_available is True
    assert "Customer concentration rising" in d.new_red_flags
    assert d.is_material


def test_red_flags_na_when_reports_absent():
    entry = _snap(_thesis(), "S1")
    new = _snap(_thesis(conviction_score=70.0), "S2")
    d = D.compute_diff(entry, new)
    assert d.red_flags_available is False
    assert d.new_red_flags == []


def test_falsifier_referenced():
    entry = _snap(
        _thesis(
            what_would_change_my_mind="data center revenue growth decelerating below 20 percent"
        ),
        "S1",
    )
    new = _snap(
        _thesis(
            conviction_score=70.0,
            bear_case=["Data center revenue growth is decelerating sharply", "x2", "x3"],
        ),
        "S2",
    )
    d = D.compute_diff(entry, new)
    assert d.falsifiers_referenced
    assert d.is_material


def test_cannot_evaluate():
    d = D.cannot_evaluate("NVDA", "S1", "delisted / no data")
    assert d.status == "cannot_evaluate"
    assert d.is_material
