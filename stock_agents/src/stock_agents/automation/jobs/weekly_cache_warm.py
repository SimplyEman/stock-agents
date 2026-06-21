"""weekly_cache_warm job (v2 Phase 5).

Sundays 02:00. Pure cache warming — no agent runs, no LLM cost. Refreshes the
data layer for every active watchlist ticker plus ETF holdings for every theme,
so the Sunday batch and ad-hoc runs hit warm caches.
"""

from __future__ import annotations

import logging

from stock_agents.data import edgar, etf, fmp
from stock_agents.track import store

log = logging.getLogger("stock_agents.automation")


def run(**_kwargs) -> dict:
    tickers = [w.ticker for w in store.list_watchlist(include_exited=False) if w.status == "active"]
    warmed, ticker_errors = 0, 0
    for t in tickers:
        try:
            fmp.get_company_profile(t)
            fmp.get_income_statement(t, 5)
            fmp.get_balance_sheet(t, 5)
            fmp.get_cash_flow_statement(t, 5)
            cik = edgar.ticker_to_cik(t)
            edgar.get_insider_transactions(cik, months=24)
            tenk = edgar.get_recent_filings(cik, "10-K", limit=1)
            if tenk:
                edgar.fetch_filing_text(tenk[0], section="full")
            warmed += 1
        except Exception as exc:  # noqa: BLE001 - per-ticker resilience
            ticker_errors += 1
            log.warning("cache warm failed for %s: %s", t, exc)

    etfs = sorted({e for basket in etf.THEME_REGISTRY.values() for e in basket})
    etf_warmed, etf_errors = 0, 0
    for e in etfs:
        try:
            etf.get_etf_holdings(e)
            etf_warmed += 1
        except Exception as exc:  # noqa: BLE001
            etf_errors += 1
            log.warning("ETF holdings warm failed for %s: %s", e, exc)

    return {
        "tickers_warmed": warmed,
        "ticker_errors": ticker_errors,
        "etfs_warmed": etf_warmed,
        "etf_errors": etf_errors,
    }
