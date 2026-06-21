"""Watchlist endpoints (v2 Phase 6)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from stock_agents.api.schemas import (
    AddWatchlistBody,
    RunIdResponse,
    SnapshotView,
    WatchlistView,
)
from stock_agents.track import store

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _view(w) -> WatchlistView:
    cur = None
    row = store.latest_snapshot_row(w.ticker)
    if row:
        cur = row.conviction
    return WatchlistView(
        ticker=w.ticker, status=w.status, entry_conviction=w.entry_conviction,
        current_conviction=cur, delta=(round(cur - w.entry_conviction, 1) if cur is not None else None),
        entry_price=w.entry_price, notes=w.notes, added_at=w.added_at,
    )


@router.get("")
def list_watchlist() -> list[WatchlistView]:
    return [_view(w) for w in store.list_watchlist()]


@router.post("", status_code=201)
def add_watchlist(body: AddWatchlistBody, background: BackgroundTasks) -> WatchlistView | RunIdResponse:
    from stock_agents import track as tracking

    if body.thesis_path:
        try:
            entry = tracking.track_add(
                body.ticker, thesis_path=body.thesis_path,
                entry_price=body.entry_price, note=body.notes,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, str(exc)) from exc
        return _view(entry)

    # No thesis provided -> run a fresh inspect in the background to establish entry.
    run = store.start_run(kind="inspect", ticker=body.ticker.upper())

    def _job():
        try:
            tracking.track_add(body.ticker, entry_price=body.entry_price, note=body.notes)
            store.finish_run(run.id, status="success")
        except Exception as exc:  # noqa: BLE001
            store.finish_run(run.id, status="failed", error=str(exc))

    background.add_task(_job)
    return RunIdResponse(run_id=run.id, status="running")


@router.delete("/{ticker}")
def untrack(ticker: str) -> dict:
    row = store.set_status(ticker, "exited")
    if not row:
        raise HTTPException(404, f"{ticker.upper()} not tracked")
    return {"ticker": row.ticker, "status": row.status}


@router.get("/{ticker}/history")
def history(ticker: str) -> list[SnapshotView]:
    rows = store.list_snapshot_rows(ticker)
    return [
        SnapshotView(
            id=r.id, taken_at=r.taken_at, conviction=r.conviction,
            fundamentals_score=r.fundamentals_score, balance_sheet_score=r.balance_sheet_score,
            management_score=r.management_score, stress_test_score=r.stress_test_score,
            run_id=r.run_id,
        )
        for r in rows
    ]


@router.post("/{ticker}/refresh")
def refresh(ticker: str, background: BackgroundTasks, forensic: bool = False) -> RunIdResponse:
    if not store.get_watchlist(ticker):
        raise HTTPException(404, f"{ticker.upper()} not tracked")
    run = store.start_run(kind="track_status", ticker=ticker.upper())

    def _job():
        from stock_agents import track as tracking

        try:
            tracking.run_track_status(ticker, run_id=run.id, forensic=forensic)
        except Exception as exc:  # noqa: BLE001
            store.finish_run(run.id, status="failed", error=str(exc))

    background.add_task(_job)
    return RunIdResponse(run_id=run.id, status="running")
