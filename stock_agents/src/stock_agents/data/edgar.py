"""SEC EDGAR client.

EDGAR requires a descriptive ``User-Agent`` header (name + email) or it rejects
requests, and asks callers to stay under 10 requests/second. Both are handled
here. Filing text is fetched and cleaned with BeautifulSoup, then truncated so a
single filing never blows past Claude's context budget.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from stock_agents.config import settings
from stock_agents.data import cache
from stock_agents.data._http import RateLimiter, raise_for_retryable_status, with_retries
from stock_agents.models.company import Filing, InsiderTransaction

# SEC asks for <= 10 req/s. We keep margin at 8.
_limiter = RateLimiter(max_per_second=8.0)

# ~50k tokens; a token averages ~4 chars of English, so cap at ~200k chars.
_MAX_FILING_CHARS = 200_000

# Form 4 transaction codes that represent open-market trades (high signal).
_OPEN_MARKET_CODES = {"P", "S"}


class EdgarError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    return {
        "User-Agent": settings.edgar_user_agent,
        "Accept-Encoding": "gzip, deflate",
    }


def _get(url: str, *, expect_json: bool = True) -> Any:
    @with_retries
    def _do() -> Any:
        _limiter.acquire()
        with httpx.Client(timeout=30.0, headers=_headers(), follow_redirects=True) as client:
            resp = client.get(url)
            raise_for_retryable_status(resp)
            if resp.status_code != 200:
                raise EdgarError(f"EDGAR {url} -> {resp.status_code}")
            return resp.json() if expect_json else resp.text

    return _do()


# ---------------------------------------------------------------------------
# Ticker -> CIK
# ---------------------------------------------------------------------------


def _ticker_map() -> dict[str, str]:
    """Full ticker->CIK map from SEC's official file (cached daily)."""

    def _load() -> dict[str, str]:
        data = _get(f"{settings.edgar_www_url}/files/company_tickers.json")
        out: dict[str, str] = {}
        for entry in data.values():
            out[str(entry["ticker"]).upper()] = f"{int(entry['cik_str']):010d}"
        return out

    return cache.cached_call("sec_ticker_map", {}, _load, ttl=cache.TTL_FILINGS)


def ticker_to_cik(ticker: str) -> str:
    cik = _ticker_map().get(ticker.upper())
    if not cik:
        raise EdgarError(f"No CIK found for ticker {ticker!r}")
    return cik


# ---------------------------------------------------------------------------
# Company facts and submissions
# ---------------------------------------------------------------------------


def get_company_facts(cik: str) -> dict[str, Any]:
    cik = f"{int(cik):010d}"
    return cache.cached_call(
        "company_facts",
        {"cik": cik},
        lambda: _get(f"{settings.edgar_data_url}/api/xbrl/companyfacts/CIK{cik}.json"),
        ttl=cache.TTL_FILINGS,
    )


def _submissions(cik: str) -> dict[str, Any]:
    cik = f"{int(cik):010d}"
    return cache.cached_call(
        "submissions",
        {"cik": cik},
        lambda: _get(f"{settings.edgar_data_url}/submissions/CIK{cik}.json"),
        ttl=cache.TTL_FILINGS,
    )


def get_recent_filings(cik: str, form_type: str, limit: int = 10) -> list[Filing]:
    data = _submissions(cik)
    recent = data.get("filings", {}).get("recent", {})
    accession = recent.get("accessionNumber", [])
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    primary = recent.get("primaryDocument", [])
    report_dates = recent.get("reportDate", [])
    items = recent.get("items", [])
    cik_int = int(cik)

    out: list[Filing] = []
    for i, form in enumerate(forms):
        if form != form_type:
            continue
        acc = accession[i]
        acc_nodash = acc.replace("-", "")
        doc = primary[i] if i < len(primary) else ""
        out.append(
            Filing(
                accession_number=acc,
                form_type=form,
                filing_date=dates[i] if i < len(dates) else "",
                primary_document=doc,
                primary_doc_url=(
                    f"{settings.edgar_www_url}/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"
                ),
                report_date=report_dates[i] if i < len(report_dates) else None,
                item_numbers=(items[i] if i < len(items) and items[i] else None),
            )
        )
        if len(out) >= limit:
            break
    return out


def fetch_filing_exhibit(cik: str, filing: Filing, *, prefer: str = "EX-99") -> str:
    """Fetch the cleaned text of a filing's press-release exhibit (e.g. EX-99.1).

    8-K earnings filings (Item 2.02) carry the press release / prepared remarks as
    an exhibit, not the short cover document. We read the filing's directory
    listing, pick the first document whose name looks like the preferred exhibit
    type, and return its cleaned text. Falls back to the primary document.
    """
    cik_int = int(cik)
    acc_nodash = filing.accession_number.replace("-", "")
    base = f"{settings.edgar_www_url}/Archives/edgar/data/{cik_int}/{acc_nodash}"
    text_exts = (".htm", ".html", ".txt")
    pref = prefer.upper()  # "EX-99"

    def _docs_by_type() -> list[tuple[str, str]]:
        """Parse the filing index page into (document_type, filename) pairs.

        The index page's table carries the authoritative exhibit TYPE (e.g.
        "EX-99.1"), which filenames do not reliably encode (NVDA: q1fy27pr.htm,
        AAPL: a8-kex991....htm). Returns [] on any parse failure.
        """
        try:
            html = cache.cached_call(
                "filing_index_html",
                {"acc": filing.accession_number},
                lambda: _get(f"{base}/{filing.accession_number}-index.html", expect_json=False),
                ttl=cache.TTL_FILINGS,
                datestamp=False,
            )
        except Exception:
            return []
        soup = BeautifulSoup(html, "lxml")
        pairs: list[tuple[str, str]] = []
        for row in soup.select("table.tableFile tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            link = cells[2].find("a")
            if not link:
                continue
            name = link.get_text(strip=True)
            doc_type = cells[3].get_text(strip=True)
            pairs.append((doc_type.upper(), name))
        return pairs

    pairs = _docs_by_type()
    target = ""
    # 1) Authoritative: the document whose type is the earnings press-release exhibit.
    for doc_type, name in pairs:
        if doc_type.startswith(pref) and name.lower().endswith(text_exts):
            target = name
            break
    # 2) Any EX-99* exhibit by type.
    if not target:
        for doc_type, name in pairs:
            if doc_type.startswith("EX-99") and name.lower().endswith(text_exts):
                target = name
                break
    # 3) Filename heuristic fallback (press release naming varies).
    if not target:
        for _t, name in pairs:
            low = name.lower()
            if low.endswith(text_exts) and (
                "ex99" in low.replace("-", "") or low.endswith("pr.htm") or "press" in low
            ):
                target = name
                break
    # 4) Last resort: the primary (cover) document.
    if not target:
        target = filing.primary_document
    if not target:
        raise EdgarError(f"no exhibit found for {filing.accession_number}")
    raw = cache.cached_call(
        "filing_exhibit",
        {"acc": filing.accession_number, "doc": target},
        lambda: _get(f"{base}/{target}", expect_json=False),
        ttl=cache.TTL_FILINGS,
        datestamp=False,
    )
    return _clean_html(raw)[:_MAX_FILING_CHARS]


# ---------------------------------------------------------------------------
# Insider transactions (Form 4)
# ---------------------------------------------------------------------------


def get_insider_transactions(cik: str, months: int = 24) -> list[InsiderTransaction]:
    """Parse Form 4 filings over a lookback window.

    EDGAR exposes each Form 4 as an XML document. We pull the recent Form 4
    submissions list, fetch each ownership XML, and extract non-derivative
    transactions. This is best-effort: malformed filings are skipped.
    """
    cutoff = (dt.date.today() - dt.timedelta(days=int(months * 30.44))).isoformat()
    filings = get_recent_filings(cik, "4", limit=80)
    cik_int = int(cik)
    txns: list[InsiderTransaction] = []

    for f in filings:
        if f.filing_date < cutoff:
            continue
        acc_nodash = f.accession_number.replace("-", "")
        index_url = (
            f"{settings.edgar_data_url}/Archives/edgar/data/"
            f"{cik_int}/{acc_nodash}/{f.accession_number}.txt"
        )
        try:
            raw = cache.cached_call(
                "form4",
                {"acc": f.accession_number},
                lambda url=index_url: _get(url, expect_json=False),
                ttl=cache.TTL_FILINGS,
                datestamp=False,
            )
            txns.extend(_parse_form4(raw))
        except Exception:
            continue
    return [t for t in txns if t.transaction_date >= cutoff]


def _parse_form4(raw: str) -> list[InsiderTransaction]:
    soup = BeautifulSoup(raw, "lxml-xml")
    owner = soup.find("rptOwnerName")
    name = owner.get_text(strip=True) if owner else "unknown"
    is_dir = soup.find("isDirector")
    title_el = soup.find("officerTitle")
    title = (
        title_el.get_text(strip=True)
        if title_el
        else ("Director" if (is_dir and is_dir.get_text(strip=True) in {"1", "true"}) else "")
    )
    out: list[InsiderTransaction] = []
    for txn in soup.find_all("nonDerivativeTransaction"):
        try:
            code = _xml_val(txn, "transactionCode") or ""
            date = _xml_val(txn, "transactionDate") or ""
            shares = float(_xml_val(txn, "transactionShares") or 0)
            price = float(_xml_val(txn, "transactionPricePerShare") or 0)
            ad = _xml_val(txn, "transactionAcquiredDisposedCode") or ""
            signed = shares * price * (1 if ad == "A" else -1)
            out.append(
                InsiderTransaction(
                    filer_name=name,
                    filer_title=title,
                    transaction_date=date,
                    transaction_type=code,
                    is_open_market=code in _OPEN_MARKET_CODES,
                    shares=shares,
                    price=price,
                    value_usd=signed,
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def _xml_val(node: Any, tag: str) -> str | None:
    el = node.find(tag)
    if not el:
        return None
    # Form 4 wraps values in <value> children for some fields.
    value = el.find("value")
    return (value or el).get_text(strip=True)


# ---------------------------------------------------------------------------
# Filing text
# ---------------------------------------------------------------------------

# Coarse section anchors for 10-K/10-Q/proxy text. Real filings vary wildly, so
# these are heuristics: we locate a header and slice to the next major header.
_SECTION_PATTERNS = {
    "mda": r"management'?s discussion and analysis",
    "risk_factors": r"risk factors",
    "exec_comp": r"(executive compensation|compensation discussion and analysis)",
    "auditor_report": r"report of independent registered public accounting firm",
}


def fetch_filing_text(filing: Filing, section: str = "full") -> str:
    """Fetch and clean a filing's primary document, optionally a single section."""
    if not filing.primary_doc_url:
        raise EdgarError(f"Filing {filing.accession_number} has no primary doc URL")
    raw = cache.cached_call(
        "filing_text",
        {"acc": filing.accession_number, "doc": filing.primary_document},
        lambda: _get(filing.primary_doc_url, expect_json=False),
        ttl=cache.TTL_FILINGS,
        datestamp=False,
    )
    text = _clean_html(raw)
    if section != "full":
        text = _extract_section(text, section)
    return text[:_MAX_FILING_CHARS]


def _clean_html(raw: str) -> str:
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style", "table"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _extract_section(text: str, section: str) -> str:
    pattern = _SECTION_PATTERNS.get(section)
    if not pattern:
        return text
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if not m:
        return text  # fall back to full text rather than returning nothing
    start = m.start()
    # Slice a generous window forward; downstream truncation caps it anyway.
    return text[start : start + 80_000]
