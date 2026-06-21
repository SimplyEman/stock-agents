"""Backtest harness.

Runs the full agent pipeline as of a historical date with point-in-time data,
then computes realized forward returns for each pick so you can compare the
top-5 against the relevant theme ETF benchmark.

This is a research aid with known leakage risks (see ``point_in_time``). The
README is explicit about survivorship bias and the web-search blackout.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from stock_agents.agents import orchestrator
from stock_agents.backtesting.point_in_time import (
    as_of_context,
    benchmark_return,
    forward_return,
)
from stock_agents.data.etf import etfs_for_theme
from stock_agents.models.thesis import FinalReport


@dataclass
class BacktestRow:
    as_of_date: str
    ticker: str
    name: str
    conviction_score: float
    fwd_1y: float | None
    fwd_3y: float | None
    fwd_5y: float | None
    delisted: bool = False


@dataclass
class BacktestResult:
    theme: str
    as_of_date: str
    report: FinalReport
    rows: list[BacktestRow] = field(default_factory=list)
    benchmark_ticker: str | None = None
    benchmark_fwd_1y: float | None = None
    benchmark_fwd_3y: float | None = None
    benchmark_fwd_5y: float | None = None

    def top5_avg(self, horizon: str) -> float | None:
        vals = [getattr(r, horizon) for r in self.rows[:5] if getattr(r, horizon) is not None]
        return sum(vals) / len(vals) if vals else None


def run_backtest(
    theme: str,
    as_of_date: str,
    *,
    max_candidates: int = 15,
    progress=None,
) -> BacktestResult:
    ctx = as_of_context(as_of_date)
    report = orchestrator.analyze_theme(
        theme, max_candidates=max_candidates, ctx=ctx, progress=progress, validate=False
    )

    rows: list[BacktestRow] = []
    for thesis in report.full_results:
        f1 = forward_return(thesis.ticker, as_of_date, 1)
        f3 = forward_return(thesis.ticker, as_of_date, 3)
        f5 = forward_return(thesis.ticker, as_of_date, 5)
        rows.append(
            BacktestRow(
                as_of_date=as_of_date,
                ticker=thesis.ticker,
                name=thesis.name,
                conviction_score=thesis.conviction_score,
                fwd_1y=f1,
                fwd_3y=f3,
                fwd_5y=f5,
                delisted=(f1 is None and f3 is None and f5 is None),
            )
        )
    rows.sort(key=lambda r: r.conviction_score, reverse=True)

    bench = (etfs_for_theme(theme) or [None])[0]
    return BacktestResult(
        theme=theme,
        as_of_date=as_of_date,
        report=report,
        rows=rows,
        benchmark_ticker=bench,
        benchmark_fwd_1y=benchmark_return(bench, as_of_date, 1) if bench else None,
        benchmark_fwd_3y=benchmark_return(bench, as_of_date, 3) if bench else None,
        benchmark_fwd_5y=benchmark_return(bench, as_of_date, 5) if bench else None,
    )
