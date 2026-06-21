"""Earnings transcript ingestion (offline)."""

from __future__ import annotations

import json

import pytest

from stock_agents.data import edgar, transcripts
from stock_agents.models.company import Filing


def test_source_priority_alphavantage_first(monkeypatch):
    monkeypatch.setattr(transcripts, "_from_alphavantage", lambda t, q: {"source": "alphavantage", "text": "AV transcript", "quarter": "Q3-2025"})
    monkeypatch.setattr(transcripts, "_from_ir", lambda t, q: {"source": "ir", "text": "IR"})
    monkeypatch.setattr(transcripts, "_from_8k", lambda t, q, before=None: {"source": "8k", "text": "8K"})
    res = transcripts.get_earnings_transcript("NVDA")
    assert res["source"] == "alphavantage"


def test_falls_through_to_8k(monkeypatch):
    monkeypatch.setattr(transcripts, "_from_alphavantage", lambda t, q: None)
    monkeypatch.setattr(transcripts, "_from_ir", lambda t, q: None)
    monkeypatch.setattr(transcripts, "_from_8k", lambda t, q, before=None: {"source": "8k", "text": "press release text", "quarter": "Q3-2025"})
    res = transcripts.get_earnings_transcript("NVDA")
    assert res["source"] == "8k"
    assert res["text"] == "press release text"


def test_unavailable_raises(monkeypatch):
    monkeypatch.setattr(transcripts, "_from_alphavantage", lambda t, q: None)
    monkeypatch.setattr(transcripts, "_from_ir", lambda t, q: None)
    monkeypatch.setattr(transcripts, "_from_8k", lambda t, q, before=None: None)
    with pytest.raises(transcripts.TranscriptUnavailable):
        transcripts.get_earnings_transcript("ZZZZ")


def test_truncation(monkeypatch):
    big = "x" * 500_000
    monkeypatch.setattr(transcripts, "_from_alphavantage", lambda t, q: {"source": "alphavantage", "text": big, "quarter": "Q1-2025"})
    res = transcripts.get_earnings_transcript("NVDA")
    assert len(res["text"]) == transcripts._MAX_TRANSCRIPT_CHARS


def test_source_error_is_swallowed(monkeypatch):
    def boom(t, q):
        raise RuntimeError("AV down")

    monkeypatch.setattr(transcripts, "_from_alphavantage", boom)
    monkeypatch.setattr(transcripts, "_from_ir", lambda t, q: None)
    monkeypatch.setattr(transcripts, "_from_8k", lambda t, q, before=None: {"source": "8k", "text": "ok text", "quarter": "Q2-2025"})
    res = transcripts.get_earnings_transcript("NVDA")
    assert res["source"] == "8k"


def test_av_quarter_normalization():
    assert transcripts._to_av_quarter("Q3-2025") == "2025Q3"
    assert transcripts._to_av_quarter("Q3 2025") == "2025Q3"


def test_infer_quarter():
    assert transcripts._infer_quarter("2025-08-15") == "Q3-2025"
    assert transcripts._infer_quarter("2025-01-31") == "Q1-2025"
    assert transcripts._infer_quarter("garbage") == ""


def test_from_8k_selects_item_202(monkeypatch):
    monkeypatch.setattr(edgar, "ticker_to_cik", lambda t: "0001045810")
    filings = [
        Filing(accession_number="0001-24-001", form_type="8-K", filing_date="2025-08-28",
               item_numbers="5.02,9.01"),  # not earnings
        Filing(accession_number="0001-24-002", form_type="8-K", filing_date="2025-08-27",
               item_numbers="2.02,9.01", report_date="2025-07-31"),  # earnings
    ]
    monkeypatch.setattr(edgar, "get_recent_filings", lambda cik, form, limit=40: filings)
    exhibit = "Prepared remarks: revenue grew 56% year over year to a record. " * 10
    monkeypatch.setattr(edgar, "fetch_filing_exhibit", lambda cik, f, prefer="EX-99": exhibit)
    res = transcripts._from_8k("NVDA", None)
    assert res["source"] == "8k"
    assert res["quarter"] == "Q3-2025"  # inferred from report_date 2025-07-31
    assert "Prepared remarks" in res["text"]


def test_from_8k_point_in_time_filter(monkeypatch):
    monkeypatch.setattr(edgar, "ticker_to_cik", lambda t: "0001045810")
    filings = [
        Filing(accession_number="a", form_type="8-K", filing_date="2025-08-27",
               item_numbers="2.02", report_date="2025-07-31"),
    ]
    monkeypatch.setattr(edgar, "get_recent_filings", lambda cik, form, limit=40: filings)
    monkeypatch.setattr(edgar, "fetch_filing_exhibit", lambda cik, f, prefer="EX-99": "text")
    # as-of before the filing -> excluded
    assert transcripts._from_8k("NVDA", None, before="2025-01-01") is None


def test_handler_returns_unavailable_gracefully(monkeypatch):
    from stock_agents.tools import handlers
    from stock_agents.tools.handlers import ToolContext

    monkeypatch.setattr(transcripts, "_from_alphavantage", lambda t, q: None)
    monkeypatch.setattr(transcripts, "_from_ir", lambda t, q: None)
    monkeypatch.setattr(transcripts, "_from_8k", lambda t, q, before=None: None)
    out = json.loads(handlers.h_earnings_transcript({"ticker": "ZZZZ"}, ToolContext()))
    assert out["available"] is False


def test_management_prefetch_block(monkeypatch):
    from stock_agents.agents import management
    from stock_agents.tools.handlers import ToolContext

    monkeypatch.setattr(
        transcripts, "get_earnings_transcript",
        lambda t, before=None: {"source": "8k", "text": "Evasive Q&A here.", "quarter": "Q3-2025"},
    )
    block = management._fetch_transcript_block("NVDA", ToolContext())
    assert "Evasive Q&A here." in block
    assert "source: 8k" in block

    def unavailable(t, before=None):
        raise transcripts.TranscriptUnavailable("none")

    monkeypatch.setattr(transcripts, "get_earnings_transcript", unavailable)
    assert management._fetch_transcript_block("NVDA", ToolContext()) == ""
