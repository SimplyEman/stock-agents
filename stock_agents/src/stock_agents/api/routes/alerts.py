"""Alert endpoints (v2 Phase 6)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from stock_agents.api.schemas import AlertView
from stock_agents.track import store

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _view(a) -> AlertView:
    return AlertView(
        id=a.id,
        kind=a.kind,
        ticker=a.ticker,
        severity=a.severity,
        message=a.message,
        created_at=a.created_at,
        delivered_at=a.delivered_at,
        acknowledged_at=a.acknowledged_at,
    )


@router.get("")
def list_alerts(status: str | None = None, limit: int = 50) -> list[AlertView]:
    return [_view(a) for a in store.list_alerts(unread_only=(status == "unread"), limit=limit)]


@router.post("/{alert_id}/ack")
def ack(alert_id: str) -> AlertView:
    row = store.acknowledge_alert(alert_id)
    if not row:
        raise HTTPException(404, "alert not found")
    return _view(row)
