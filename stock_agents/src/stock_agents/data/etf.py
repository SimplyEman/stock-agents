"""ETF holdings scrapers + theme registry.

Each fund family exposes holdings differently. We implement a small per-family
scraper and a dispatch table keyed by ETF ticker. When a ticker isn't covered
by a bespoke scraper we fall back to FMP's ``etf-holder`` endpoint so the
screener always gets *something* rather than failing the whole theme.

Holdings sources change format often; scrapers are best-effort and cached for a
day. The registry below maps human themes to a basket of relevant ETFs.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from stock_agents.data import cache
from stock_agents.data._http import RateLimiter, raise_for_retryable_status, with_retries
from stock_agents.models.company import ETFHolding, ETFHoldings

_limiter = RateLimiter(max_per_second=3.0)


class ETFError(RuntimeError):
    pass


THEME_REGISTRY: dict[str, list[str]] = {
    "ai_infrastructure": ["SMH", "SOXX", "BOTZ", "AIQ", "ROBO"],
    "biotech": ["IBB", "XBI", "ARKG"],
    "cybersecurity": ["HACK", "CIBR", "BUG"],
    "clean_energy": ["ICLN", "TAN", "QCLN", "PBW"],
    "fintech": ["FINX", "ARKF", "IPAY"],
    "cloud_software": ["SKYY", "WCLD", "CLOU"],
    "semiconductors": ["SMH", "SOXX", "XSD", "PSI"],
    "robotics": ["BOTZ", "ROBO", "ARKQ"],
    "genomics": ["ARKG", "GNOM", "IDNA"],
    "space": ["ARKX", "UFO", "ROKT"],
    "ev_battery": ["LIT", "DRIV", "KARS"],
}

# ARK funds publish a stable CSV per fund.
_ARK_CSV = {
    "ARKK": "ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
    "ARKG": "ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
    "ARKQ": "ARK_AUTONOMOUS_TECH._&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    "ARKF": "ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv",
    "ARKW": "ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
    "ARKX": "ARK_SPACE_EXPLORATION_&_INNOVATION_ETF_ARKX_HOLDINGS.csv",
}

# iShares funds expose an AJAX CSV keyed by product id + slug.
_ISHARES = {
    "SOXX": ("239705", "ishares-phlx-semiconductor-etf"),
    "IBB": ("239699", "ishares-nasdaq-biotechnology-etf"),
}


def _get_text(url: str, params: dict[str, Any] | None = None) -> str:
    @with_retries
    def _do() -> str:
        _limiter.acquire()
        headers = {"User-Agent": "Mozilla/5.0 (stock-agents research)"}
        with httpx.Client(timeout=30.0, headers=headers, follow_redirects=True) as client:
            resp = client.get(url, params=params)
            raise_for_retryable_status(resp)
            if resp.status_code != 200:
                raise ETFError(f"{url} -> {resp.status_code}")
            return resp.text

    return _do()


# ---------------------------------------------------------------------------
# Per-family scrapers
# ---------------------------------------------------------------------------


def _scrape_ark(etf: str) -> ETFHoldings:
    fname = _ARK_CSV[etf]
    url = f"https://assets.ark-funds.com/fund-documents/funds-etf-csv/{fname}"
    text = _get_text(url)
    holdings: list[ETFHolding] = []
    for row in csv.DictReader(io.StringIO(text)):
        ticker = (row.get("ticker") or "").strip()
        if not ticker:
            continue
        try:
            weight = float((row.get("weight (%)") or row.get("weight") or "0").strip() or 0)
        except ValueError:
            weight = 0.0
        holdings.append(
            ETFHolding(ticker=ticker, name=(row.get("company") or "").strip(), weight_pct=weight)
        )
    return ETFHoldings(etf_ticker=etf, holdings=holdings)


def _scrape_ishares(etf: str) -> ETFHoldings:
    product_id, slug = _ISHARES[etf]
    url = (
        f"https://www.ishares.com/us/products/{product_id}/{slug}/"
        f"1467271812596.ajax?fileType=csv&fileName={etf}_holdings&dataType=fund"
    )
    text = _get_text(url)
    # iShares CSVs carry a preamble before the real header row "Ticker,Name,...".
    lines = text.splitlines()
    start = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.lower().startswith('"ticker"') or ln.lower().startswith("ticker")
        ),
        0,
    )
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    holdings: list[ETFHolding] = []
    for row in reader:
        ticker = (row.get("Ticker") or "").strip()
        if not ticker or ticker == "-":
            continue
        try:
            weight = float((row.get("Weight (%)") or "0").replace(",", "").strip() or 0)
        except ValueError:
            weight = 0.0
        holdings.append(
            ETFHolding(ticker=ticker, name=(row.get("Name") or "").strip(), weight_pct=weight)
        )
    return ETFHoldings(etf_ticker=etf, holdings=holdings)


def _scrape_fmp_fallback(etf: str) -> ETFHoldings:
    """Fallback via FMP's /stable ETF holdings endpoint (best effort).

    Note: on the current FMP plan ``etf/holdings`` returns HTTP 402 "Restricted
    Endpoint", so this fallback usually yields nothing — the bespoke iShares/ARK
    scrapers are the real coverage. We swallow the error and return empty rather
    than failing the whole screen.
    """
    from stock_agents.data import fmp  # local import to avoid hard dependency cycle

    try:
        rows = cache.cached_call(
            "etf/holdings",
            {"symbol": etf},
            lambda: fmp._get("etf/holdings", {"symbol": etf}),  # noqa: SLF001 - intentional internal reuse
            ttl=cache.TTL_ETF,
        )
    except Exception:
        rows = []
    holdings: list[ETFHolding] = []
    for r in rows if isinstance(rows, list) else []:
        sym = str(r.get("asset") or r.get("symbol") or "").strip()
        if not sym:
            continue
        holdings.append(
            ETFHolding(
                ticker=sym,
                name=str(r.get("name", "")),
                weight_pct=float(r.get("weightPercentage", r.get("weightPercent", 0)) or 0),
            )
        )
    return ETFHoldings(etf_ticker=etf, holdings=holdings)


_SCRAPERS: dict[str, Callable[[str], ETFHoldings]] = {}
for _t in _ARK_CSV:
    _SCRAPERS[_t] = _scrape_ark
for _t in _ISHARES:
    _SCRAPERS[_t] = _scrape_ishares


def get_etf_holdings(etf: str, top_n: int = 25) -> ETFHoldings:
    """Return holdings for an ETF, preferring the bespoke scraper, then FMP.

    Cached for a day. Results are sorted by weight and truncated to ``top_n``.
    """
    etf = etf.upper()

    def _load() -> ETFHoldings:
        scraper = _SCRAPERS.get(etf, _scrape_fmp_fallback)
        try:
            result = scraper(etf)
            if not result.holdings:
                raise ETFError("empty holdings")
            return result
        except Exception:
            if scraper is not _scrape_fmp_fallback:
                return _scrape_fmp_fallback(etf)
            raise

    result = cache.cached_call("etf_holdings", {"etf": etf}, _load, ttl=cache.TTL_ETF)
    ranked = sorted(result.holdings, key=lambda h: h.weight_pct, reverse=True)[:top_n]
    return ETFHoldings(etf_ticker=etf, as_of=result.as_of, holdings=ranked)


@dataclass
class AsymmetricFilter:
    """Market-cap (and optional price) band for biasing toward smaller names.

    Thresholds are stored in USD (converted from GBP at construction time). The
    price filter is rarely used; when set, a market-cap floor is auto-applied
    unless one was given explicitly, to keep out illiquid sub-£500M junk.
    """

    min_cap_usd: float | None = None
    max_cap_usd: float | None = None
    max_price_usd: float | None = None
    # Anti-momentum gate (addendum follow-up): drop names whose trailing 12-month
    # price return exceeds this %. Bias the universe toward names where the move
    # hasn't already happened. None = no momentum filter.
    max_12m_return_pct: float | None = None
    currency: str = "gbp"  # for reporting only

    @property
    def active(self) -> bool:
        return any(
            v is not None
            for v in (
                self.min_cap_usd,
                self.max_cap_usd,
                self.max_price_usd,
                self.max_12m_return_pct,
            )
        )

    def describe(self) -> str:
        parts = []
        if self.min_cap_usd is not None:
            parts.append(f"market cap >= ${self.min_cap_usd / 1e9:.2f}B")
        if self.max_cap_usd is not None:
            parts.append(f"market cap <= ${self.max_cap_usd / 1e9:.2f}B")
        if self.max_price_usd is not None:
            parts.append(f"share price <= ${self.max_price_usd:.2f}")
        if self.max_12m_return_pct is not None:
            parts.append(f"trailing 12m return <= {self.max_12m_return_pct:.0f}%")
        return "; ".join(parts) if parts else "no constraints"


def build_filter(
    *,
    min_market_cap_gbp: float | None = None,
    max_market_cap_gbp: float | None = None,
    max_price_gbp: float | None = None,
    max_12m_return_pct: float | None = None,
    currency: str = "gbp",
) -> AsymmetricFilter | None:
    """Build an AsymmetricFilter from user-supplied options, converting GBP->USD.

    The CLI ``analyze`` flags and the FastAPI ``/themes/{theme}/analyze`` endpoint
    both call this so they apply the same defaults and FX conversion rules:
    £500M floor / £50B ceiling when any cap-style arg is given, a £500M floor
    auto-applied when ``max_price_gbp`` is set (anti-junk), and an independent
    currency-agnostic anti-momentum gate.
    """
    from stock_agents.data import fmp

    if all(
        v is None
        for v in (
            min_market_cap_gbp,
            max_market_cap_gbp,
            max_price_gbp,
            max_12m_return_pct,
        )
    ):
        return None
    currency = (currency or "gbp").lower()
    rate = fmp.get_fx_rate("GBPUSD") or 1.27 if currency == "gbp" else 1.0

    min_cap = min_market_cap_gbp if min_market_cap_gbp is not None else 500_000_000
    max_cap = max_market_cap_gbp if max_market_cap_gbp is not None else 50_000_000_000
    if max_price_gbp is not None and min_cap < 500_000_000:
        min_cap = 500_000_000  # price filter -> enforce liquidity floor

    def to_usd(v):
        return v * rate if currency == "gbp" else v

    return AsymmetricFilter(
        min_cap_usd=to_usd(min_cap),
        max_cap_usd=to_usd(max_cap),
        max_price_usd=(to_usd(max_price_gbp) if max_price_gbp is not None else None),
        max_12m_return_pct=max_12m_return_pct,
        currency=currency,
    )


def filter_candidates(
    tickers: list[str], filt: AsymmetricFilter
) -> tuple[list[str], dict[str, list[str]]]:
    """Split tickers into (kept, exclusions-by-reason) per the asymmetric filter.

    Market caps and prices come from FMP (USD), cached. Tickers whose data can't
    be fetched are KEPT (fail-open) so a flaky lookup never silently shrinks the
    universe. Returns the kept list plus an exclusion log keyed by reason.
    """
    from stock_agents.data import fmp

    if not filt.active:
        return tickers, {}
    kept: list[str] = []
    excluded: dict[str, list[str]] = {
        "too_large": [],
        "too_small": [],
        "too_expensive": [],
        "ran_too_hot": [],
    }
    for t in tickers:
        try:
            cap = fmp.get_company_profile(t).market_cap_usd
        except Exception:
            kept.append(t)
            continue
        if filt.max_cap_usd is not None and cap and cap > filt.max_cap_usd:
            excluded["too_large"].append(t)
            continue
        if filt.min_cap_usd is not None and cap and cap < filt.min_cap_usd:
            excluded["too_small"].append(t)
            continue
        if filt.max_price_usd is not None:
            try:
                price = fmp.get_quote_price(t)
            except Exception:
                price = None
            if price is not None and price > filt.max_price_usd:
                excluded["too_expensive"].append(t)
                continue
        if filt.max_12m_return_pct is not None:
            try:
                ret = fmp.get_12m_return_pct(t)
            except Exception:
                ret = None
            # Fail-open: if we can't compute the return, keep the name rather than
            # silently drop it.
            if ret is not None and ret > filt.max_12m_return_pct:
                excluded["ran_too_hot"].append(t)
                continue
        kept.append(t)
    return kept, {k: v for k, v in excluded.items() if v}


def etfs_for_theme(theme: str) -> list[str]:
    """Best-effort theme -> ETF basket lookup with fuzzy key matching."""
    key = theme.strip().lower().replace(" ", "_").replace("-", "_")
    if key in THEME_REGISTRY:
        return THEME_REGISTRY[key]
    # Substring match so "ai infra" or "cloud" resolve to a registry entry.
    for reg_key, etfs in THEME_REGISTRY.items():
        if reg_key in key or key in reg_key:
            return etfs
    tokens = set(key.split("_"))
    for reg_key, etfs in THEME_REGISTRY.items():
        if tokens & set(reg_key.split("_")):
            return etfs
    return []
