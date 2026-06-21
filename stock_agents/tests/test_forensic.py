"""Forensic agent, citation guard, compare_risk_factors, asymmetric filter (offline)."""

from __future__ import annotations

import json

from stock_agents.agents import base, forensic
from stock_agents.agents.base import extract_accessions
from stock_agents.data import edgar, etf
from stock_agents.models.analysis import ForensicFinding, ForensicReport
from stock_agents.models.company import Filing
from tests.conftest import fake_anthropic_returning


def _report(accession="0000320193-24-000010", **over):
    base_ = dict(
        ticker="AAPL",
        findings=[
            ForensicFinding(
                category="footnote",
                finding="related-party note",
                severity="yellow",
                citation=f"{accession} (Note 12)",
            )
        ],
        risk_factor_delta_summary="minor changes",
        no_notable_findings_categories=["insider_pattern"],
        forensic_risk_score_1_to_10=3,
        reasoning="clean-ish",
        sources=[accession],
    )
    base_.update(over)
    return ForensicReport(**base_)


def test_extract_accessions():
    assert extract_accessions("see 0000320193-24-000010 (Item 1A)") == ["0000320193-24-000010"]
    assert extract_accessions("no accession here") == []
    got = extract_accessions("a 0001045810-26-000051 and 0000320193-24-000010 b")
    assert set(got) == {"0001045810-26-000051", "0000320193-24-000010"}


def test_invalid_findings_detects_uncited():
    rep = _report(accession="9999999999-99-999999")  # citation accession
    # seen set does NOT contain that accession -> finding is invalid
    bad = forensic._invalid_findings(rep, seen={"0000320193-24-000010"})
    assert len(bad) == 1
    # when the cited accession IS seen, it's valid
    ok = forensic._invalid_findings(rep, seen={"9999999999-99-999999"})
    assert ok == []


def test_finding_without_citation_is_invalid():
    rep = ForensicReport(
        ticker="X",
        findings=[
            ForensicFinding(
                category="footnote",
                finding="vague concern",
                severity="red",
                citation="no accession number here",
            )
        ],
        risk_factor_delta_summary="s",
        forensic_risk_score_1_to_10=7,
        reasoning="r",
    )
    assert forensic._invalid_findings(rep, seen={"0000320193-24-000010"})


def test_forensic_agent_accepts_valid_citation(monkeypatch, tmp_path):
    monkeypatch.setattr(base.settings, "audit_log_dir", tmp_path)
    acc = "0000320193-24-000010"
    monkeypatch.setattr(base, "Anthropic", fake_anthropic_returning(_report(acc).model_dump_json()))
    # Inject the accession into the run's audit so the citation traces to a "fetched" filing.
    orig = forensic.AgentRunner.run

    def patched_run(self, *a, **k):
        res = orig(self, *a, **k)
        res.audit_log.append({"tool": "fetch_filing_content", "accessions": [acc]})
        return res

    monkeypatch.setattr(forensic.AgentRunner, "run", patched_run)
    result = forensic.run("AAPL")
    assert isinstance(result.output, ForensicReport)
    assert result.output.forensic_risk_score_1_to_10 == 3
    assert len(result.output.findings) == 1  # kept (citation valid)


def test_compare_risk_factors_handler(monkeypatch):
    from stock_agents.tools import handlers
    from stock_agents.tools.handlers import ToolContext

    monkeypatch.setattr(edgar, "ticker_to_cik", lambda t: "0000320193")
    filings = [
        Filing(accession_number="0000320193-24-000010", form_type="10-K", filing_date="2024-11-01"),
        Filing(accession_number="0000320193-23-000106", form_type="10-K", filing_date="2023-11-03"),
    ]
    monkeypatch.setattr(edgar, "get_recent_filings", lambda cik, form, limit=2: filings)
    new_txt = "\n".join(
        [
            "Competition risk is significant and growing across all our markets worldwide.",
            "A brand-new supply chain concentration risk in a single region has emerged this year.",
        ]
    )
    old_txt = "Competition risk is significant and growing across all our markets worldwide."
    monkeypatch.setattr(
        edgar,
        "fetch_filing_text",
        lambda f, section="full": new_txt if f.accession_number.endswith("24-000010") else old_txt,
    )
    out = json.loads(handlers.h_compare_risk_factors({"ticker": "AAPL"}, ToolContext()))
    assert out["newer_filing"]["accession"] == "0000320193-24-000010"
    assert out["added_count"] >= 1
    assert any("supply chain" in a for a in out["added"])


# --- asymmetric filter (Part 1) -------------------------------------------


def test_asymmetric_filter_band(monkeypatch):
    from stock_agents.data import fmp
    from stock_agents.models.company import CompanyProfile

    caps = {"NVDA": 3.0e12, "SMCI": 3.0e10, "CRDO": 8.0e9, "TINY": 1.0e8}
    monkeypatch.setattr(
        fmp,
        "get_company_profile",
        lambda t: CompanyProfile(ticker=t, market_cap_usd=caps.get(t, 0.0)),
    )
    filt = etf.AsymmetricFilter(min_cap_usd=5e8, max_cap_usd=5e10)  # $0.5B–$50B
    kept, excl = etf.filter_candidates(["NVDA", "SMCI", "CRDO", "TINY"], filt)
    assert "SMCI" in kept and "CRDO" in kept
    assert "NVDA" in excl["too_large"]
    assert "TINY" in excl["too_small"]


def test_asymmetric_filter_inactive_is_noop():
    filt = etf.AsymmetricFilter()
    assert not filt.active
    kept, excl = etf.filter_candidates(["NVDA", "AMD"], filt)
    assert kept == ["NVDA", "AMD"] and excl == {}


def test_asymmetric_filter_fail_open(monkeypatch):
    from stock_agents.data import fmp

    def boom(t):
        raise RuntimeError("fmp down")

    monkeypatch.setattr(fmp, "get_company_profile", boom)
    filt = etf.AsymmetricFilter(max_cap_usd=1e10)
    kept, excl = etf.filter_candidates(["NVDA"], filt)
    assert kept == ["NVDA"]  # data error -> kept (fail-open)


def test_momentum_filter_drops_runners(monkeypatch):
    from stock_agents.data import fmp
    from stock_agents.models.company import CompanyProfile

    # In-band caps for all; the momentum filter is what differentiates.
    monkeypatch.setattr(
        fmp, "get_company_profile", lambda t: CompanyProfile(ticker=t, market_cap_usd=5e9)
    )
    returns = {"COOL": 30.0, "HOT": 250.0, "BLEH": -10.0}
    monkeypatch.setattr(fmp, "get_12m_return_pct", lambda t: returns.get(t))
    filt = etf.AsymmetricFilter(max_cap_usd=1e10, max_12m_return_pct=100.0)
    assert filt.active
    kept, excl = etf.filter_candidates(["COOL", "HOT", "BLEH"], filt)
    assert kept == ["COOL", "BLEH"]
    assert excl["ran_too_hot"] == ["HOT"]


def test_momentum_filter_fail_open(monkeypatch):
    """If the 12-month return is unavailable, the name is kept (don't silently drop)."""
    from stock_agents.data import fmp
    from stock_agents.models.company import CompanyProfile

    monkeypatch.setattr(
        fmp, "get_company_profile", lambda t: CompanyProfile(ticker=t, market_cap_usd=2e9)
    )
    monkeypatch.setattr(fmp, "get_12m_return_pct", lambda t: None)
    filt = etf.AsymmetricFilter(max_cap_usd=1e10, max_12m_return_pct=50.0)
    kept, excl = etf.filter_candidates(["UNKN"], filt)
    assert kept == ["UNKN"] and "ran_too_hot" not in excl


def test_momentum_filter_describe():
    f = etf.AsymmetricFilter(max_cap_usd=4e9, max_12m_return_pct=100.0)
    desc = f.describe()
    assert "trailing 12m return <= 100%" in desc
