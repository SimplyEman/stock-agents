# CLAUDE.md

This file is read fresh by every Claude Code session, subagent, and team member working on this repository. Keep it accurate. If you change architecture, update this file in the same commit.

## Mission

`stock_agents` is an autonomous equity research pipeline that finds asymmetric long opportunities — companies that look like Apple in 2010 or Nvidia in 2021 before the consensus catches up. Specialist Claude agents screen thematic ETFs, analyze fundamentals, evaluate balance sheets, vet management, stress-test theses, and produce ranked investment write-ups with explicit bull and bear cases.

**This is a research tool, not a trading system.** Output is a written thesis with conviction scores. There is no execution, no portfolio sizing math, no real-time signal generation, no broker integration. Do not add any of that without explicit user approval.

## Architecture at a glance

A theme (e.g., "AI infrastructure") enters the orchestrator. The orchestrator calls the ETF screener to produce 15-25 candidates, then for each candidate runs four analyst agents (Fundamentals, Balance Sheet, Management, Stress Test) in parallel, then runs the Synthesizer to weight inputs and produce a final `InvestmentThesis`. Top picks are ranked into a `FinalReport`. The orchestrator is mostly Python code with a thread-safe budget guard; only the screener-validation step and the analyst agents themselves are Claude calls.

```
theme → orchestrator
         ├── macro_overlay (Sonnet, once/run)   → MacroContext  ──┐ (→ synthesizer)
         ├── etf_screener (Sonnet)              → CandidateList   │
         └── for each candidate (parallel, 4 workers):            │
              ├── fundamentals (Sonnet)         → FundamentalsReport
              ├── balance_sheet (Sonnet)        → BalanceSheetReport
              ├── management (Sonnet)           → ManagementReport
              ├── stress_test (Opus)            → StressTestReport
              ├── peer_comparison (Sonnet)      → PeerComparisonReport
              └── synthesizer (Opus)            → InvestmentThesis
                                                 → FinalReport (+ macro_context)
```

v2 Phase 2 added `macro_overlay` (once per run, before screening) and
`peer_comparison` (per candidate, after stress test). They inform the
synthesizer and surface as `peer_preference_strength` / `macro_fit` on each
thesis and `macro_context` on the report; they do NOT change the conviction
composite. Cost: a 5-candidate run rose ~$5.8 → ~$9.7 equivalent (+66%, above
the spec's 30-40% estimate — peer comparison pulls peer financials).

## Tech stack

- Python 3.11+, dependency-managed with `uv`.
- `anthropic`, `pydantic` v2, `pydantic-settings`, `httpx`, `tenacity`, `diskcache`, `rich`, `typer`, `beautifulsoup4`, `lxml`.
- Dev: `pytest`, `pytest-vcr`, `pytest-cov`, `vcrpy`, `ruff`.
- Lint: `ruff` (config in `pyproject.toml`). Run `ruff check` and `ruff format` before committing.

**Model selection (cost-relevant — do not change without reason):**
- Orchestrator validation step + Stress Test + Synthesizer → `claude-opus-4-7`
- ETF Screener + Fundamentals + Balance Sheet + Management + Peer Comparison + Macro Overlay → `claude-sonnet-4-6`

The reasoning: Stress Test needs adversarial creativity, Synthesizer needs to weigh conflicting signals; everything else is structured analysis Sonnet does well at lower cost.

## Repository layout

```
src/stock_agents/
  config.py                    # pydantic-settings, reads .env
  models/                      # All Pydantic schemas — authoritative output contracts
    company.py                 # Candidate, CandidateList
    analysis.py                # FundamentalsReport, BalanceSheetReport, ManagementReport, StressTestReport
    thesis.py                  # InvestmentThesis, FinalReport
  data/
    fmp.py                     # Financial Modeling Prep client
    edgar.py                   # SEC EDGAR client (requires User-Agent)
    etf.py                     # iShares + ARK scrapers, FMP fallback
    tiingo.py                  # News (optional)
    cache.py                   # diskcache wrapper
    metrics.py                 # Deterministic ratio math (NOT done by Claude)
    _http.py                   # Shared httpx client + retries
  tools/
    definitions.py             # 13 tool schemas + Anthropic web_search
    handlers.py                # Tool implementations, accept ToolContext(as_of=...)
  agents/
    base.py                    # AgentRunner: tool loop, JSON validation, cost tracking
    orchestrator.py            # Mostly Python; spawns 4-worker thread pool
    etf_screener.py
    fundamentals.py
    balance_sheet.py
    management.py
    stress_test.py
    synthesizer.py
  backtesting/
    point_in_time.py           # Filing-date filtering, drops undated rows
    harness.py                 # Forward-return math, benchmark comparison
  cli.py                       # `stockagents analyze | inspect | cost-report`
```

System prompts live inside each agent module as a `SYSTEM_PROMPT` constant. The prompts are the agent — change them carefully and re-run calibration after changes.

## Quickstart

```bash
cp .env.example .env           # add ANTHROPIC_API_KEY, FMP_API_KEY, EDGAR_USER_AGENT
uv sync
uv run pytest                  # 42 should pass, 1 live test skips without keys
uv run stockagents inspect AAPL                                # sanity check, ~$0.30
uv run stockagents analyze "AI infrastructure" --max-candidates 5 --output report.json
uv run stockagents cost-report                                  # cumulative spend ledger
uv run stockagents analyze "cloud software" --backtest-date 2020-01-01
```

## Current focus

**Update this section whenever you switch tasks.** It's the single most useful signal for the next session.

- **As of last update (2026-05-26):** First live calibration session. Two blockers
  found and fixed: (1) FMP deprecated the legacy `/api/v3` API (403) — migrated
  the client to `/stable` (see `data/fmp.py`, user-approved); (2) `AgentRunner`
  passed `tools=null` for the tool-less synthesizer (400) — fixed in `base.py`.
- **Cost finding:** with metered API + Opus stress_test+synthesizer, a 5-candidate
  run is ~$9.5 and trips the $5 guard; Calibration Target #1 ($1.25/5-candidate) is
  unreachable without changing model assignments. Target NOT lowered.
- **Backend pivot:** Added a `claude_code` LLM backend (`agents/claude_code_backend.py`)
  that drives the `claude` CLI via the Claude Agent SDK on a Max subscription, so
  model usage counts against the plan instead of metered API dollars. Select with
  `LLM_BACKEND=claude_code` and an UNSET `ANTHROPIC_API_KEY`. Calibration runs use
  this backend. The Anthropic API backend remains the default (and is what the
  offline test mocks exercise).
- **Calibration done (2026-05-26):** Ran AI-infra (baseline + 1 iteration), biotech,
  and the cloud-software 2020 backtest on the Max backend. One prompt change
  (stress_test full-range survivability anchors) moved conviction spread 17.5->25.0
  (now PASS) and stress stdev 1.02->1.47 (still <2.0). Targets #2/#4/#5 met; #1
  unreachable on metered API; #3 improved but short (partly structural); #6 NOT
  credibly met — the LLM screener has lookahead (picked CRWV/IPO-2025 and PLTR for a
  2020 backtest). See `docs/iteration_notes.md` and the README "Results" section.
- **V2 addendum (Forensic + asymmetric filtering) — done (2026-05-27):**
  Part 1: `etf.AsymmetricFilter` + `etf.filter_candidates` + `fmp.get_fx_rate`
  (GBP→USD); CLI `--min/max-market-cap-gbp`, `--max-price-gbp`, `--currency`;
  report `filter_note`. Part 2: `agents/forensic.py` (Opus), `ForensicReport`/
  `ForensicFinding`, `compare_risk_factors` tool, anti-hallucination citation guard
  (`base.extract_accessions` records fetched accessions in audit entries; forensic.run
  rejects/strips uncited findings + one re-run). Forensic runs after balance sheet,
  before stress test, behind `--forensic`; re-weights conviction (forensic risk 15%,
  inverted). Stress Test + Synthesizer consume the forensic report. README: "What
  hidden information means" + Asymmetric/Forensic mode sections.
- **v2 Phase 6 (Web UI) — done (2026-05-27):** FastAPI backend (`src/stock_agents/api/`,
  routes for watchlist/runs/alerts/themes/thesis/settings, CORS to :3000, background
  tasks return run_id, `tests/test_api.py`) + Next.js 14 app (`stock_agents_ui/`,
  7 pages, shadcn-style primitives, Recharts, dark mode, SWR). New deps: `fastapi`,
  `python-multipart` (backend); Node app is separate. `serve-api` CLI command added.
  Lighthouse is a manual local check (can't run headless here).
- **v2 Phase 5 (job bodies) — done (2026-05-27):** the four jobs are real now.
  `post_earnings` (FMP earnings calendar -> track-status -> material alerts, daily
  budget guard); `eight_k_monitor` (feedparser on EDGAR's 8-K atom feed, watchlist-
  CIK filter, material-item alerts, `eight_k_seen` dedup, opt-in `--summarize` Haiku);
  `weekly_cache_warm` (no-LLM cache warming); `sunday_batch` (BATCH_THEMES x
  SUNDAY_BATCH_MAX_CANDIDATES -> reports/batch/{date}/{theme}.json -> week-over-week
  diff -> digest email, weekly budget guard). New dep: `feedparser`. Added
  `fmp.get_earnings_calendar` and `eight_k_seen` store CRUD.
- **v2 Phase 4 (Automation infra) — done (2026-05-27):** `automation/` (runner +
  4 stub jobs + APScheduler daemon + cron generation) and `notify/` (Pushover +
  SendGrid over httpx, formatter, dispatch). CLI: `daemon`, `generate-cron`,
  `run-job`, `notify-test`. Alerts CRUD added to `track/store.py`. Every job writes
  a `runs` row; failures write an `important` alert + notify. New dep: `apscheduler`
  (Pushover/SendGrid use raw httpx — no python-pushover/aiosmtplib). Job BODIES are
  stubs — Phase 5 fills them. `feedparser` deferred to Phase 5 (8-K RSS).
- **v2 Phase 3 (Earnings transcripts) — done (2026-05-27):** `data/transcripts.py`
  (AlphaVantage → IR registry → SEC 8-K Item 2.02 exhibit, legal-first; never
  Seeking Alpha/Motley Fool). New tool `get_earnings_transcript`; Management agent
  pre-fetches the transcript and scores Q&A vagueness/evasion (live A/B/C: evasive
  call drops score 8→6, flips call_quality to "evasive"). `ALPHAVANTAGE_API_KEY`
  optional. Point-in-time constituents deferred — see `docs/v2_decisions.md`.
- **v2 Phase 2 (Peer Comparison + Macro Overlay) — done (2026-05-27):** two new
  Sonnet agents wired into the topology (diagram above); schemas
  `PeerComparisonReport` / `MacroContext`; `InvestmentThesis` gained
  `peer_preference_strength` + `macro_fit`, `FinalReport` gained `macro_context`
  (all backward-compatible defaults). Conviction composite unchanged. Live-verified
  on Max; cost band ~$9-10/5-candidate. Tests 68 passed, 1 skipped.
- **v2 Phase 1 (Track + Watchlist) — done (2026-05-27):** new `track/` package
  (SQLModel-backed SQLite at `data/stock_agents.db` + JSON snapshots under
  `data/snapshots/`), CLI `track / watchlist / track-status / track-history /
  untrack / track-pause / track-resume`, and material-change `Diff`. New dep:
  `sqlmodel` (ULIDs generated in-stdlib, no `ulid` dep). Orchestrator gained
  `analyze_single_detailed` / `analyze_ticker_detailed` returning the analyst
  reports + cost (so snapshots can diff red flags). No agent SYSTEM prompts changed.
  See V2_BUILD_SPEC.md for the full v2 plan; build phases in spec order.
- **Backtest follow-up (lower priority):** to make backtests trustworthy, constrain the
  candidate universe to a point-in-time constituents dataset (the LLM screener leaks
  future knowledge); future-IPO lookahead is already blocked via `was_investable_on`.
- **Active questions:** Is the $1.25/5-candidate cost target meant for the metered
  API path? It is unreachable there with two Opus calls per candidate; on the Max
  backend, per-candidate "cost" is a usage-equivalent estimate, not billed.

## Calibration targets

Every quality decision is measured against these. If a change improves one of these without regressing the others, ship it.

1. **Cost per run:** A 15-candidate analysis should land between $1.50 and $3.50. A 5-candidate run should land under $1.25. Hard ceiling per run: $5 (budget guard aborts above this).
2. **Conviction score spread:** Top 5 picks in a `FinalReport` should span ≥20 points. If everything is clustered 55–70, the synthesizer is hedging — fix the prompt.
3. **Stress test variance:** Survivability scores across candidates should have ≥2.0 standard deviation. If every score is 7-8, the bear cases are toothless — make the stress test prompt more adversarial.
4. **Candidate relevance:** For a known theme like "AI infrastructure," the candidate list must include the obvious names (NVDA, AMD, AVGO, MU, ARM) and surface non-obvious ones (e.g., VRT, SMCI, CRDO, ALAB). If mega-caps with weak thematic fit (MSFT, GOOG) crowd the top-5, the screener is over-indexing on market cap.
5. **JSON validation rate:** Each agent should pass validation on the first try ≥90% of the time. Track failures in the audit log. If one agent falls below 90%, tighten its schema description in the prompt.
6. **Backtest signal:** Top-5 picks should beat the relevant theme ETF benchmark by ≥2% annualized averaged across at least three historical themes. One backtest is not signal; variance is high.

## Iteration priorities (likely problems, in expected order)

When live runs reveal issues, they will probably be in this order. Expect to spend time here:

1. **Management agent noise.** Web search results vary widely; Claude's read of "governance concerns" drifts. If this is the biggest issue, consider adding a deterministic Form 4 aggregation step in `data/metrics.py` and passing the pre-computed numbers into the agent rather than asking it to do the math.
2. **Synthesizer score hedging.** LLMs trained for safety over-hedge. Likely fix: explicit instruction to use the full 0-100 range, and a calibration example in the system prompt showing what a 30 vs 80 looks like.
3. **Stress test toothlessness.** If survivability scores are all 7+, amplify the adversarial framing in the prompt. The point of this agent is rigor, not balance.
4. **ETF screener filter bounds.** The $500M floor and $500B ceiling are guesses. If runs show good ideas at $300M getting filtered or genuine 10x candidates being excluded as too small, adjust.
5. **Cost overruns.** If runs exceed budget, the most likely culprit is re-fetching the same 10-K for multiple agents. Check `diskcache` hit rates.

## Known limitations (be honest about these)

These are documented in the README. Do not silently work around them.

- **Short interest is stubbed.** FMP's free tier has unreliable short interest data. The tool returns a clear "not implemented" message rather than fake numbers. If a paid data source becomes available, wire it in.
- **No survivorship-bias correction in backtests.** The delisted-securities dataset is not yet wired in. Backtest results overstate performance because failed companies are excluded from the historical candidate universe.
- **Web search is disabled in backtests.** Point-in-time web results are not reliably available. The Management agent in historical mode has less signal than in live mode.
- **Single-issuer ETF coverage.** Only iShares and ARK are scraped natively; everything else falls back to FMP. Vanguard, VanEck, Global X, First Trust ETFs may have less complete holdings data.
- **No earnings call transcripts.** AlphaSense and similar are enterprise-priced. Management quality reads are based on shareholder letters, proxy filings, and web search — not call Q&A as originally specced.

## Conventions

- **Schemas are contracts.** Every agent returns a Pydantic model. No freeform text. If you need to add a field, update the model first, then the prompt, then the consumer.
- **No mutable globals.** Configuration goes through `config.py`. Per-run state (cost, audit log) goes through explicit parameters.
- **Deterministic math in Python, judgment in Claude.** Ratios, CAGRs, dilution rates, score weightings → `data/metrics.py`. Pattern recognition, narrative interpretation, scoring → agents.
- **Tool handlers thread `ToolContext`** so `as_of` filtering works in backtests. Do not hardcode "today" anywhere.
- **No emojis in code or output.** Plain text only.
- **Ruff is canonical.** Disagree with a rule? Configure it in `pyproject.toml`, don't sprinkle `# noqa` comments.

## Cost discipline

The single biggest cost trap is cache misses. Rules:

- Every external API call goes through `data/cache.py`. No raw `httpx` calls outside the data layer.
- Cache keys must include any parameter that changes the response, including `as_of` for backtests.
- Cache TTL: 24h for fundamentals, 7d for historical prices, 30d for proxy statements (they update annually), 1h for ETF holdings (they update daily but intra-day stability matters for a single run).
- The budget guard in `orchestrator.py` is thread-safe. Do not bypass it.
- Before any unattended `/goal` run, set a session budget ceiling explicitly: `--budget 10` for a $10 cap. Default is $5.

## Data layer rules

- **EDGAR requires a User-Agent header.** Pulled from `EDGAR_USER_AGENT` env var. Without it, SEC will block the request. Do not hardcode a fake one.
- **EDGAR rate limit is 10 req/sec.** `_http.py` enforces this. Do not parallelize EDGAR scraping past 10 workers.
- **FMP has a rate limit per minute that depends on plan tier.** Tenacity retries with backoff handle 429s, but bulk operations should pace themselves.
- **Filing text is truncated to ~50k tokens before being passed to Claude.** Section extraction (MD&A, risk factors, exec comp) lives in `data/edgar.py`. Do not pass full 10-Ks into agent context.
- **Point-in-time filtering:** `data/edgar.py` filters filings by `filed_date <= as_of`. `data/fmp.py` uses FMP's `acceptedDate` field where available. Filings with no `accepted_date` are dropped in backtest mode — do not silently include them.

## Agent authoring rules

- **JSON output forced via system prompt + validation.** `AgentRunner` validates the final assistant message against the agent's output schema. On parse failure, one correction message is sent. Two failures = the agent is broken; do not paper over it with a third retry.
- **System prompts are version-controlled.** Treat changes like API contract changes. Re-run calibration after changes.
- **Tools are typed.** Tool input schemas in `tools/definitions.py` must match handler signatures in `tools/handlers.py`. If you change one, change both in the same commit.
- **Stress Test gets prior reports in the user message,** not via tool calls. It is meant to react to the bullish analysis, not start from scratch.
- **Synthesizer has no tools.** It is pure reasoning over the four prior reports. Do not add tools to it without removing them from somewhere — every tool a synthesizer can call is a tool the analysts should have called first.

## Testing

- `pytest-vcr` cassettes for all external API calls. Tests run offline.
- Anthropic client is mocked for agent unit tests. Assert on schema validity, retry behavior, cost tracking — not on conviction scores (those drift with model updates).
- One live end-to-end test exists and auto-skips without API keys. Do not delete it. Run it manually after material agent changes.
- New agents need at minimum: schema test, valid-input test, malformed-JSON-correction test.

## When to ask the user

Ask before:
- Adding any new runtime dependency
- Changing data providers (FMP → Polygon, etc.)
- Changing the agent topology (adding, removing, or merging agents)
- Anything related to real money: live trading, broker integration, position sizing
- Changing the model assignments above (Opus ↔ Sonnet)
- Modifying the calibration targets in this file

Do not ask before:
- Improving prompt clarity within an existing agent
- Adding tools the existing agents need
- Adding tests
- Fixing bugs
- Updating this file's "Current focus" section

## Common pitfalls (do not repeat)

- **Do not have Claude do math the data layer can do.** Computing CAGR from a list of revenues is a deterministic operation; route it through `metrics.py`. Letting Claude do arithmetic produces drift between runs.
- **Do not let prompts grow unbounded.** Each agent's full context (system + user + tools + prior turns) should stay under ~30k tokens. If you're stuffing more in, the data layer is doing too little preprocessing.
- **Do not write "as of today" anywhere.** Use `ToolContext.as_of`. Hardcoding the current date breaks backtests silently.
- **Do not assume search is available in backtests.** It isn't, by design. Conditional agent behavior must check `ctx.is_backtest`.
- **Do not bypass the audit log.** Every agent invocation writes to JSONL. Do not add a "fast path" that skips it.
- **Do not interpret one backtest as signal.** Variance is high. Three themes minimum, five years minimum, and explicit benchmark comparison.

## Useful references inside the repo

- `examples/ai_infrastructure.py` — reference end-to-end run
- `docs/iteration_notes.md` — running log of what was tried and what happened (create if it doesn't exist; append to it after every meaningful calibration run)
- `tests/test_data/` — VCR cassettes; check what's recorded before adding new ones
