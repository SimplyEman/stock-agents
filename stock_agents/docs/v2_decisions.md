# v2 decisions

Durable decisions made during the v2 build, with rationale. Pairs with
`docs/iteration_notes.md` (the running run-by-run log).

## Earnings transcripts (Phase 3) — IMPLEMENTED

Source priority, legal-first (see `data/transcripts.py`):

1. **AlphaVantage** `EARNINGS_CALL_TRANSCRIPT` — free tier, needs
   `ALPHAVANTAGE_API_KEY`. Full Q&A transcripts. The spec's designated primary
   source. Inactive until a key is configured.
2. **Company IR sites** — a small manual registry (`transcripts.IR_REGISTRY`).
   Sparse by design: most IR pages serve transcripts as JS-gated PDFs, so this
   stays small and the other two sources carry the load.
3. **SEC 8-K Item 2.02 exhibit** — the earnings press release / prepared remarks,
   filed as an EX-99 exhibit. Not a full Q&A transcript, but **always available
   and free via EDGAR**, and point-in-time safe (filtered by filing date). This is
   the reliable fallback and what the live acceptance test exercises.

**Explicitly not scraped:** Seeking Alpha and Motley Fool (ToS prohibits it).

The Management agent pre-fetches the best available transcript into its user
message (skipped / 8-K-date-filtered in backtest mode to avoid lookahead) and its
prompt now scores Q&A vagueness, executive evasion, and cross-quarter consistency.

## Point-in-time index constituents (Phase 3) — NOT BUILT (deferred)

True backtest validation requires knowing each theme's investable universe *as of*
the historical date — not today's ETF holdings. The v1/v2 backtests use a
future-IPO filter (`was_investable_on`) which removes the egregious lookahead
(companies that did not yet trade), but it does **not** remove survivorship
(candidates still come from today's holdings) or training-data leakage. Closing
that gap needs a point-in-time constituents dataset. Options identified:

| Option | Cost | Notes |
|--------|------|-------|
| **Sharadar SF1** (Nasdaq Data Link) | ~$50/mo, **paid** | Clean point-in-time fundamentals + tickers; the obvious solution. Requires user approval to subscribe. |
| **WRDS** (CRSP/Compustat) | Academic only | Gold standard, but institutional/academic licensing — not available for personal use. |
| **Manual CSVs per year** | Free, **high maintenance** | Hand-curate constituents per theme per year. Brittle, error-prone, doesn't scale across themes. |

**Decision: defer.** Backtests retain the "indicative, not audit-grade" caveat.
This is the path to true backtest validation; revisit once forward use has shown
the system is worth that ongoing $50/mo (and the subscription needs explicit
user approval per the spec — do not subscribe unilaterally).

Per the spec: do not propose a workaround that pretends to solve this without the
data. The future-IPO filter is an honest partial mitigation, not a solution.
