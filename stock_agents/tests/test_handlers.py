"""Tool handler tests (offline).

Handlers are the bridge between Claude tool calls and the data layer. We patch
the data layer and assert handlers return well-formed JSON and honor the
point-in-time context.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_agents.data import edgar, etf, fmp, tiingo
from stock_agents.tools import handlers
from stock_agents.tools.handlers import ToolContext

DATA = Path(__file__).parent / "test_data"


@pytest.fixture
def patched_fmp(monkeypatch):
    income = json.loads((DATA / "fmp_income_aapl.json").read_text())
    balance = json.loads((DATA / "fmp_balance_aapl.json").read_text())
    cashflow = json.loads((DATA / "fmp_cashflow_aapl.json").read_text())

    def fake_get(path, params=None):
        if path.startswith("income-statement"):
            return income
        if path.startswith("balance-sheet-statement"):
            return balance
        if path.startswith("cash-flow-statement"):
            return cashflow
        return []

    monkeypatch.setattr(fmp, "_get", fake_get)


def test_income_handler_includes_derived(patched_fmp):
    out = json.loads(handlers.h_income_statement({"ticker": "AAPL", "years": 5}, ToolContext()))
    assert out["ticker"] == "AAPL"
    assert "derived_metrics" in out
    assert out["derived_metrics"]["gross_margin_latest"] == pytest.approx(44.13, abs=0.3)
    assert len(out["periods"]) == 5


def test_income_handler_point_in_time(patched_fmp):
    out = json.loads(
        handlers.h_income_statement({"ticker": "AAPL"}, ToolContext(as_of="2022-01-01"))
    )
    years = {p["fiscal_year"] for p in out["periods"]}
    assert years == {2019, 2020, 2021}


def test_analyst_estimates_disabled_in_backtest():
    out = json.loads(handlers.h_analyst_estimates({"ticker": "AAPL"}, ToolContext(as_of="2018-01-01")))
    assert "disabled" in out["note"]


def test_search_thematic_etfs_handler():
    out = json.loads(handlers.h_search_thematic_etfs({"theme": "biotech"}, ToolContext()))
    assert "IBB" in out["etfs"]
    assert "registry_themes" in out


def test_insider_transactions_handler(monkeypatch):
    from stock_agents.models.company import InsiderTransaction

    monkeypatch.setattr(edgar, "ticker_to_cik", lambda t: "0000320193")
    monkeypatch.setattr(
        edgar,
        "get_insider_transactions",
        lambda cik, months: [
            InsiderTransaction(filer_name="A", transaction_date="2024-04-01", transaction_type="S", is_open_market=True, value_usd=-1000.0),
            InsiderTransaction(filer_name="B", transaction_date="2024-02-01", transaction_type="P", is_open_market=True, value_usd=500.0),
        ],
    )
    out = json.loads(handlers.h_insider_transactions({"ticker": "AAPL", "months": 24}, ToolContext()))
    assert out["net_usd_all"] == pytest.approx(-500.0)
    assert out["net_usd_open_market"] == pytest.approx(-500.0)
    assert out["transaction_count"] == 2


def test_etf_holdings_handler(monkeypatch):
    from stock_agents.models.company import ETFHolding, ETFHoldings

    monkeypatch.setattr(
        etf,
        "get_etf_holdings",
        lambda t, top_n=25: ETFHoldings(etf_ticker=t, holdings=[ETFHolding(ticker="NVDA", weight_pct=9.0)]),
    )
    out = json.loads(handlers.h_etf_holdings({"etf_ticker": "SOXX", "top_n": 25}, ToolContext()))
    assert out["holdings"][0]["ticker"] == "NVDA"


def test_get_handlers_excludes_web_search():
    h = handlers.get_handlers(["get_income_statement", "web_search"])
    assert "get_income_statement" in h
    assert "web_search" not in h


def test_tiingo_returns_empty_without_key(monkeypatch):
    monkeypatch.setattr(tiingo.settings, "tiingo_api_key", "")
    assert tiingo.get_news("AAPL") == []
