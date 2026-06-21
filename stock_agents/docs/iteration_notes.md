# Calibration & Iteration Notes

Running log of live calibration runs for the `stock_agents` pipeline. Append an
entry after every meaningful run. Entries carry numerical evidence, not just
narrative.

## Calibration targets (from CLAUDE.md, verbatim — not to be lowered)

1. **Cost per run:** 15-candidate run $1.50–$3.50; 5-candidate run < $1.25; hard ceiling $5.
2. **Conviction spread:** top-5 conviction scores span >= 20 points.
3. **Stress test variance:** survivability scores across candidates have stdev >= 2.0.
4. **Candidate relevance:** known theme surfaces obvious + non-obvious names; mega-caps with weak fit should not crowd the top-5.
5. **JSON validation rate:** each agent passes first-try validation >= 90%.
6. **Backtest signal:** top-5 beat theme ETF by >= 2% annualized across >= 3 themes (high variance; one backtest is not signal).

## Session baseline (pre-calibration)

- **Timestamp:** 2026-05-26
- **Test suite:** `41 passed, 1 skipped` (42 collected).
- **Ledger spend before this session:** $2.96 (a partial live run occurred when keys were first added; 4 prior agent invocations). All session-cost figures below are reported as *incremental* over this baseline, and the final `cost-report` total is the authoritative session cap check.
- **Note on prompt constants:** CLAUDE.md refers to `SYSTEM_PROMPT`; the code uses `SYSTEM` constants inside each `agents/*.py`. These are the same thing — calibration edits target the `SYSTEM` constants.

---

## Entry 1 — Baseline `inspect AAPL` (BLOCKED: data layer 403)

- **Timestamp:** 2026-05-26 20:55–20:57
- **Command:** `uv run stockagents inspect AAPL`
- **Result:** FAILED, exit=1. Final error: `schema validation failed: no JSON object found in model output`.
- **Incremental cost:** ~$0.82 (ledger $2.96 -> $3.78).
- **Per-agent this run (from audit_logs/tool_calls.jsonl):**
  - management: $0.40 (in=344, out=2791) — ran on EDGAR filings only
  - balance_sheet: $0.36 (in=92,873, out=4,706)
  - stress_test: $2.16 (in=42,160, out=8,697) — burned tokens with no FMP data, eventually no JSON
  - fundamentals: $0.028 (out=731) — failed first, no data to analyze
  - synthesizer: did not run (upstream agents failed)

### Root cause — DATA LAYER, not prompts

Every FMP call returns HTTP 403:
```
"Legacy Endpoint : Due to Legacy endpoints being no longer supported - This
endpoint is only available for legacy users who have valid subscriptions prior
August 31, 2025."
```
FMP deprecated the entire `/api/v3/*` surface (what `data/fmp.py` + `config.py::fmp_base_url` use) on 2025-08-31.

Verified the user's key is valid against FMP's NEW `/stable/*` API:
```
GET https://financialmodelingprep.com/stable/profile?symbol=AAPL  -> 200
[{"symbol":"AAPL","price":308.34,"marketCap":4528699349040,"companyName":"Apple Inc.",...}]
```
The new API differs in: base path (`/stable` not `/api/v3`), query style (`?symbol=AAPL` not path segment), and response field names/shapes.

### Calibration targets — UNMEASURABLE in current state

Targets 1-6 cannot be honestly measured: no analyst receives financial data, so
conviction/stress/relevance/backtest numbers would be meaningless artifacts of
EDGAR-only context. JSON validation failures here are a symptom of starved
agents, not prompt defects.

### Why iteration is BLOCKED (hard-abort per goal + CLAUDE.md)

The fix requires editing `data/fmp.py` and `config.py` (base URL, endpoint
paths, query params, response field mapping) — a data-layer change. Both the
goal's hard-abort list and CLAUDE.md "When to ask the user" require explicit
user review before touching `data/`. No SYSTEM_PROMPT edit can fix a 403.
Surfaced to user; awaiting approval to migrate the FMP client to `/stable/*`.

---
## Prerequisite fixes (required before any calibration could run)

Two blocking defects were found and fixed before calibration was possible. Both
are outside the protected set (not data-source logic / schemas / topology /
model assignments), and CLAUDE.md sanctions bug fixes without asking:

1. **FMP `/api/v3` -> `/stable` migration** (data layer; user approved explicitly).
   `config.py::fmp_base_url` and `data/fmp.py` endpoint paths/params/field names
   migrated. Statement field names were unchanged (kept legacy-key fallbacks);
   only `calendarYear`->`fiscalYear`, `fillingDate`->`filingDate`, `mktCap`->`marketCap`,
   `stock-screener`->`company-screener`, peers/prices/quote shapes. Three offline
   test fixtures updated to the real `/stable` shapes (peers flat list, prices
   flat list, quote). NOTE: `etf/holdings` is HTTP 402 (restricted on this plan) —
   FMP ETF fallback now returns empty; bespoke iShares/ARK scrapers are the real
   coverage. Verified live: AAPL profile/income/balance/cashflow/peers all return.
2. **`agents/base.py` tools=None bug.** AgentRunner passed `tools=self.tools or None`;
   the tool-less synthesizer sent `tools=null`, which the API rejects
   (`400 tools: Input should be a valid array`). Fixed to omit `tools` when empty.
   Tests: 41 passed, 1 skipped (unchanged). This was a hard blocker — synthesizer
   failed on every run until fixed.

## Entry 2 — `inspect AAPL` baseline (post-fix) + management cost optimization

- **Timestamp:** 2026-05-26 21:09–21:14
- **Command:** `uv run stockagents inspect AAPL`  → exit 0, SUCCESS.
- **Result:** conviction 68.5 (high); component scores F=6 B=9 M=7 S=6.
  Deterministic conviction check: (6*.25+9*.20+7*.25+6*.30)*10 = 68.5 ✓.
- **Sanity check (condition 1) — PASS:**
  - Balance sheet: no false red flags. net debt/EBITDA 0.4x, interest cov 54.7x,
    ROIC ~52%, clean EY audit since 2009, zero goodwill, no restatements. Correct for AAPL.
  - Management: no invented insider alarm. Notes negligible insider ownership
    (true: 0.03%) and $0 net open-market buying — factual, not a fabricated fraud flag.
  - Stress test: substantive real bear case — valuation multiple-compression with
    named analogues (MSFT 2000-13, CSCO 1999-02, IBM 2012-20), DOJ-Google ~$18-20B
    TAC risk, EU DMA Article 6(4), China/Huawei. Not boilerplate.

### Cost finding — per-candidate far above target

Clean per-candidate cost ~$2.35 (ledger delta $4.46 included an earlier failed
run's wasted analyst spend). Breakdown (from audit_logs/tool_calls.jsonl):
| agent | cost | note |
|-------|------|------|
| stress_test (Opus) | ~$1.10 | 8.3k output tokens |
| management (Sonnet) | ~$0.60-0.70 | fetched 4 FULL filings ~640k chars (~160k tokens) — violates CLAUDE.md "no full 10-Ks in context" |
| balance_sheet (Sonnet) | ~$0.22 | one 184k-char full 10-K |
| synthesizer (Opus) | ~$0.32 | |
| fundamentals (Sonnet) | ~$0.11 | cheap, no filings |

### Change 1 (management SYSTEM prompt) — cost + CLAUDE.md priority #1 (noise)

Edited `agents/management.py` SYSTEM: fetch ONLY the latest DEF 14A `exec_comp`
section, at most ONE filing, no 10-K/10-Q/8-K, at most ONE web_search, do not
manufacture governance concerns from thin web noise, keep summaries concise.

**Before -> After (isolated `management.run("AAPL")`):**
- cost: ~$0.60-0.70 -> **$0.110** (~82% reduction)
- filing fetches: 4 (~640k chars) -> **1 (83k chars, exec_comp)**
- output quality: maintained/improved. CEO Tim Cook, founder_led=False, tenure 14y,
  insider_ownership 0.03%, net_buying_24mo $0, score 8, call_quality strong.
  governance_concerns now filing-substantiated (negligible insider ownership for
  non-founder CEO; board waived age-75 re-election guideline for Levinson/Sugar) —
  verifiable proxy facts, not web noise. Condition-1 "no invented Tim Cook concerns": PASS.

## Entry 3 — `inspect AAPL` post-optimization + cost projection (BUDGET CONFLICT)

- **Timestamp:** 2026-05-26 21:24
- **Command:** `uv run stockagents inspect AAPL` → exit 0, SUCCESS.
- **Result:** conviction 68.5 (high), scores F=6 B=9 M=7 S=6 (unchanged — quality intact post-optimization).
- **Changes measured (Change 2 batch: stress_test + balance_sheet + synthesizer SYSTEM prompts):**
  - stress_test: instructed <=2 web_search, punchy output. **Cost ~$1.10 -> $1.286** (out 8.3k -> 6.97k). Barely moved: Opus emits ~7k tokens regardless of "be concise." This is the binding cost wall.
  - synthesizer: concise + "use full 0-100 range" (calibration target #2). Cost $0.32 -> $0.259.
  - management: $0.096 (holds the Change-1 win).
  - fundamentals: $0.110.
- **Measured optimized per-candidate: ~$1.75** (stress_test = 74% of it).
- **Ledger total now: $10.15** (authoritative session spend per cost-report).

### Structural budget conflict (surfaced to user; STOP)

Projection for the required deliverables, using the *measured* $1.75/candidate:
- One 5-candidate `analyze` = 5 x $1.75 + screener (~$0.2) + Opus validation (~$0.3) + Opus commentary (~$0.2) ≈ **$9.5/run**.
- This **trips the $5 budget guard** (hard-abort: "any single run exceeds $5").
- Four required runs (AI-infra baseline, AI-infra rerun, biotech, cloud backtest) ≈ **$30-38**, on top of $10.15 already spent ≈ **$40-48 total** — **exceeds the $25 session cap** (second hard-abort).
- Even an aggressive floor (~$1.1/candidate if stress_test could be halved) gives ~$6.5/run, still > $5 guard; 4 runs still ~$26 + $10 spent = $36 > $25.

**Root causes:**
1. Two Opus calls per candidate (stress_test + synthesizer) per CLAUDE.md model
   assignments. stress_test (~$1.3) dominates and is prompt-irreducible.
2. ~$10 already spent, much of it on the two debugging-failure inspect runs
   (FMP 403 legacy-endpoint, then the tools=null synthesizer bug) before the
   pipeline could complete a single clean run.

### Calibration Target #1 (cost) — UNREACHABLE as stated, given model assignments

Target: "5-candidate run under $1.25." Measured: ~$9.5. The gap is ~7.6x and is
driven almost entirely by the mandated Opus stress_test+synthesizer. Hitting
$1.25 would require moving stress_test (and likely synthesizer) to Sonnet — a
model-assignment change that CLAUDE.md says requires explicit user approval.
Per the rules, NOT lowering the target; surfacing to user as a separate decision.

**BLOCKED pending user decision** on one of: (A) approve Opus->Sonnet for
stress_test/synthesizer; (B) raise the $25 cap + per-run --budget; (C) reduce
scope (fewer candidates/themes). Did not burn remaining budget proving a
projection already grounded in measured numbers.

## Note — "build on Claude Code instead of API?" (investigated)

User asked whether the pipeline could run on Claude Code (CLI/subscription)
instead of the metered Anthropic API to dodge per-run dollar cost.

Findings (2026-05-26 21:30):
- `claude` CLI present (v2.1.150). Feasible in principle via the Claude Agent SDK
  (`claude-agent-sdk`) or headless `claude -p` subprocess-per-agent.
- BUT `claude -p "say OK"` returns **"Credit balance is too low"** — the Claude
  Code auth in THIS environment (separate creds from `.env`) is already
  exhausted. The `.env` ANTHROPIC_API_KEY is what funds the current pipeline and
  still has balance.
- Therefore Claude Code is NOT a cheaper path here: both bill an Anthropic
  balance, and the Claude Code side has none. It would also be a major rewrite
  (rebuild AgentRunner on the Agent SDK, re-expose 13 tools as in-process MCP
  tools, add a runtime dependency, retire the $ cost ledger) — an architecture
  change requiring explicit approval and outside this calibration goal's scope.
- Only pays off with a Claude subscription/Max seat wired into `claude` (token
  use counts against the subscription, not metered $). Not the case here.

Conclusion: does not resolve the cost conflict in this environment. Real options
remain: (A) Opus->Sonnet for stress_test [+/- synthesizer], (B) raise budget,
(C) reduce scope. Awaiting user decision.

## Entry 4 — AI infrastructure BASELINE (Claude Code / Max backend)

- **Timestamp:** 2026-05-26 ~21:14–22:23
- **Command:** `LLM_BACKEND=claude_code uv run stockagents analyze "AI infrastructure" --max-candidates 5`
- **Backend:** Claude Code on Max subscription (model usage, not metered API $).
- **Result — top-5:** TSM 76.5(high), NVDA 75.5(high), AVGO 69.5(high), AMD 64.0(high), PLTR 59.0(medium).
- **Component scores [F,B,M,S]:** TSM[8,9,7,7] NVDA[9,9,8,5] AVGO[7,7,8,6] AMD[6,7,8,5] PLTR[8,6,6,4].

### Calibration metrics (measured)
| Target | Measured | Status |
|--------|----------|--------|
| #1 cost ($1.25/5-cand) | $5.54 usage-EQUIVALENT on Max (NOT billed; real API spend $0 this run) | n/a on Max; unreachable on metered API w/ Opus (see Entry 3) |
| #2 conviction spread >=20 | **17.5** (76.5 - 59.0) | MISS (close) |
| #3 stress survivability stdev >=2.0 | **1.02** (scores [7,5,6,5,4]) | MISS (worst) |
| #4 candidate relevance | TSM,NVDA,AVGO,AMD,PLTR — obvious names present, PLTR as AI-software wildcard, NO mega-cap (MSFT/GOOG) crowding | PASS |
| #5 JSON validation >=90% first-try | 0 schema-validation failures across 28 agent calls (100%) | PASS |
| #6 backtest signal | pending cloud-software backtest | pending |

Note: the 53 "error" lines in tool_calls.jsonl are tool-level (FMP etf/holdings 402,
transient EDGAR fetches), NOT schema failures (`schema validation` count = 0).

### Worst miss -> next change
Stress-test survivability stdev (1.02 vs 2.0) is the worst miss and cascades into
conviction spread (#2), since stress is 30% of the conviction weight. Survivability
clustered at 4-7 — insufficient discrimination. Next: ONE change to the stress_test
SYSTEM prompt to use the full 1-10 survivability range and differentiate sharply.

## Entry 5 — AI infrastructure RERUN after stress-test prompt change (Change 3)

- **Timestamp:** 2026-05-26 ~22:30–22:46
- **Command:** `LLM_BACKEND=claude_code uv run stockagents analyze "AI infrastructure" --max-candidates 5`
- **Change 3 (stress_test SYSTEM prompt):** replaced the terse "score 1-10" line with
  full-range anchors (9-10 / 7-8 / 5-6 / 3-4 / 1-2 definitions) plus an explicit
  anti-clustering instruction ("do not cluster at 4-7 ... if every name lands within
  two points you did not differentiate hard enough"). One change, isolated.
- **Result — top-5:** NVDA 81.5(very high), ASML 75.0(high), TSM 74.5(high), PLTR 59.5(medium), ARM 56.5(medium).
- **Component [F,B,M,S]:** NVDA[9,9,8,7] ASML[7,8,7,8] TSM[8,8,7,7] PLTR[8,5,7,4] ARM[6,7,5,5].

### Before -> After (worst-miss agent = stress_test)
| metric | baseline (Entry 4) | after Change 3 | target | verdict |
|--------|--------------------|----------------|--------|---------|
| stress survivability stdev | 1.02 ([7,5,6,5,4]) | **1.47** ([7,8,7,4,5]) | >=2.0 | improved +44%, still short |
| conviction spread | 17.5 | **25.0** | >=20 | **now PASS** |
| candidate relevance (#4) | PASS | PASS (NVDA,ASML,TSM,PLTR,ARM) | — | PASS |
| JSON validation (#5) | 100% | 100% (0 schema fails) | >=90% | PASS |
| cost equiv | $5.54 | $5.84 | — | Max usage-equiv, not billed |

### Stress stdev still < 2.0 — honest assessment (one attempt made, improved)
Change 3 moved stress stdev 1.02 -> 1.47 (clear improvement, so NOT the "two failed
attempts" abort case). The residual gap to 2.0 appears partly STRUCTURAL: a 5-name
basket inside ONE tight theme (AI-infra is "a single correlated capex cycle," per the
model's own commentary) has intrinsically correlated bull-thesis robustness, so
survivability scores legitimately bunch. Hitting stdev>=2.0 likely needs either a
weaker name deliberately included (the screener filters those out) or cross-theme
dispersion. Per the iteration rules I made one good attempt with measurable
improvement and move on rather than burning a third run; biotech below gives an
independent stress-variance data point. Target NOT lowered.

## Entry 6 — biotech (generalization check, Claude Code / Max backend)

- **Timestamp:** 2026-05-26 ~22:47–22:57
- **Command:** `LLM_BACKEND=claude_code uv run stockagents analyze "biotech" --max-candidates 5`
- **Pipeline:** ran end-to-end successfully (condition 3 satisfied). Screener sourced
  from IBB (iShares) + ARKG (ARK); it surfaced 3 candidates after filtering (XBI falls
  back to FMP which is 402-restricted, so coverage is IBB+ARKG only).
- **Result — picks:** NTRA 63.0(high), IONS 48.0(medium), ILMN 38.5(low).
- **Component [F,B,M,S]:** NTRA[7,5,7,6] IONS[4,4,6,5] ILMN[3,6,4,3].
- **Metrics:** conviction spread 24.5 (>=20 PASS); stress stdev 1.25 (3 names: [6,5,3]);
  cost equiv $5.29 (Max, not billed); JSON validation 100% (0 schema fails).
- **Calibration signal:** the synthesizer used the FULL range here — ILMN landed at
  38.5 (low), IONS 48 (medium), NTRA 63 (high). The post-Change-3 prompts produce
  genuine dispersion and low scores on weak names, exactly target #2's intent.
  Generalizes beyond AI-infra: different sector, sensible relevant names
  (Natera/Ionis/Illumina), no hedging-cluster.

## Entry 7 — cloud software BACKTEST as of 2020-01-01 (Claude Code / Max)

- **Timestamp:** 2026-05-26 ~22:58–23:14
- **Command:** `LLM_BACKEND=claude_code uv run stockagents analyze "cloud software" --backtest-date 2020-01-01 --max-candidates 5`
- **Pipeline:** ran end-to-end (condition 4 satisfied). 4 analyzed (DDOG dropped — see below).
- **Forward-return table (vs benchmark SKYY):**
  | ticker | conviction | fwd_1Y | fwd_3Y | fwd_5Y |
  |--------|-----------|--------|--------|--------|
  | CRWD | 68.0 | +324.7% | +111.1% | +586.1% |
  | SHOP | 64.5 | +184.7% | -12.7% | +167.4% |
  | PLTR | 64.5 | n/a (not public until 2020-09) | n/a | n/a |
  | CRWV | 45.0 | n/a (not public until 2025-03) | n/a | n/a |
  - top-5 avg: fwd_1Y +254.7%, fwd_3Y +49.2%, fwd_5Y +376.8%
  - benchmark SKYY: 1Y +57.4%, 3Y -4.6%, 5Y +97.3%
  - equiv cost $5.50 (Max, not billed).

### Calibration Target #6 (backtest signal >=2% annualized over >=3 themes): NOT credibly met — and why

The harness MECHANICALLY works: point-in-time financials (filings filtered by
acceptedDate), 1/3/5Y forward returns computed from /stable historical prices,
benchmark comparison rendered. But the headline "outperformance" (+254.7% vs
SKYY +57.4%) is INVALID due to **LLM-screener lookahead**:
- The screener picked **CRWV (CoreWeave)** — IPO **March 2025**, 5 years AFTER the
  as-of date — and **PLTR** — IPO **Sept 2020**, after the as-of date. Neither
  traded on 2020-01-01 (shown as "delisted"/no price).
- The surviving picks (CRWD, SHOP) are exactly the cloud names a 2026-trained model
  KNOWS became winners. This is selection/survivorship bias at the candidate-
  generation stage.

Root cause: point-in-time discipline filters DATA by filing date, but cannot stop
an LLM screener from selecting names using post-as-of-date knowledge. The candidate-
selection stage is not point-in-time-safe when the selector is an LLM trained on
the future. This is a fundamental limitation (CLAUDE.md already flags "no
survivorship-bias correction" and "web disabled in backtests"); the LLM-knowledge
leak is an additional, arguably larger, source of bias. Fixing it would require a
point-in-time-constrained candidate universe (a historical holdings/constituents
dataset), which is not wired in. Only 1 theme was backtested. Target #6 is therefore
NOT claimed as met; the apparent outperformance is not trustworthy signal. Target
NOT lowered — documented honestly per the rules.

Note: condition-4 expectation ("top picks include one of CRM/NOW/SNOW/NET/DDOG"):
DDOG was selected but its synthesizer output failed JSON validation twice and was
dropped (the single hard JSON failure observed this session). The run still met the
spirit (cloud names CRWD/SHOP/PLTR surfaced), but flag the DDOG drop.

## Calibration target scorecard (all six)

| # | target | measured | verdict |
|---|--------|----------|---------|
| 1 | cost: 5-cand < $1.25 | API path ~$9.5 (unreachable w/ Opus, Entry 3); Max path: real billed $0/run, usage-equiv ~$5.3-5.8/run | NOT met on metered API (documented, not lowered); moot on Max (subscription) |
| 2 | conviction spread >=20 | AI-infra 17.5 -> **25.0** after Change 3; biotech 24.5 | MET (post-iteration) |
| 3 | stress survivability stdev >=2.0 | AI-infra 1.02 -> **1.47** after Change 3; biotech 1.25 | improved, still short; partly structural (single-theme correlation), documented |
| 4 | candidate relevance | AI-infra: NVDA/TSM/ASML/AVGO/AMD/PLTR/ARM, no mega-cap crowding; biotech: NTRA/IONS/ILMN | MET |
| 5 | JSON validation >=90% first-try | 0 schema fails across AI-infra x2 + biotech (~80 calls); 1 hard fail (DDOG) in backtest | MET (~99%) |
| 6 | backtest beats benchmark >=2% annualized over >=3 themes | 1 theme run; apparent +254% vs +57% but INVALID (LLM-screener lookahead) | NOT credibly met; documented honestly |

### Real metered API spend this session: $10.15 (cost-report TOTAL metered) — under the $25 cap.
Everything after the FMP migration + base.py fix ran on the Claude Max backend
(usage-equivalent $28.90, NOT billed). Switching backends froze metered API spend.

## Lookahead-bias fix (data-layer; no prompt changes)

### Deliverable 1 — point-in-time universe data source chosen
**Choice: FMP `ipoDate` (from `/stable/profile`) + price availability on the as-of
date (`/stable/historical-price-eod`).** Both are FREE and already wired in — no new
dependency, no new subscription, no cost. Rule: a name is investable on `as_of` if
`ipoDate <= as_of` OR a close price exists within 45 days on/before `as_of`; it is
rejected only when both signals say it had not yet gone public. Errors fail OPEN
(treated as investable) so a flaky data call never silently shrinks the universe.

Implementation (data-layer / orchestrator logic only — NO agents/*.py SYSTEM prompts):
- `data/fmp.py`: added `get_ipo_date()`; `get_price_on()` gained a `lookback_days` arg.
- `backtesting/point_in_time.py`: `was_investable_on(ticker, as_of)` + `filter_to_investable()`.
- `tools/handlers.py` `h_etf_holdings`: in backtest mode, filters ETF holdings to
  investable tickers BEFORE the screener LLM sees them (deliverable 2).
- `agents/orchestrator.py` `analyze_theme`: in backtest mode, filters the screener's
  OUTPUT candidate list to investable names before analysis (the guarantee layer —
  catches names the LLM invents from training when ETF holdings are empty, as with
  cloud-software ETFs that have no scraper). Filtering runs before truncation so the
  set still fills to max_candidates.

**Limitation / residual bias:** this removes the egregious future-IPO leak, but does
NOT remove training-data leakage on names that DID exist at the as-of date (the model
still preferentially knows which existing companies became winners). It also still
draws candidates from TODAY's ETF holdings (survivorship). A fuller fix needs a
historical point-in-time constituents dataset; none free was wired in.

Offline gate verification (live FMP, no model calls), universe filtered to 2020-01-01:
- investable: CRWD, SHOP, CRM, NOW, NET, DDOG (all IPO'd < 2020-01-01)
- excluded:  CRWV (IPO 2025-03), PLTR (2020-09), SNOW (2020-09)

### Entry 8 — cloud software BACKTEST 2020-01-01 RERUN (with universe filter)
- **Command:** `LLM_BACKEND=claude_code analyze "cloud software" --backtest-date 2020-01-01 --max-candidates 5`
- **Filter fired:** "Point-in-time filter (2020-01-01): excluded ..." — final candidates
  **CRM, NOW, ADBE, WDAY, DDOG**, all public before 2020-01-01. **No CRWV/PLTR/SNOW.**
  Compare Entry 7 (pre-fix) which picked CRWV (IPO 2025) and PLTR (IPO 2020-09).
- **Forward returns (vs SKYY 1Y +57.4 / 3Y -4.6 / 5Y +97.3):**
  | ticker | conv | 1Y | 3Y | 5Y |
  |--------|------|----|----|----|
  | DDOG | 70.0 | +160.6 | +94.5 | +278.2 |
  | NOW | 67.5 | +95.0 | +37.5 | +275.5 |
  | CRM | 65.5 | +36.8 | -18.5 | +105.6 |
  | WDAY | 62.5 | +45.7 | +1.8 | +56.9 |
  | ADBE | 59.0 | +51.6 | +2.0 | +34.8 |
  - top-5 avg: 1Y **+77.9** (vs +57.4), 3Y **+23.5** (vs -4.6), 5Y **+150.2** (vs +97.3).
  - equiv cost $6.68 (Max, not billed). All 5 have REAL forward returns (no future-IPO "delisted" rows).

### Entry 9 — biotech BACKTEST 2018-01-01 (generalization)
- **Command:** `LLM_BACKEND=claude_code analyze "biotech" --backtest-date 2018-01-01 --max-candidates 5`
- **Candidates:** CRSP, ILMN, NTRA, NTLA, VCYT — IPO dates 2016-10, 2000-07, 2015-07,
  2016-05, 2013-10 respectively; **all public before 2018-01-01.** Filter generalizes.
- **Forward returns (vs IBB 1Y -9.7 / 3Y +41.9):** NTRA 61.0 (+55.3/+1007/+346.8),
  VCYT 57.0 (+92.6/+649.5/+263.4), CRSP 39.0 (+21.7/+552.1/+73.1), ILMN 37.0 (+37.3/+69.3/-7.5).
  - top-5 avg: 1Y **+51.7** (vs -9.7), 3Y **+569.5** (vs +41.9), 5Y **+169.0**.
  - equiv cost $5.90 (Max, not billed).

### Result: future-IPO lookahead ELIMINATED across both themes
Pre-fix (Entry 7) the cloud backtest selected CRWV (IPO 2025) and PLTR (IPO 2020-09);
post-fix every candidate in both backtests was public/tradable on the as-of date.
The remaining outperformance is more modest and credible but still carries residual
training-data selection bias (documented above), so backtest results remain
"indicative, not audit-grade." Tests: 50 passed, 1 skipped. No SYSTEM prompts changed.

## v2 Phase 2 — Peer Comparison + Macro Overlay agents (2026-05-27)

Two new agents added to the topology (pre-approved in V2_BUILD_SPEC.md). No
change to the conviction composite — peer/macro inform the synthesizer's
reasoning and surface as `peer_preference_strength` / `macro_fit` on each thesis
and `macro_context` on the FinalReport.

- **Peer Comparison** (Sonnet): runs after Stress Test, before Synthesizer, per
  candidate. Tools: profile, income, balance, key_metrics, peer_comparison.
- **Macro Overlay** (Sonnet): runs once per `analyze`, before screening; web_search
  gated off in backtest mode. Output threaded to the synthesizer for every candidate.

### Live verification (Claude Code / Max), `analyze "AI infrastructure" --max-candidates 5`
- Top-5: ANET 71.0(high), VRT 66.0(high), CRDO 63.0(high), MRVL 62.0(high), SMCI 44.0(medium).
- **Both reports referenced in every thesis:** all 5 carry `peer_preference_strength`
  (7,7,5,7,7) and a substantive `macro_fit` phrase; the report carries `macro_context`
  (regime winners = "capital-efficient incumbents with locked-in long-duration demand").
- The regime lens is doing real work: SMCI tagged "leans regime-losers (thin-margin,
  China exposure)" and landed lowest at 44; ANET tagged "matches regime-winners".
- JSON validation: all agents passed (0 schema failures).

### New cost band (HONEST — exceeds the spec's estimate)
- Equivalent cost: **$9.70** (Max usage-equivalent, NOT billed) vs ~$5.84 for the
  pre-Phase-2 AI-infra run (Entry 5) = **+66%**.
- The spec projected ~30-40%. The actual increase is roughly double that. Driver:
  the peer-comparison agent fetches financials for the subject AND 3 peers
  (profile/income/balance/key_metrics × ~4 companies), ~$0.8-1.0/candidate observed
  (e.g. MRVL peer call $0.99), plus ~$0.3 for the single macro call.
- Documented as the real band: **a 5-candidate run is now ~$9-10 equivalent**
  (was ~$5.8). Not a budget hard-stop on Max. A future prompt-level optimization
  (cap how much peer financial data is pulled) could narrow the gap toward the
  spec's estimate, but that is calibration, not Phase 2 scope.

Tests: 68 passed, 1 skipped (+4: test_peer_comparison.py, test_macro_overlay.py).

## v2 Phase 3 — Earnings transcripts + PIT-constituents deferral (2026-05-27)

### Transcript ingestion (`data/transcripts.py`)
Legal-first sources, in order: AlphaVantage (free tier, needs key — inactive here),
company IR registry (sparse), SEC 8-K Item 2.02 exhibit (free via EDGAR, PIT-safe).
Seeking Alpha / Motley Fool never scraped. New tool `get_earnings_transcript` +
handler; Management agent pre-fetches the transcript into its user message
(8-K-only and date-filtered in backtest mode) and its prompt now scores Q&A
vagueness / evasion / cross-quarter consistency.

EDGAR fix: 8-K exhibit selection reads the filing index page's document *type*
column (EX-99.1), not the filename — filenames vary (AAPL `a8-kex991....htm`,
NVDA `q1fy27pr.htm`, MSFT `msft-ex99_1.htm`). The first cut matched filename
prefixes and wrongly returned the iXBRL cover; fixed.

**Acceptance — transcript fetched for AAPL/NVDA/MSFT (live, free 8-K path):**
- AAPL → "Apple reports second quarter results" (5,908 chars)
- NVDA → "NVIDIA Announces Financial Results for First Quarter Fiscal 2027" (13,243 chars)
- MSFT → "Microsoft Cloud and AI Strength Fuels Third Quarter Results" (11,810 chars)

**Acceptance — Management score moves with the transcript (live A/B/C on NVDA, Max):**
| variant | score | earnings_call_quality |
|---------|-------|------------------------|
| A — no transcript | 8 | strong |
| B — real 8-K press release | 9 | strong |
| C — synthetic EVASIVE Q&A | **6** | **evasive** |
Score is transcript-sensitive (8→9 with a real source) and a vague/evasive call
drops it to 6 and flips call_quality to "evasive" — matches the spec's test
("a vague Q&A should reduce the score"). ~$0.21 equivalent per run (Max, not billed).

### Point-in-time constituents — NOT BUILT (deferred)
Documented in `docs/v2_decisions.md`: Sharadar SF1 ($50/mo, paid, needs approval),
WRDS (academic only), manual CSVs (high maintenance). Decision: defer; backtests
keep the "indicative, not audit-grade" caveat. No workaround that pretends to solve
it without the data.

Tests: 79 passed, 1 skipped (+11: test_transcripts.py). No conviction-formula or
model-assignment changes.

## v2 Phase 5 — automated job bodies (2026-05-27)

Filled the four stub jobs. New dep `feedparser`; added `fmp.get_earnings_calendar`
and `eight_k_seen` store CRUD. No agent SYSTEM-prompt or model-assignment changes.

- **post_earnings** (daily 06:00): FMP earnings calendar → which active watchlist
  tickers reported in last 24h → `run_track_status` each → material diffs emit an
  `important` earnings_diff alert; cannot-evaluate logs a quiet alert (daily cadence
  = the 24h retry). Daily cost ceiling honored (metered backend only).
- **eight_k_monitor** (every 30 min): feedparser on EDGAR's getcurrent 8-K atom feed,
  filtered to watchlist CIKs, dedup via `eight_k_seen`, alert on the 13 material item
  codes (1.01/2.02/5.02/…). `--summarize` adds an opt-in ~$0.005 Haiku line.
- **weekly_cache_warm** (Sun 02:00): warms profile/income/balance/cashflow/insiders/
  10-K per active ticker + ETF holdings for every theme. No LLM.
- **sunday_batch** (Sun 04:00): runs BATCH_THEMES × SUNDAY_BATCH_MAX_CANDIDATES,
  writes `reports/batch/{date}/{theme}.json`, diffs top-5 vs last week (new/dropped/
  conviction shifts >15), emails one digest. Weekly cost ceiling honored.

### Live acceptance (3-ticker watchlist: TSM, NVDA, ARM; Max backend)
All four jobs ran via `run-job` and wrote `runs` rows (status=success):
- eight_k_monitor: success (real EDGAR feed; 0 new material in the poll window).
- post_earnings: success (0 watchlist reporters in last 24h → no inspects).
- weekly_cache_warm: success (3 tickers warmed; ETFs warmed, non-scraped ETFs like
  XSD fail gracefully and are counted, not fatal).
- sunday_batch: minimal config (1 theme × 2 candidates) to prove end-to-end cheaply;
  default is 3 themes × 10 (~$10-20 metered). [result appended below]

### sunday_batch live result (minimal config)
`BATCH_THEMES="AI infrastructure" SUNDAY_BATCH_MAX_CANDIDATES=2 run-job sunday_batch`
→ success. Wrote `reports/batch/2026-05-27/ai_infrastructure.json`; emitted digest
alert "Weekly research digest — 2026-05-27 (1 themes)". Confirms the full chain:
analyze → store report → week-over-week diff (first run) → digest email. run_job
now records the job's aggregate `spent_usd` on the runs row.

Tests: 99 passed, 1 skipped (+7 Phase 5 in test_automation.py). All four jobs
verified end-to-end on a 3-ticker watchlist; each writes a runs row (success).

## v2 Phase 6 — Web UI (2026-05-27)

### Backend — FastAPI (`src/stock_agents/api/`)
Routes for watchlist (list/add/delete/history/refresh), runs (list/detail/report),
alerts (list/ack), themes (list/analyze), thesis (snapshot detail), settings
(masked GET / overlay POST). CORS restricted to localhost:3000. Long ops
(analyze/inspect/refresh) return a `run_id` immediately and run as FastAPI
background tasks; `run_track_status` gained an optional `run_id` so the API's
pre-created run row is the one polled. New deps: `fastapi`, `python-multipart`.
`serve-api` CLI command added. 11 offline tests in `tests/test_api.py`.

### Frontend — Next.js 14 (`stock_agents_ui/`)
7 pages (Dashboard, Watchlist, Ticker detail, Runs, Run detail, Themes, Settings),
shadcn-style hand-rolled primitives (Card/Button/Badge/Table/Skeleton), Recharts
conviction trend, dark-mode default, SWR data fetching, monospace tickers, shimmer
skeletons, single accent color. `lib/api.ts` mirrors the backend schemas.

### Verification
- `npm install` (clean) + `npm run build`: **✓ Compiled successfully**, all 8
  routes built, TypeScript validated, 0 errors.
- Servers up: backend `/api/health` 200; all 7 frontend routes serve HTTP 200.
- Backend returns real SQLite data (watchlist TSM/NVDA/ARM, 10 runs, 11 themes,
  masked keys). CORS verified: cross-origin GET + POST preflight from :3000 return
  `access-control-allow-origin: http://localhost:3000`.
- NOT done here: in-browser click-through and Lighthouse (≥90) — these need a real
  browser session / Playwright browser binaries (heavy install). Flagged as local
  manual checks. The build's type-check covers the SWR call signatures.

Tests: 110 passed, 1 skipped (unchanged by the FE; +11 API in Phase 6). This
completes the v2 spec phases 1-6.

## V2 addendum — Forensic agent + asymmetric filtering (2026-05-27)

### Part 1 — asymmetric opportunity filtering
`etf.AsymmetricFilter` + `etf.filter_candidates` (market-cap band + optional price,
fail-open on data errors); `fmp.get_fx_rate("GBPUSD")` for GBP→USD (cached daily).
CLI `--min/max-market-cap-gbp`, `--max-price-gbp`, `--currency`; defaults £500M–£50B;
price filter auto-applies the £500M floor. Screener is told the band; output is
hard-filtered; `FinalReport.filter_note` records thresholds + per-reason exclusions.
NOTE: the addendum named `ETFScreener._filter_candidates`, but the v1 screener is an
LLM agent, not a class — so the filter applies to the screener's candidate universe
(prompt + hard output filter), documented as a deliberate deviation.
Offline tests: band include/exclude, inactive no-op, fail-open.

### Part 2 — Forensic agent
`agents/forensic.py` (Opus), after balance sheet / before stress test, behind
`--forensic`. `ForensicReport`/`ForensicFinding` schemas; `compare_risk_factors` tool
(diffs the two most recent 10-Ks' Risk Factors). Stress Test + Synthesizer consume
the report; conviction re-weights in forensic mode (forensic risk 15%, inverted:
(0.20f+0.15b+0.20m+0.30s+0.15(11-risk))·10).

**Anti-hallucination guard:** `base.extract_accessions` records the accession numbers
each tool call surfaced into the audit entries (both backends). `forensic.run` checks
every finding's citation against the fetched-accession set; if any finding cites an
accession that wasn't fetched (or has no citation), it re-runs once with a correction,
then strips still-invalid findings rather than emit a fabricated red flag.

### Live verification
- `compare_risk_factors AAPL` (free, EDGAR): diffed FY2025 (0000320193-25-000079) vs
  FY2024 (0000320193-24-000123) 10-Ks — real accessions, 1 added / 1 removed.
- `inspect AAPL --forensic` (Max): forensic risk **3/10** (expected 2-4 for Apple's
  clean filings); conviction 72.5 via the forensic formula (6·.20+9·.15+7·.20+7·.30+
  (11-3)·.15)·10 = 72.5 ✓. Forensic agent equiv ~$1.8 (above the addendum's $0.4-0.8
  estimate — it reads several full filings on Opus; the citation re-run can double it).
- Citation validation (standalone forensic.run AAPL): [appended below].

Tests: 118 passed, 1 skipped (+8 test_forensic.py). One existing test's mock synth
signature updated for the new forensic_report kwarg (not weakened).

### Citation validation result (standalone forensic.run AAPL)
forensic_risk 3, 8 findings (5 green / 3 yellow / 0 red), equiv $0.66, 23 accessions
fetched. Every finding cites a real, fetched accession — ALL CITATIONS VALID = True
(10-K 0000320193-25-000079, DEF 14A 0001308179-26-000008, 8-K 0001140361-26-015711).
Predominantly green, score in the expected 2-4 band for Apple. NOTE: the forensic
agent occasionally returns no valid JSON (heaviest agent; one standalone attempt did)
— the pipeline treats that as non-fatal (forensic_report=None), so a miss degrades
gracefully rather than blocking the run.
