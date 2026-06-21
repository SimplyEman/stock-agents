"""Financial Modeling Prep (FMP) client.

Wraps the handful of FMP endpoints the analysts need, returning typed Pydantic
models rather than raw dicts. Every call is rate-limited, retried, and cached.

FMP line-item names are normalized into the generic keys defined below so the
analyst agents and ratio helpers don't depend on FMP's exact JSON field names.
"""

from __future__ import annotations

from typing import Any

import httpx

from stock_agents.config import settings
from stock_agents.data import cache
from stock_agents.data._http import RateLimiter, raise_for_retryable_status, with_retries
from stock_agents.models.company import (
    Candidate,
    CompanyProfile,
    FinancialPeriod,
    PricePoint,
    StatementSeries,
)

# Free tier is ~300 calls/min; throttle to a safe ~4 req/s.
_limiter = RateLimiter(max_per_second=4.0)


class FMPError(RuntimeError):
    pass


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    params = dict(params or {})
    if not settings.fmp_api_key:
        raise FMPError("FMP_API_KEY is not set")
    params["apikey"] = settings.fmp_api_key

    @with_retries
    def _do() -> Any:
        _limiter.acquire()
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{settings.fmp_base_url}/{path}", params=params)
            raise_for_retryable_status(resp)
            if resp.status_code != 200:
                raise FMPError(f"FMP {path} -> {resp.status_code}: {resp.text[:200]}")
            return resp.json()

    return _do()


# ---------------------------------------------------------------------------
# Line-item normalization
# ---------------------------------------------------------------------------

# Map our generic keys -> the FMP JSON field that holds them.
_INCOME_FIELDS = {
    "revenue": "revenue",
    "cost_of_revenue": "costOfRevenue",
    "gross_profit": "grossProfit",
    "operating_income": "operatingIncome",
    "ebitda": "ebitda",
    "net_income": "netIncome",
    "interest_expense": "interestExpense",
    "rnd_expense": "researchAndDevelopmentExpenses",
    "weighted_shares_diluted": "weightedAverageShsOutDil",
}
_BALANCE_FIELDS = {
    "total_assets": "totalAssets",
    "total_debt": "totalDebt",
    "cash_and_equivalents": "cashAndCashEquivalents",
    "short_term_investments": "shortTermInvestments",
    "total_current_assets": "totalCurrentAssets",
    "total_current_liabilities": "totalCurrentLiabilities",
    "goodwill": "goodwill",
    "goodwill_and_intangibles": "goodwillAndIntangibleAssets",
    "total_stockholders_equity": "totalStockholdersEquity",
}
_CASHFLOW_FIELDS = {
    "operating_cash_flow": "operatingCashFlow",
    "capex": "capitalExpenditure",
    "free_cash_flow": "freeCashFlow",
    "stock_based_compensation": "stockBasedCompensation",
    "net_income": "netIncome",
    "common_stock_repurchased": "commonStockRepurchased",
    # /stable renamed dividendsPaid -> netDividendsPaid (older payloads may still
    # carry the legacy key, so accept either via _first_present below).
    "dividends_paid": "netDividendsPaid",
    "acquisitions_net": "acquisitionsNet",
}

# Legacy -> stable key aliases applied when the primary key is absent.
_FIELD_ALIASES = {
    "netDividendsPaid": "dividendsPaid",
}


def _to_period(row: dict[str, Any], fields: dict[str, str]) -> FinancialPeriod:
    line_items: dict[str, float | None] = {}
    for generic, fmp_key in fields.items():
        val = row.get(fmp_key)
        if val is None and fmp_key in _FIELD_ALIASES:
            val = row.get(_FIELD_ALIASES[fmp_key])
        line_items[generic] = float(val) if isinstance(val, (int, float)) else None
    return FinancialPeriod(
        # /stable uses fiscalYear / filingDate (legacy used calendarYear / fillingDate).
        fiscal_year=int(
            row.get("fiscalYear") or row.get("calendarYear") or row.get("date", "0")[:4] or 0
        ),
        period=str(row.get("period", "FY")),
        date=str(row.get("date", "")),
        filed_date=(
            row.get("filingDate")
            or row.get("fillingDate")
            or row.get("acceptedDate")
            or row.get("date")
        ),
        reported_currency=str(row.get("reportedCurrency", "USD")),
        line_items=line_items,
    )


def _statement(ticker: str, path: str, kind: str, fields: dict[str, str], years: int) -> StatementSeries:
    rows = cache.cached_call(
        path,
        {"symbol": ticker, "period": "annual", "limit": years},
        lambda: _get(path, {"symbol": ticker, "period": "annual", "limit": years}),
        ttl=cache.TTL_FUNDAMENTALS,
    )
    if not isinstance(rows, list):
        rows = []
    periods = [_to_period(r, fields) for r in rows]
    return StatementSeries(ticker=ticker.upper(), statement_type=kind, periods=periods)


def get_income_statement(ticker: str, years: int = 10) -> StatementSeries:
    return _statement(ticker, "income-statement", "income", _INCOME_FIELDS, years)


def get_balance_sheet(ticker: str, years: int = 10) -> StatementSeries:
    return _statement(ticker, "balance-sheet-statement", "balance_sheet", _BALANCE_FIELDS, years)


def get_cash_flow_statement(ticker: str, years: int = 10) -> StatementSeries:
    return _statement(ticker, "cash-flow-statement", "cash_flow", _CASHFLOW_FIELDS, years)


def get_company_profile(ticker: str) -> CompanyProfile:
    rows = cache.cached_call(
        "profile",
        {"symbol": ticker},
        lambda: _get("profile", {"symbol": ticker}),
        ttl=cache.TTL_FUNDAMENTALS,
    )
    row = rows[0] if isinstance(rows, list) and rows else {}
    return CompanyProfile(
        ticker=ticker.upper(),
        name=str(row.get("companyName", "")),
        sector=str(row.get("sector", "")),
        industry=str(row.get("industry", "")),
        # /stable: marketCap (legacy used mktCap); exchange (legacy: exchangeShortName).
        market_cap_usd=float(row.get("marketCap", row.get("mktCap", 0)) or 0),
        ceo=str(row.get("ceo", "")),
        description=str(row.get("description", "")),
        country=str(row.get("country", "")),
        exchange=str(row.get("exchange", row.get("exchangeShortName", ""))),
        cik=str(row["cik"]) if row.get("cik") else None,
    )


def stock_screener(
    *,
    market_cap_more_than: float | None = None,
    market_cap_lower_than: float | None = None,
    sector: str | None = None,
    limit: int = 100,
) -> list[Candidate]:
    params: dict[str, Any] = {"limit": limit, "isActivelyTrading": "true"}
    if market_cap_more_than is not None:
        params["marketCapMoreThan"] = int(market_cap_more_than)
    if market_cap_lower_than is not None:
        params["marketCapLowerThan"] = int(market_cap_lower_than)
    if sector:
        params["sector"] = sector
    rows = cache.cached_call(
        "company-screener",
        params,
        lambda: _get("company-screener", params),
        ttl=cache.TTL_FUNDAMENTALS,
    )
    out: list[Candidate] = []
    for r in rows if isinstance(rows, list) else []:
        out.append(
            Candidate(
                ticker=str(r.get("symbol", "")),
                name=str(r.get("companyName", "")),
                market_cap_usd=float(r.get("marketCap", 0) or 0),
                sector=str(r.get("sector", "")),
                industry=str(r.get("industry", "")),
            )
        )
    return out


def get_historical_prices(ticker: str, from_date: str, to_date: str) -> list[PricePoint]:
    # /stable: historical-price-eod/full returns a flat list with `close`. There
    # is no `adjClose` on this endpoint/plan, so adj_close is left None and
    # downstream return math falls back to close (a documented backtest caveat).
    rows = cache.cached_call(
        "historical-price-eod/full",
        {"symbol": ticker, "from": from_date, "to": to_date},
        lambda: _get(
            "historical-price-eod/full", {"symbol": ticker, "from": from_date, "to": to_date}
        ),
        ttl=cache.TTL_PRICES,
        datestamp=False,  # bounded by from/to, doesn't change with wall clock
    )
    if not isinstance(rows, list):
        rows = []
    return [
        PricePoint(
            date=str(r.get("date", "")),
            close=float(r.get("close", 0) or 0),
            adj_close=float(r["adjClose"]) if r.get("adjClose") is not None else None,
        )
        for r in rows
    ]


def _ratio_series(ticker: str, path: str, kind: str, years: int) -> StatementSeries:
    """Ratios / key-metrics come as flat dicts; pass numeric fields through."""
    rows = cache.cached_call(
        path,
        {"symbol": ticker, "period": "annual", "limit": years},
        lambda: _get(path, {"symbol": ticker, "period": "annual", "limit": years}),
        ttl=cache.TTL_FUNDAMENTALS,
    )
    periods: list[FinancialPeriod] = []
    for r in rows if isinstance(rows, list) else []:
        line_items = {
            k: float(v) for k, v in r.items() if isinstance(v, (int, float))
        }
        periods.append(
            FinancialPeriod(
                fiscal_year=int(
                    r.get("fiscalYear") or r.get("calendarYear") or r.get("date", "0")[:4] or 0
                ),
                period=str(r.get("period", "FY")),
                date=str(r.get("date", "")),
                filed_date=r.get("date"),
                line_items=line_items,
            )
        )
    return StatementSeries(ticker=ticker.upper(), statement_type=kind, periods=periods)


def get_ratios(ticker: str, years: int = 10) -> StatementSeries:
    return _ratio_series(ticker, "ratios", "ratios", years)


def get_key_metrics(ticker: str, years: int = 10) -> StatementSeries:
    return _ratio_series(ticker, "key-metrics", "key_metrics", years)


def get_peers(ticker: str) -> list[str]:
    # /stable stock-peers returns a flat list of peer rows: [{symbol, companyName,
    # price, mktCap}, ...]. Exclude the queried symbol itself and cap at 5.
    data = cache.cached_call(
        "stock-peers",
        {"symbol": ticker},
        lambda: _get("stock-peers", {"symbol": ticker}),
        ttl=cache.TTL_FUNDAMENTALS,
    )
    if not isinstance(data, list):
        return []
    syms = [str(r.get("symbol", "")) for r in data if r.get("symbol")]
    return [s for s in syms if s.upper() != ticker.upper()][:5]


def get_analyst_estimates(ticker: str, years: int = 3) -> list[dict[str, Any]]:
    rows = cache.cached_call(
        "analyst-estimates",
        {"symbol": ticker, "limit": years},
        lambda: _get("analyst-estimates", {"symbol": ticker, "period": "annual", "limit": years}),
        ttl=cache.TTL_FUNDAMENTALS,
    )
    return rows if isinstance(rows, list) else []


def get_fx_rate(pair: str = "GBPUSD") -> float | None:
    """Latest FX rate for ``pair`` (e.g. GBPUSD -> USD per 1 GBP), cached daily."""
    rows = cache.cached_call(
        "fx_quote",
        {"symbol": pair},
        lambda: _get("quote", {"symbol": pair}),
        ttl=cache.TTL_FUNDAMENTALS,
    )
    row = rows[0] if isinstance(rows, list) and rows else {}
    price = row.get("price")
    return float(price) if isinstance(price, (int, float)) and price else None


def get_12m_return_pct(ticker: str) -> float | None:
    """Trailing 12-month total price return (%, adj close-based). None on missing data.

    Used by the anti-momentum universe filter to drop names that already ran.
    """
    import datetime as _dt

    today = _dt.date.today()
    year_ago = (today - _dt.timedelta(days=365)).isoformat()
    p_now = get_quote_price(ticker)
    p_then = get_price_on(ticker, year_ago, lookback_days=30)
    if not p_now or not p_then:
        return None
    return (p_now / p_then - 1.0) * 100.0


def get_quote_price(ticker: str) -> float | None:
    """Latest share price for a ticker (used by the optional price filter)."""
    rows = cache.cached_call(
        "quote_price",
        {"symbol": ticker},
        lambda: _get("quote", {"symbol": ticker}),
        ttl=cache.TTL_FUNDAMENTALS,
    )
    row = rows[0] if isinstance(rows, list) and rows else {}
    price = row.get("price")
    return float(price) if isinstance(price, (int, float)) and price else None


def get_earnings_calendar(from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Companies reporting earnings between two ISO dates (FMP /stable).

    Returns rows like {symbol, date, epsActual, epsEstimate, revenueActual, ...}.
    Used by the post_earnings job to find watchlist tickers that just reported.
    """
    rows = cache.cached_call(
        "earnings-calendar",
        {"from": from_date, "to": to_date},
        lambda: _get("earnings-calendar", {"from": from_date, "to": to_date}),
        ttl=cache.TTL_FUNDAMENTALS,
        datestamp=False,
    )
    return rows if isinstance(rows, list) else []


def get_short_interest(ticker: str) -> dict[str, Any]:
    """Best-effort short interest. FMP does not expose reliable short interest on
    this plan, so we surface only what the /stable quote carries and flag absence."""
    rows = cache.cached_call(
        "quote_short",
        {"symbol": ticker},
        lambda: _get("quote", {"symbol": ticker}),
        ttl=cache.TTL_FUNDAMENTALS,
    )
    row = rows[0] if isinstance(rows, list) and rows else {}
    return {
        "ticker": ticker.upper(),
        "market_cap": row.get("marketCap"),
        "volume": row.get("volume"),
        "note": "FMP does not provide reliable short-interest data on this plan; treat short interest as unavailable.",
    }


def get_price_on(ticker: str, date: str, lookback_days: int = 10) -> float | None:
    """Closest available close on or just before ``date`` (point-in-time safe)."""
    import datetime as _dt

    end = _dt.date.fromisoformat(date)
    start = end - _dt.timedelta(days=lookback_days)
    points = get_historical_prices(ticker, start.isoformat(), end.isoformat())
    eligible = [p for p in points if p.date <= date]
    if not eligible:
        return None
    latest = max(eligible, key=lambda p: p.date)
    return latest.adj_close or latest.close


def get_ipo_date(ticker: str) -> str | None:
    """Return the company's IPO date (ISO string) from the /stable profile, if any.

    Used by the backtest point-in-time universe filter to reject companies that
    had not gone public as of the backtest date.
    """
    rows = cache.cached_call(
        "profile",
        {"symbol": ticker},
        lambda: _get("profile", {"symbol": ticker}),
        ttl=cache.TTL_FUNDAMENTALS,
    )
    row = rows[0] if isinstance(rows, list) and rows else {}
    ipo = row.get("ipoDate")
    return str(ipo) if ipo else None
