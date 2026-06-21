"""Backtesting + point-in-time discipline tests (offline)."""

from __future__ import annotations

import pytest

from stock_agents.backtesting import point_in_time as pit
from stock_agents.data import etf, fmp
from stock_agents.data.etf import etfs_for_theme
from stock_agents.models.company import FinancialPeriod, StatementSeries


def test_as_of_context_disables_web():
    ctx = pit.as_of_context("2018-01-01")
    assert ctx.as_of == "2018-01-01"
    assert ctx.allow_web is False


def test_statement_series_as_of_drops_undated_and_future():
    series = StatementSeries(
        ticker="X",
        statement_type="income",
        periods=[
            FinancialPeriod(fiscal_year=2020, filed_date="2021-02-01", line_items={"revenue": 100}),
            FinancialPeriod(fiscal_year=2017, filed_date="2018-02-01", line_items={"revenue": 50}),
            FinancialPeriod(fiscal_year=2016, filed_date=None, line_items={"revenue": 40}),
        ],
    )
    filtered = series.as_of("2019-01-01")
    assert [p.fiscal_year for p in filtered.periods] == [2017]


def test_forward_return(monkeypatch):
    # Start price at the as-of date; end price one year later.
    monkeypatch.setattr(
        fmp,
        "get_price_on",
        lambda t, d: 60.0 if d == "2020-01-02" else (130.0 if d >= "2021-01-01" else None),
    )
    ret = pit.forward_return("NVDA", "2020-01-02", 1)
    assert ret == pytest.approx((130.0 / 60.0 - 1) * 100, abs=0.01)


def test_forward_return_delisted(monkeypatch):
    monkeypatch.setattr(fmp, "get_price_on", lambda t, d: None)
    assert pit.forward_return("DEAD", "2018-01-01", 1) is None


def test_was_investable_on_rejects_future_ipo(monkeypatch):
    # CoreWeave-style: IPO after the as-of date, no price -> excluded.
    monkeypatch.setattr(fmp, "get_ipo_date", lambda t: "2025-03-28")
    monkeypatch.setattr(fmp, "get_price_on", lambda t, d, lookback_days=45: None)
    assert pit.was_investable_on("CRWV", "2020-01-01") is False


def test_was_investable_on_accepts_existing(monkeypatch):
    monkeypatch.setattr(fmp, "get_ipo_date", lambda t: "2019-06-12")
    assert pit.was_investable_on("CRWD", "2020-01-01") is True


def test_was_investable_on_price_fallback(monkeypatch):
    # No ipoDate, but a price existed on/before as-of -> investable.
    monkeypatch.setattr(fmp, "get_ipo_date", lambda t: None)
    monkeypatch.setattr(fmp, "get_price_on", lambda t, d, lookback_days=45: 42.0)
    assert pit.was_investable_on("OLDCO", "2018-01-01") is True


def test_was_investable_fail_open(monkeypatch):
    # Data errors must not silently shrink the universe (fail-open).
    def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(fmp, "get_ipo_date", boom)
    monkeypatch.setattr(fmp, "get_price_on", boom)
    assert pit.was_investable_on("FLAKY", "2018-01-01") is True


def test_filter_to_investable_splits(monkeypatch):
    monkeypatch.setattr(pit, "was_investable_on", lambda t, d: t in {"CRM", "NOW"})
    keep, drop = pit.filter_to_investable(["CRM", "CRWV", "NOW", "PLTR"], "2020-01-01")
    assert keep == ["CRM", "NOW"]
    assert drop == ["CRWV", "PLTR"]


def test_theme_registry_lookup():
    assert "SMH" in etfs_for_theme("ai_infrastructure")
    assert "SMH" in etfs_for_theme("AI Infrastructure")  # fuzzy
    assert etfs_for_theme("biotech") == etf.THEME_REGISTRY["biotech"]


# --- live integration (skipped without keys) --------------------------------

from tests.conftest import requires_anthropic, requires_fmp  # noqa: E402


@requires_anthropic
@requires_fmp
def test_backtest_cloud_software_2020():
    """Top picks as of 2020-01-01 should surface a recognizable cloud name."""
    from stock_agents.backtesting.harness import run_backtest

    result = run_backtest("cloud_software", "2020-01-01", max_candidates=8)
    tickers = {r.ticker for r in result.rows}
    assert tickers & {"CRM", "NOW", "SNOW", "NET", "DDOG"}
