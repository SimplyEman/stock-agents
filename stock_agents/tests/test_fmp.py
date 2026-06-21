"""FMP client tests.

We monkeypatch ``fmp._get`` (the single HTTP chokepoint) to return canned
fixtures, then assert the normalization into typed models and the derived-metric
math are correct. No network access.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_agents.data import fmp, metrics

DATA = Path(__file__).parent / "test_data"


def _load(name: str):
    return json.loads((DATA / name).read_text())


@pytest.fixture
def patched_fmp(monkeypatch):
    income = _load("fmp_income_aapl.json")
    balance = _load("fmp_balance_aapl.json")
    cashflow = _load("fmp_cashflow_aapl.json")

    def fake_get(path: str, params=None):
        if path.startswith("income-statement"):
            return income
        if path.startswith("balance-sheet-statement"):
            return balance
        if path.startswith("cash-flow-statement"):
            return cashflow
        if path.startswith("profile"):
            return [{"companyName": "Apple Inc.", "sector": "Technology", "mktCap": 3.0e12, "ceo": "Timothy Cook", "cik": "320193"}]
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(fmp, "_get", fake_get)
    return fake_get


def test_income_statement_normalization(patched_fmp):
    series = fmp.get_income_statement("AAPL", 5)
    assert series.ticker == "AAPL"
    assert len(series.periods) == 5
    latest = series.periods[0]
    assert latest.fiscal_year == 2023
    assert latest.filed_date == "2023-11-03"
    assert latest.get("revenue") == 383285000000


def test_profile_typed(patched_fmp):
    profile = fmp.get_company_profile("AAPL")
    assert profile.name == "Apple Inc."
    assert profile.ceo == "Timothy Cook"
    assert profile.cik == "320193"


def test_derived_metrics(patched_fmp):
    income = fmp.get_income_statement("AAPL", 5)
    balance = fmp.get_balance_sheet("AAPL", 5)
    cash = fmp.get_cash_flow_statement("AAPL", 5)
    summary = metrics.summarize(income, balance, cash)

    # Gross margin 2023 = 169148/383285 = ~44.1%
    assert summary["gross_margin_latest"] == pytest.approx(44.13, abs=0.2)
    # Current ratio 2023 = 143566/145308 = ~0.988
    assert summary["current_ratio"] == pytest.approx(0.988, abs=0.01)
    # SBC % revenue 2023 = 10833/383285 = ~2.83%
    assert summary["sbc_pct_revenue"] == pytest.approx(2.83, abs=0.1)
    # Net debt/EBITDA: (111088 - 29965 - 31590)/129188 = ~0.383
    assert summary["net_debt_to_ebitda"] == pytest.approx(0.383, abs=0.02)
    # 5y revenue CAGR from 2019 (260174) to 2023 (383285) over 4 yrs ~ 10.2%
    assert summary["revenue_cagr_5y"] is None  # only 5 periods => index 5 missing
    assert summary["revenue_cagr_3y"] == pytest.approx(11.79, abs=0.5)


def test_as_of_filtering(patched_fmp):
    series = fmp.get_income_statement("AAPL", 5)
    # As of 2022-01-01 only FY2019/2020/2021 were filed.
    filtered = series.as_of("2022-01-01")
    years = {p.fiscal_year for p in filtered.periods}
    assert years == {2019, 2020, 2021}


def test_ratios_and_key_metrics(monkeypatch):
    rows = [
        {"date": "2023-09-30", "calendarYear": "2023", "period": "FY", "peRatio": 30.1, "roic": 0.55},
        {"date": "2022-09-30", "calendarYear": "2022", "period": "FY", "peRatio": 24.4, "roic": 0.50},
    ]
    monkeypatch.setattr(fmp, "_get", lambda path, params=None: rows)
    km = fmp.get_key_metrics("AAPL", 2)
    assert km.statement_type == "key_metrics"
    assert km.periods[0].get("peRatio") == 30.1
    assert km.periods[0].get("roic") == 0.55


def test_stock_screener(monkeypatch):
    monkeypatch.setattr(
        fmp,
        "_get",
        lambda path, params=None: [
            {"symbol": "NVDA", "companyName": "NVIDIA", "marketCap": 2.0e12, "sector": "Technology", "industry": "Semis"},
            {"symbol": "AMD", "companyName": "AMD", "marketCap": 2.5e11, "sector": "Technology", "industry": "Semis"},
        ],
    )
    cands = fmp.stock_screener(market_cap_more_than=1e9, sector="Technology")
    assert {c.ticker for c in cands} == {"NVDA", "AMD"}
    assert cands[0].market_cap_usd == 2.0e12


def test_peers(monkeypatch):
    # /stable stock-peers returns a flat list of peer rows (incl. the queried symbol).
    monkeypatch.setattr(
        fmp,
        "_get",
        lambda path, params=None: [
            {"symbol": "NVDA", "companyName": "NVIDIA", "mktCap": 2e12},
            {"symbol": "AMD", "companyName": "AMD", "mktCap": 2.5e11},
            {"symbol": "INTC", "companyName": "Intel", "mktCap": 1.5e11},
            {"symbol": "AVGO", "companyName": "Broadcom", "mktCap": 8e11},
        ],
    )
    # Queried symbol is excluded from its own peer list.
    assert fmp.get_peers("NVDA") == ["AMD", "INTC", "AVGO"]


def test_historical_prices_and_price_on(monkeypatch):
    # /stable historical-price-eod/full is a flat list with `close` (no adjClose).
    payload = [
        {"symbol": "NVDA", "date": "2021-01-04", "close": 130.0},
        {"symbol": "NVDA", "date": "2021-01-02", "close": 120.0},
        {"symbol": "NVDA", "date": "2020-12-31", "close": 110.0},
    ]
    monkeypatch.setattr(fmp, "_get", lambda path, params=None: payload)
    points = fmp.get_historical_prices("NVDA", "2020-12-31", "2021-01-04")
    assert len(points) == 3
    # price on 2021-01-03 should pick the latest close on/before -> 2021-01-02
    assert fmp.get_price_on("NVDA", "2021-01-03") == 120.0


def test_short_interest_flags_unavailable(monkeypatch):
    monkeypatch.setattr(fmp, "_get", lambda path, params=None: [{"marketCap": 2e12, "volume": 500}])
    si = fmp.get_short_interest("NVDA")
    assert si["market_cap"] == 2e12
    assert "unavailable" in si["note"]


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.setattr(fmp.settings, "fmp_api_key", "")
    with pytest.raises(fmp.FMPError):
        fmp._get("profile/AAPL")
