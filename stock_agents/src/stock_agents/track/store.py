"""SQLite-backed persistence for the watchlist workstation.

A thin typed layer over SQLModel. The engine points at ``settings.db_path``;
tables are created lazily on first use. All timestamps are ISO-8601 UTC strings.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from stock_agents.config import settings
from stock_agents.track.models import (
    Alert,
    EightKSeen,
    Run,
    ThesisSnapshotRow,
    Watchlist,
    new_ulid,
)

_engine: Engine | None = None


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{settings.db_path}", echo=False)
        SQLModel.metadata.create_all(_engine)
    return _engine


def reset_engine() -> None:
    """Drop the cached engine (used by tests that point at a temp DB)."""
    global _engine
    _engine = None


def session() -> Session:
    return Session(get_engine())


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


def add_watchlist(
    ticker: str,
    *,
    entry_thesis_path: str,
    entry_conviction: float,
    entry_price: float | None = None,
    notes: str | None = None,
) -> Watchlist:
    ticker = ticker.upper()
    with session() as s:
        existing = s.get(Watchlist, ticker)
        if existing:
            # Re-tracking: refresh entry data and reactivate.
            existing.entry_thesis_path = entry_thesis_path
            existing.entry_conviction = entry_conviction
            existing.entry_price = entry_price
            existing.notes = notes
            existing.status = "active"
            existing.added_at = now_iso()
            s.add(existing)
            s.commit()
            s.refresh(existing)
            return existing
        row = Watchlist(
            ticker=ticker,
            added_at=now_iso(),
            entry_thesis_path=entry_thesis_path,
            entry_conviction=entry_conviction,
            entry_price=entry_price,
            notes=notes,
            status="active",
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def get_watchlist(ticker: str) -> Watchlist | None:
    with session() as s:
        return s.get(Watchlist, ticker.upper())


def list_watchlist(include_exited: bool = True) -> list[Watchlist]:
    with session() as s:
        stmt = select(Watchlist)
        if not include_exited:
            stmt = stmt.where(Watchlist.status != "exited")
        return list(s.exec(stmt.order_by(Watchlist.added_at)))


def set_status(ticker: str, status: str, *, note: str | None = None) -> Watchlist | None:
    with session() as s:
        row = s.get(Watchlist, ticker.upper())
        if not row:
            return None
        row.status = status
        if note:
            row.notes = f"{row.notes + ' | ' if row.notes else ''}{note}"
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def start_run(kind: str, *, ticker: str | None = None, theme: str | None = None,
              as_of: str | None = None) -> Run:
    with session() as s:
        row = Run(
            id=new_ulid(), kind=kind, ticker=ticker, theme=theme, as_of=as_of,
            started_at=now_iso(), status="running",
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def finish_run(run_id: str, *, status: str, cost_estimate_usd: float | None = None,
               report_path: str | None = None, error: str | None = None) -> None:
    with session() as s:
        row = s.get(Run, run_id)
        if not row:
            return
        row.status = status
        row.finished_at = now_iso()
        row.cost_estimate_usd = cost_estimate_usd
        row.report_path = report_path
        row.error = error
        s.add(row)
        s.commit()


def list_runs(limit: int = 50) -> list[Run]:
    with session() as s:
        return list(s.exec(select(Run).order_by(Run.started_at.desc()).limit(limit)))


# ---------------------------------------------------------------------------
# Thesis snapshots (DB rows; JSON bodies live in snapshots.py)
# ---------------------------------------------------------------------------


def add_snapshot_row(
    *,
    snapshot_id: str,
    ticker: str,
    run_id: str,
    taken_at: str,
    conviction: float,
    snapshot_path: str,
    fundamentals_score: int | None = None,
    balance_sheet_score: int | None = None,
    management_score: int | None = None,
    stress_test_score: int | None = None,
) -> ThesisSnapshotRow:
    with session() as s:
        row = ThesisSnapshotRow(
            id=snapshot_id, ticker=ticker.upper(), run_id=run_id, taken_at=taken_at,
            conviction=conviction, snapshot_path=snapshot_path,
            fundamentals_score=fundamentals_score, balance_sheet_score=balance_sheet_score,
            management_score=management_score, stress_test_score=stress_test_score,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def list_snapshot_rows(ticker: str) -> list[ThesisSnapshotRow]:
    with session() as s:
        return list(
            s.exec(
                select(ThesisSnapshotRow)
                .where(ThesisSnapshotRow.ticker == ticker.upper())
                .order_by(ThesisSnapshotRow.taken_at)
            )
        )


def latest_snapshot_row(ticker: str) -> ThesisSnapshotRow | None:
    rows = list_snapshot_rows(ticker)
    return rows[-1] if rows else None


def get_snapshot_row(snapshot_id: str) -> ThesisSnapshotRow | None:
    with session() as s:
        return s.get(ThesisSnapshotRow, snapshot_id)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def add_alert(
    *,
    kind: str,
    severity: str,
    message: str,
    ticker: str | None = None,
    payload_path: str | None = None,
) -> Alert:
    with session() as s:
        row = Alert(
            id=new_ulid(), kind=kind, severity=severity, message=message, ticker=ticker,
            payload_path=payload_path, created_at=now_iso(),
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def list_alerts(*, unread_only: bool = False, limit: int = 50) -> list[Alert]:
    with session() as s:
        stmt = select(Alert)
        if unread_only:
            stmt = stmt.where(Alert.acknowledged_at.is_(None))
        return list(s.exec(stmt.order_by(Alert.created_at.desc()).limit(limit)))


def mark_alert_delivered(alert_id: str) -> None:
    with session() as s:
        row = s.get(Alert, alert_id)
        if row:
            row.delivered_at = now_iso()
            s.add(row)
            s.commit()


def acknowledge_alert(alert_id: str) -> Alert | None:
    with session() as s:
        row = s.get(Alert, alert_id)
        if not row:
            return None
        row.acknowledged_at = now_iso()
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


# ---------------------------------------------------------------------------
# 8-K dedup
# ---------------------------------------------------------------------------


def is_eight_k_seen(accession_number: str) -> bool:
    with session() as s:
        return s.get(EightKSeen, accession_number) is not None


def mark_eight_k_seen(
    *, accession_number: str, ticker: str, filed_at: str, item_numbers: str | None, url: str
) -> None:
    with session() as s:
        if s.get(EightKSeen, accession_number):
            return
        s.add(EightKSeen(
            accession_number=accession_number, ticker=ticker.upper(), filed_at=filed_at,
            item_numbers=item_numbers, url=url,
        ))
        s.commit()
