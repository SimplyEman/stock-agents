"""Earnings transcript ingestion (v2 Phase 3).

Legal-first source priority. We never scrape Seeking Alpha or Motley Fool (their
ToS prohibits it). Sources, in the order tried:

1. **AlphaVantage** EARNINGS_CALL_TRANSCRIPT (free tier; needs ALPHAVANTAGE_API_KEY).
   The spec's designated primary source — full Q&A transcripts when available.
2. **Company IR sites** — a small manual registry of investor-relations transcript
   pages. Best-effort text extraction; sparse by design and expanded over time.
3. **SEC 8-K Item 2.02 exhibit** — the earnings press release / prepared remarks
   filed as an exhibit. Not a full transcript, but always available and free via
   EDGAR. This is the reliable fallback used when no key / IR page exists.

``get_earnings_transcript`` returns ``{"source", "text", "quarter"}`` or raises
``TranscriptUnavailable``. Text is truncated to ~30k tokens before use.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from stock_agents.config import settings
from stock_agents.data import cache, edgar
from stock_agents.data._http import RateLimiter, raise_for_retryable_status, with_retries

_limiter = RateLimiter(max_per_second=1.0)  # AlphaVantage free tier is strict

# ~30k tokens ≈ 120k chars of English.
_MAX_TRANSCRIPT_CHARS = 120_000


class TranscriptUnavailable(RuntimeError):
    pass


# Manual IR transcript-page registry. Maps ticker -> a URL (or URL template with
# {quarter}). Intentionally small; extend as pages are confirmed stable.
IR_REGISTRY: dict[str, str] = {
    # Example shape — most companies post PDFs behind JS, so this stays sparse and
    # the 8-K / AlphaVantage paths carry the load.
    # "CRM": "https://investor.salesforce.com/financials/",
}


# ---------------------------------------------------------------------------
# Source 1: AlphaVantage
# ---------------------------------------------------------------------------


def _from_alphavantage(ticker: str, quarter: str | None) -> dict[str, Any] | None:
    if not settings.alphavantage_api_key:
        return None

    def _load() -> dict[str, Any]:
        @with_retries
        def _do() -> dict[str, Any]:
            _limiter.acquire()
            params = {
                "function": "EARNINGS_CALL_TRANSCRIPT",
                "symbol": ticker.upper(),
                "apikey": settings.alphavantage_api_key,
            }
            if quarter:
                params["quarter"] = _to_av_quarter(quarter)
            with httpx.Client(timeout=30.0) as client:
                resp = client.get("https://www.alphavantage.co/query", params=params)
                raise_for_retryable_status(resp)
                return resp.json() if resp.status_code == 200 else {}

        return _do()

    data = cache.cached_call(
        "av_transcript", {"ticker": ticker, "quarter": quarter}, _load, ttl=cache.TTL_FUNDAMENTALS
    )
    # AlphaVantage returns {"symbol":..., "quarter":..., "transcript":[{"speaker","title","content"}...]}
    rows = data.get("transcript") if isinstance(data, dict) else None
    if not rows:
        return None
    text = "\n".join(
        f"{r.get('speaker', '')} ({r.get('title', '')}): {r.get('content', '')}".strip()
        for r in rows
    )
    if not text.strip():
        return None
    return {"source": "alphavantage", "text": text, "quarter": data.get("quarter") or quarter or ""}


def _to_av_quarter(quarter: str) -> str:
    """Normalize 'Q3-2025' / 'Q3 2025' to AlphaVantage's 'YYYYQM' form '2025Q3'."""
    q = quarter.upper().replace(" ", "-")
    if "-" in q and q.startswith("Q"):
        qpart, ypart = q.split("-", 1)
        return f"{ypart}{qpart}"
    return quarter


# ---------------------------------------------------------------------------
# Source 2: company IR sites (best-effort)
# ---------------------------------------------------------------------------


def _from_ir(ticker: str, quarter: str | None) -> dict[str, Any] | None:
    url_tmpl = IR_REGISTRY.get(ticker.upper())
    if not url_tmpl:
        return None
    url = url_tmpl.format(quarter=quarter or "")

    def _load() -> str:
        @with_retries
        def _do() -> str:
            _limiter.acquire()
            headers = {"User-Agent": "Mozilla/5.0 (stock-agents research)"}
            with httpx.Client(timeout=30.0, headers=headers, follow_redirects=True) as client:
                resp = client.get(url)
                raise_for_retryable_status(resp)
                return resp.text if resp.status_code == 200 else ""

        return _do()

    raw = cache.cached_call("ir_transcript", {"url": url}, _load, ttl=cache.TTL_FUNDAMENTALS)
    text = edgar._clean_html(raw) if raw else ""  # noqa: SLF001 - reuse HTML cleaner
    if len(text) < 500:  # too short to be a transcript
        return None
    return {"source": "ir", "text": text, "quarter": quarter or ""}


# ---------------------------------------------------------------------------
# Source 3: SEC 8-K Item 2.02 exhibit (always available)
# ---------------------------------------------------------------------------


def _from_8k(ticker: str, quarter: str | None, *, before: str | None = None) -> dict[str, Any] | None:
    cik = edgar.ticker_to_cik(ticker)
    filings = edgar.get_recent_filings(cik, "8-K", limit=40)
    # Earnings 8-Ks carry Item 2.02 (Results of Operations).
    earnings = [f for f in filings if f.item_numbers and "2.02" in f.item_numbers]
    if before:
        earnings = [f for f in earnings if f.filing_date < before]
    if not earnings:
        return None
    filing = earnings[0]  # most recent
    text = edgar.fetch_filing_exhibit(cik, filing, prefer="EX-99")
    if not text or len(text) < 200:
        return None
    q = quarter or _infer_quarter(filing.report_date or filing.filing_date)
    return {"source": "8k", "text": text, "quarter": q}


def _infer_quarter(date_str: str) -> str:
    try:
        d = dt.date.fromisoformat(date_str[:10])
        return f"Q{(d.month - 1) // 3 + 1}-{d.year}"
    except (ValueError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_earnings_transcript(
    ticker: str, quarter: str | None = None, *, before: str | None = None
) -> dict[str, Any]:
    """Return the best available earnings transcript/press release for a ticker.

    ``before`` (ISO date) restricts the SEC 8-K source to filings dated before it,
    for point-in-time use. Raises :class:`TranscriptUnavailable` if no source has
    content. Text is truncated to ~30k tokens.
    """
    ticker = ticker.upper()
    for fetch in (
        lambda: _from_alphavantage(ticker, quarter),
        lambda: _from_ir(ticker, quarter),
        lambda: _from_8k(ticker, quarter, before=before),
    ):
        try:
            result = fetch()
        except Exception:
            result = None
        if result and result.get("text"):
            result["text"] = result["text"][:_MAX_TRANSCRIPT_CHARS]
            return result
    raise TranscriptUnavailable(f"no earnings transcript available for {ticker}")
