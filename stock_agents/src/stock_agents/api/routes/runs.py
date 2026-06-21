"""Run history endpoints (v2 Phase 6)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from stock_agents.api.schemas import RunView
from stock_agents.config import settings
from stock_agents.track import store

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _view(r) -> RunView:
    return RunView(
        id=r.id,
        kind=r.kind,
        theme=r.theme,
        ticker=r.ticker,
        status=r.status,
        started_at=r.started_at,
        finished_at=r.finished_at,
        cost_estimate_usd=r.cost_estimate_usd,
        report_path=r.report_path,
        error=r.error,
    )


@router.get("")
def list_runs(limit: int = 50) -> list[RunView]:
    return [_view(r) for r in store.list_runs(limit=limit)]


@router.get("/{run_id}")
def get_run(run_id: str) -> RunView:
    for r in store.list_runs(limit=500):
        if r.id == run_id:
            return _view(r)
    raise HTTPException(404, "run not found")


@router.get("/{run_id}/report")
def get_report(run_id: str) -> dict:
    run = next((r for r in store.list_runs(limit=500) if r.id == run_id), None)
    if not run:
        raise HTTPException(404, "run not found")
    if not run.report_path:
        raise HTTPException(404, "no report for this run (still running or failed)")
    path = Path(run.report_path)
    if not path.is_absolute():
        path = settings.data_dir / path
    if not path.exists():
        path = Path(run.report_path)  # try as-is (e.g. reports/api/{id}.json under cwd)
    if not path.exists():
        raise HTTPException(404, "report file missing")
    return json.loads(path.read_text())
