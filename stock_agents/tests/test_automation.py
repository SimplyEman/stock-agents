"""Job runner + notification layer (v2 Phase 4, offline)."""

from __future__ import annotations

import pytest

from stock_agents.notify import formatter
from stock_agents.notify.base import NotificationChannel
from stock_agents.track.models import Diff


@pytest.fixture
def temp_store(tmp_path, monkeypatch):
    from stock_agents.config import settings
    from stock_agents.track import store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    store.reset_engine()
    yield store
    store.reset_engine()


# --- runner ----------------------------------------------------------------


def test_job_registry():
    from stock_agents.automation import JOBS

    assert set(JOBS) == {
        "post_earnings",
        "eight_k_monitor",
        "weekly_cache_warm",
        "sunday_batch",
        "quarterly_retest",
    }
    for spec in JOBS.values():
        assert len(spec.cron.split()) == 5  # valid 5-field crontab


def test_run_job_success_writes_run(temp_store):
    from stock_agents.automation import run_job

    result = run_job("post_earnings")
    assert result["status"] == "success"
    runs = temp_store.list_runs()
    assert len(runs) == 1
    assert runs[0].kind == "post_earnings" and runs[0].status == "success"


def test_run_job_failure_writes_alert(temp_store, monkeypatch):
    from stock_agents.automation import runner

    monkeypatch.setattr(
        runner.JOBS["sunday_batch"], "func", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    # No channels configured -> emit_alert still records the alert row.
    result = runner.run_job("sunday_batch")
    assert result["status"] == "failed"
    runs = temp_store.list_runs()
    assert runs[0].status == "failed" and runs[0].error == "boom"
    alerts = temp_store.list_alerts()
    assert len(alerts) == 1
    assert alerts[0].kind == "run_failure" and alerts[0].severity == "important"


def test_unknown_job_raises():
    from stock_agents.automation import run_job

    with pytest.raises(KeyError):
        run_job("nope")


def test_generate_cron_snippet():
    from stock_agents.automation import generate_cron_snippet

    snip = generate_cron_snippet()
    for name in ("post_earnings", "eight_k_monitor", "weekly_cache_warm", "sunday_batch"):
        assert f"run-job {name}" in snip
    assert "0 6 * * *" in snip and "0 4 * * 0" in snip


def test_build_scheduler_registers_all():
    from stock_agents.automation import build_scheduler

    sch = build_scheduler()
    try:
        assert {j.id for j in sch.get_jobs()} == {
            "post_earnings",
            "eight_k_monitor",
            "weekly_cache_warm",
            "sunday_batch",
            "quarterly_retest",
        }
    finally:
        pass  # never started; nothing to shut down


# --- notifications ---------------------------------------------------------


class _FakeChannel(NotificationChannel):
    def __init__(self, name, ok=True, conf=True):
        self.name = name
        self._ok = ok
        self._conf = conf
        self.calls = []

    def configured(self):
        return self._conf

    def send(self, subject, short, html=None):
        self.calls.append((subject, short, html))
        return self._ok


def test_get_channels_selection(monkeypatch):
    from stock_agents import notify
    from stock_agents.config import settings

    monkeypatch.setattr(settings, "alert_channel", "both")
    assert {c.name for c in notify.get_channels()} == {"pushover", "email"}
    monkeypatch.setattr(settings, "alert_channel", "pushover")
    assert [c.name for c in notify.get_channels()] == ["pushover"]
    monkeypatch.setattr(settings, "alert_channel", "email")
    assert [c.name for c in notify.get_channels()] == ["email"]


def test_dispatch_skips_unconfigured(monkeypatch):
    from stock_agents import notify

    monkeypatch.setattr(
        notify,
        "get_channels",
        lambda: [
            _FakeChannel("pushover", ok=True, conf=True),
            _FakeChannel("email", ok=True, conf=False),
        ],
    )
    results = notify.dispatch("s", "short", "<p>h</p>")
    assert results == {"pushover": True, "email": False}


def test_emit_alert_records_and_delivers(temp_store, monkeypatch):
    from stock_agents import notify

    monkeypatch.setattr(notify, "get_channels", lambda: [_FakeChannel("pushover", ok=True)])
    notify.emit_alert(
        kind="earnings_diff", severity="notice", subject="s", short="x", ticker="NVDA"
    )
    alerts = temp_store.list_alerts()
    assert len(alerts) == 1 and alerts[0].delivered_at is not None  # delivered -> timestamp set


def test_pushover_send_false_when_unconfigured(monkeypatch):
    from stock_agents.config import settings
    from stock_agents.notify.pushover import PushoverChannel

    monkeypatch.setattr(settings, "pushover_user_key", "")
    ch = PushoverChannel()
    assert ch.configured() is False
    assert ch.send("s", "m") is False  # no network attempted


# --- formatter -------------------------------------------------------------


def test_format_diff_material():
    d = Diff(
        ticker="NVDA",
        from_snapshot_id="a",
        to_snapshot_id="b",
        conviction_from=80.0,
        conviction_to=60.0,
        conviction_delta=-20.0,
        component_deltas={"stress_test": -3},
        material_reasons=["conviction moved -20.0"],
    )
    subject, short, html = formatter.format_diff(d)
    assert "NVDA" in subject and "MATERIAL" in subject
    assert len(short) <= 240
    assert "stress_test" in html


def test_format_diff_cannot_evaluate():
    d = Diff(
        ticker="ZZZ",
        from_snapshot_id="a",
        to_snapshot_id=None,
        status="cannot_evaluate",
        material_reasons=["cannot_evaluate: delisted"],
    )
    subject, short, html = formatter.format_diff(d)
    assert "cannot evaluate" in subject


def test_format_eight_k_and_item_map():
    subject, short, html = formatter.format_eight_k("AAPL", "2.02,9.01", "https://sec.gov/x")
    assert "AAPL" in subject
    assert "Results of Operations" in subject or "Results of Operations" in html
    assert formatter.describe_items("5.02")[0].startswith("Item 5.02")


# --- Phase 5 job bodies ----------------------------------------------------


def _track(ticker="NVDA"):
    """Add an active watchlist row with a dummy entry snapshot path."""
    from stock_agents.track import store

    store.add_watchlist(ticker, entry_thesis_path="x.json", entry_conviction=70.0)


def test_weekly_cache_warm(temp_store, monkeypatch):
    from stock_agents.automation.jobs import weekly_cache_warm
    from stock_agents.data import edgar, etf, fmp
    from stock_agents.models.company import Filing

    _track("NVDA")
    _track("AMD")
    for fn in (
        "get_company_profile",
        "get_income_statement",
        "get_balance_sheet",
        "get_cash_flow_statement",
    ):
        monkeypatch.setattr(fmp, fn, lambda *a, **k: None)
    monkeypatch.setattr(edgar, "ticker_to_cik", lambda t: "0000000001")
    monkeypatch.setattr(edgar, "get_insider_transactions", lambda cik, months: [])
    monkeypatch.setattr(
        edgar,
        "get_recent_filings",
        lambda cik, form, limit=1: [
            Filing(accession_number="a", form_type="10-K", filing_date="2025-01-01")
        ],
    )
    monkeypatch.setattr(edgar, "fetch_filing_text", lambda f, section="full": "10-K text")
    monkeypatch.setattr(etf, "get_etf_holdings", lambda e: None)

    result = weekly_cache_warm.run()
    assert result["tickers_warmed"] == 2
    assert result["ticker_errors"] == 0
    assert result["etfs_warmed"] > 0  # THEME_REGISTRY ETFs


def test_post_earnings_material_alert(temp_store, monkeypatch):
    from stock_agents import track as tracking
    from stock_agents.automation.jobs import post_earnings
    from stock_agents.data import fmp

    _track("NVDA")
    _track("AMD")
    # Only NVDA reported in the last 24h.
    monkeypatch.setattr(fmp, "get_earnings_calendar", lambda f, t: [{"symbol": "NVDA"}])
    material = Diff(
        ticker="NVDA",
        from_snapshot_id="a",
        to_snapshot_id="b",
        conviction_from=80.0,
        conviction_to=60.0,
        conviction_delta=-20.0,
        material_reasons=["conviction moved -20.0"],
    )
    monkeypatch.setattr(tracking, "run_track_status", lambda t, **k: (material, None))

    result = post_earnings.run()
    assert result["reporters"] == 1 and result["processed"] == 1
    assert result["material_alerts"] == 1
    alerts = temp_store.list_alerts()
    assert any(a.kind == "earnings_diff" and a.severity == "important" for a in alerts)


def test_post_earnings_no_reporters(temp_store, monkeypatch):
    from stock_agents.automation.jobs import post_earnings
    from stock_agents.data import fmp

    _track("NVDA")
    monkeypatch.setattr(fmp, "get_earnings_calendar", lambda f, t: [{"symbol": "ZZZZ"}])
    result = post_earnings.run()
    assert result["reporters"] == 0 and result["processed"] == 0


def test_eight_k_monitor_alerts_and_dedups(temp_store, monkeypatch):
    from stock_agents.automation.jobs import eight_k_monitor
    from stock_agents.data import edgar

    _track("NVDA")
    monkeypatch.setattr(edgar, "ticker_to_cik", lambda t: "0001045810")
    entry = {
        "title": "8-K - NVIDIA CORP (0001045810) (Filer)",
        "link": "https://www.sec.gov/.../0001045810-26-000051-index.htm",
        "updated": "2026-05-20T16:05:00-04:00",
    }
    monkeypatch.setattr(eight_k_monitor, "_fetch_feed", lambda: [entry])
    monkeypatch.setattr(
        eight_k_monitor, "_items_and_url", lambda cik, acc, e: ("2.02,9.01", "https://sec.gov/x")
    )

    r1 = eight_k_monitor.run()
    assert r1["new_material"] == 1
    assert temp_store.is_eight_k_seen("0001045810-26-000051")
    # Second run: already seen -> no new material.
    r2 = eight_k_monitor.run()
    assert r2["new_material"] == 0


def test_eight_k_extract_helpers():
    from stock_agents.automation.jobs import eight_k_monitor as m

    e = {
        "title": "8-K - APPLE INC (0000320193) (Filer)",
        "link": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000011/0000320193-26-000011-index.htm",
    }
    assert m._extract_cik(e) == "0000320193"
    assert m._extract_accession(e) == "0000320193-26-000011"


def test_sunday_batch(temp_store, monkeypatch, tmp_path):
    from stock_agents.agents import orchestrator
    from stock_agents.automation.jobs import sunday_batch
    from stock_agents.models.thesis import FinalReport, InvestmentThesis

    monkeypatch.chdir(tmp_path)  # reports/ written under tmp

    def fake_analyze(theme, max_candidates=10):
        t = InvestmentThesis(
            ticker="NVDA",
            name="NVIDIA",
            one_paragraph_summary="s",
            bull_case=["b"],
            bear_case=["x"],
            what_would_change_my_mind="w",
            conviction_score=80.0,
            conviction_label="very high",
            fundamentals_score=9,
            balance_sheet_score=9,
            management_score=8,
            stress_test_score=7,
        )
        return FinalReport(
            theme=theme,
            run_timestamp="2026-05-27T00:00:00+00:00",
            candidates_analyzed=1,
            api_cost_usd=1.5,
            top_picks=[t],
            full_results=[t],
        )

    monkeypatch.setattr(orchestrator, "analyze_theme", fake_analyze)
    result = sunday_batch.run(themes=["AI infrastructure"], max_candidates=2)
    assert result["completed"] == ["AI infrastructure"]
    assert result["spent_usd"] == 1.5
    # report written + digest alert emitted
    assert (tmp_path / "reports" / "batch").exists()
    assert any(a.message.startswith("Weekly research digest") for a in temp_store.list_alerts())


def test_sunday_batch_theme_diff():
    from stock_agents.automation.jobs.sunday_batch import _theme_diff

    cur = {
        "top_picks": [
            {"ticker": "NVDA", "conviction_score": 80},
            {"ticker": "AMD", "conviction_score": 60},
        ]
    }
    prev = {
        "top_picks": [
            {"ticker": "NVDA", "conviction_score": 60},
            {"ticker": "INTC", "conviction_score": 55},
        ]
    }
    d = _theme_diff("semis", cur, prev)
    assert d["new_entries"] == ["AMD"]
    assert d["dropouts"] == ["INTC"]
    assert (
        d["conviction_shifts"][0]["ticker"] == "NVDA" and d["conviction_shifts"][0]["delta"] == 20.0
    )
