# /goal: stock_agents calibration run

## How to use

1. Make sure `CLAUDE.md` is at the repo root and current (it defines the calibration targets this goal references).
2. Make sure `.env` has `ANTHROPIC_API_KEY`, `FMP_API_KEY`, and `EDGAR_USER_AGENT` set.
3. Run `uv run pytest` first and confirm 42 passed, 1 skipped. Do not start the goal with a red test suite.
4. Create empty `docs/iteration_notes.md` if it doesn't exist.
5. Start Claude Code in the repo root.
6. Paste the entire block under "Goal text" below as one `/goal` invocation.
7. Walk away. Check back in 30-60 minutes.

## Expected cost and time

- Realistic API spend: **$8–$15** for a full calibration cycle.
- Hard ceiling enforced inside the goal: **$25**. The session aborts above this.
- Wall-clock time: **30–90 minutes** depending on how many iterations are needed.

If the goal is still running after 2 hours, something is wrong — interrupt and inspect.

## Goal text (paste this after `/goal `)

```
Calibrate and validate the stock_agents pipeline through live runs, iterate on agent system prompts to hit the calibration targets defined in CLAUDE.md, and document results honestly. This goal is complete when ALL conditions below are satisfied, and the Haiku verifier confirms each by reading the actual files produced — not by trusting the agent's claims.

COMPLETION CONDITIONS (all must be true):

1. `uv run stockagents inspect AAPL` was executed and the output is sanity-checked. Apple is a known quantity: there should be no false balance sheet red flags, no false insider-selling alarm, no governance concerns invented from web noise. If the output looks wrong on AAPL, fix the responsible agent's prompt before proceeding.

2. `uv run stockagents analyze "AI infrastructure" --max-candidates 5` has been run at least twice: once as a baseline, then at least once more after a measurable prompt improvement to whichever agent had the worst calibration miss in the baseline.

3. `uv run stockagents analyze "biotech" --max-candidates 5` has been run successfully end-to-end, verifying the pipeline generalizes beyond one theme.

4. `uv run stockagents analyze "cloud software" --backtest-date 2020-01-01 --max-candidates 5` has been run and forward-return numbers vs the relevant ETF benchmark are computed and logged.

5. For each Calibration Target listed in CLAUDE.md (cost per run, conviction spread, stress test variance, candidate relevance, JSON validation rate, backtest signal), the measured result is recorded. Each target is either (a) hit, or (b) explicitly documented in docs/iteration_notes.md with: what was tried, what numbers were observed, what would be needed to hit it. Do NOT lower the targets in CLAUDE.md to make the goal pass.

6. `docs/iteration_notes.md` contains at least one entry per run (minimum 4 entries) with: timestamp, exact command, total cost, key numbers (conviction spread across top-5, stress test survivability stdev, per-agent JSON validation failure rate), what was learned, what (if anything) was changed afterward. Entries must contain numerical evidence, not just narrative.

7. The README has a "Results" section populated with actual numbers from these runs: top picks per theme, cost per run, calibration target outcomes, honest assessment of backtest performance vs benchmark. No placeholder text.

8. `uv run pytest` passes with the same or higher count than before (≥42 passed, ≤1 skipped). Tests were not deleted, weakened, or skipped to make this goal pass.

9. Total Anthropic API spend for this entire goal session is under $25 (verifiable via `uv run stockagents cost-report`).

HARD ABORT CONDITIONS — surface to user immediately and stop:

- Any single run exceeds $5 and the budget guard fires
- Cumulative session spend exceeds $25
- Two consecutive iterations on the same calibration target both fail to improve it (do not infinite-loop; document the miss in iteration_notes.md and move on)
- The diagnosis of any failure points to the data layer (`data/`, `tools/handlers.py`, or `metrics.py`) rather than to agent prompts — data layer changes require user review
- Any required change touches a Pydantic schema in `models/`, agent topology, the model selection in CLAUDE.md, or adds a runtime dependency — all require explicit user approval per CLAUDE.md
- The existing test suite goes red at any point
- About to commit `.env` or any file containing API keys

ITERATION RULES:

- System prompt changes only. Touch agents/*.py SYSTEM_PROMPT constants. Do not modify schemas, tool definitions, data layer code, or thread pool sizing.
- After every prompt change, re-run the affected agent (preferably via `inspect TICKER` on a stable test ticker like AAPL or NVDA) and record before/after numbers in iteration_notes.md before claiming progress.
- Make one change at a time. Two simultaneous prompt edits make the diagnosis ambiguous.
- If a calibration target appears unreachable after two honest attempts, document why in iteration_notes.md and move on rather than burning cost on a third attempt.
- Never edit the calibration targets in CLAUDE.md downward to make this goal pass. If a target is genuinely wrong, surface that finding to the user as a separate question — don't decide unilaterally.

VERIFIER GUIDANCE FOR HAIKU:

- Conditions 1-4 are verified by reading the latest entries in `docs/iteration_notes.md` and confirming the listed commands were actually run with non-error output.
- Conditions 5-6 are verified by reading `docs/iteration_notes.md` and checking for numerical content (numbers, ticker symbols, dollar amounts) — not narrative claims.
- Condition 7 is verified by reading the README and confirming the Results section contains specific numbers, not placeholders like "TBD" or "TODO" or "results pending."
- Condition 8 is verified by running `uv run pytest` and parsing the pass/skip counts.
- Condition 9 is verified by running `uv run stockagents cost-report` and reading the total.

Do not mark this goal complete until every condition is independently verifiable from files in the repo, not from chat assertions.
```

## What to expect during the run

You'll see Claude Code work through the conditions roughly in order, with `/goal`'s panel showing turn count and token spend. The most common patterns:

- **First half hour:** AAPL sanity check, then baseline runs on AI infrastructure. Cost so far: $2-4.
- **Middle:** Diagnosis and one or two iterations on whichever agent had the worst miss. This is where most of the value gets created — the system prompt edits here are what makes the system work better. Cost: $3-7 cumulative.
- **Last stretch:** Biotech run, backtest, documentation pass. Cost: $7-12 cumulative.
- **Verification loop:** Haiku may run a few extra turns confirming the conditions are actually met by reading the files. Cost: $0.50-1.

## What to do when it finishes

Whether it completes or aborts:

1. Read `docs/iteration_notes.md` first. This is the audit trail of what actually happened.
2. Read the new "Results" section of the README. The numbers there are the real outcome.
3. Run `uv run stockagents cost-report` to confirm spend.
4. Run `uv run pytest` to confirm no tests broke.
5. Look at the calibration target results. Three categories matter:
   - **Hit:** The system is working as designed for this dimension.
   - **Documented miss with explanation:** The agent honestly hit a wall. Read the explanation and decide whether the target was wrong, the agent needs more work, or the data layer needs to do more.
   - **Anything else:** Failure mode. The goal completed but didn't actually validate. Investigate.

## What to do if it aborts

Aborts are not failures — they're the system catching a problem before it compounds. Likely causes:

- **Budget abort:** Something is fetching data inefficiently. Check cache hit rates in the audit log. Often a single agent is re-fetching the same 10-K.
- **Data layer abort:** The agent diagnosed a problem outside its allowed scope. Read iteration_notes.md for the diagnosis — this is usually genuinely useful information. Address the underlying issue manually, then re-run the goal.
- **Test suite abort:** A prompt change broke something downstream. `git diff` will show what changed; revert and retry with a more conservative prompt edit.
- **Stuck iteration:** Two consecutive failed improvements on the same target usually means the target is wrong or the data isn't there. Read the notes, decide which.

## Iterating after the first goal run

If results look good, the next goal can be narrower and cheaper:

```
Improve only the [worst-performing-agent] prompt to hit its calibration target. Test via `inspect AAPL` and `inspect NVDA` after each change. Document each iteration. Done when the target is hit OR three iterations have been attempted and the failure is documented. Budget ceiling: $5.
```

Narrow goals with strict budgets are how `/goal` becomes a tight feedback loop instead of an open-ended drain.

## Final caution

The biggest risk with unattended `/goal` runs on a financial analysis system is producing outputs that *look* polished and credible but encode subtle calibration failures (a synthesizer that says "high conviction" about everything, a stress test that no longer disagrees with anything). The completion conditions above try to instrument against this by requiring numerical evidence in files Haiku can read. But before you act on any output, read at least two of the produced theses end-to-end yourself. The system is a research assistant. Final judgment is still yours.
