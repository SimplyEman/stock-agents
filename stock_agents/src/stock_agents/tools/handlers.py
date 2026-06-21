"""Tool implementations.

Each handler takes the tool ``input`` dict plus a :class:`ToolContext` and
returns a JSON string fed back to Claude as the tool result. Handlers are thin:
they call the data layer, attach pre-computed metrics where useful, and enforce
point-in-time filtering when the context carries an ``as_of`` date.

The :class:`ToolContext` is what makes the same tools usable both live and in
backtests — set ``as_of`` and statement series are sliced to filings dated
before that date, and web search is disabled (there's no point-in-time web).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from stock_agents.data import edgar, etf, fmp, metrics
from stock_agents.models.company import Filing


@dataclass
class ToolContext:
    """Execution context threaded into every handler.

    ``as_of`` (ISO date string) activates point-in-time discipline. ``allow_web``
    is informational here (web search is server-side) but recorded for audit.
    """

    as_of: str | None = None
    allow_web: bool = True


def _json(payload: Any) -> str:
    return json.dumps(payload, default=str)


def _series_payload(series, as_of: str | None) -> list[dict[str, Any]]:
    series = series.as_of(as_of)
    return [
        {"fiscal_year": p.fiscal_year, "date": p.date, "filed_date": p.filed_date, **p.line_items}
        for p in series.periods
    ]


# ---------------------------------------------------------------------------
# Financial statement handlers
# ---------------------------------------------------------------------------


def h_income_statement(inp: dict, ctx: ToolContext) -> str:
    ticker = inp["ticker"]
    years = int(inp.get("years", 5))
    income = fmp.get_income_statement(ticker, years)
    cash = fmp.get_cash_flow_statement(ticker, years)
    derived = metrics.summarize(income, fmp.get_balance_sheet(ticker, years), cash)
    return _json(
        {
            "ticker": ticker.upper(),
            "as_of": ctx.as_of,
            "periods": _series_payload(income, ctx.as_of),
            "derived_metrics": {
                k: derived[k]
                for k in (
                    "revenue_cagr_3y",
                    "revenue_cagr_5y",
                    "gross_margin_latest",
                    "operating_margin_latest",
                    "fcf_conversion",
                    "rule_of_40_score",
                )
            },
        }
    )


def h_balance_sheet(inp: dict, ctx: ToolContext) -> str:
    ticker = inp["ticker"]
    years = int(inp.get("years", 5))
    balance = fmp.get_balance_sheet(ticker, years)
    income = fmp.get_income_statement(ticker, years)
    derived = metrics.summarize(income, balance, fmp.get_cash_flow_statement(ticker, years))
    return _json(
        {
            "ticker": ticker.upper(),
            "as_of": ctx.as_of,
            "periods": _series_payload(balance, ctx.as_of),
            "derived_metrics": {
                k: derived[k]
                for k in (
                    "net_debt_to_ebitda",
                    "interest_coverage",
                    "current_ratio",
                    "goodwill_pct_assets",
                )
            },
        }
    )


def h_cash_flow(inp: dict, ctx: ToolContext) -> str:
    ticker = inp["ticker"]
    years = int(inp.get("years", 5))
    cash = fmp.get_cash_flow_statement(ticker, years)
    income = fmp.get_income_statement(ticker, years)
    derived = metrics.summarize(income, fmp.get_balance_sheet(ticker, years), cash)
    return _json(
        {
            "ticker": ticker.upper(),
            "as_of": ctx.as_of,
            "periods": _series_payload(cash, ctx.as_of),
            "derived_metrics": {
                k: derived[k]
                for k in (
                    "shares_outstanding_cagr_3y",
                    "sbc_pct_revenue",
                    "fcf_vs_netincome_gap_pct",
                    "fcf_conversion",
                )
            },
        }
    )


def h_key_metrics(inp: dict, ctx: ToolContext) -> str:
    ticker = inp["ticker"]
    series = fmp.get_key_metrics(ticker, int(inp.get("years", 5)))
    return _json({"ticker": ticker.upper(), "periods": _series_payload(series, ctx.as_of)})


# ---------------------------------------------------------------------------
# Profile / peers / estimates / short interest
# ---------------------------------------------------------------------------


def h_company_profile(inp: dict, ctx: ToolContext) -> str:
    profile = fmp.get_company_profile(inp["ticker"])
    data = profile.model_dump()
    if ctx.as_of:
        # Market cap from current profile would be lookahead; recompute at as_of.
        price = fmp.get_price_on(inp["ticker"], ctx.as_of)
        data["market_cap_usd"] = None  # shares*price not reliably point-in-time here
        data["price_as_of"] = price
        data["note"] = "market_cap suppressed for point-in-time run; use price_as_of"
    return _json(data)


def h_peer_comparison(inp: dict, ctx: ToolContext) -> str:
    ticker = inp["ticker"]
    peers = fmp.get_peers(ticker)
    rows = []
    for p in peers:
        try:
            prof = fmp.get_company_profile(p)
            km = fmp.get_key_metrics(p, 1)
            latest = km.periods[0].line_items if km.periods else {}
            rows.append(
                {
                    "ticker": p,
                    "name": prof.name,
                    "market_cap_usd": prof.market_cap_usd,
                    "pe": latest.get("peRatio"),
                    "ev_ebitda": latest.get("enterpriseValueOverEBITDA"),
                    "roic": latest.get("roic"),
                }
            )
        except Exception:
            rows.append({"ticker": p, "error": "data unavailable"})
    return _json({"ticker": ticker.upper(), "peers": rows})


def h_analyst_estimates(inp: dict, ctx: ToolContext) -> str:
    if ctx.as_of:
        return _json({"note": "analyst estimates disabled in point-in-time runs (forward-looking)"})
    return _json(
        {
            "ticker": inp["ticker"].upper(),
            "estimates": fmp.get_analyst_estimates(inp["ticker"], int(inp.get("years", 3))),
        }
    )


def h_short_interest(inp: dict, ctx: ToolContext) -> str:
    return _json(fmp.get_short_interest(inp["ticker"]))


def h_compare_risk_factors(inp: dict, ctx: ToolContext) -> str:
    import difflib

    ticker = inp["ticker"]
    n = max(2, int(inp.get("recent_count", 2)))
    cik = edgar.ticker_to_cik(ticker)
    filings = edgar.get_recent_filings(cik, "10-K", limit=n)
    if ctx.as_of:
        filings = [f for f in filings if f.filing_date < ctx.as_of]
    if len(filings) < 2:
        return _json(
            {
                "ticker": ticker.upper(),
                "error": "fewer than two 10-Ks available",
                "added": [],
                "removed": [],
            }
        )
    newer, older = filings[0], filings[1]
    new_txt = edgar.fetch_filing_text(newer, section="risk_factors")
    old_txt = edgar.fetch_filing_text(older, section="risk_factors")

    def _paras(t: str) -> list[str]:
        return [p.strip() for p in t.split("\n") if len(p.strip()) > 80]

    new_p, old_p = _paras(new_txt), _paras(old_txt)
    sm = difflib.SequenceMatcher(None, old_p, new_p)
    added, removed = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            added.extend(new_p[j1:j2])
        if tag in ("delete", "replace"):
            removed.extend(old_p[i1:i2])
    return _json(
        {
            "ticker": ticker.upper(),
            "newer_filing": {"accession": newer.accession_number, "date": newer.filing_date},
            "older_filing": {"accession": older.accession_number, "date": older.filing_date},
            "added": added[:40],
            "removed": removed[:40],
            "added_count": len(added),
            "removed_count": len(removed),
        }
    )


def h_earnings_transcript(inp: dict, ctx: ToolContext) -> str:
    from stock_agents.data import transcripts

    # Point-in-time: restrict the SEC 8-K source to filings before the as-of date.
    try:
        result = transcripts.get_earnings_transcript(
            inp["ticker"], inp.get("quarter"), before=ctx.as_of
        )
        return _json(result)
    except transcripts.TranscriptUnavailable as exc:
        return _json({"error": str(exc), "available": False})


# ---------------------------------------------------------------------------
# ETF handlers
# ---------------------------------------------------------------------------


def h_search_thematic_etfs(inp: dict, ctx: ToolContext) -> str:
    theme = inp["theme"]
    found = etf.etfs_for_theme(theme)
    return _json(
        {
            "theme": theme,
            "etfs": found,
            "registry_themes": list(etf.THEME_REGISTRY.keys()),
            "note": "" if found else "No registry match; pick ETFs from registry_themes that fit.",
        }
    )


def h_etf_holdings(inp: dict, ctx: ToolContext) -> str:
    holdings = etf.get_etf_holdings(inp["etf_ticker"], int(inp.get("top_n", 25)))
    payload = holdings.model_dump()
    if ctx.as_of:
        # Point-in-time universe filter: drop holdings that were not public/tradable
        # as of the backtest date, so the screener LLM never sees future-IPO names.
        from stock_agents.backtesting.point_in_time import was_investable_on

        kept, dropped = [], []
        for h in payload["holdings"]:
            (kept if was_investable_on(h["ticker"], ctx.as_of) else dropped).append(h)
        payload["holdings"] = kept
        payload["as_of"] = ctx.as_of
        payload["excluded_not_yet_investable"] = [h["ticker"] for h in dropped]
    return _json(payload)


# ---------------------------------------------------------------------------
# EDGAR handlers
# ---------------------------------------------------------------------------


def h_insider_transactions(inp: dict, ctx: ToolContext) -> str:
    ticker = inp["ticker"]
    months = int(inp.get("months", 24))
    cik = edgar.ticker_to_cik(ticker)
    txns = edgar.get_insider_transactions(cik, months)
    if ctx.as_of:
        txns = [t for t in txns if t.transaction_date <= ctx.as_of]
    net = sum(t.value_usd for t in txns)
    open_market_net = sum(t.value_usd for t in txns if t.is_open_market)
    return _json(
        {
            "ticker": ticker.upper(),
            "lookback_months": months,
            "transaction_count": len(txns),
            "net_usd_all": net,
            "net_usd_open_market": open_market_net,
            "transactions": [t.model_dump() for t in txns[:50]],
        }
    )


def h_search_edgar_filings(inp: dict, ctx: ToolContext) -> str:
    ticker = inp["ticker"]
    cik = edgar.ticker_to_cik(ticker)
    filings = edgar.get_recent_filings(cik, inp["form_type"], int(inp.get("limit", 5)))
    if ctx.as_of:
        filings = [f for f in filings if f.filing_date < ctx.as_of]
    return _json(
        {
            "ticker": ticker.upper(),
            "form_type": inp["form_type"],
            "filings": [f.model_dump() for f in filings],
        }
    )


def h_fetch_filing_content(inp: dict, ctx: ToolContext) -> str:
    ticker = inp["ticker"]
    accession = inp["accession_number"]
    cik = edgar.ticker_to_cik(ticker)
    # Resolve the accession to a Filing (we need its primary_doc_url).
    target: Filing | None = None
    for form in ("10-K", "10-Q", "DEF 14A", "8-K", "4"):
        for f in edgar.get_recent_filings(cik, form, limit=40):
            if f.accession_number == accession:
                target = f
                break
        if target:
            break
    if target is None:
        return _json({"error": f"accession {accession} not found for {ticker}"})
    text = edgar.fetch_filing_text(target, inp.get("section", "full"))
    return _json(
        {
            "ticker": ticker.upper(),
            "accession_number": accession,
            "form_type": target.form_type,
            "section": inp.get("section", "full"),
            "text": text,
        }
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

Handler = Callable[[dict, ToolContext], str]

HANDLERS: dict[str, Handler] = {
    "get_income_statement": h_income_statement,
    "get_balance_sheet": h_balance_sheet,
    "get_cash_flow_statement": h_cash_flow,
    "get_key_metrics": h_key_metrics,
    "get_company_profile": h_company_profile,
    "get_peer_comparison": h_peer_comparison,
    "get_analyst_estimates": h_analyst_estimates,
    "get_short_interest": h_short_interest,
    "get_earnings_transcript": h_earnings_transcript,
    "compare_risk_factors": h_compare_risk_factors,
    "search_thematic_etfs": h_search_thematic_etfs,
    "get_etf_holdings": h_etf_holdings,
    "get_insider_transactions": h_insider_transactions,
    "search_edgar_filings": h_search_edgar_filings,
    "fetch_filing_content": h_fetch_filing_content,
}


def get_handlers(names: list[str]) -> dict[str, Handler]:
    """Return the subset of handlers for the given tool names (web_search skipped)."""
    return {n: HANDLERS[n] for n in names if n in HANDLERS}
