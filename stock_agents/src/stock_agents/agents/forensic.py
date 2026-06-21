"""Forensic agent (V2 addendum).

Reads SEC filings for signals that are public but rarely in mainstream coverage:
risk-factor deltas, footnote anomalies, working-capital quirks, auditor/restatement
signals, insider patterns, proxy governance, recent 8-Ks. NOT a bull or a bear — a
reader of documents. Every finding must cite a real filing; the citation guard
below rejects any accession number the agent did not actually fetch.

Runs after Balance Sheet, before Stress Test, only when forensic mode is enabled.
Model: claude-opus-4-7 (reading- and judgment-heavy).
"""

from __future__ import annotations

from stock_agents.agents.base import AgentResult, AgentRunner, extract_accessions
from stock_agents.models.analysis import ForensicReport
from stock_agents.tools import definitions as d
from stock_agents.tools import get_handlers
from stock_agents.tools.handlers import ToolContext

NAME = "forensic"
MODEL = "claude-opus-4-7"

TOOLS = [
    d.COMPARE_RISK_FACTORS,
    d.SEARCH_EDGAR_FILINGS,
    d.FETCH_FILING_CONTENT,
    d.GET_INSIDER_TRANSACTIONS,
    d.GET_COMPANY_PROFILE,
    d.GET_INCOME_STATEMENT,
    d.GET_BALANCE_SHEET,
    d.GET_CASH_FLOW_STATEMENT,
]

SYSTEM = """You are a forensic financial analyst. Your job is to read SEC filings carefully and surface signals that are not currently in mainstream coverage. You are NOT a bear or a bull. You are a reader of documents.

For the given ticker, work through this checklist. For each item, either state a finding with a specific filing citation (accession number, section, page if possible), or state explicitly "no notable finding."

1. RISK FACTOR DELTAS (compare_risk_factors tool):
   - What risk factors were added in the most recent 10-K vs the prior year?
   - What risk factors were removed?
   - What language was meaningfully changed?
   - Added risks are signals management sees something new. Removed risks may be signals of overconfidence or, occasionally, that a real issue was resolved.

2. FOOTNOTE REVIEW (fetch_filing_content, most recent 10-K):
   - Related-party transactions: any disclosed? Any unusual?
   - Off-balance-sheet arrangements?
   - Contingent liabilities, guarantees, indemnifications?
   - Significant accounting policy changes?
   - Lease commitments relative to revenue?
   - Goodwill allocation and impairment testing assumptions — are the assumptions plausible?

3. WORKING CAPITAL FORENSICS (income/balance/cashflow tools):
   - Accounts receivable growth vs revenue growth — is AR growing faster? (Quality of revenue concern)
   - Inventory days outstanding — building up? (Demand softness)
   - Deferred revenue trends — declining? (Future revenue at risk)
   - DSO trend over 3 years.

4. AUDITOR + RESTATEMENT SIGNALS:
   - Has the auditor changed in the past 3 years? Why?
   - Any 10-K/A amendments filed?
   - Any 8-K Item 4.02 filings (non-reliance on prior financials)?
   - Any going-concern language in audit opinions?

5. INSIDER ACTIVITY PATTERNS (get_insider_transactions, 24mo):
   - Cluster buying or cluster selling around specific events?
   - Open-market purchases by anyone (rare, high-signal)?
   - 10b5-1 plan adoptions or modifications timed near material announcements?
   - C-suite turnover events with related-party severance terms?

6. PROXY STATEMENT DETAILS (DEF 14A):
   - Exec comp structure: cash-heavy or equity-heavy? Performance-linked or time-vested?
   - Related-party deals with executives or board members?
   - Significant changes to board composition?
   - Any classified board, dual-class share, or other governance friction?

7. RECENT 8-K SCAN (last 12 months):
   - Item 1.01 (material agreements): any new contracts/customers that could materially shift the business?
   - Item 5.02 (officer changes): any unexplained departures?
   - Item 8.01 (other events): anything unusual?

Every finding's `citation` field MUST contain the accession number of a filing you actually fetched with a tool in THIS analysis. Do NOT invent accession numbers. If you cannot find document evidence for a concern, do not raise it — report "no notable finding" for that category instead. A confident-sounding hallucinated red flag is the worst possible output.

Final score 1-10 on "forensic risk":
- 1 = clean filings, consistent risk factors, no working capital quirks, no insider red flags, stable auditor
- 5 = a few yellow flags but nothing definitive
- 10 = multiple red flags including restatement risk, auditor concerns, hostile insider activity, or governance issues

Be calibrated. Most companies score 3-5. A 1 should be rare (genuinely pristine filings). A 9-10 should be even rarer."""


def _citation_accessions(report: ForensicReport) -> dict[str, list[str]]:
    """Map each finding to the accession numbers in its citation."""
    return {f.finding[:40]: extract_accessions(f.citation, f.source_url or "") for f in report.findings}


def _invalid_findings(report: ForensicReport, seen: set[str]) -> list[str]:
    """Findings whose citation references no fetched accession (and one IS expected)."""
    bad = []
    for f in report.findings:
        cited = extract_accessions(f.citation, f.source_url or "")
        # A finding must cite at least one accession, and every cited accession must
        # be one the agent actually fetched.
        if not cited or any(a not in seen for a in cited):
            bad.append(f.finding[:60])
    return bad


def run(ticker: str, *, ctx: ToolContext | None = None) -> AgentResult:
    runner = AgentRunner(
        model=MODEL,
        tools=TOOLS,
        handlers=get_handlers([t["name"] for t in TOOLS]),
        agent_name=NAME,
        max_tokens=6000,
    )
    base_msg = (
        f"Run the forensic checklist on {ticker.upper()}. Cite a fetched filing's "
        "accession number for every finding. Return a ForensicReport."
    )
    result = runner.run(system=SYSTEM, user_message=base_msg, output_schema=ForensicReport,
                        ctx=ctx, ticker=ticker.upper(), max_iters=16)

    if not isinstance(result.output, ForensicReport):
        return result

    seen = {a for e in result.audit_log for a in e.get("accessions", [])}
    bad = _invalid_findings(result.output, seen)
    if bad and seen:
        # Anti-hallucination: re-run once, instructing the agent to drop findings
        # whose citations don't trace to a filing it actually fetched.
        correction = (
            base_msg
            + "\n\nYour previous attempt cited accession numbers that were not in any "
            "filing you fetched, or omitted citations. Re-do it: every finding must cite "
            "the accession number of a filing you actually retrieve with a tool in this run. "
            "Drop any finding you cannot back with a fetched filing."
        )
        retry = runner.run(system=SYSTEM, user_message=correction, output_schema=ForensicReport,
                           ctx=ctx, ticker=ticker.upper(), max_iters=16)
        if isinstance(retry.output, ForensicReport):
            retry.cost_usd += result.cost_usd
            seen2 = {a for e in retry.audit_log for a in e.get("accessions", [])}
            still_bad = set(_invalid_findings(retry.output, seen2))
            if still_bad:
                # Last resort: strip the uncited findings rather than emit a hallucinated flag.
                retry.output.findings = [
                    f for f in retry.output.findings if f.finding[:60] not in still_bad
                ]
            return retry
    return result
