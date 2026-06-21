# Walkthrough: a real run, end to end

This is an annotated walk through an **actual run** of the pipeline — not a mockup.
It pairs with [`ARCHITECTURE.md`](ARCHITECTURE.md) (the *why*) by showing the
*what*: what you type, what each stage produces, and how to read the output.

The second half is a **Loom recording script** — scene-by-scene narration you can
read while screen-recording, so the video stays tight and grounded in this run.

> Run captured: theme **"AI infrastructure"**, 5 candidates, Claude Max backend.
> Wall-clock ~30 min; usage-equivalent **$9.30**. Numbers below are verbatim from
> that run.

---

## Part 1 — The annotated run

### The command

```bash
cd stock_agents
env -u ANTHROPIC_API_KEY LLM_BACKEND=claude_code \
  uv run stockagents analyze "AI infrastructure" --max-candidates 5 \
  --budget 50 --output report.json
```

- `env -u ANTHROPIC_API_KEY LLM_BACKEND=claude_code` runs against the **Claude Max
  subscription** instead of the metered API (usage counts against the plan).
- `--max-candidates 5` keeps it cheap for a demo; a real screen uses 15-25.
- `--budget 50` lifts the default $5 guard, which a 5-candidate run trips on the
  metered API (two Opus calls per name).
- `--output report.json` writes the full structured `FinalReport`.

### Stage 1 — Macro / Sector Overlay (once, before screening)

The first thing that prints is the regime read, because everything downstream is
judged against it. From this run:

> **Cycle position:** "Peak acceleration phase of an AI capex supercycle
> (mid-2026). The four major hyperscalers … guiding $700–725B in 2026 capex, up
> ~77% YoY … The Fed held at 3.50%–3.75% at its June 17, 2026 meeting (fourth
> consecutive hold) … Higher-for-longer rates compress multiples on long-duration
> capex beneficiaries … but cash-generative infrastructure incumbents remain
> supported by relentless hyperscaler demand."

It then names the **regime winners** ("capital-light, cash-generative
picks-and-shovels incumbents with pricing power and contracted order books") and
losers ("negative-FCF software names dependent on cheap capital"). Hold onto that
winners/losers framing — it reappears as `macro_fit` on every thesis.

### Stage 2 — ETF Screener (theme → candidate universe)

The screener finds matching ETFs (SMH, SOXX, specialist AI/robotics funds),
pulls their holdings, scores by cumulative weight + appearances + market cap, and
filters out mega-caps, illiquid names, and poor thematic fits. The orchestrator
runs one Opus validation pass over the list. For this demo we capped analysis at
the **top 5** survivors.

### Stage 3 — Per-candidate analysis (4 parallel workers)

For each candidate, the core analysts (Fundamentals, Balance Sheet, Management)
run concurrently; then Stress Test (reading their reports), then Peer Comparison,
then the Synthesizer. You can see the parallelism and the variable cost in the
completion log — names finish out of order and at very different times:

```
12:45:50   ✓ AMAT  conviction=60.0
12:47:20   ✓ MRVL  conviction=62.0
12:49:50   ✓ LRCX  conviction=71.0
12:57:44   ✓ KLAC  conviction=73.5
12:57:54  Run complete: 5 analyzed, $9.30
```

KLAC took ~8 minutes longer than AMAT — that's the Stress Test and Balance Sheet
agents choosing to fetch and read filings for the higher-quality name, exactly
the cost-aware behavior the prompts are designed to produce.

### Stage 4 — The ranked report

```
                  Top picks — AI infrastructure
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┳━━━┳━━━┳━━━┳━━━┓
┃ Ticker ┃ Name                     ┃ Conviction ┃ Label ┃ F ┃ B ┃ M ┃ S ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━╇━━━╇━━━╇━━━╇━━━┩
│ KLAC   │ KLA Corporation          │       73.5 │ high  │ 7 │ 9 │ 8 │ 6 │
│ LRCX   │ Lam Research Corporation │       71.0 │ high  │ 7 │ 9 │ 7 │ 6 │
│ ANET   │ Arista Networks, Inc.    │       70.5 │ high  │ 8 │ 9 │ 7 │ 5 │
│ MRVL   │ Marvell Technology, Inc. │       62.0 │ high  │ 7 │ 6 │ 7 │ 5 │
│ AMAT   │ Applied Materials, Inc.  │       60.0 │ high  │ 5 │ 9 │ 7 │ 4 │
└────────┴──────────────────────────┴────────────┴───────┴───┴───┴───┴───┘
```

`F / B / M / S` are the four component scores (Fundamentals, Balance sheet,
Management, Stress test). Read the table against the conviction formula in
[ARCHITECTURE.md](ARCHITECTURE.md#the-conviction-score--deterministic-by-design):
Stress test carries the heaviest weight (0.30), which is why **AMAT lands last
(60.0) despite a 9 balance sheet** — its stress score of 4 drags it down. The
math is doing exactly its job: a great balance sheet does not rescue a fragile
bear case.

The closing **market commentary** (the orchestrator's only other Claude call):

> "AI infrastructure remains a crowded, consensus long, but the top picks skew
> toward picks-and-shovels names with durable earnings power rather than the most
> hyped accelerator stories … No name cleared a true standout bar (>75), so
> position sizing should respect that this is a relative-value sleeve within a
> well-owned theme rather than a differentiated edge."

### Reading one full thesis — KLAC (73.5, "high")

This is the unit of output: a structured `InvestmentThesis`. Component scores
**F7 / B9 / M8 / S6**, `peer_preference_strength` **7**, and a telling
`macro_fit`:

> "Fits the regime-winner profile as a cash-generative AI picks-and-shovels
> incumbent, **but** with China-exposure and peak-multiple traits of the losers
> profile."

That single line is the macro overlay paying off — the same company sits on both
sides of the regime split, and the thesis says so instead of hand-waving.

**Summary (excerpt):** "KLA is a best-in-class semiconductor process-control
franchise with a 55–60% share of wafer inspection … 62% gross margins … The catch
is price and cycle: at ~28x EV/Sales and ~75-80x earnings on what is empirically
peak-cycle revenue … a true Tier-1 business at a Tier-1 price."

**Bull case (3 bullets, verbatim):**
1. Structural process-control oligopoly (55–60% share) with step-count expansion
   driving 710bps of operating-margin gains since FY2021, fortified by KLA Care
   service annuities that softened the FY2024 down-cycle to just -6.5%.
2. Best-in-class financial profile in semicap — first in the peer group on gross
   margin (62.3%), operating margin (43.1%), FCF margin (32.9%), ROE (86.6%).
3. Direct beneficiary of the regime-winner profile … riding $725B of 2026
   hyperscaler capex and a leading-edge node roadmap.

**Bear case (3 bullets, verbatim) — from the Stress Test:**
1. Valuation is priced for a perpetual super-cycle — ~28x EV/Sales … historical
   KLAC, AMAT, and LRCX drawdowns from comparable multiples were **45–80%**.
2. China (28–35% of revenue) faces the explicit 50% domestic-equipment mandate
   plus state-backed Hwatsing/RSIC challengers … 10–15% of TAM at risk.
3. Leading-edge demand is concentrated in essentially one customer (TSMC) …
   **and ASML at an 8% multiple discount is a credible same-thesis alternative**
   (← that clause is the Peer Comparison agent tempering the bull case).

**What would change my mind (excerpt):** specific, falsifiable triggers, both
directions — e.g. downside: "two consecutive quarters of double-digit YoY China
decline with management acknowledging share loss to Hwatsing/RSIC"; upside: "a
multiple reset to ~18-20x sales without an earnings cut."

**Catalysts:** dated and concrete — "KLAC Q4 FY2026 earnings (late July 2026)",
"TSMC and Samsung 2027 capex guidance (Q3-Q4 2026)", "Fed Sept/Dec 2026 meetings."

That's the whole point of the design in one card: a bull case, an *independently
produced* bear case strong enough to knock the score down to a 6 on
survivability, a peer check that names a better-priced alternative, and a price
computed by Python — not vibes.

### The artifact

`report.json` is the full `FinalReport`: `theme`, `macro_context`, all five
`top_picks` and `full_results` with every component score and citation list, plus
`api_cost_usd`. It's the input to the watchlist/tracking commands and the web UI.
The exact output of this run is checked in at
[`sample_run_report.json`](sample_run_report.json) if you want to read the raw
structure.

---

## Part 2 — Loom recording script (~5-6 min)

Screen-record your terminal + editor. Read these beats; keep each scene short.
Time budget in brackets.

**Scene 0 — Hook [0:00-0:20]**
> "This is an autonomous equity-research pipeline. You give it a theme — say 'AI
> infrastructure' — and a committee of specialist Claude agents screens ETFs,
> analyzes each company, builds the bear case, and hands back ranked theses with a
> conviction score. It's a research tool, not a trading system — no execution, no
> position sizing. Let me show you a real run."

**Scene 1 — The architecture in 30 seconds [0:20-1:00]**
Open `docs/ARCHITECTURE.md`, show the topology diagram.
> "The core idea: don't use one generalist agent. Use a committee of narrow
> specialists, because the agent that finds reasons to buy should not be the agent
> that scores the downside. Macro overlay runs once to set the regime. The screener
> turns the theme into a candidate list. Then for each name, three analysts run in
> parallel — fundamentals, balance sheet, management — then an adversarial stress
> test reads their work and attacks it, a peer check asks 'why this and not the
> obvious alternative,' and a synthesizer weighs everything. The final score is
> computed in Python, not by a model, so it's exact and auditable."

**Scene 2 — Kick off the run [1:00-1:30]**
Show and run the command (or start it pre-warmed).
> "Max-subscription backend so it bills the plan, not the API. Five candidates to
> keep it quick — a real screen does 15 to 25. Watch the order it works in."

**Scene 3 — Macro overlay [1:30-2:15]**
Scroll to the macro output.
> "Before any stock, it places the theme in the current regime. Here: peak of an
> AI capex super-cycle, hyperscalers guiding $725B for 2026, but the Fed holding
> higher-for-longer. So it names the winners — cash-generative picks-and-shovels
> incumbents — and the losers — negative-FCF names that need cheap capital. Every
> thesis gets judged against this."

**Scene 4 — Watch the parallel analysis [2:15-2:50]**
Point at the completion log lines.
> "Each name fans out to four parallel workers. Notice they finish out of order
> and at very different times — KLAC took eight minutes longer than AMAT, because
> the balance-sheet and stress-test agents *chose* to pull and read filings for
> the higher-quality name. That's the cost-aware prompting: fetch a 10-K only when
> a specific number demands it."

**Scene 5 — The ranked table [2:50-3:40]**
Show the top-picks table.
> "Here's the payoff. F-B-M-S are the four component scores. Look at AMAT — a 9 on
> the balance sheet, but it lands *last* at 60, because its stress score is a 4 and
> the stress test carries the heaviest weight by design. The whole thesis of the
> system is right there: the bear case matters more than the bull case. And the
> commentary is honest — nothing cleared a 75, so this is a relative-value sleeve,
> not a differentiated edge."

**Scene 6 — One full thesis [3:40-5:00]**
Open `report.json` (or the walkthrough) to KLAC.
> "Drill into the top pick. Three-bullet bull case. Three-bullet bear case — and
> this bear case is strong enough to hold survivability to a 6: valuation priced
> for a perpetual super-cycle with 45-to-80-percent historical drawdowns, China
> TAM at risk, single-customer concentration. See this clause — 'ASML at an 8%
> discount is a credible same-thesis alternative' — that's the peer agent saying
> the obvious alternative might be the better buy. Then falsifiable triggers and
> dated catalysts. This is what an analyst would write, except the bear case wasn't
> written by the same person who wrote the bull case."

**Scene 7 — Close [5:00-5:30]**
> "Everything's a typed schema with citations, written to an audit log, and the
> conviction math is deterministic Python. There's a CLI, a FastAPI backend, and a
> Next.js UI — one-click launchers for Mac and Windows. Architecture doc's in the
> repo if you want the why behind each agent. Thanks for watching."

**Recording tips**
- Pre-run once so caches are warm and a second live run is faster, or record the
  narration over this captured run if a fresh one would run long.
- Keep the editor on `docs/ARCHITECTURE.md` and `report.json` in split panes so
  you can cut between the *why* and the *what*.
- Zoom the terminal font; the tables and tree diagram need to be legible.
