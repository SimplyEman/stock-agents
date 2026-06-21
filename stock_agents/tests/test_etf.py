"""ETF scraper tests (offline) — exercise CSV parsing and dispatch."""

from __future__ import annotations

import pytest

from stock_agents.data import etf

ARK_CSV = """date,fund,company,ticker,cusip,shares,market value ($),weight (%)
04/01/2024,ARKK,TESLA INC,TSLA,88160R101,3000000,540000000,8.50
04/01/2024,ARKK,ROKU INC,ROKU,77543R102,4000000,250000000,4.20
04/01/2024,ARKK,,,,,,
"""

ISHARES_CSV = """
iShares Fund,,,
Holdings as of,"Apr 01, 2024",,
\x20
"Ticker","Name","Sector","Weight (%)"
"NVDA","NVIDIA CORP","Information Technology","9.50"
"AVGO","BROADCOM INC","Information Technology","8.10"
"-","Cash","Cash","0.50"
"""


def test_scrape_ark(monkeypatch):
    monkeypatch.setattr(etf, "_get_text", lambda url, params=None: ARK_CSV)
    result = etf._scrape_ark("ARKK")
    tickers = [h.ticker for h in result.holdings]
    assert tickers == ["TSLA", "ROKU"]  # blank row dropped
    assert result.holdings[0].weight_pct == pytest.approx(8.5)


def test_scrape_ishares(monkeypatch):
    monkeypatch.setattr(etf, "_get_text", lambda url, params=None: ISHARES_CSV)
    result = etf._scrape_ishares("SOXX")
    tickers = [h.ticker for h in result.holdings]
    assert "NVDA" in tickers and "AVGO" in tickers
    assert "-" not in tickers  # cash row dropped
    assert result.holdings[0].weight_pct == pytest.approx(9.5)


def test_get_etf_holdings_sorts_and_truncates(monkeypatch):
    monkeypatch.setattr(etf, "_get_text", lambda url, params=None: ARK_CSV)
    holdings = etf.get_etf_holdings("ARKK", top_n=1)
    assert len(holdings.holdings) == 1
    assert holdings.holdings[0].ticker == "TSLA"  # highest weight first


def test_fallback_to_fmp_on_failure(monkeypatch):
    # Force the bespoke scraper to fail, expect FMP fallback to be used.
    monkeypatch.setattr(etf, "_get_text", lambda url, params=None: "garbage,no,header")

    def fake_fmp_fallback(symbol):
        from stock_agents.models.company import ETFHolding, ETFHoldings

        return ETFHoldings(
            etf_ticker=symbol, holdings=[ETFHolding(ticker="FALLBACK", weight_pct=1.0)]
        )

    monkeypatch.setattr(etf, "_scrape_fmp_fallback", fake_fmp_fallback)
    holdings = etf.get_etf_holdings("ARKK")
    assert holdings.holdings[0].ticker == "FALLBACK"


def test_etfs_for_theme_variants():
    assert etf.etfs_for_theme("cybersecurity") == etf.THEME_REGISTRY["cybersecurity"]
    assert etf.etfs_for_theme("clean energy")  # space normalized
    assert etf.etfs_for_theme("totally unknown theme xyz") == []
