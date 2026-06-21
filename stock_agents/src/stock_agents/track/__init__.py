"""Watchlist + thesis tracking + material-change diffing.

High-level operations the CLI / API call. Lower layers: :mod:`store` (SQLite),
:mod:`snapshots` (JSON bodies), :mod:`diff` (material-change detection),
:mod:`models` (tables + payloads).
"""

from __future__ import annotations

from stock_agents.track import diff as _diff
from stock_agents.track import snapshots, store
from stock_agents.track.models import Diff, ThesisSnapshot, Watchlist


class TrackError(RuntimeError):
    pass


def track_add(
    ticker: str,
    *,
    thesis_path: str | None = None,
    entry_price: float | None = None,
    note: str | None = None,
    ctx=None,
    progress=None,
) -> Watchlist:
    """Add a ticker to the watchlist.

    If ``thesis_path`` is given, the entry thesis is loaded from it (a v1
    FinalReport, a bare thesis, or a saved snapshot). If omitted, a fresh inspect
    is run to establish the entry (and its analyst reports are captured). Either
    way we write an entry snapshot and record it as the first history point.
    """
    ticker = ticker.upper()

    if thesis_path:
        thesis = snapshots.load_entry_thesis(thesis_path, ticker)
        run = store.start_run(kind="track_add", ticker=ticker)
        snap = snapshots.build_snapshot(ticker, run.id, thesis)
        rel = snapshots.write_snapshot(snap)
        store.finish_run(run.id, status="success", report_path=thesis_path)
        analysis_cost = 0.0
    else:
        from stock_agents.agents import orchestrator

        run = store.start_run(kind="inspect", ticker=ticker)
        result = orchestrator.analyze_ticker_detailed(ticker, ctx=ctx, progress=progress)
        if not result.thesis:
            store.finish_run(run.id, status="failed", cost_estimate_usd=result.cost_usd,
                             error=result.error)
            raise TrackError(f"inspect failed for {ticker}: {result.error}")
        thesis = result.thesis
        snap = snapshots.build_snapshot(
            ticker, run.id, thesis,
            fundamentals=result.fundamentals, balance_sheet=result.balance_sheet,
            management=result.management, stress_test=result.stress_test,
        )
        rel = snapshots.write_snapshot(snap)
        store.finish_run(run.id, status="success", cost_estimate_usd=result.cost_usd,
                         report_path=rel)
        analysis_cost = result.cost_usd

    store.add_snapshot_row(
        snapshot_id=snap.id, ticker=ticker, run_id=run.id, taken_at=snap.taken_at,
        conviction=thesis.conviction_score, snapshot_path=rel,
        fundamentals_score=thesis.fundamentals_score,
        balance_sheet_score=thesis.balance_sheet_score,
        management_score=thesis.management_score,
        stress_test_score=thesis.stress_test_score,
    )
    entry = store.add_watchlist(
        ticker, entry_thesis_path=rel, entry_conviction=thesis.conviction_score,
        entry_price=entry_price, notes=note,
    )
    _ = analysis_cost
    return entry


def run_track_status(
    ticker: str, *, ctx=None, progress=None, run_id: str | None = None,
    forensic: bool = False,
) -> tuple[Diff, ThesisSnapshot | None]:
    """Run a fresh inspect on a tracked ticker, store the snapshot, and diff vs entry.

    If ``run_id`` is given (e.g. the API pre-created a ``running`` row so it could
    return the id immediately), that row is finished here instead of a new one.
    """
    from stock_agents.agents import orchestrator

    ticker = ticker.upper()
    wl = store.get_watchlist(ticker)
    if not wl:
        raise TrackError(f"{ticker} is not tracked; run `track {ticker}` first")

    run = store.start_run(kind="track_status", ticker=ticker) if run_id is None else None
    rid = run.id if run is not None else run_id
    result = orchestrator.analyze_ticker_detailed(
        ticker, ctx=ctx, forensic=forensic, progress=progress,
    )

    if not result.thesis:
        store.finish_run(rid, status="failed", cost_estimate_usd=result.cost_usd,
                         error=result.error)
        return _diff.cannot_evaluate(ticker, wl.entry_thesis_path, result.error or "inspect failed"), None

    new_snap = snapshots.build_snapshot(
        ticker, rid, result.thesis,
        fundamentals=result.fundamentals, balance_sheet=result.balance_sheet,
        management=result.management, stress_test=result.stress_test,
    )
    rel = snapshots.write_snapshot(new_snap)
    store.add_snapshot_row(
        snapshot_id=new_snap.id, ticker=ticker, run_id=rid, taken_at=new_snap.taken_at,
        conviction=result.thesis.conviction_score, snapshot_path=rel,
        fundamentals_score=result.thesis.fundamentals_score,
        balance_sheet_score=result.thesis.balance_sheet_score,
        management_score=result.thesis.management_score,
        stress_test_score=result.thesis.stress_test_score,
    )
    store.finish_run(rid, status="success", cost_estimate_usd=result.cost_usd, report_path=rel)

    try:
        entry_snap = snapshots.read_snapshot(wl.entry_thesis_path)
    except Exception as exc:
        raise TrackError(f"could not read entry snapshot for {ticker}: {exc}") from exc

    return _diff.compute_diff(entry_snap, new_snap), new_snap


def current_conviction(ticker: str) -> float | None:
    row = store.latest_snapshot_row(ticker)
    return row.conviction if row else None


__all__ = [
    "Diff", "ThesisSnapshot", "Watchlist", "TrackError",
    "track_add", "run_track_status", "current_conviction", "store", "snapshots",
]
