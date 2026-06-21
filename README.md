# stock_agents

An autonomous equity-research pipeline that hunts for asymmetric long
opportunities — companies that look like Apple in 2010 or Nvidia in 2021 before
the consensus catches up. Specialist Claude agents screen thematic ETFs, analyze
fundamentals and balance sheets, vet management, stress-test the thesis, and
produce ranked investment write-ups with explicit bull and bear cases.

> **This is a research tool, not a trading system.** Output is a written thesis
> with conviction scores. There is no execution, position sizing, real-time
> signals, or broker integration.

The repo has two parts:

| Path | What it is |
|------|------------|
| [`stock_agents/`](stock_agents/) | Python package: the agents, data layer, CLI, and FastAPI backend. See its [README](stock_agents/README.md) for full docs. |
| [`stock_agents_ui/`](stock_agents_ui/) | Next.js 14 web UI (watchlist, runs, alerts, theses). |

## One-click start

The launchers start the API backend (`:8001`) and the web UI (`:3000`) together
and open your browser.

- **macOS** — double-click **`start.command`** in Finder (or run `./start.command`).
- **Windows** — double-click **`start.bat`** in Explorer.

Both default to the **Claude Max subscription** backend (`USE_MAX=1`), which runs
the `claude` CLI against your subscription instead of billing the metered API.
To use the metered Anthropic API instead, set `USE_MAX=0` at the top of the
launcher and put a funded `ANTHROPIC_API_KEY` in `stock_agents/.env`.

## Prerequisites

Install these once, then the launchers handle the rest:

1. **[uv](https://docs.astral.sh/uv/)** — Python package/dependency manager.
2. **[Node.js](https://nodejs.org)** (v18+) — for the web UI.
3. **Either** a logged-in **[Claude CLI](https://docs.claude.com/en/docs/claude-code)**
   (`claude`, for the Max-subscription backend) **or** a funded
   `ANTHROPIC_API_KEY` (for the metered API backend).
4. **API keys** — copy `stock_agents/.env.example` to `stock_agents/.env` and
   fill in `FMP_API_KEY` (financials) and `EDGAR_USER_AGENT` (SEC requires it).
   The rest are optional.

```bash
cp stock_agents/.env.example stock_agents/.env   # then edit it
```

## Manual start (without the launchers)

Backend:

```bash
cd stock_agents
uv sync
# Max subscription:
env -u ANTHROPIC_API_KEY LLM_BACKEND=claude_code uv run stockagents serve-api --port 8001
# or metered API (ANTHROPIC_API_KEY set in .env):
uv run stockagents serve-api --port 8001
```

Frontend (in a second terminal):

```bash
cd stock_agents_ui
npm install            # first run only
npm run dev            # serves http://localhost:3000
```

The UI reads the backend URL from `NEXT_PUBLIC_API_BASE`
(default `http://localhost:8001`; see `stock_agents_ui/.env.local.example`).

## Command line only (no UI)

```bash
cd stock_agents
uv run stockagents inspect AAPL                                  # sanity check
uv run stockagents analyze "AI infrastructure" --max-candidates 5 --output report.json
uv run stockagents cost-report                                   # cumulative spend
```

## Cost note

A 5-candidate analysis runs roughly $9–10 on the metered API (two Opus calls per
candidate). The budget guard aborts a run above `RUN_BUDGET_USD` (default $5), so
on the metered backend either raise the ceiling (`--budget 10`) or use the Max
subscription backend, where usage counts against your plan rather than per-call
dollars.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — **how the pipeline works and the *why* behind each agent.** Start here.
- [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md) — annotated walkthrough of a real run (+ a Loom recording script).
- [`stock_agents/README.md`](stock_agents/README.md) — usage reference, calibration, and results.
- [`CLAUDE.md`](CLAUDE.md) — engineering guide and conventions.
- [`V2_BUILD_SPEC.md`](V2_BUILD_SPEC.md) / [`V2_ADDENDUM_FORENSIC.md`](V2_ADDENDUM_FORENSIC.md) — v2 design.
