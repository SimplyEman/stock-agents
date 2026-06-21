"""Point-in-time discipline for backtests.

The core mechanism is :class:`ToolContext` with an ``as_of`` date — handlers
slice statement series to filings dated before it, drop forward-looking analyst
estimates, suppress current market caps, and (via the agents) disable web search.
This module adds the as-of helpers and forward-return math the harness needs.

Known limitations (documented honestly in the README):
- Web search has no point-in-time equivalent and is disabled in backtests.
- FMP fundamentals carry filed dates, but corporate actions / restatements can
  still leak; treat backtest results as indicative, not audit-grade.
"""

from __future__ import annotations

import datetime as dt

from stock_agents.data import fmp
from stock_agents.tools.handlers import ToolContext


def as_of_context(date: str) -> ToolContext:
    """Build a point-in-time context for the given ISO date."""
    return ToolContext(as_of=date, allow_web=False)


def was_investable_on(ticker: str, as_of: str) -> bool:
    """True if ``ticker`` was a public, tradable company on/before ``as_of``.

    This is the point-in-time *universe* filter that stops the LLM screener from
    selecting companies that had not yet IPO'd at the backtest date (e.g. CoreWeave
    for a 2020 backtest). It complements — does not replace — the existing
    filing-date discipline, which constrains the financial *data* but not which
    names the screener may pick.

    Two free signals, both from FMP data already wired in:
    - A close price exists on/before ``as_of`` (ground truth that it traded). We
      widen the lookback to absorb data gaps / holidays and avoid false excludes.
    - The profile ``ipoDate`` is present and <= ``as_of`` (definitive IPO gate).

    A name passes if EITHER signal says investable; it is rejected only when both
    say it was not yet public. Errors are treated as "investable" (fail-open) so a
    flaky data call never silently shrinks the universe.
    """
    try:
        ipo = fmp.get_ipo_date(ticker)
    except Exception:
        ipo = None
    if ipo and ipo <= as_of:
        return True
    if ipo and ipo > as_of:
        # IPO is definitively after the as-of date -> not investable.
        return False
    # No usable ipoDate: fall back to price availability (wide lookback).
    try:
        return fmp.get_price_on(ticker, as_of, lookback_days=45) is not None
    except Exception:
        return True  # fail-open rather than silently dropping a real name


def filter_to_investable(tickers: list[str], as_of: str) -> tuple[list[str], list[str]]:
    """Split tickers into (investable, excluded) as of ``as_of``."""
    keep, drop = [], []
    for t in tickers:
        (keep if was_investable_on(t, as_of) else drop).append(t)
    return keep, drop


def forward_return(ticker: str, start_date: str, years: int) -> float | None:
    """Total price return over ``years`` from ``start_date`` (adjusted closes).

    Returns ``None`` when either endpoint price is unavailable (e.g. the company
    was delisted — which is itself informative and surfaced by the harness).
    """
    start_price = fmp.get_price_on(ticker, start_date)
    if not start_price:
        return None
    end = (dt.date.fromisoformat(start_date) + dt.timedelta(days=round(365.25 * years))).isoformat()
    # Don't peek past today.
    today = dt.date.today().isoformat()
    if end > today:
        return None
    end_price = fmp.get_price_on(ticker, end)
    if not end_price:
        return None
    return (end_price / start_price - 1.0) * 100.0


def benchmark_return(etf_ticker: str, start_date: str, years: int) -> float | None:
    return forward_return(etf_ticker, start_date, years)
