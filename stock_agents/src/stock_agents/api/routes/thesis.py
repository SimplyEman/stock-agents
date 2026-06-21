"""Thesis snapshot detail endpoint (v2 Phase 6).

Returns the full stored ThesisSnapshot (thesis + analyst reports when present) so
the ticker-detail page can render bull/bear bullets, falsifiers, and scores.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from stock_agents.track import snapshots, store

router = APIRouter(prefix="/api/thesis", tags=["thesis"])


@router.get("/{snapshot_id}")
def get_thesis(snapshot_id: str) -> dict:
    row = store.get_snapshot_row(snapshot_id)
    if not row:
        raise HTTPException(404, "snapshot not found")
    try:
        snap = snapshots.read_snapshot(row.snapshot_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"snapshot file missing: {exc}") from exc
    return snap.model_dump()
