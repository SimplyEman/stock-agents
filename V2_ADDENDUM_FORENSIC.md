# V2 Addendum — Forensic Agent + Asymmetric Opportunity Filtering

This addendum extends the V2 build spec with two related capabilities:

1. **Forensic Agent** — a new specialist that reads SEC filings for *what's not in the headlines but IS in the documents*: footnote anomalies, risk factor deltas, related-party transactions, insider trade patterns, restatement risk, and other signals that mainstream coverage misses.
2. **Asymmetric opportunity filtering** — extending the ETF Screener and CLI to filter candidates by market cap and (optionally) share price, so the pipeline is biased toward sub-£10B companies where 5-10x upside is plausible.

Read this addendum *after* the main V2 spec. It assumes Phase 2 (Peer Comparison and Macro Overlay agents) is implemented; the Forensic Agent slots in alongside them.

---

## Part 1: Asymmetric opportunity filtering

### CLI changes

Add to `analyze` and `inspect`:

```bash
stockagents analyze "AI infrastructure" \
  --max-market-cap-gbp 10000000000 \    # £10B ceiling (or USD with --currency usd)
  --min-market-cap-gbp 100000000 \      # £100M floor (illiquidity boundary)
  --max-price-gbp 100 \                  # optional, only if you have a broker reason
  --max-candidates 15
```

### Behavior

- All thresholds are **optional**. Defaults: `--min-market-cap-gbp 500000000`, `--max-market-cap-gbp 50000000000` (£500M to £50B), no price filter.
- Currency conversion uses the latest GBP/USD rate from FMP. Cache the rate daily.
- The filters apply **after** ETF holdings retrieval and **before** the screener Claude call, so the LLM never sees mega-caps that would crowd out smaller names.
- Defend against the "too cheap" trap: if `--max-price-gbp` is set, also auto-set `--min-market-cap-gbp 500000000` unless explicitly overridden. Sub-£500M companies are illiquid and frequently distressed; the price filter alone surfaces too many junk names.

### Where to wire it

`data/etf.py::ETFScreener._filter_candidates` is the right chokepoint. Apply the filters there, log how many candidates were excluded by each filter, and pass the exclusion log through to the screener's user message so the LLM knows the universe is pre-constrained.

### Acceptance

- A run with `--max-market-cap-gbp 5000000000` on "AI infrastructure" produces a candidate list with NVDA, AMD, TSM, AVGO etc. all excluded. The list should include names like SMCI, CRDO, ALAB, VRT, ARM (depending on current market caps and FX).
- The output report explicitly states the filter thresholds used and how many candidates were excluded by each.
- README updated with a "Asymmetric opportunity mode" section explaining the filters and the rationale (small caps for upside, market cap not share price for the right filter).

---

## Part 2: Forensic Agent

### Role and framing

The Forensic Agent reads what most coverage doesn't: footnotes, risk factor changes, related-party transactions, auditor changes, restatement signals, and insider trade patterns. It is **not** a contrarian agent (that's the Stress Test). It is a **forensic** agent — its output is "here are signals from the filings that are not in the headlines."

**Critical framing for the system prompt:** the agent must NEVER invent signals or speculate. Every claim must cite the exact filing (accession number) and ideally the section/item. If the agent cannot find documented evidence of an issue, it must say so explicitly and score the candidate accordingly — not manufacture concerns to look thorough.

### Position in pipeline

After Balance Sheet, before Stress Test. The Stress Test reads the Forensic Report as one of its inputs — forensic findings often become the strongest bear case material.

### Model

`claude-opus-4-7`. This is reading-heavy and judgment-heavy work; the cost is worth it.

### Tools

Existing: `search_edgar_filings`, `fetch_filing_content`, `get_insider_transactions`, `get_company_profile`.

New tool to add: `compare_risk_factors(ticker, recent_count=2)` — fetches the Risk Factors section from the two most recent 10-Ks and returns a structured diff showing added, removed, and substantially modified risk factors. Implement in `tools/handlers.py` using existing EDGAR client functions + a simple line-by-line diff.

### Process (in system prompt)

```
You are a forensic financial analyst. Your job is to read SEC filings carefully and surface signals that are not currently in mainstream coverage. You are NOT a bear or a bull. You are a reader of documents.

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

3. WORKING CAPITAL FORENSICS (existing income/balance/cashflow tools):
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

Output schema: every finding has a `citation` field with the filing accession number. Findings with no specific citation are not valid — either find the document evidence or report "no notable finding."

Final score 1-10 on "forensic risk":
- 1 = clean filings, consistent risk factors, no working capital quirks, no insider red flags, stable auditor
- 5 = a few yellow flags but nothing definitive
- 10 = multiple red flags including restatement risk, auditor concerns, hostile insider activity, or governance issues

Be calibrated. Most companies score 3-5. A 1 should be rare (genuinely pristine filings). A 9-10 should be even rarer.
```

### Output schema (`ForensicReport`)

```python
class ForensicFinding(BaseModel):
    category: Literal[
        "risk_factor_delta", "footnote", "working_capital",
        "auditor_or_restatement", "insider_pattern",
        "proxy_governance", "recent_8k"
    ]
    finding: str                         # One paragraph describing the signal
    severity: Literal["green", "yellow", "red"]
    citation: str                        # Accession number + section
    source_url: str | None = None        # Direct EDGAR link if available

class ForensicReport(BaseModel):
    ticker: str
    findings: list[ForensicFinding]
    risk_factor_delta_summary: str       # ~3 sentences on what changed YoY
    no_notable_findings_categories: list[str]   # Categories with nothing to flag
    forensic_risk_score_1_to_10: int
    reasoning: str
    sources: list[str]                   # All accession numbers cited
```

### Anti-hallucination guardrails

Add to `agents/base.py` a post-validation step specifically for ForensicReport: every `ForensicFinding.citation` must be an accession number that appears in the audit log of EDGAR tool calls made by this agent. If a citation isn't traceable to an actual fetched filing, reject the output and force the agent to re-do it without that finding. This prevents the Forensic Agent from inventing accession numbers, which is the most damaging failure mode (a confident-sounding hallucinated red flag).

### Cost impact

Adds ~$0.40-$0.80 per candidate on Opus, depending on filing length. A 5-candidate forensic-mode run goes from ~$1.50 to ~$5. Worth it for the depth, but expensive enough that you'll want a `--forensic` flag on the CLI to enable selectively, not by default.

CLI:
```bash
stockagents analyze "AI infrastructure" --max-candidates 10 --forensic
stockagents inspect NVDA --forensic
```

Without the flag, the pipeline runs as before. With the flag, the Forensic Agent runs per candidate.

### Integration with existing agents

- **Stress Test agent**: when forensic mode is on, the Stress Test's user message includes the ForensicReport. The Stress Test system prompt is updated: "If the Forensic Report identifies red findings, your bear case MUST address them specifically. Do not produce a generic bear thesis that ignores documented forensic risks."
- **Synthesizer**: when forensic mode is on, the conviction weighting changes: forensic_risk becomes a new component with 15% weight, redistributed from fundamentals (down to 20%) and balance sheet (down to 15%). The Synthesizer system prompt is updated to explicitly weight forensic findings.

New conviction formula in forensic mode:
```
conviction = (0.20·fundamentals + 0.15·balance_sheet
              + 0.20·management + 0.30·stress_test
              + 0.15·(11 - forensic_risk)) · 10
```
(Note: forensic score is inverted because higher forensic_risk should LOWER conviction.)

### Acceptance criteria

- ForensicAgent implemented with the system prompt above and the schema above.
- `compare_risk_factors` tool implemented and tested against AAPL (10-K 2023 vs 2024 should produce a real diff with at least some changes).
- A test on AAPL produces a ForensicReport with predominantly green findings, score 2-4 (Apple's filings are clean).
- A test on a known restatement company (any company with a recent 10-K/A) produces red findings with proper citations.
- All citations in test outputs are verifiable accession numbers.
- README updated with a "Forensic mode" section explaining what it does, what it costs, and when to use it.

---

## Part 3: Honest framing for the README

Add a new section to the README's "How it works" area, **before** any usage instructions:

> **What "hidden information" actually means.** This system reads SEC filings carefully and surfaces things that are publicly available but rarely in mainstream coverage — risk factor changes, footnote anomalies, insider trade patterns, working capital quirks, auditor changes. These are signals real analysts use; the system's edge is reading them consistently across many companies, not exposing secrets. It cannot find information that is not in public filings. It cannot consistently beat professional sell-side analysts on companies they're paid to cover. It can absolutely surface things that aren't in headlines, news articles, or social media coverage of a stock — which is most companies, most of the time.
>
> Use the Forensic Agent's output to *ask better questions* about a candidate. Use the citations to read the source documents yourself. The system is a research aid that helps you read filings more thoroughly, not an oracle that bypasses them.

---

## Build order

1. Implement asymmetric opportunity filters first (Part 1) — small, isolated change to ETF screener.
2. Implement the Forensic Agent (Part 2) without integration. Test on AAPL and 2-3 other tickers manually.
3. Wire the agent into the orchestrator behind the `--forensic` flag.
4. Update Stress Test and Synthesizer prompts to consume forensic output.
5. Update README with both new sections.

Build time estimate: 1-2 days for the filters, 2-3 days for the Forensic Agent (the system prompt and anti-hallucination logic will need iteration).

## What this addendum does NOT do

- Does not promise to find information that is not in public filings.
- Does not connect to any non-SEC data source (no Twitter sentiment, no Reddit scraping, no private leak channels).
- Does not generate "insider tips" or attempt to source non-public information.
- Does not change the non-goals from V2: no broker integration, no auto-execution, no position sizing.

The Forensic Agent reads public documents better. That's the entire claim.
