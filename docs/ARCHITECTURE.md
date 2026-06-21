# Architecture

This document explains how the pipeline is wired and — more importantly — **why
each agent exists, what problem it solves, and why it is built the way it is.**
For setup and usage, see the [root README](../README.md) and
[`stock_agents/README.md`](../stock_agents/README.md).

---

## The core idea

Most equity "research" is bullish boilerplate: a narrative, a price target, and a
list of reasons to buy. The hard part — the part that actually protects capital —
is the adversarial read: *who is on the other side of this trade, and what do
they see that the bulls miss?*

So the system is built as a **committee of narrow specialists**, not one
generalist agent. Each specialist has a single job, a fixed tool set, and a
strict output schema. A bullish fundamentals read and a hostile bear case are
produced by *different* agents with *different* incentives, then a portfolio
manager weighs them. This mirrors how a real investment committee works, and it
has three concrete benefits:

1. **No single point of bias.** The agent that finds reasons to buy is not the
   agent that scores survivability. One can't quietly rationalize away the other.
2. **Auditable reasoning.** Every step is a typed report with citations, written
   to a JSONL audit log. You can see exactly why a name scored what it did.
3. **Cost control by scope.** A narrow agent needs less context and fewer tools,
   so each call is cheap and cacheable.

A guiding principle runs through the whole design: **deterministic math in
Python, judgment in Claude.** CAGRs, margins, dilution rates, and the final
conviction weighting are computed in `data/metrics.py` and `synthesizer.py` — not
by a model — so the numbers never drift between runs. Claude is used only for
what it is good at: pattern recognition, narrative interpretation, and scoring.

---

## Topology

```
theme ──▶ Macro / Sector Overlay (once per run) ───────────────┐ (context →
   │                                                            │  synthesizer)
   ▼                                                            │
ETF Screener ──▶ candidate list (15-25 names)                   │
                               │                                │
                  ┌────────────┴── for each candidate (4 parallel workers) ──┐
                  ▼                                                           │
        ┌─ Fundamentals ─┐                                                    │
        ├─ Balance Sheet ┤  (core analysts run concurrently)                 │
        └─ Management ───┘                                                    │
                  ▼                                                           │
            [Forensic]  (optional, --forensic; reads filings)                │
                  ▼                                                           │
            Stress Test (adversarial; reads the prior reports)               │
                  ▼                                                           │
            Peer Comparison (why this and not the closest peer?)             │
                  ▼                                                           │
            Synthesizer (weighs core reports + peer + macro + forensic)      │
                  └───────────────────────────────────────────────────────────┘
                               ▼
                     ranked FinalReport + market commentary
```

The **orchestrator is mostly plain Python**: it runs the parallel thread pool,
enforces a thread-safe budget guard, computes the conviction composite, and ranks
the results. It calls Claude for only two narrow decisions — sanity-checking the
screened candidate list and writing the closing market commentary. Everything
else labeled "agent" above is a Claude call with a schema.

---

## Model assignment — and why

| Agent           | Model               | Why this model |
|-----------------|---------------------|----------------|
| Macro Overlay   | `claude-sonnet-4-6` | Structured synthesis of public cycle data — Sonnet is plenty. |
| ETF Screener    | `claude-sonnet-4-6` | Mechanical: pull holdings, score, filter. |
| Fundamentals    | `claude-sonnet-4-6` | Structured financial analysis over pre-computed metrics. |
| Balance Sheet   | `claude-sonnet-4-6` | Structured red-flag checklist. |
| Management      | `claude-sonnet-4-6` | Structured read of filings + transcript. |
| Forensic        | `claude-opus-4-7`   | Document forensics with a zero-hallucination bar — needs care. |
| **Stress Test** | `claude-opus-4-7`   | **Adversarial creativity** — the hardest reasoning in the system. |
| Peer Comparison | `claude-sonnet-4-6` | Structured relative-value matrix. |
| **Synthesizer** | `claude-opus-4-7`   | **Weighing conflicting signals** — judgment under tension. |
| Orchestrator    | `claude-opus-4-7`   | List validation + commentary only. |

The rule: **reasoning-heavy or adversarial work gets Opus; structured analysis
that Sonnet does well gets Sonnet.** Two Opus calls per candidate (Stress Test +
Synthesizer) is the dominant cost driver, and that is deliberate — those are the
two steps where being wrong is most expensive.

---

## The agents, and the "why" behind each

### Macro / Sector Overlay — *run once, before anything else*
**Problem it solves:** a company that is excellent in the abstract can still be
the wrong vehicle in the current regime. A negative-FCF software name dependent
on cheap capital is a different bet at 0% rates than at 5%.

**What it does:** places the theme in cycle/regime context — rates, capex cycle,
patent cliff, regulatory regime — and names which *types* of companies win and
lose under that regime right now. It uses web search to ground itself in the
present, not the training cutoff.

**Why it's separate and runs once:** the regime is a property of the *theme*, not
of any one stock, so computing it 5 times would be waste. Its output feeds the
synthesizer as context. Crucially, it informs *reasoning* — it surfaces as
`macro_fit` on each thesis — but it does **not** enter the conviction number.
Macro is a tilt, not a score, so a confident macro call can't override a weak
balance sheet.

### ETF Screener — *theme → candidate universe*
**Problem it solves:** "AI infrastructure" is not a list of tickers. You need a
defensible, reproducible way to turn a theme into 15-25 names worth deep work.

**What it does:** finds 5-10 matching ETFs (mainstream *and* specialist),
retrieves their top holdings, and scores each stock by cumulative ETF weight,
number of appearances, and market cap. It filters aggressively: out go mega-caps
over $500B (unless the theme demands them), sub-$500M illiquid names, and
companies whose business doesn't actually match the theme.

**Why ETFs as the universe:** thematic ETF construction is itself a curated,
liquidity-screened view of a theme — it's a strong prior. Using *multiple* ETFs
and weighting by overlap surfaces the names that show up everywhere (high
conviction) and lets non-obvious specialists bubble up. The orchestrator then
runs one Opus validation pass over the list to catch obvious misses or
thematic mismatches before spending money on full analysis.

### Fundamentals — *is the business actually good?*
**Problem it solves:** separating real, durable growth from accounting flattery.

**What it does:** 5 years of income/cash-flow data → revenue CAGR, margin trends,
FCF conversion, Rule of 40, segment-level growth, and concentration risk (top
customer, geography, single product). It scores 1-10 where **10 = Nvidia-2021
quality** (>40% growth, expanding margins, a segment with a massive runway).

**Why it's built this way:** the prompt demands *numbers, not adjectives*
("revenue grew 47% YoY," not "strong growth") and explicitly hunts for accounting
red flags — pulled-forward revenue, receivables outrunning revenue, capitalized
software dressed up as R&D. The deterministic CAGRs and Rule-of-40 are computed
in Python and handed to the agent, so it interprets rather than calculates.

### Balance Sheet — *what could quietly kill it?*
**Problem it solves:** income statements lie by omission; the balance sheet is
where leverage, dilution, and bad capital allocation hide.

**What it does:** a credit-analyst checklist — net debt/EBITDA, interest
coverage, share-count CAGR (flag >5%/yr), SBC as % of revenue (flag >10%),
FCF-vs-net-income divergence (flag >20%), goodwill as % of assets (flag >30%),
and debt-maturity walls. It distinguishes **red flags** (disqualifying) from
**yellow flags** (context).

**Why the cost discipline matters:** fetching a full 10-K is expensive, so the
prompt instructs it to fetch a filing *only* when a specific number demands it
(a maturity wall when leverage is high, an acquisition concern when goodwill is
large) and to request the narrowest section. If leverage is low and goodwill is
immaterial, it fetches nothing. This is a direct response to the system's biggest
cost trap — re-fetching the same filing across agents.

### Management — *can you trust the people running it?*
**Problem it solves:** capital allocation skill is not charisma, and governance
risk rarely shows up in the financials until it's too late.

**What it does:** nets insider open-market activity, pulls the most recent DEF 14A
exec-comp section (CEO pay, ownership, board composition, related-party deals),
confirms founder status/tenure, and — when an earnings transcript is available —
scores Q&A *quality*: vagueness, evasion, and consistency versus prior quarters.

**Why the strict guardrails:** web search on "governance concerns" is noisy and
Claude tends to over-flag. The prompt forbids manufacturing concerns from thin
web noise — a concern is reported only if a filing or credible source
substantiates it — and limits it to at most one web search and one filing. This
agent owns *only* the proxy; it is explicitly told not to fetch 10-K/10-Q/8-K
filings that other agents own, so the committee doesn't pay for the same document
twice.

### Forensic *(optional — `--forensic`)* — *what's in the filings that nobody's reading?*
**Problem it solves:** the highest-signal red flags live in footnotes, risk-factor
deltas, and 8-K items that mainstream coverage skips.

**What it does:** works a 7-point document checklist — risk-factor year-over-year
deltas, footnote review (related-party, off-balance-sheet, contingencies),
working-capital forensics (AR vs revenue, DSO, deferred revenue), auditor/
restatement signals (4.02 filings, going-concern language), insider patterns,
proxy details, and a recent 8-K scan. It is explicitly **neither bull nor bear**
— "a reader of documents."

**Why the anti-hallucination guard:** a confident, *invented* red flag is the
worst possible output. So every finding's `citation` must contain an accession
number of a filing actually fetched in that run; the runner records fetched
accessions (`base.extract_accessions`) and the agent rejects/strips any uncited
finding, with one re-run allowed. If there's no document evidence, it must report
"no notable finding." When enabled, forensic risk re-weights the conviction
composite at 15% (inverted — see below).

### Stress Test — *the most important agent*
**Problem it solves:** every prior report is, by construction, looking for
reasons the thesis works. Someone has to attack it.

**What it does:** reads the prior analyst reports and builds the *strongest*
bear case an intelligent short-seller would make — three specific
counterarguments, a "who has to lose for this to win?" disruption test, a
valuation test (if revenue 5x'd, what multiple is implied — is that historically
plausible?), specific failed historical analogues (Cisco '99, Sun '00, Peloton
'20), and regulatory/political risk. It scores survivability 1-10.

**Why it gets Opus and the largest weight:** this is the differentiator. The
prompt is deliberately antagonistic ("if you can't make a credible bear case, you
haven't looked hard enough"), and the scoring rubric forces use of the *full*
range with explicit anchors, because the failure mode is clustering every name at
4-7. The Stress Test gets **30%** of the conviction composite — more than any
other component — on the principle that rigorous adversarial review, not
optimism, is what separates a real opportunity from a story.

It receives the prior reports **in its prompt** rather than via tools: it is meant
to *react* to the bullish analysis, not start from scratch.

### Peer Comparison — *why this one and not the obvious alternative?*
**Problem it solves:** a stock can look great in isolation and still be the
*second-best* way to express a thesis. Relative value is its own question.

**What it does:** finds the 3 closest comparables (same sub-industry, similar
market-cap band), builds a metric-by-metric matrix (growth, margins, FCF, ROE,
leverage, multiples), ranks the subject on each, and — for every dimension where
the subject is *worse* — states the explicit question "why hold X instead of Y?"
and answers it honestly or admits there's no good answer. It scores preference
strength 1-10.

**Why it informs but doesn't score:** like macro, it surfaces as
`peer_preference_strength` and tempers the synthesizer's narrative (a plainly
better peer belongs in the bear case) but does **not** enter the conviction
composite. The point is to catch "right theme, wrong vehicle," not to double-count
fundamentals already scored upstream.

### Synthesizer — *the portfolio manager*
**Problem it solves:** the specialists will disagree. A pristine balance sheet
doesn't save bad management; strong fundamentals don't survive a fragile bear
case. Someone has to resolve the tension and commit.

**What it does:** reads all reports, names the conflicts explicitly, carries
forward the four core component scores *exactly as reported*, and writes the
thesis — a 4-6 sentence summary, exactly three bull bullets, exactly three bear
bullets, a falsifiable "what would change my mind," and 2-4 dated catalysts. It
has **no tools** — it is pure reasoning over the reports.

**Why no tools:** every tool a synthesizer could call is a tool an analyst should
have called first. Giving it tools would let it re-litigate the analysis and
reintroduce the single-agent bias the committee structure exists to avoid.

**Why it doesn't compute the final score:** the prompt is blunt that
`conviction_score` is *recomputed downstream* from the component scores, so the
model should focus on the narrative and on carrying the four scores accurately.
This is the "judgment in Claude, math in Python" rule at its most load-bearing —
the weighting must be exact and auditable, so a model never does it.

---

## The conviction score — deterministic by design

The synthesizer carries forward four component scores (1-10). The composite is
computed in Python (`synthesizer.compute_conviction`), never by the model:

```
conviction = (0.25·fundamentals + 0.20·balance_sheet
              + 0.25·management  + 0.30·stress_test) · 10
```

→ `0-40 low · 40-60 medium · 60-80 high · 80-100 very high`.

When `--forensic` is enabled, the weighting shifts to make room for forensic risk
(inverted, so higher risk *lowers* conviction; 15% is redistributed from
fundamentals and balance sheet):

```
conviction = (0.20·fundamentals + 0.15·balance_sheet + 0.20·management
              + 0.30·stress_test + 0.15·(11 − forensic_risk)) · 10
```

Stress Test keeps the largest weight in both modes. That is the whole thesis of
the system in one constant: **the bear case matters more than the bull case.**

Peer Comparison and Macro Overlay deliberately stay *out* of this formula. They
shape the written narrative (`peer_preference_strength`, `macro_fit`,
`macro_context`) but not the number — context should inform a human reading the
thesis, not silently move a score.

---

## Cross-cutting design rules

- **Schemas are contracts.** Every agent returns a Pydantic model; there is no
  freeform text. `AgentRunner` validates the final message against the schema and
  sends exactly one correction message on a parse failure. Two failures means the
  agent is broken — there is no third retry papering over it.
- **Everything is auditable.** Every agent invocation writes a JSONL audit entry
  (including fetched filing accessions, which power the forensic citation guard).
  There is no fast path that skips the log.
- **Point-in-time correctness.** Tool handlers thread a `ToolContext(as_of=…)` so
  backtests filter filings by date and never leak future knowledge. Nothing
  hardcodes "today." Web search is disabled in backtests by design.
- **Cost discipline is structural, not incidental.** Narrow scopes, shared
  filing ownership (each filing type belongs to one agent), pre-computed metrics,
  aggressive caching, and a thread-safe budget guard that aborts a run above its
  ceiling.

For the known limitations (stubbed short interest, no survivorship-bias
correction in backtests, single-issuer ETF coverage), see the
[README's Limitations section](../stock_agents/README.md#limitations).
