# stock_agents v2 — Build Specification

## Mission

Take v1 of stock_agents (the research pipeline) and turn it into a **persistent research workstation**: tracked watchlists, automated post-earnings re-analysis, 8-K monitoring, weekly batch runs, two new analyst agents, and a clean web UI to actually browse and act on everything the system produces.

The system remains a **research tool, not a trading system**. No broker integration, no execution, no auto-sizing, no auto-buy/sell. All decisions remain explicit human ones. This is non-negotiable and applies through every phase below.

## Non-goals (do not build, even if it seems easy)

- Broker connections (Alpaca, IBKR, Robinhood, etc.)
- Auto-execution of any trade
- Position sizing logic
- Stop-loss or take-profit automation
- Mobile app
- Multi-user accounts / SaaS deployment
- Real-time price streaming (the system is event-driven on earnings/8-Ks/schedules, not tick-driven)

## Pre-build decisions (already made, override only if you disagree)

1. **Notification channel: Pushover** for personal alerts. Free for personal use ($5 one-time per device), trivial API, no SMTP config hell. SendGrid SMTP is the fallback if you want proper email digests. Both are supported; pick at config time.
2. **Earnings transcripts: company IR sites + AlphaVantage** (free tier exists). Do NOT scrape Seeking Alpha — their ToS prohibits it and they're litigious.
3. **Point-in-time constituents: NOT in scope.** Sharadar SF1 is $50/mo and requires user approval. Documented as a remaining known limitation. Do not add without explicit approval.
4. **Scheduler: cron** on macOS/Linux. Launchd is supported as an alternative for macOS native. Do not add Airflow/Prefect/Celery — overkill for personal use.
5. **Web UI: Next.js 14 (App Router) + shadcn/ui + Tailwind**, served locally on `localhost:3000` against a FastAPI backend on `localhost:8001`. No auth (local-only). Deploy later if you ever want it remote.
6. **Database: SQLite** for watchlist/runs/alerts metadata. JSON files for thesis snapshots and reports. No Postgres — single user, single machine, file-based wins.

## Tech stack additions to v1

Backend:
- `apscheduler` — for in-process scheduling if user prefers it over cron
- `feedparser` — for EDGAR 8-K RSS
- `sqlmodel` or `sqlite3` — watchlist/runs/alerts persistence (sqlmodel preferred for typed access)
- `httpx-sse` — for streaming AlphaVantage if needed
- `python-pushover` or raw httpx — Pushover client
- `aiosmtplib` — async SMTP for SendGrid fallback
- `fastapi`, `uvicorn`, `python-multipart` — web backend

Frontend (new package, separate folder):
- Next.js 14, TypeScript, Tailwind, shadcn/ui
- `swr` or `tanstack-query` — data fetching
- `recharts` — for conviction trend charts
- `lucide-react` — icons

## Repository structure additions

```
stock_agents/                          # existing v1
  src/stock_agents/
    track/                             # NEW: watchlist + thesis storage + diffing
      __init__.py
      models.py                        # WatchlistEntry, ThesisSnapshot, Diff
      store.py                         # SQLite-backed watchlist
      snapshots.py                     # JSON thesis snapshot read/write
      diff.py                          # Material-change detection
    automation/                        # NEW: scheduled jobs
      __init__.py
      jobs/
        post_earnings.py
        eight_k_monitor.py
        weekly_cache_warm.py
        sunday_batch.py
      runner.py                        # apscheduler entry point
      cron.sh                          # generated crontab snippet
    notify/                            # NEW: alerting
      __init__.py
      base.py                          # NotificationChannel ABC
      pushover.py
      sendgrid.py
      formatter.py                     # Diff/8-K → human-readable summary
    agents/
      peer_comparison.py               # NEW agent
      macro_overlay.py                 # NEW agent
    data/
      transcripts.py                   # NEW: earnings transcript fetcher
    api/                               # NEW: FastAPI backend for the UI
      __init__.py
      main.py
      routes/
        watchlist.py
        runs.py
        thesis.py
        alerts.py
        themes.py
      schemas.py
  tests/
    test_track.py
    test_diff.py
    test_peer_comparison.py
    test_macro_overlay.py
    test_transcripts.py
    test_automation.py
    test_api.py

stock_agents_ui/                       # NEW: separate Next.js app
  package.json
  app/
    layout.tsx
    page.tsx                           # Dashboard
    watchlist/
      page.tsx
      [ticker]/page.tsx
    runs/
      page.tsx
      [run_id]/page.tsx
    themes/
      page.tsx
    settings/
      page.tsx
  components/
    ui/                                # shadcn primitives
    conviction-chart.tsx
    diff-view.tsx
    thesis-card.tsx
    falsifier-list.tsx
  lib/
    api.ts                             # backend client
  styles/
    globals.css
```

## Database schema (SQLite via SQLModel)

```sql
-- watchlist
CREATE TABLE watchlist (
  ticker TEXT PRIMARY KEY,
  added_at TEXT NOT NULL,             -- ISO timestamp
  entry_thesis_path TEXT NOT NULL,    -- relative path to snapshot JSON
  entry_conviction REAL NOT NULL,
  entry_price REAL,                   -- optional, user-entered
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'active'  -- active|paused|exited
);

-- run history
CREATE TABLE runs (
  id TEXT PRIMARY KEY,                -- ulid
  kind TEXT NOT NULL,                 -- analyze|inspect|backtest|post_earnings
  theme TEXT,
  ticker TEXT,
  as_of TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,               -- running|success|failed|aborted
  cost_estimate_usd REAL,
  report_path TEXT,                   -- relative path to FinalReport / inspect output
  error TEXT
);

-- thesis snapshots (one per inspect/analyze of a tracked ticker)
CREATE TABLE thesis_snapshots (
  id TEXT PRIMARY KEY,
  ticker TEXT NOT NULL,
  run_id TEXT NOT NULL,
  taken_at TEXT NOT NULL,
  conviction REAL NOT NULL,
  fundamentals_score INTEGER,
  balance_sheet_score INTEGER,
  management_score INTEGER,
  stress_test_score INTEGER,
  snapshot_path TEXT NOT NULL,        -- full thesis JSON
  FOREIGN KEY (ticker) REFERENCES watchlist(ticker),
  FOREIGN KEY (run_id) REFERENCES runs(id)
);

-- alerts emitted by the system
CREATE TABLE alerts (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,                 -- earnings_diff|eight_k|run_failure|cost_warning
  ticker TEXT,
  severity TEXT NOT NULL,             -- info|notice|important
  payload_path TEXT,                  -- JSON detail
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  delivered_at TEXT,                  -- null until pushover/email succeeds
  acknowledged_at TEXT                -- user marked read in UI
);

-- 8-K seen tracking (dedup)
CREATE TABLE eight_k_seen (
  accession_number TEXT PRIMARY KEY,
  ticker TEXT NOT NULL,
  filed_at TEXT NOT NULL,
  item_numbers TEXT,                  -- "1.01,2.02"
  url TEXT NOT NULL
);
```

## Phase 1: Track + Watchlist (FOUNDATION — build first)

Everything else depends on this. Do not start Phase 2+ before Phase 1 is shipped and tested.

### CLI additions

```bash
# Add a ticker to the watchlist using the most recent inspect/analyze report for it.
# If no report exists, run inspect first.
stockagents track NVDA --thesis ./reports/ai_infra_2026-05-26.json --entry-price 1450 --note "Position from theme run"

# Show the watchlist with current vs entry conviction
stockagents watchlist

# Run a fresh inspect against a tracked ticker, store snapshot, diff vs entry
stockagents track-status NVDA

# Show full thesis history for a ticker
stockagents track-history NVDA

# Mark as exited (sold position)
stockagents untrack NVDA --reason "Falsifier fired: data center growth decelerating per Q3"

# Pause monitoring without removing
stockagents track-pause NVDA
stockagents track-resume NVDA
```

### Track command behavior

When `track-status` runs:
1. Fetch the entry thesis snapshot.
2. Run a fresh `inspect TICKER` (full pipeline on one ticker, ~$0.30-0.60).
3. Store the new snapshot.
4. Compute a Diff (see Phase 1 diff logic below).
5. If material, emit an alert (Phase 4 wiring). Otherwise just print the diff.
6. Return the diff for human review.

### Diff logic (Phase 1 minimum, refined later)

A "material change" is any of:
- Composite conviction shifted by ≥15 points in either direction
- Any component score (fundamentals/balance/management/stress) shifted by ≥3 (on the 1-10 scale)
- A new red flag appeared in any agent's report
- A specific falsifier from the entry thesis is referenced by the new bear case as having moved (substring match on the "what would change my mind" text — imperfect but useful)
- Status changes: the ticker is now flagged with `cannot_evaluate` (data missing, delisted, etc.)

Anything else is a quiet diff: stored for history but not alerted on.

### Phase 1 acceptance

- All `track*` CLI commands work and round-trip through SQLite.
- `track-status NVDA` produces a Diff object with all of the above fields populated.
- Diff renders cleanly in the terminal with `rich` (no JSON dumps to the user).
- pytest passes including new `test_track.py` and `test_diff.py`.
- Documented in README under a new "Watchlist & tracking" section.

## Phase 2: Two new agents (Peer Comparison + Macro Overlay)

These extend the agent topology. Per `CLAUDE.md` this is a structural change — the user has approved it by including these in the spec.

### Peer Comparison agent

**Role.** Force the question "why this one and not the closest alternative" before the synthesizer locks in conviction.

**Position in pipeline.** Runs after Stress Test, before Synthesizer, per analyzed candidate. Synthesizer reads its output.

**Model.** `claude-sonnet-4-6` (structured, not adversarial).

**Tools.** `get_company_profile`, `get_income_statement`, `get_balance_sheet`, `get_key_metrics`, `get_peer_comparison` (existing FMP endpoint).

**Process:**
1. Identify 3 closest comparable companies — same sector/sub-industry, similar market cap band (0.3x to 3x of subject), publicly traded, with available financials.
2. Pull last 4 quarters of key metrics for each: revenue growth, gross margin, operating margin, FCF margin, ROE, net debt/EBITDA, EV/Revenue, EV/EBITDA, P/E.
3. Build a comparison matrix.
4. Identify where the subject is materially better, materially worse, and roughly equal across comps.
5. For each "materially worse" dimension, state explicitly: "Why hold subject instead of [comp] given this?"
6. Answer your own question or flag that there isn't a good answer.
7. Score 1-10 on "preference strength" — how confidently the subject is the right pick versus the alternatives.

**Output schema (`PeerComparisonReport`):**

```python
class PeerMetric(BaseModel):
    name: str                        # "Gross margin"
    subject_value: float
    peer_values: dict[str, float]    # {"AMD": 47.2, "INTC": 39.1, "AVGO": 75.4}
    subject_rank: int                # 1-4 across the group

class PeerComparisonReport(BaseModel):
    ticker: str
    peers: list[str]                 # ["AMD", "INTC", "AVGO"]
    metrics: list[PeerMetric]
    subject_advantages: list[str]    # Dimensions where subject clearly leads
    subject_disadvantages: list[str] # Dimensions where subject clearly trails
    rebuttals: list[str]             # For each disadvantage, why subject is still preferred (or admission that it isn't)
    preference_strength_1_to_10: int
    reasoning: str
```

### Macro/Sector Overlay agent

**Role.** Place the theme in cycle/regime context so the synthesizer doesn't read every company in a vacuum.

**Position in pipeline.** Runs once per `analyze` invocation, before screening. Output passed to the Synthesizer for every candidate in that run.

**Model.** `claude-sonnet-4-6`.

**Tools.** `web_search` (for current macro/regulatory context), `get_company_profile` (to confirm sector classifications).

**Process:**
1. Identify the dominant sector(s) the theme touches.
2. Identify the relevant cycle: rates (financials), capex (semis, energy), patent cliff (pharma), regulatory regime (defense, healthcare).
3. Find current placement in that cycle from public data (Fed dot plot, capex announcements, regulatory calendar).
4. Identify 2-3 tailwinds and 2-3 headwinds specific to the regime right now.
5. Identify which company *types* in this theme benefit / suffer from the current regime (e.g., "in a high-rate environment, software companies with negative FCF and dilution are penalized more than capital-light cash-generative comps").

**Output schema (`MacroContext`):**

```python
class MacroContext(BaseModel):
    theme: str
    sectors_covered: list[str]
    cycle_position: str              # Free text, ~3 sentences
    tailwinds: list[str]             # 2-3 bullets
    headwinds: list[str]             # 2-3 bullets
    regime_winners_profile: str      # "Cash-generative incumbents with pricing power"
    regime_losers_profile: str       # "Negative-FCF growth names dependent on cheap capital"
    sources: list[str]
```

The Synthesizer's prompt is updated to read this and adjust its conviction reasoning ("In current regime, this candidate fits/doesn't fit the winners profile").

### Phase 2 acceptance

- Both agents implemented, tested, integrated into orchestrator.
- `analyze` runs produce FinalReports that reference both reports in each thesis.
- Cost per 5-candidate run goes up by approximately 30-40% (one extra agent per candidate plus one macro call total). Document the new cost band.
- CLAUDE.md and README updated to reflect new topology.

## Phase 3: Data layer additions

### Earnings transcript ingestion

**Source priority (legal-first):**
1. **Company IR sites.** Many companies post transcripts as PDFs on `investor.{company}.com/events`. Implement a per-ticker IR URL registry (manual at first, expand over time). Fetch + extract text.
2. **AlphaVantage earnings call transcripts API.** Free tier exists. Endpoint: `https://www.alphavantage.co/query?function=EARNINGS_CALL_TRANSCRIPT&symbol=...&quarter=...`. Use this as the primary source.
3. **SEC 8-K (Item 2.02) attachments.** Earnings press releases are filed as 8-K exhibits. Not full transcripts but often include prepared remarks.

**Do NOT scrape:**
- Seeking Alpha (ToS prohibits)
- Motley Fool transcripts pages (ToS prohibits)

**Tool:** `get_earnings_transcript(ticker, quarter)` returns `{"source": "ir|alphavantage|8k", "text": "...", "quarter": "Q3-2025"}` or raises `TranscriptUnavailable`.

**Wire into Management agent:** Add transcript text (truncated to ~30k tokens) to the Management agent's user message when available. Update Management agent's system prompt to specifically read Q&A vagueness, executive evasion, and consistency with prior quarters.

**Acceptance:** Transcript is fetched for AAPL, NVDA, MSFT successfully via at least one source. Management agent's score moves measurably when transcript is included vs excluded on the same ticker (the test: a vague Q&A should reduce the score).

### Point-in-time constituents — NOT BUILT

Document in `docs/v2_decisions.md`:
- Three options identified: Sharadar SF1 ($50/mo, paid), WRDS (academic only), manual CSVs per year (high maintenance).
- Decision: defer. Backtests retain the "indicative not audit-grade" caveat from v1.
- This is the path to true backtest validation; revisit when forward use has demonstrated the system is worth that investment.

Do not propose a workaround that pretends to solve this without the data.

## Phase 4: Automation infrastructure

### Job runner

Two supported modes, choose at install time:
1. **cron** (default). The system generates a `cron.sh` snippet with the recommended schedule. User installs with `crontab cron.sh` or appends to existing crontab.
2. **In-process APScheduler.** Run `stockagents daemon` to start a background scheduler that runs jobs on the schedule. Good for users without cron access.

Each job is idempotent and writes a row to `runs` table before starting. Failed jobs log to `alerts` with severity `important`.

### Notification layer

`notify/base.py` defines `NotificationChannel`. Implementations:
- `pushover.py` — short messages, ~250 char limit per notification
- `sendgrid.py` — full HTML email digests

Config in `.env`:
```
PUSHOVER_USER_KEY=
PUSHOVER_APP_TOKEN=
SENDGRID_API_KEY=
ALERT_EMAIL=you@example.com
ALERT_CHANNEL=pushover|email|both
```

`notify/formatter.py` takes a Diff or 8-K and produces both short (Pushover) and long (email) representations.

### Phase 4 acceptance

- `stockagents daemon` runs APScheduler with stub jobs.
- `stockagents generate-cron` outputs a crontab snippet.
- Pushover and SendGrid clients send test messages with `stockagents notify-test`.
- All scheduled jobs write to the `runs` table; failures write `alerts`.

## Phase 5: Specific automated workflows

Each is a job under `automation/jobs/`. They use Phase 1-4 primitives.

### `post_earnings.py`

**Schedule.** Daily at 06:00 local time.

**Behavior.**
1. Query an earnings calendar for which watchlist tickers reported in the last 24h.
   - Source: FMP's `earning_calendar` endpoint (already in FMP client). No new dependency.
2. For each, run `track-status TICKER`.
3. If the diff is material, emit an alert.
4. If `inspect` fails (transcript not yet available, data error), log a quiet alert and schedule a retry in 24h.

**Cost guard.** Daily budget ceiling defaults to $5; configurable. Aborts if projected spend exceeds it.

### `eight_k_monitor.py`

**Schedule.** Every 30 minutes during US market hours, hourly outside.

**Behavior.**
1. Fetch EDGAR's recent 8-K RSS feed: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom`.
2. Parse with `feedparser`. Filter to entries where the filer's CIK matches a watchlist ticker.
3. For each new filing (not in `eight_k_seen`), extract item numbers from the 8-K text. Material item codes: 1.01, 1.02, 1.03, 2.01, 2.02, 2.04, 2.05, 4.01, 4.02, 5.02, 5.03, 7.01, 8.01.
4. For material items, send a Pushover alert: `[TICKER] 8-K filed: Item 2.02 (Results of Operations) — {url}`. No LLM call required; the item-code-to-description mapping is hardcoded.
5. Store the accession number in `eight_k_seen`.

**Optional LLM enrichment.** A `--summarize` flag that runs a single Haiku call per 8-K to produce a one-sentence plain-English summary. Costs ~$0.005 per filing. Off by default.

### `weekly_cache_warm.py`

**Schedule.** Sundays at 02:00 local time.

**Behavior.**
1. For each active watchlist ticker, refresh: profile, income statement (5y), balance sheet (5y), cash flow (5y), insider transactions (24mo), most recent 10-K text.
2. Pre-fetch ETF holdings for all themes in `THEME_REGISTRY`.
3. No agent runs — this is pure cache warming.
4. Total expected time: 5-15 minutes depending on watchlist size. No LLM cost.

### `sunday_batch.py`

**Schedule.** Sundays at 04:00 local time.

**Behavior.**
1. Read `config.batch_themes` list from settings (user-configurable; defaults to 3-4 themes).
2. For each theme, run `analyze "theme" --max-candidates 10`. Store FinalReport to `reports/batch/{YYYY-MM-DD}/{theme}.json`.
3. Compute the diff vs last week's batch run for the same theme: top-5 composition changes, conviction shifts >15 points, new entries, dropouts.
4. Send a single weekly digest email (SendGrid) summarizing all four themes' top picks plus material changes from last week.

**Cost.** Realistic estimate $10-20 per Sunday with 4 themes at 10 candidates each, assuming non-Max API billing.

### Phase 5 acceptance

- Each job runs end-to-end successfully on a test watchlist of 3 tickers.
- Each job writes a `runs` row and any resulting `alerts`.
- A test cron schedule fires all four jobs once and they all complete.
- Documented in README under "Automation" with the schedule and cost expectations.

## Phase 6: Web UI

This is its own subproject under `stock_agents_ui/`. It does not modify Python; it consumes the FastAPI backend.

### Backend (FastAPI, under `src/stock_agents/api/`)

Endpoints:

```
GET  /api/watchlist                         → list of WatchlistEntry with current status
POST /api/watchlist                         → add a ticker (body: {ticker, thesis_path, entry_price})
DELETE /api/watchlist/{ticker}              → untrack
GET  /api/watchlist/{ticker}/history        → list of thesis snapshots
POST /api/watchlist/{ticker}/refresh        → trigger track-status (returns run_id)

GET  /api/runs                              → recent runs (paginated)
GET  /api/runs/{run_id}                     → run detail
GET  /api/runs/{run_id}/report              → the FinalReport / inspect output

GET  /api/themes                            → registered themes
POST /api/themes/{theme}/analyze            → kick off analyze (returns run_id; runs background task)

GET  /api/alerts?status=unread              → recent alerts
POST /api/alerts/{id}/ack                   → mark read

GET  /api/settings                          → masked view of env config
POST /api/settings                          → update non-secret settings
```

All endpoints return Pydantic models serialized as JSON. Long-running operations (analyze, inspect) return a run_id immediately and process in the background; the UI polls for status.

CORS: allow `localhost:3000` only.

### Frontend (Next.js 14, under `stock_agents_ui/`)

**Pages:**

1. **Dashboard (`/`)** — Three columns:
   - Watchlist summary (ticker, entry conviction, current conviction, delta, last refresh)
   - Recent alerts (clickable, marks read on open)
   - Recent runs (timestamp, kind, status, cost)
   - One CTA button: "Run a theme analysis" → modal with theme picker
   
2. **Watchlist (`/watchlist`)** — Table of all tracked tickers. Columns: ticker, name, entry date, entry conviction, current conviction, Δ, last refresh, status (active/paused/exited). Sortable. Row click → ticker detail.

3. **Ticker detail (`/watchlist/[ticker]`)** — Layout:
   - Header: ticker, name, current conviction with color-coded badge (low/medium/high/very high)
   - Conviction chart (Recharts) showing the conviction trend over all snapshots
   - Component score breakdown (4 small horizontal bars: fundamentals/balance/management/stress)
   - Bull case bullets (latest snapshot)
   - Bear case bullets (latest snapshot)
   - Falsifier list with status indicators (green = not triggered, yellow = approaching, red = fired)
   - Recent diffs vs entry thesis (timeline view)
   - Actions: Refresh now, Pause, Untrack

4. **Runs (`/runs`)** — Paginated table of all runs. Row click → run detail.

5. **Run detail (`/runs/[run_id]`)** — Full FinalReport rendered:
   - Theme + timestamp + cost
   - Top picks table (sortable by conviction)
   - Per-thesis cards (bull/bear, falsifiers, scores)
   - Link to original JSON download

6. **Themes (`/themes`)** — List of registered themes. Each shows: last analyzed date, top-5 from most recent run, button to "Run now."

7. **Settings (`/settings`)** — Form to edit non-secret config (batch themes list, alert channel preference, cost ceilings). Shows masked view of API keys (configured/not configured) without revealing them.

**Aesthetic direction:**
- Tailwind base, shadcn primitives.
- Dark mode default. Light mode toggle.
- Generous whitespace. No dashboards-from-2014 dense grids.
- Color discipline: one accent color (suggest deep blue or slate-emerald). Conviction badges use a fixed scale (gray/blue/green/dark-green) rather than rainbow.
- Monospace for tickers and numbers.
- No emoji in the UI chrome.
- Loading states use shimmer skeletons, not spinners.
- Tables use small, dense rows but with comfortable vertical rhythm — closer to Linear than to Salesforce.

### Phase 6 acceptance

- Backend serves all listed endpoints with valid Pydantic schemas.
- Frontend renders all six pages.
- One end-to-end manual test: add NVDA to watchlist via UI, refresh status, view conviction chart, mark alert as read, kick off a theme analysis from Dashboard, see it appear in Runs with status running → success.
- Lighthouse score on Dashboard ≥90 for performance and accessibility on a local build.

## Cost expectations

Per-week recurring (assumes Max subscription OFF; on Max most of this is free):

- Sunday batch (4 themes × 10 candidates): $10-20
- Post-earnings (assumes 5-10 watchlist tickers reporting/quarter): $1-3
- 8-K monitor (no LLM by default): $0
- Track-status manual calls (~5/week typical use): $2-5
- **Total: $13-28/week** on metered API

If on Max subscription, treat these as usage-equivalent estimates rather than billing.

Add hard ceilings in config:
```
WEEKLY_BUDGET_USD=40
DAILY_POST_EARNINGS_BUDGET_USD=5
SUNDAY_BATCH_BUDGET_USD=25
```

Jobs that would exceed their ceiling skip with an alert rather than running over.

## Acceptance criteria for v2 as a whole

The build is "done" when:

1. All six phases ship with passing tests.
2. A new user can: install dependencies, configure `.env`, run `stockagents daemon` and `cd stock_agents_ui && npm run dev`, and have a working end-to-end research workstation.
3. README has new sections: "Watchlist & tracking", "Automation", "Web UI", "v2 architecture".
4. Cost ceilings work — a deliberately too-expensive theme run hits the ceiling and aborts cleanly.
5. The non-goals list (no broker, no auto-execution) is still respected. If at any point in the build an agent or job is proposing to "make a buy/sell decision" or "size a position," that's a hard stop.

## When to ask the user

Ask before:
- Subscribing to any paid data source (Sharadar, AlphaVantage premium, SendGrid paid tier, etc.)
- Adding a new agent beyond Peer Comparison and Macro Overlay
- Changing the cost ceilings upward
- Changing the non-goals list (e.g., "actually wouldn't broker integration be useful for tracking entry prices automatically" — NO)
- Picking a non-default scheduler, notification channel, or web framework
- Storing any credentials anywhere outside `.env`

Do not ask before:
- Improving prompts within an existing agent
- Adding tests
- Adding minor utility commands
- Refining the UI styling within the established design language
- Fixing bugs

## Phasing summary (the order to build in)

1. **Phase 1 — Track + Watchlist** (foundation, 1-2 days)
2. **Phase 4 — Automation infrastructure** (the runner and notify layer, 1 day)
3. **Phase 5 — `post_earnings` and `eight_k_monitor` jobs** (use 1 + 4; 1 day)
4. **Phase 3 — Earnings transcripts** (independent; 1 day)
5. **Phase 2 — Peer Comparison and Macro Overlay agents** (1-2 days)
6. **Phase 5 — `weekly_cache_warm` and `sunday_batch`** (1 day)
7. **Phase 6 — API backend** (1 day)
8. **Phase 6 — Web UI** (2-3 days)

Total: ~10 days of focused work for one developer, more realistic at 2-3 weeks part-time.

Do not work on phases out of order. Each phase delivers something usable on its own.

## Final reminder

The system gets bigger here, not different. It's still a research aid. The decisions remain yours. Every alert is information, not instruction. Every refresh is a re-evaluation, not a signal. No part of this stack should ever know what your position size is, what your broker password is, or what tax bracket you're in. That separation is what makes it usable — and what makes it not dangerous.

Build it.
