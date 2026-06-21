"""EDGAR client tests (offline).

Exercises CIK mapping, Form 4 XML parsing, the submissions->filings transform,
and HTML cleaning, by patching the ``_get`` chokepoint or calling pure helpers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stock_agents.data import edgar

DATA = Path(__file__).parent / "test_data"


def test_ticker_to_cik(monkeypatch):
    monkeypatch.setattr(
        edgar,
        "_get",
        lambda url, expect_json=True: {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA Corp"},
        },
    )
    assert edgar.ticker_to_cik("aapl") == "0000320193"
    assert edgar.ticker_to_cik("NVDA") == "0001045810"
    with pytest.raises(edgar.EdgarError):
        edgar.ticker_to_cik("ZZZZ")


def test_parse_form4():
    raw = (DATA / "form4_sample.xml").read_text()
    txns = edgar._parse_form4(raw)
    assert len(txns) == 2
    sale = next(t for t in txns if t.transaction_type == "S")
    buy = next(t for t in txns if t.transaction_type == "P")
    assert sale.filer_name == "COOK TIMOTHY D"
    assert sale.value_usd == pytest.approx(-100000 * 170.0)  # disposed => negative
    assert buy.value_usd == pytest.approx(5000 * 180.0)  # acquired => positive
    assert buy.is_open_market is True


def test_recent_filings_transform(monkeypatch):
    submissions = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-23-000106", "0000320193-23-000077"],
                "form": ["10-K", "8-K"],
                "filingDate": ["2023-11-03", "2023-08-04"],
                "primaryDocument": ["aapl-20230930.htm", "ex.htm"],
                "reportDate": ["2023-09-30", "2023-08-03"],
            }
        }
    }
    monkeypatch.setattr(edgar, "_submissions", lambda cik: submissions)
    filings = edgar.get_recent_filings("320193", "10-K", limit=5)
    assert len(filings) == 1
    f = filings[0]
    assert f.accession_number == "0000320193-23-000106"
    assert "000032019323000106" in f.primary_doc_url
    assert f.primary_doc_url.endswith("aapl-20230930.htm")


def test_clean_html_strips_tags():
    html = "<html><body><p>Risk Factors</p><script>bad()</script><div>Real text here</div></body></html>"
    cleaned = edgar._clean_html(html)
    assert "bad()" not in cleaned
    assert "Real text here" in cleaned


def test_extract_section():
    text = "Intro blah blah. Risk Factors we face many risks including competition. Item 7 Management's Discussion and Analysis of stuff."
    section = edgar._extract_section(text, "risk_factors")
    assert section.lower().startswith("risk factors")
