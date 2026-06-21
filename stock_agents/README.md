# stock-agents

A multi-agent equity research pipeline that hunts for **asymmetric long
opportunities** — the kind of setups that looked like Apple in 2010 or Nvidia in
2021 *before* they were obvious. A coordinated team of specialist Claude agents
screens thematic ETFs, analyzes fundamentals, dissects balance sheets, vets
management, stress-tests the bull case, and synthesizes a ranked investment
write-up with explicit bull/bear cases and a calibrated conviction score.

> **This is a research tool, not a trading system.** Output is a written thesis
> with conviction scores. There is no order execution, no portfolio management,
> no position sizing, and no real-time signals. Nothing here is investment
> advice. The system produces confident-sounding output that is still
> fundamentally uncertain — read the [Limitations](#limitations) section before
> trusting any number it emits.

## What "hidden information" actually means

This system reads SEC filings carefully and surfaces things that are publicly
available but rarely in mainstream coverage — risk factor changes, footnote
anomalies, insider trade patterns, working capital quirks, auditor changes. These
are signals real analysts use; the system's edge is reading them consistently
across many companies, not exposing secrets. It cannot find information that is not
in public filings. It cannot consistently beat professional sell-side analysts on
companies they're paid to cover. It can absolutely surface things that aren't in
headlines, news articles, or social media coverage of a stock — which is most
companies, most of the time.

Use the Forensic agent's output to *ask better questions* about a candidate. Use the
citations to read the source documents yourself. The system is a research aid that
helps you read filings more thoroughly, not an oracle that bypasses them.

## How it works

```
theme ──▶ Macro/Sector Overlay (once per run) ─────────────────┐ (context →
   │                                                            │  synthesizer)
   ▼                                                            │
ETF Screener ──▶ candidate list (15-25 names)                   │
                               │                                │
                  ┌────────────┴── for each candidate (parallel) ──┐
                  ▼                                                 │
        ┌─ Fundamentals ─┐                                          │
        ├─ Balance Sheet ┤  (3 analysts run concurrently)          │
        └─ Management ───┘                                          │
                  ▼                                                 │
            Stress Test (adversarial; reads the 3 reports)         │
                  ▼                                                 │
            Peer Comparison (why this and not the closest peer?)   │
                  ▼                                                 │
            Synthesizer (weighs the 4 core reports + peer + macro) │
                  └─────────────────────────────────────────────────┘
                               ▼
                     ranked FinalReport + market commentary
```

Every agent has a **narrow scope, a fixed tool set, and a Pydantic output
schema** — no freeform text. The orchestrator is mostly plain Python (parallel
execution, budget guard, ranking) and only calls Claude for two narrow
decisions: sanity-checking the screened list and writing the closing commentary.

### Agents & models

| Agent          | Model            | Job |
|----------------|------------------|-----|
| Macro Overlay  | `claude-sonnet-4-6` | Once per run: cycle/regime context for the theme |
| ETF Screener   | `claude-sonnet-4-6` | Theme → deduplicated, weighted candidate list |
| Fundamentals   | `claude-sonnet-4-6` | Revenue quality, margins, growth durability |
| Balance Sheet  | `claude-sonnet-4-6` | Leverage, dilution, capital allocation, red flags |
| Management     | `claude-sonnet-4-6` | Insider behavior, governance, capital stewardship |
| Stress Test    | `claude-opus-4-7`   | The strongest bear case — **the most important agent** |
| Peer Comparison| `claude-sonnet-4-6` | Why this one and not the closest investable alternative |
| Synthesizer    | `claude-opus-4-7`   | Weigh the 4 core reports (+ peer & macro context) → thesis |
| Orchestrator   | `claude-opus-4-7`   | List validation + market commentary only |

Reasoning-heavy / adversarial agents get Opus; structured analysts get the
cheaper Sonnet. **Peer Comparison** (per candidate) and **Macro Overlay** (once
per run) were added in v2 Phase 2. They inform the synthesizer's *reasoning* and
surface as `peer_preference_strength` / `macro_fit` on each thesis and
`macro_context` on the report — but they do **not** enter the conviction
composite (the four-component weighting below is unchanged).

### Conviction score

The synthesizer carries forward the four component scores (1–10); the composite
is computed **deterministically in Python**, not by the model, so the weighting
is exact and auditable:

```
conviction = (0.25·fundamentals + 0.20·balance_sheet
              + 0.25·management + 0.30·stress_test) · 10
```

→ `0–40 low · 40–60 medium · 60–80 high · 80–100 very high`. The stress test
gets the largest weight on purpose: most stock analysis is bullish boilerplate;
the differentiator here is rigorous adversarial review.

## Setup

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev          # create .venv and install deps
cp .env.example .env         # then fill in your keys
```

`.env` keys:

| Variable | Required | Notes |
|----------|----------|-------|
| `ANTHROPIC_API_KEY` | yes | The agents |
| `FMP_API_KEY` | yes | [Financial Modeling Prep](https://site.financialmodelingprep.com/developer) — financials, prices, screener |
| `EDGAR_USER_AGENT` | yes | SEC **requires** a `"Name email@example.com"` UA or rejects requests |
| `TIINGO_API_KEY` | no | News (optional; not part of scoring) |
| `CACHE_DIR` | no | Default `.cache` |
| `RUN_BUDGET_USD` | no | Default `5.0`; run aborts if projected spend exceeds it |

## Usage

```bash
# Full thematic run
uv run stockagents analyze "AI infrastructure" --max-candidates 15 --output report.json

# Point-in-time backtest (no lookahead — see Limitations)
uv run stockagents analyze "biotech" --backtest-date 2018-01-01

# Single ticker, ad hoc
uv run stockagents inspect NVDA

# Cumulative API spend across all runs
uv run stockagents cost-report
```

Or drive it from Python — see [`examples/ai_infrastructure.py`](examples/ai_infrastructure.py).

Supported themes ship in `data/etf.py::THEME_REGISTRY` (AI infrastructure,
biotech, cybersecurity, clean energy, fintech, cloud software, semiconductors,
robotics, genomics, space, EV/battery). Unknown themes fall back to fuzzy
matching; extend the registry to add your own.

## Asymmetric opportunity mode

Bias the universe toward smaller companies where 5–10x upside is still plausible,
by **market cap** (the right filter) rather than share price (the wrong one):

```bash
stockagents analyze "AI infrastructure" \
  --max-market-cap-gbp 10000000000 \   # £10B ceiling
  --min-market-cap-gbp 100000000 \     # £100M floor (illiquidity boundary)
  --max-price-gbp 100 \                # optional; rarely useful
  --currency gbp                       # or --currency usd
```

All thresholds are optional; defaults are £500M–£50B, no price filter. GBP
thresholds are converted to USD using the FMP `GBPUSD` rate (cached daily).
Filters apply to the candidate universe (the screener is told the band up front
and out-of-band names are hard-dropped), and the report's `filter_note` states the
thresholds used and how many names each filter excluded. If `--max-price-gbp` is
set, a £500M cap floor is auto-applied — a price filter alone surfaces too much
illiquid junk. **Why market cap, not price:** share price is arbitrary (a £500 stock
can be smaller than a £5 one); market cap is the real measure of size and upside room.

## Forensic mode

`--forensic` adds a Forensic agent (Opus) per candidate that reads the filings for
what's *in the documents but not the headlines*: risk-factor deltas year-over-year,
footnote anomalies (related-party deals, off-balance-sheet items), working-capital
quirks, auditor/restatement signals, insider patterns, proxy governance, and recent
8-Ks. It is not a bull or a bear — it is a reader of documents.

```bash
stockagents analyze "AI infrastructure" --max-candidates 10 --forensic
stockagents inspect NVDA --forensic
```

Every finding must cite a real filing (accession number); an **anti-hallucination
guard** rejects any citation that doesn't trace to a filing the agent actually
fetched, re-runs once, and strips uncited findings rather than emit a confident
fabricated red flag. In forensic mode the conviction composite re-weights to give
forensic risk 15% (higher forensic risk lowers conviction):

```
conviction = (0.20·fundamentals + 0.15·balance_sheet + 0.20·management
              + 0.30·stress_test + 0.15·(11 − forensic_risk)) · 10
```

**Cost:** ~$0.40–$0.80 per candidate on Opus (a 5-candidate forensic run is ~$5 on
the metered API; usage-equivalent on Max). Off by default — enable per run with the
flag. The Stress Test reads the forensic report and must address red findings; the
Synthesizer weights them.

## Watchlist & tracking (v2)

Turn one-off analyses into a persistent watchlist that you can re-evaluate over
time. State lives in SQLite (`data/stock_agents.db`) plus JSON thesis snapshots
(`data/snapshots/{TICKER}/`); nothing here knows your position size — every
refresh is a re-evaluation, not a signal.

```bash
# Track a ticker using the thesis from a prior report (FinalReport, a bare
# thesis, or a saved snapshot). Omit --thesis to run a fresh inspect for the entry.
stockagents track NVDA --thesis ./report.json --entry-price 1450 --note "From AI-infra run"

# Show the watchlist with entry vs current conviction and the delta.
stockagents watchlist

# Re-run a full inspect, store a new snapshot, and diff it against the entry thesis.
stockagents track-status NVDA

# Full snapshot history for a ticker (conviction + component scores over time).
stockagents track-history NVDA

# Lifecycle.
stockagents track-pause NVDA      # stop monitoring, keep history
stockagents track-resume NVDA
stockagents untrack NVDA --reason "Falsifier fired: data-center growth decelerating"
```

**What `track-status` detects.** Each refresh produces a *diff* against the entry
thesis and flags it **material** when any of: composite conviction moved ≥15
points; any component score (fundamentals/balance/management/stress) moved ≥3; a
new red flag appeared in an analyst report; an entry falsifier ("what would
change my mind") is now echoed by the new bear case; or the ticker can no longer
be evaluated (delisted / missing data). Anything else is a quiet diff — stored
for history, not alerted. The diff renders in the terminal with `rich`.

Note on red flags: an entry imported from a theme `FinalReport` carries only the
synthesized thesis, not the per-agent reports, so the red-flag dimension shows
`n/a` until the first `track-status` (which captures the full analyst reports).
Snapshots from `track-status` and `inspect`-based entries do carry them.

## Earnings transcripts (v2)

The Management agent reads the latest earnings call when available, to judge Q&A
vagueness, executive evasion, and cross-quarter consistency. `data/transcripts.py`
fetches it legal-first, in priority order:

1. **AlphaVantage** `EARNINGS_CALL_TRANSCRIPT` (free tier; set `ALPHAVANTAGE_API_KEY`) — full Q&A.
2. **Company IR sites** — a small manual registry (`transcripts.IR_REGISTRY`); sparse by design.
3. **SEC 8-K Item 2.02 exhibit** — the earnings press release / prepared remarks, always
   available and free via EDGAR, selected by the filing's document *type* (EX-99.1).

Seeking Alpha and Motley Fool are **never** scraped (ToS). The transcript is
pre-fetched into the Management agent's user message (truncated to ~30k tokens);
in backtest mode only the 8-K source is used, filtered to filings before the
as-of date. If no source has content the agent proceeds on filings + insider data
alone. Verified live: AAPL, NVDA, MSFT all resolve via the 8-K path.

## Automation (v2)

Scheduled jobs turn the workstation from on-demand into event-driven. Job bodies
are stubs in Phase 4 and filled in Phase 5; the runner, scheduler, and alerting
are live now. Every job records a `runs` row before starting and, on failure,
writes an `important` alert and notifies.

Two execution modes — choose one:

```bash
# Mode A — cron (default). Print the snippet, review paths, install it.
stockagents generate-cron            # or --write to save automation/cron.sh
crontab automation/cron.sh

# Mode B — in-process scheduler (no cron access needed). Runs until Ctrl-C.
stockagents daemon

# Run a single job once (what cron invokes; also handy for testing).
stockagents run-job post_earnings
```

| Job | Schedule | What it does | Cost/run |
|-----|----------|--------------|----------|
| `post_earnings` | daily 06:00 | Finds watchlist tickers that reported in the last 24h (FMP calendar), re-runs `track-status`, alerts on material diffs; honors `DAILY_POST_EARNINGS_BUDGET_USD` | $1-3 (0 if none reported) |
| `eight_k_monitor` | every 30 min | Polls EDGAR's recent 8-K atom feed, filters to watchlist CIKs, alerts on material item codes (1.01, 2.02, 5.02, …); dedups via `eight_k_seen`. `--summarize` adds a ~$0.005 Haiku line per filing | ~$0 (no LLM by default) |
| `weekly_cache_warm` | Sun 02:00 | Refreshes fundamentals/filings/insider caches for active tickers + ETF holdings for every theme. No agents | $0 |
| `sunday_batch` | Sun 04:00 | Runs `BATCH_THEMES` (default 3) at `SUNDAY_BATCH_MAX_CANDIDATES` (default 10), stores `reports/batch/{date}/{theme}.json`, diffs each theme's top-5 vs last week, emails one digest; honors `WEEKLY_BUDGET_USD` | $10-20 (4×10, metered) |

Cost figures are metered-API estimates; on the Claude Max backend they are
usage-equivalent, not billed. Per-week recurring total is roughly $13-28 metered.

**Notifications.** Set a channel in `.env` (`ALERT_CHANNEL=pushover|email|both`):

```
PUSHOVER_USER_KEY=    PUSHOVER_APP_TOKEN=          # short push alerts
SENDGRID_API_KEY=     ALERT_EMAIL=  ALERT_FROM_EMAIL=   # HTML email digests
```

Both clients use plain HTTPS (no extra dependency). Test delivery with
`stockagents notify-test`; unconfigured channels are skipped, not errored. Diffs
and 8-Ks are rendered to short (Pushover) and long (email) form by
`notify/formatter.py`. Per-job cost ceilings (`WEEKLY_BUDGET_USD`,
`DAILY_POST_EARNINGS_BUDGET_USD`, `SUNDAY_BATCH_BUDGET_USD`) are honored by the
Phase 5 job bodies.

## Web UI (v2)

A local FastAPI backend + Next.js 14 frontend. No auth — local-only.

### One click

Double-click **`start.command`** (in the `Lidia/` folder, alongside `stock_agents/`)
from Finder — or run `./start.command`. It frees the ports, starts the backend
(:8001) and frontend (:3000), opens `http://localhost:3000`, and stops both when you
press Ctrl-C or close the window. First run installs the frontend deps automatically.

The launcher defaults to your **Claude Max subscription** (no metered $). To bill the
metered Anthropic API instead, set `USE_MAX=0` at the top of `start.command`.

### Manual (two terminals)

```bash
# Backend (FastAPI on :8001)
uv run stockagents serve-api            # or: uvicorn stock_agents.api.main:app --port 8001

# Frontend (Next.js on :3000) — in a second terminal
cd ../stock_agents_ui
cp .env.local.example .env.local        # NEXT_PUBLIC_API_BASE=http://localhost:8001
npm install
npm run dev                             # http://localhost:3000
```

**Backend** (`src/stock_agents/api/`): typed FastAPI routes for watchlist, runs,
alerts, themes, thesis snapshots, and settings. CORS is restricted to
`localhost:3000`. Long-running operations (`analyze`, `inspect`, `refresh`)
return a `run_id` immediately and execute as background tasks; the UI polls
`/api/runs/{run_id}`. `GET /api/settings` masks secrets (configured/not, never
values); `POST /api/settings` persists non-secret prefs to a `ui_settings.json`
overlay. Endpoints are covered by `tests/test_api.py` (offline, `TestClient`).

**Frontend** (`stock_agents_ui/`): seven pages — Dashboard, Watchlist, Ticker
detail (Recharts conviction trend + component bars + bull/bear + falsifiers +
snapshot history), Runs, Run detail (renders the FinalReport), Themes, Settings.
Dark mode default, Tailwind + shadcn-style primitives, monospace tickers/numbers,
shimmer skeletons, one accent color. Data via SWR.

> Lighthouse (perf/accessibility ≥90) is a local check — run it against your own
> `npm run dev` / `npm run build` session; it can't be measured headlessly here.

## Cost controls

- **Caching.** Every external API call is cached on disk (`diskcache`). Cache
  keys fold in a date stamp so daily-changing data refreshes naturally;
  fundamentals cache 24h, prices 7d. The same filing/financial is never fetched
  twice in a run.
- **Model split.** Sonnet for structured analysts, Opus only where reasoning is
  the product.
- **Budget guard.** A thread-safe cost tracker stops launching new candidates
  once spend crosses `RUN_BUDGET_USD`.
- **Audit log.** `audit_logs/tool_calls.jsonl` records every tool call and a
  per-agent token/cost summary; `cost_ledger.jsonl` powers `cost-report`.
- **v2 Phase 2 cost impact.** Adding Peer Comparison (per candidate) and Macro
  Overlay (once per run) raised a 5-candidate run from ~$5.8 to ~$9.7 equivalent
  (+66%, above the spec's 30-40% estimate — peer comparison pulls peer financials
  for the subject plus three comparables). Measured on the Claude Max backend, so
  not metered dollars; see `docs/iteration_notes.md` for the breakdown.

## Extending it

The orchestrator depends only on each agent's `run(...) -> AgentResult`
contract, so:

- **New agent:** add a module under `agents/` with a `SYSTEM` prompt and a
  `run()` wrapping `AgentRunner`, plus an output schema in `models/`. Wire it
  into `orchestrator.analyze_single`.
- **New tool:** add a schema to `tools/definitions.py` and a handler to
  `tools/handlers.py::HANDLERS`. Give it to whichever agents need it.
- **New data source:** add a client under `data/` following the existing
  pattern (rate limiter + `@with_retries` + `cache.cached_call` + typed return).
  Swapping FMP for another provider is isolated to `data/fmp.py` + handlers.

## Testing

```bash
uv run pytest                      # full suite, fully offline
uv run pytest --cov                # with coverage
```

Tests run **offline**: the data clients are exercised by patching their single
HTTP chokepoint with canned fixtures (`tests/test_data/`), and the agent runner
is tested against a fully mocked Anthropic client. Coverage is ~76% on the data
layer and ~63% overall. Live integration tests (real Anthropic + FMP) are
present but auto-skip unless the relevant API keys are set; a `vcr_config` is
provided for recording them against cassettes.

## Results (live calibration run, 2026-05-26)

These are real numbers from the first live calibration session. Two prerequisite
fixes were required first: FMP deprecated its legacy `/api/v3` API (migrated the
client to `/stable`), and the tool-less synthesizer crashed on `tools=null` (fixed
in `AgentRunner`). Full run-by-run detail with before/after numbers is in
[`docs/iteration_notes.md`](docs/iteration_notes.md).

**Backend note.** Calibration ran on the **Claude Code / Max subscription backend**
(`LLM_BACKEND=claude_code`), not the metered API. Per-run dollar figures below are
the SDK's *usage-equivalent* estimate; they are **not billed per token** (they draw
on the subscription). Real metered Anthropic API spend for the whole session was
**$10.15** and froze the moment we switched backends (verify with `stockagents
cost-report`, which splits the two).

### Top picks per theme

| Theme | Top picks (conviction) | Run cost (equiv) |
|-------|------------------------|------------------|
| AI infrastructure | NVDA 81.5 (very high), ASML 75.0, TSM 74.5, PLTR 59.5, ARM 56.5 | ~$5.8 |
| Biotech | NTRA 63.0 (high), IONS 48.0 (medium), ILMN 38.5 (low) | ~$5.3 |

Candidate relevance is strong: AI-infra surfaced semis/foundry/IP/networking leaders
with **no mega-cap (MSFT/GOOG) crowding**; biotech surfaced genomics/therapeutics
names and used the full conviction range (ILMN scored *low* at 38.5).

### Calibration target outcomes

| # | Target | Result | Verdict |
|---|--------|--------|---------|
| 1 | 5-candidate run < $1.25 | ~$9.5 on metered API (two Opus calls/candidate); $0 billed on Max | **Not met on API** (documented, not lowered); moot on Max |
| 2 | Conviction spread ≥ 20 | 17.5 → **25.0** after a stress-test prompt change; biotech 24.5 | **Met** (after one iteration) |
| 3 | Stress survivability stdev ≥ 2.0 | 1.02 → **1.47** after the same change; biotech 1.25 | Improved +44%, still short — partly structural (single-theme correlation) |
| 4 | Candidate relevance | obvious + non-obvious names, no mega-cap crowding | **Met** |
| 5 | JSON validation ≥ 90% first-try | ~99% (1 hard fail: DDOG in backtest) | **Met** |
| 6 | Backtest beats benchmark ≥ 2% annualized over ≥ 3 themes | see below | **Not credibly met** |

The worst baseline miss was stress-test variance; one targeted prompt change (full
1–10 survivability range with explicit anchors + an anti-clustering instruction)
moved stdev 1.02 → 1.47 **and** pushed conviction spread 17.5 → 25.0.

### Backtest: honest assessment

**A point-in-time universe filter now blocks future-IPO lookahead.** In backtest
mode the pipeline rejects any candidate that was not public/tradable on the as-of
date, using a free investability gate (`was_investable_on`): the FMP `ipoDate` plus
price-availability on/before the as-of date. The filter runs both on the ETF holdings
the screener sees *and* on the screener's output candidate list (the guarantee layer,
which catches names the LLM invents from training when ETF holdings are unavailable).
Filing-date discipline on financial data is unchanged; this adds a universe layer.

**Before the fix** (original cloud-software 2020-01-01 run): the screener picked
**CRWV (CoreWeave, IPO March 2025)** and **PLTR (IPO Sept 2020)** for a January-2020
as-of date — companies that did not trade then — and the top-5 *appeared* to return
+254.7% (1Y) vs SKYY +57.4%, an untrustworthy number.

**After the fix**, every candidate in both backtests was investable on the as-of date:

| Backtest | Top picks (all public before the date) | Top-5 avg fwd 1Y / 3Y / 5Y | Benchmark 1Y / 3Y / 5Y |
|----------|------------------------------------------|----------------------------|------------------------|
| cloud software, 2020-01-01 | DDOG, NOW, CRM, WDAY, ADBE | +77.9% / +23.5% / +150.2% | SKYY +57.4% / −4.6% / +97.3% |
| biotech, 2018-01-01 | NTRA, VCYT, CRSP, NTLA, ILMN | +51.7% / +569.5% / +169.0% | IBB −9.7% / +41.9% / — |

CRWV/PLTR/SNOW were explicitly excluded (verifiable in the run log: "Point-in-time
filter (2020-01-01): excluded …"). The apparent outperformance is now more modest and
credible.

**Residual bias that remains (do not over-trust these numbers).** The filter removes
future-IPO leakage, but two biases persist: (1) **training-data leakage** — a
2026-trained screener still preferentially knows which *already-public* names (DDOG,
NOW, NTRA, CRSP) went on to win; and (2) **survivorship** — candidates are still drawn
from *today's* ETF holdings/coverage. Fully fixing both needs a historical
point-in-time constituents dataset (none free was available). So backtest results are
**indicative, not audit-grade**, and Target #6 (≥2% annualized signal across ≥3
themes) is still not formally claimed — but the egregious lookahead is gone.

## Backtesting

`backtesting/harness.py` reruns the whole pipeline **as of a historical date**
with point-in-time data discipline, then computes realized 1/3/5-year forward
returns for each pick versus the theme's benchmark ETF.

How point-in-time is enforced: a `ToolContext(as_of=…)` is threaded into every
tool handler. Statement series are sliced to filings **dated before** the as-of
date (FMP carries filing dates); insider transactions are filtered to `<=
as_of`; forward-looking analyst estimates are disabled; current market caps are
suppressed in favor of the as-of price; and web search is turned off.

```bash
uv run stockagents analyze "cloud software" --backtest-date 2020-01-01
```

A **point-in-time universe filter** runs in backtest mode on top of the filing-date
discipline above: `was_investable_on(ticker, as_of)` (FMP `ipoDate` + price on/before
the as-of date) drops any candidate that was not public/tradable on the backtest
date, applied both to the ETF holdings the screener sees and to its output list. This
blocks future-IPO lookahead — the original 2020-01-01 cloud run picked CoreWeave (IPO
2025) and Palantir (IPO Sept 2020); reruns exclude them and surface only names that
traded then (see the Results section for the new numbers).

The system "has value" if top-5 picks beat the relevant ETF by >2% annualized across
the test window (suggested grid: January of each year 2015–2020 for AI infrastructure,
biotech, fintech). **Backtest results remain indicative, not audit-grade.** Two biases
the universe filter does *not* remove: (1) **training-data leakage** — the LLM screener
still preferentially knows which *already-public* names won; and (2) **survivorship** —
candidates are drawn from today's ETF holdings/coverage. Fully closing both needs a
historical point-in-time constituents dataset, which is not wired in.

## Limitations

Read this section. The system is designed to be honest about what it can't do.

- **Survivorship bias.** The candidate universe is built from *today's* ETF
  holdings and FMP's coverage, which skews toward companies that survived.
  Historical backtests therefore under-count failures that would have been in
  the universe at the time. A proper fix needs a delisted-securities dataset;
  this is **not** wired in for v1. Treat backtest outperformance with
  corresponding skepticism.
- **LLM-screener lookahead — future-IPO leak now blocked, training-data leak
  remains.** The screener is a language model trained past the as-of date, so in a
  backtest it could once select companies that did not yet exist (the original
  2020-01-01 cloud run picked CoreWeave, IPO 2025, and Palantir, IPO Sept 2020). A
  point-in-time **universe filter** (`backtesting.point_in_time.was_investable_on`,
  gating on FMP `ipoDate` + price-availability on/before the as-of date) now drops
  any candidate that was not public/tradable on the backtest date — applied both to
  the ETF holdings the screener sees and to its output candidate list. Future-IPO
  names are excluded (verifiable in the run log). **Residual bias remains:** the
  model still preferentially *knows* which already-public names went on to win
  (training-data leakage on extant tickers), and the filter cannot correct that. So
  backtests are more credible than before but still not audit-grade.
- **Web search has no point-in-time equivalent.** It's disabled in backtests
  (the management and stress-test agents lose their qualitative web context),
  so historical runs are weaker than live runs in a way that's hard to quantify.
- **Restatement / corporate-action leakage.** Even with filing-date filtering,
  restatements, splits, and reclassifications can leak information backward.
- **Data-source coverage.** Short interest is effectively unavailable on FMP's
  free tier (the tool says so). ETF holdings scrapers are best-effort and break
  when fund families change their export formats; there's an FMP fallback.
- **Model uncertainty.** Conviction scores are calibrated opinions from a
  language model over noisy data, not probabilities. They will drift across
  model versions. The point is the *reasoning and the bear case*, not the digit.
- **Not advice.** No execution, no sizing, no guarantees. Do your own work.

## Project layout

```
src/stock_agents/
├── config.py            # settings + model/pricing tables
├── models/              # Pydantic schemas (company, analysis, thesis)
├── data/                # FMP, EDGAR, ETF, Tiingo clients + cache + metrics
├── tools/               # Anthropic tool schemas + handlers (with as-of context)
├── agents/              # 6 specialist agents + orchestrator + base runner
├── backtesting/         # point-in-time filtering + forward-return harness
└── cli.py               # typer CLI (analyze / inspect / cost-report)
```
