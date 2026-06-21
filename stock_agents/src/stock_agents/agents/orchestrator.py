"""Orchestrator — mostly Python, with two narrow Claude decisions.

Flow:
1. Screen the theme into a candidate list (ETF screener agent).
2. (Claude) Sanity-check the candidate list; re-screen once with feedback if off.
3. For each candidate, run the four analysts (3 in parallel, then stress test),
   then synthesize a thesis. Candidates are themselves processed in parallel.
4. Rank by conviction and (Claude) write a short market commentary.

A thread-safe cost tracker enforces the per-run budget guard: once projected
spend crosses the configured ceiling, no new candidates are started.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from stock_agents.data.etf import AsymmetricFilter

from stock_agents.agents import (
    balance_sheet,
    etf_screener,
    fundamentals,
    macro_overlay,
    management,
    peer_comparison,
    stress_test,
    synthesizer,
)
from stock_agents.agents.base import AgentRunner
from stock_agents.config import MODEL_OPUS, settings
from stock_agents.models.analysis import (
    BalanceSheetReport,
    ForensicReport,
    FundamentalsReport,
    MacroContext,
    ManagementReport,
    PeerComparisonReport,
    StressTestReport,
)
from stock_agents.models.company import Candidate, CandidateList
from stock_agents.models.thesis import FinalReport, InvestmentThesis
from stock_agents.tools.handlers import ToolContext

ProgressCb = Callable[[dict], None]


class _Validation(BaseModel):
    ok: bool
    feedback: str = ""


class _Commentary(BaseModel):
    commentary: str


@dataclass
class _CostTracker:
    budget: float
    lock: threading.Lock = field(default_factory=threading.Lock)
    total: float = 0.0
    aborted: bool = False

    def add(self, amount: float) -> float:
        with self.lock:
            self.total += amount
            if self.total >= self.budget:
                self.aborted = True
            return self.total

    @property
    def over_budget(self) -> bool:
        with self.lock:
            return self.aborted


def _emit(cb: ProgressCb | None, **event) -> None:
    if cb:
        cb(event)


# ---------------------------------------------------------------------------
# Single-candidate pipeline
# ---------------------------------------------------------------------------


@dataclass
class CandidateAnalysis:
    """Full result of analyzing one ticker: the thesis plus the analyst reports
    that produced it, the summed cost, and an error if the pipeline failed.

    The reports are what the tracking layer snapshots so red-flag diffing works;
    the thesis-only ``analyze_single`` wrapper preserves the v1 contract used by
    ``analyze_theme``.
    """

    ticker: str
    thesis: InvestmentThesis | None
    fundamentals: FundamentalsReport | None = None
    balance_sheet: BalanceSheetReport | None = None
    management: ManagementReport | None = None
    stress_test: StressTestReport | None = None
    peer_comparison: PeerComparisonReport | None = None
    forensic: ForensicReport | None = None
    cost_usd: float = 0.0
    error: str | None = None


def analyze_single_detailed(
    candidate: Candidate,
    *,
    ctx: ToolContext | None = None,
    macro: MacroContext | None = None,
    forensic: bool = False,
    progress: ProgressCb | None = None,
) -> CandidateAnalysis:
    ticker = candidate.ticker
    _emit(progress, stage="analyst_start", ticker=ticker)
    cost = 0.0

    # Three independent analysts run concurrently.
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_fut = pool.submit(fundamentals.run, ticker, ctx=ctx)
        b_fut = pool.submit(balance_sheet.run, ticker, ctx=ctx)
        m_fut = pool.submit(management.run, ticker, ctx=ctx)
        f_res, b_res, m_res = f_fut.result(), b_fut.result(), m_fut.result()

    cost += f_res.cost_usd + b_res.cost_usd + m_res.cost_usd
    if not (f_res.output and b_res.output and m_res.output):
        errs = [r.error for r in (f_res, b_res, m_res) if r.error]
        _emit(progress, stage="analyst_failed", ticker=ticker, errors=errs)
        return CandidateAnalysis(
            ticker=ticker, thesis=None,
            fundamentals=f_res.output, balance_sheet=b_res.output, management=m_res.output,
            cost_usd=cost, error="; ".join(str(e) for e in errs) or "analyst failure",
        )

    # Forensic agent (addendum): after balance sheet, before stress test, when enabled.
    # Non-fatal — its report feeds the stress test and synthesizer.
    forensic_report = None
    if forensic:
        from stock_agents.agents import forensic as forensic_agent

        fo_res = forensic_agent.run(ticker, ctx=ctx)
        cost += fo_res.cost_usd
        forensic_report = fo_res.output
        if forensic_report:
            _emit(progress, stage="forensic_done", ticker=ticker,
                  forensic_risk=forensic_report.forensic_risk_score_1_to_10)

    # Stress test depends on the first three (+ forensic findings when present).
    s_res = stress_test.run(
        ticker, [f_res.output, b_res.output, m_res.output],
        forensic_report=forensic_report, ctx=ctx,
    )
    cost += s_res.cost_usd
    if not s_res.output:
        _emit(progress, stage="analyst_failed", ticker=ticker, errors=[s_res.error])
        return CandidateAnalysis(
            ticker=ticker, thesis=None,
            fundamentals=f_res.output, balance_sheet=b_res.output, management=m_res.output,
            forensic=forensic_report, cost_usd=cost, error=s_res.error or "stress test failure",
        )

    # Peer comparison: after stress test, before synthesis (v2 Phase 2). Non-fatal
    # if it fails — the synthesizer can still produce a thesis without it.
    p_res = peer_comparison.run(ticker, ctx=ctx)
    cost += p_res.cost_usd
    peer_report = p_res.output

    syn_res = synthesizer.run(
        ticker, [f_res.output, b_res.output, m_res.output, s_res.output],
        peer_report=peer_report, macro=macro, forensic_report=forensic_report, ctx=ctx,
    )
    cost += syn_res.cost_usd
    if not syn_res.output:
        _emit(progress, stage="analyst_failed", ticker=ticker, errors=[syn_res.error])
        return CandidateAnalysis(
            ticker=ticker, thesis=None,
            fundamentals=f_res.output, balance_sheet=b_res.output, management=m_res.output,
            stress_test=s_res.output, peer_comparison=peer_report, forensic=forensic_report,
            cost_usd=cost, error=syn_res.error or "synthesis failure",
        )

    thesis = syn_res.output
    if not thesis.name and candidate.name:
        thesis.name = candidate.name
    # Backstop: surface peer preference strength even if the synthesizer omitted it.
    if thesis.peer_preference_strength is None and peer_report is not None:
        thesis.peer_preference_strength = peer_report.preference_strength_1_to_10
    # Forensic mode: surface the forensic risk and recompute conviction with the
    # forensic-weighted formula (forensic risk lowers conviction).
    if forensic_report is not None:
        thesis.forensic_risk_score = forensic_report.forensic_risk_score_1_to_10
        score, label = synthesizer.compute_conviction(
            thesis.fundamentals_score, thesis.balance_sheet_score,
            thesis.management_score, thesis.stress_test_score,
            forensic_risk=forensic_report.forensic_risk_score_1_to_10,
        )
        thesis.conviction_score, thesis.conviction_label = score, label
    _emit(progress, stage="analyst_done", ticker=ticker, conviction=thesis.conviction_score)
    return CandidateAnalysis(
        ticker=ticker, thesis=thesis,
        fundamentals=f_res.output, balance_sheet=b_res.output,
        management=m_res.output, stress_test=s_res.output, peer_comparison=peer_report,
        forensic=forensic_report, cost_usd=cost,
    )


def analyze_single(
    candidate: Candidate,
    *,
    ctx: ToolContext | None = None,
    macro: MacroContext | None = None,
    forensic: bool = False,
    tracker: _CostTracker | None = None,
    progress: ProgressCb | None = None,
) -> InvestmentThesis | None:
    result = analyze_single_detailed(candidate, ctx=ctx, macro=macro, forensic=forensic, progress=progress)
    if tracker:
        tracker.add(result.cost_usd)
    return result.thesis


# ---------------------------------------------------------------------------
# Theme pipeline
# ---------------------------------------------------------------------------


def _validate_candidates(theme: str, candidates: CandidateList) -> tuple[_Validation, float]:
    runner = AgentRunner(model=MODEL_OPUS, tools=[], handlers={}, agent_name="orchestrator")
    res = runner.run(
        system=(
            "You review a screened candidate list for an investment theme. Judge whether "
            "the list is reasonable: do the companies actually fit the theme, is it "
            "appropriately focused (not 40 names, not 3), and free of obvious junk? "
            "Return ok=true if usable, else ok=false with one sentence of feedback the "
            "screener can act on."
        ),
        user_message=f"Theme: {theme}\n\nCandidate list:\n{candidates.model_dump_json(indent=2)}",
        output_schema=_Validation,
        max_iters=6,  # SDK counts turns conservatively; give tool-free meta-calls headroom
    )
    return (res.output or _Validation(ok=True)), res.cost_usd


def _market_commentary(theme: str, theses: list[InvestmentThesis]) -> tuple[str, float]:
    top = theses[:5]
    runner = AgentRunner(model=MODEL_OPUS, tools=[], handlers={}, agent_name="orchestrator")
    payload = "\n".join(
        f"- {t.ticker} ({t.name}): conviction {t.conviction_score} ({t.conviction_label})"
        for t in top
    )
    res = runner.run(
        system=(
            "You are a PM writing a 2-3 sentence overall market commentary for a thematic "
            "research run. Be calibrated and honest; note if the theme looks crowded or if "
            "no candidate cleared a high-conviction bar."
        ),
        user_message=f"Theme: {theme}\nTop picks:\n{payload}",
        output_schema=_Commentary,
        max_iters=6,  # SDK counts turns conservatively; give tool-free meta-calls headroom
    )
    return (res.output.commentary if res.output else ""), res.cost_usd


def analyze_theme(
    theme: str,
    *,
    max_candidates: int = 15,
    ctx: ToolContext | None = None,
    progress: ProgressCb | None = None,
    budget_usd: float | None = None,
    validate: bool = True,
    asym: AsymmetricFilter | None = None,
    forensic: bool = False,
) -> FinalReport:
    # On the Claude subscription backend, per-agent cost_usd is a usage-equivalent
    # estimate, not metered spend, so the dollar budget guard does not apply.
    if budget_usd is None:
        budget_usd = 10_000.0 if settings.llm_backend == "claude_code" else settings.run_budget_usd
    tracker = _CostTracker(budget=budget_usd)

    # 0. Macro/sector overlay (v2 Phase 2): one call per run, before screening.
    # Its context is passed to the synthesizer for every candidate. Non-fatal.
    _emit(progress, stage="macro_start", theme=theme)
    macro_res = macro_overlay.run(theme, ctx=ctx)
    tracker.add(macro_res.cost_usd)
    macro: MacroContext | None = macro_res.output
    if macro:
        _emit(progress, stage="macro_done", winners=macro.regime_winners_profile)

    # 1. Screen. When an asymmetric filter is active, tell the screener the band
    # up front so it biases toward in-band names (we also hard-filter below).
    _emit(progress, stage="screen_start", theme=theme)
    constraints = asym.describe() if (asym and asym.active) else ""
    screen = etf_screener.run(theme, ctx=ctx, constraints=constraints)
    tracker.add(screen.cost_usd)
    if not screen.output:
        raise RuntimeError(f"ETF screener failed: {screen.error}")
    candidates: CandidateList = screen.output

    # 2. Validate (one re-screen with feedback if needed).
    if validate and candidates.candidates:
        verdict, validate_cost = _validate_candidates(theme, candidates)
        tracker.add(validate_cost)
        if not verdict.ok:
            _emit(progress, stage="rescreen", feedback=verdict.feedback)
            screen = etf_screener.run(f"{theme}\n\nReviewer feedback: {verdict.feedback}", ctx=ctx)
            tracker.add(screen.cost_usd)
            if screen.output:
                candidates = screen.output

    # 2b. Point-in-time universe gate (backtest only). The screener — especially
    # when ETF holdings are unavailable — can propose names it knows from training
    # that had not yet IPO'd at the as-of date (lookahead bias). Drop any candidate
    # that was not investable on the backtest date BEFORE analysis. Filtering runs
    # before truncation so the final set still fills up to max_candidates.
    pool_candidates = candidates.candidates
    if ctx and ctx.as_of:
        from stock_agents.backtesting.point_in_time import was_investable_on

        kept, dropped = [], []
        for c in candidates.candidates:
            (kept if was_investable_on(c.ticker, ctx.as_of) else dropped).append(c)
        pool_candidates = kept
        if dropped:
            _emit(progress, stage="universe_filtered", as_of=ctx.as_of,
                  excluded=[c.ticker for c in dropped])

    # 2c. Asymmetric market-cap / price filter (addendum). Hard-drop out-of-band
    # names so mega-caps can't crowd the list, regardless of what the LLM picked.
    filter_note = ""
    if asym and asym.active:
        from stock_agents.data import etf as _etf

        kept_t, excl = _etf.filter_candidates([c.ticker for c in pool_candidates], asym)
        kept_set = set(kept_t)
        pool_candidates = [c for c in pool_candidates if c.ticker in kept_set]
        excl_counts = "; ".join(f"{reason}: {len(t)} ({', '.join(t)})" for reason, t in excl.items())
        filter_note = (
            f"Asymmetric filter [{asym.describe()}] — excluded {sum(len(t) for t in excl.values())} "
            f"candidate(s){': ' + excl_counts if excl_counts else ''}."
        )
        _emit(progress, stage="asym_filtered", note=filter_note)

    selected = pool_candidates[:max_candidates]
    _emit(progress, stage="screened", count=len(selected),
          tickers=[c.ticker for c in selected])

    # 3. Analyze candidates in parallel (4 workers), honoring the budget guard.
    theses: list[InvestmentThesis] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {}
        for c in selected:
            if tracker.over_budget:
                _emit(progress, stage="budget_abort", spent=tracker.total)
                break
            futures[pool.submit(
                analyze_single, c, ctx=ctx, macro=macro, forensic=forensic,
                tracker=tracker, progress=progress,
            )] = c
        for fut in as_completed(futures):
            thesis = fut.result()
            if thesis:
                theses.append(thesis)

    # 4. Rank + commentary.
    theses.sort(key=lambda t: t.conviction_score, reverse=True)
    commentary = ""
    if theses:
        commentary, c_cost = _market_commentary(theme, theses)
        tracker.add(c_cost)

    _emit(progress, stage="done", cost=tracker.total, analyzed=len(theses))
    return FinalReport(
        theme=theme,
        run_timestamp=dt.datetime.now(dt.UTC),
        candidates_analyzed=len(theses),
        api_cost_usd=round(tracker.total, 4),
        market_commentary=commentary,
        macro_context=macro,
        filter_note=filter_note,
        top_picks=theses[:5],
        full_results=theses,
    )


def _candidate_for(ticker: str) -> Candidate:
    from stock_agents.data import fmp

    try:
        p = fmp.get_company_profile(ticker)
        return Candidate(
            ticker=ticker.upper(), name=p.name, market_cap_usd=p.market_cap_usd,
            sector=p.sector, industry=p.industry,
        )
    except Exception:
        return Candidate(ticker=ticker.upper(), name=ticker.upper(), market_cap_usd=0.0,
                         sector="", industry="")


def analyze_ticker_detailed(
    ticker: str, *, ctx: ToolContext | None = None, forensic: bool = False,
    progress: ProgressCb | None = None,
) -> CandidateAnalysis:
    """Run the analyst pipeline on one ticker, returning thesis + reports + cost.
    Used by the tracking layer (track-status) to snapshot the analyst reports."""
    return analyze_single_detailed(_candidate_for(ticker), ctx=ctx, forensic=forensic, progress=progress)


def analyze_ticker(
    ticker: str, *, ctx: ToolContext | None = None, forensic: bool = False,
    progress: ProgressCb | None = None,
) -> InvestmentThesis | None:
    """Run the analyst pipeline on a single user-specified ticker (CLI `inspect`)."""
    return analyze_single_detailed(
        _candidate_for(ticker), ctx=ctx, forensic=forensic, progress=progress
    ).thesis
