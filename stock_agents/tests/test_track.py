"""Watchlist persistence + track-status flow (offline: temp DB, mocked analysis)."""

from __future__ import annotations

import pytest

from stock_agents.models.analysis import (
    BalanceSheetReport,
    FundamentalsReport,
    ManagementReport,
    StressTestReport,
)
from stock_agents.models.thesis import InvestmentThesis


@pytest.fixture
def temp_store(tmp_path, monkeypatch):
    """Point the store at a temp data dir and reset the cached engine."""
    from stock_agents.config import settings
    from stock_agents.track import store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    store.reset_engine()
    yield store
    store.reset_engine()


def _thesis(ticker="NVDA", conviction=70.0, **over) -> InvestmentThesis:
    base = dict(
        ticker=ticker,
        name="NVIDIA",
        one_paragraph_summary="s",
        bull_case=["b1"],
        bear_case=["x1"],
        what_would_change_my_mind="growth stalls",
        conviction_score=conviction,
        conviction_label="high",
        fundamentals_score=8,
        balance_sheet_score=8,
        management_score=7,
        stress_test_score=6,
    )
    base.update(over)
    return InvestmentThesis(**base)


def _reports(ticker="NVDA"):
    return (
        FundamentalsReport(
            ticker=ticker,
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
        BalanceSheetReport(
            ticker=ticker,
            current_ratio=3.0,
            shares_outstanding_cagr_3y=1.0,
            sbc_pct_revenue=5.0,
            fcf_vs_netincome_gap_pct=5.0,
            goodwill_pct_assets=2.0,
            debt_maturity_risk="low",
            capital_allocation_grade="A",
            red_flags=[],
            yellow_flags=[],
            score_1_to_10=8,
            reasoning="r",
        ),
        ManagementReport(
            ticker=ticker,
            ceo_name="J",
            ceo_tenure_years=10,
            is_founder_led=True,
            insider_ownership_pct=3.0,
            insider_net_buying_24mo=0.0,
            shareholder_letter_summary="s",
            governance_concerns=[],
            capital_allocation_track_record="t",
            earnings_call_quality="strong",
            score_1_to_10=7,
            reasoning="r",
        ),
        StressTestReport(
            ticker=ticker,
            bear_thesis="b",
            counterargument_1="1",
            counterargument_2="2",
            counterargument_3="3",
            who_has_to_lose="x",
            regulatory_risk="r",
            valuation_check="v",
            historical_analogues=["a"],
            survivability_score_1_to_10=6,
            reasoning="r",
        ),
    )


def test_track_add_from_finalreport(temp_store, tmp_path):
    from stock_agents import track as tracking
    from stock_agents.models.thesis import FinalReport

    report = FinalReport(
        theme="ai",
        run_timestamp="2026-01-01T00:00:00+00:00",
        candidates_analyzed=1,
        api_cost_usd=1.0,
        top_picks=[_thesis()],
        full_results=[_thesis()],
    )
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json())

    entry = tracking.track_add("NVDA", thesis_path=str(path), entry_price=1450.0, note="from theme")
    assert entry.ticker == "NVDA"
    assert entry.entry_conviction == 70.0
    assert entry.entry_price == 1450.0

    # round-trips through SQLite
    assert temp_store.get_watchlist("NVDA").notes == "from theme"
    assert len(temp_store.list_snapshot_rows("NVDA")) == 1


def test_track_add_unknown_ticker_in_report_raises(temp_store, tmp_path):
    from stock_agents import track as tracking
    from stock_agents.models.thesis import FinalReport
    from stock_agents.track.snapshots import ThesisFileError

    report = FinalReport(
        theme="ai",
        run_timestamp="2026-01-01T00:00:00+00:00",
        candidates_analyzed=1,
        api_cost_usd=1.0,
        top_picks=[_thesis("AMD")],
        full_results=[_thesis("AMD")],
    )
    path = tmp_path / "r.json"
    path.write_text(report.model_dump_json())
    with pytest.raises(ThesisFileError):
        tracking.track_add("NVDA", thesis_path=str(path))


def test_status_transitions(temp_store, tmp_path):
    from stock_agents import track as tracking

    path = tmp_path / "t.json"
    path.write_text(_thesis().model_dump_json())
    tracking.track_add("NVDA", thesis_path=str(path))

    assert temp_store.set_status("NVDA", "paused").status == "paused"
    assert temp_store.set_status("NVDA", "active").status == "active"
    exited = temp_store.set_status("NVDA", "exited", note="falsifier fired")
    assert exited.status == "exited"
    assert "falsifier fired" in exited.notes


def test_track_status_stores_snapshot_and_diffs(temp_store, tmp_path, monkeypatch):
    from stock_agents import track as tracking
    from stock_agents.agents import orchestrator

    # Entry at conviction 70 from a report.
    path = tmp_path / "entry.json"
    path.write_text(_thesis(conviction=70.0).model_dump_json())
    tracking.track_add("NVDA", thesis_path=str(path))

    # Fresh inspect returns a materially lower conviction + analyst reports.
    f, b, m, s = _reports()
    fake = orchestrator.CandidateAnalysis(
        ticker="NVDA",
        thesis=_thesis(conviction=50.0, stress_test_score=3),
        fundamentals=f,
        balance_sheet=b,
        management=m,
        stress_test=s,
        cost_usd=0.42,
    )
    monkeypatch.setattr(orchestrator, "analyze_ticker_detailed", lambda t, **k: fake)

    diff, snap = tracking.run_track_status("NVDA")
    assert snap is not None
    assert diff.is_material  # -20 conviction and -3 stress
    assert diff.conviction_delta == -20.0
    # second snapshot recorded -> history has 2
    assert len(temp_store.list_snapshot_rows("NVDA")) == 2
    # run row recorded with cost
    runs = temp_store.list_runs()
    assert any(r.kind == "track_status" and r.cost_estimate_usd == 0.42 for r in runs)


def test_track_status_cannot_evaluate(temp_store, tmp_path, monkeypatch):
    from stock_agents import track as tracking
    from stock_agents.agents import orchestrator

    path = tmp_path / "e.json"
    path.write_text(_thesis().model_dump_json())
    tracking.track_add("NVDA", thesis_path=str(path))

    fake = orchestrator.CandidateAnalysis(
        ticker="NVDA", thesis=None, cost_usd=0.1, error="no data / delisted"
    )
    monkeypatch.setattr(orchestrator, "analyze_ticker_detailed", lambda t, **k: fake)
    diff, snap = tracking.run_track_status("NVDA")
    assert snap is None
    assert diff.status == "cannot_evaluate"
    assert diff.is_material


def test_track_status_untracked_raises(temp_store):
    from stock_agents import track as tracking

    with pytest.raises(tracking.TrackError):
        tracking.run_track_status("ZZZZ")


def test_load_entry_thesis_formats(tmp_path):
    from stock_agents.track import snapshots

    # bare thesis
    p = tmp_path / "bare.json"
    p.write_text(_thesis().model_dump_json())
    assert snapshots.load_entry_thesis(str(p), "NVDA").ticker == "NVDA"
