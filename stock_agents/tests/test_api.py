"""FastAPI backend tests (offline: temp DB, TestClient, mocked orchestrator)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stock_agents.api.main import app
from stock_agents.models.thesis import InvestmentThesis


@pytest.fixture
def client(tmp_path, monkeypatch):
    from stock_agents.config import settings
    from stock_agents.track import store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    store.reset_engine()
    with TestClient(app) as c:
        yield c
    store.reset_engine()


def _thesis(ticker="NVDA", conviction=70.0) -> InvestmentThesis:
    return InvestmentThesis(
        ticker=ticker, name="NVIDIA", one_paragraph_summary="s", bull_case=["b"],
        bear_case=["x"], what_would_change_my_mind="w", conviction_score=conviction,
        conviction_label="high", fundamentals_score=8, balance_sheet_score=8,
        management_score=7, stress_test_score=6,
    )


def _track_via_report(client, tmp_path, ticker="NVDA"):
    from stock_agents.models.thesis import FinalReport

    report = FinalReport(theme="ai", run_timestamp="2026-01-01T00:00:00+00:00",
                         candidates_analyzed=1, api_cost_usd=1.0,
                         top_picks=[_thesis(ticker)], full_results=[_thesis(ticker)])
    path = tmp_path / f"{ticker}.json"
    path.write_text(report.model_dump_json())
    return client.post("/api/watchlist", json={"ticker": ticker, "thesis_path": str(path)})


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_watchlist_add_and_list(client, tmp_path):
    r = _track_via_report(client, tmp_path, "NVDA")
    assert r.status_code == 201
    assert r.json()["ticker"] == "NVDA"
    rows = client.get("/api/watchlist").json()
    assert len(rows) == 1
    assert rows[0]["entry_conviction"] == 70.0
    assert rows[0]["current_conviction"] == 70.0  # entry snapshot


def test_watchlist_history(client, tmp_path):
    _track_via_report(client, tmp_path, "NVDA")
    hist = client.get("/api/watchlist/NVDA/history").json()
    assert len(hist) == 1
    assert hist[0]["conviction"] == 70.0


def test_untrack(client, tmp_path):
    _track_via_report(client, tmp_path, "NVDA")
    r = client.delete("/api/watchlist/NVDA")
    assert r.json()["status"] == "exited"


def test_untrack_unknown_404(client):
    assert client.delete("/api/watchlist/ZZZZ").status_code == 404


def test_refresh_returns_run_id(client, tmp_path, monkeypatch):
    from stock_agents import track as tracking

    _track_via_report(client, tmp_path, "NVDA")
    # Make the background track-status a no-op so the test stays offline/fast.
    monkeypatch.setattr(tracking, "run_track_status", lambda t, **k: (None, None))
    r = client.post("/api/watchlist/NVDA/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running" and body["run_id"]
    # the pre-created run row is visible in /api/runs
    runs = client.get("/api/runs").json()
    assert any(run["id"] == body["run_id"] and run["kind"] == "track_status" for run in runs)


def test_analyze_returns_run_id_and_report(client, monkeypatch):
    from stock_agents.agents import orchestrator
    from stock_agents.models.thesis import FinalReport

    def fake_analyze(theme, max_candidates=5, **k):
        return FinalReport(theme=theme, run_timestamp="2026-01-01T00:00:00+00:00",
                           candidates_analyzed=1, api_cost_usd=2.0,
                           top_picks=[_thesis()], full_results=[_thesis()])

    monkeypatch.setattr(orchestrator, "analyze_theme", fake_analyze)
    r = client.post("/api/themes/ai_infrastructure/analyze?max_candidates=2")
    run_id = r.json()["run_id"]
    # TestClient runs background tasks synchronously after the response.
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "success" and run["cost_estimate_usd"] == 2.0
    report = client.get(f"/api/runs/{run_id}/report").json()
    assert report["theme"] == "ai_infrastructure"
    assert report["top_picks"][0]["ticker"] == "NVDA"


def test_analyze_forwards_filter_and_forensic_kwargs(client, monkeypatch):
    """Cap/momentum/forensic params on the analyze endpoint reach the orchestrator."""
    from stock_agents.agents import orchestrator
    from stock_agents.data import fmp
    from stock_agents.models.thesis import FinalReport

    captured = {}

    def fake_analyze(theme, max_candidates=5, asym=None, forensic=False, **k):
        captured["asym"] = asym
        captured["forensic"] = forensic
        captured["max_candidates"] = max_candidates
        return FinalReport(theme=theme, run_timestamp="2026-01-01T00:00:00+00:00",
                           candidates_analyzed=0, api_cost_usd=0.0)

    monkeypatch.setattr(orchestrator, "analyze_theme", fake_analyze)
    monkeypatch.setattr(fmp, "get_fx_rate", lambda *_a, **_k: 1.27)

    client.post(
        "/api/themes/x/analyze"
        "?max_candidates=5&forensic=true&max_market_cap_gbp=3000000000"
        "&max_12m_return_pct=100&currency=gbp"
    )

    assert captured["forensic"] is True
    assert captured["max_candidates"] == 5
    f = captured["asym"]
    assert f is not None and f.active
    assert f.max_12m_return_pct == 100
    # £3B at 1.27 USD/GBP -> ~$3.81B ceiling
    assert abs(f.max_cap_usd - 3_810_000_000) < 1_000_000


def test_themes_list(client):
    themes = client.get("/api/themes").json()
    names = {t["theme"] for t in themes}
    assert "ai_infrastructure" in names and "biotech" in names
    assert all("etfs" in t for t in themes)


def test_alerts_and_ack(client):
    from stock_agents.track import store

    a = store.add_alert(kind="eight_k", severity="notice", message="test", ticker="NVDA")
    alerts = client.get("/api/alerts?status=unread").json()
    assert any(al["id"] == a.id for al in alerts)
    acked = client.post(f"/api/alerts/{a.id}/ack").json()
    assert acked["acknowledged_at"] is not None
    # now excluded from unread
    assert not any(al["id"] == a.id for al in client.get("/api/alerts?status=unread").json())


def test_settings_get_masks_secrets_and_post_persists(client):
    s = client.get("/api/settings").json()
    assert set(s["keys_configured"]) >= {"anthropic", "fmp", "pushover"}
    assert isinstance(s["keys_configured"]["anthropic"], bool)  # masked: bool not value
    assert "batch_themes" in s
    upd = client.post("/api/settings", json={"alert_channel": "both", "batch_themes": ["x", "y"]})
    assert upd.json()["alert_channel"] == "both"
    assert client.get("/api/settings").json()["batch_themes"] == ["x", "y"]


def test_thesis_detail(client, tmp_path):
    _track_via_report(client, tmp_path, "NVDA")
    hist = client.get("/api/watchlist/NVDA/history").json()
    snap_id = hist[0]["id"]
    detail = client.get(f"/api/thesis/{snap_id}").json()
    assert detail["thesis"]["ticker"] == "NVDA"
