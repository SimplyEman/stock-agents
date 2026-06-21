"""eight_k_monitor job (v2 Phase 5).

Polls EDGAR's recent 8-K atom feed, filters to watchlist filers by CIK, and for
each previously-unseen filing with a material item code, emits a Pushover alert.
No LLM by default; ``summarize=True`` adds one cheap Haiku sentence per filing.

Item codes are mapped to descriptions in ``notify.formatter.EIGHT_K_ITEMS``; the
material subset is defined below (per the v2 spec).
"""

from __future__ import annotations

import logging
import re

import feedparser

from stock_agents.config import settings
from stock_agents.data import edgar
from stock_agents.track import store

log = logging.getLogger("stock_agents.automation")

_FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom"
)
MATERIAL_ITEMS = {
    "1.01", "1.02", "1.03", "2.01", "2.02", "2.04", "2.05",
    "4.01", "4.02", "5.02", "5.03", "7.01", "8.01",
}
_CIK_RE = re.compile(r"\((\d{1,10})\)")
_ACC_RE = re.compile(r"accession[_-]?number=([\d-]+)", re.IGNORECASE)


def _fetch_feed() -> list[dict]:
    """Fetch + parse the recent 8-K atom feed (with the required EDGAR UA)."""
    raw = edgar._get(_FEED_URL, expect_json=False)  # noqa: SLF001 - reuse UA + rate limit
    parsed = feedparser.parse(raw)
    return parsed.entries


def _extract_cik(entry) -> str | None:
    m = _CIK_RE.search(entry.get("title", ""))
    return f"{int(m.group(1)):010d}" if m else None


def _extract_accession(entry) -> str | None:
    link = entry.get("link", "")
    m = _ACC_RE.search(link)
    if m:
        return m.group(1)
    # Fall back to the accession embedded in the archives path (…/0000320193-26-000011-index.htm)
    m2 = re.search(r"(\d{10}-\d{2}-\d{6})", link)
    return m2.group(1) if m2 else None


def run(*, summarize: bool = False, **_kwargs) -> dict:
    from stock_agents import notify

    active = [w for w in store.list_watchlist(include_exited=False) if w.status == "active"]
    # Map watchlist CIK -> ticker (skip tickers we can't resolve).
    cik_to_ticker: dict[str, str] = {}
    for w in active:
        try:
            cik_to_ticker[edgar.ticker_to_cik(w.ticker)] = w.ticker
        except Exception:  # noqa: BLE001
            continue
    if not cik_to_ticker:
        return {"watchlist_ciks": 0, "feed_entries": 0, "new_material": 0}

    try:
        entries = _fetch_feed()
    except Exception as exc:  # noqa: BLE001
        log.warning("8-K feed fetch failed: %s", exc)
        return {"error": str(exc), "feed_entries": 0, "new_material": 0}

    new_material, alerted = 0, 0
    for entry in entries:
        cik = _extract_cik(entry)
        if not cik or cik not in cik_to_ticker:
            continue
        accession = _extract_accession(entry)
        if not accession or store.is_eight_k_seen(accession):
            continue
        ticker = cik_to_ticker[cik]
        # Look up item numbers + URL from the submissions feed (authoritative).
        items, url = _items_and_url(cik, accession, entry)
        store.mark_eight_k_seen(
            accession_number=accession, ticker=ticker,
            filed_at=entry.get("updated", ""), item_numbers=items, url=url,
        )
        item_set = {c.strip() for c in (items or "").split(",") if c.strip()}
        if not (item_set & MATERIAL_ITEMS):
            continue
        new_material += 1
        subject, short, html = notify.formatter.format_eight_k(ticker, items, url)
        if summarize:
            short = f"{short} | {_summarize(ticker, items)}"[:240]
        res = notify.emit_alert(kind="eight_k", severity="notice", ticker=ticker,
                                subject=subject, short=short, html=html)
        if any(res.values()):
            alerted += 1

    return {
        "watchlist_ciks": len(cik_to_ticker), "feed_entries": len(entries),
        "new_material": new_material, "alerted": alerted,
    }


def _items_and_url(cik: str, accession: str, entry) -> tuple[str | None, str]:
    """Resolve a filing's item numbers + index URL from submissions (best effort)."""
    try:
        for f in edgar.get_recent_filings(cik, "8-K", limit=20):
            if f.accession_number == accession:
                acc_nodash = accession.replace("-", "")
                url = (f"{settings.edgar_www_url}/Archives/edgar/data/"
                       f"{int(cik)}/{acc_nodash}/{accession}-index.html")
                return f.item_numbers, url
    except Exception:  # noqa: BLE001
        pass
    return None, entry.get("link", "")


def _summarize(ticker: str, items: str | None) -> str:
    """One-sentence Haiku summary of the 8-K (opt-in; ~$0.005)."""
    from stock_agents.agents.base import AgentRunner
    from stock_agents.notify.formatter import describe_items

    desc = "; ".join(describe_items(items)) or "8-K"
    try:
        runner = AgentRunner(model="claude-haiku-4-5-20251001", tools=[], handlers={},
                             agent_name="eight_k_summary", max_tokens=120)
        from pydantic import BaseModel

        class _S(BaseModel):
            summary: str

        res = runner.run(
            system="Summarize an SEC 8-K filing in ONE plain-English sentence for an investor.",
            user_message=f"{ticker} filed an 8-K covering: {desc}. One sentence.",
            output_schema=_S, max_iters=2,
        )
        return res.output.summary if res.output else desc
    except Exception:  # noqa: BLE001
        return desc
