"""Persistence models for the watchlist / tracking workstation.

SQLModel tables mirror the v2 build-spec schema. Phase 1 actively uses
``watchlist``, ``runs`` and ``thesis_snapshots``; ``alerts`` and ``eight_k_seen``
are created here too (cheap, keeps one source of truth) and wired in Phases 4-5.

Also defines the in-memory payload models — :class:`ThesisSnapshot` (the JSON
written to disk) and :class:`Diff` (material-change detection output) — which are
plain Pydantic, not tables.
"""

from __future__ import annotations

import os
import time

from pydantic import BaseModel
from pydantic import Field as PydField
from sqlmodel import Field, SQLModel

from stock_agents.models.analysis import (
    BalanceSheetReport,
    FundamentalsReport,
    ManagementReport,
    StressTestReport,
)
from stock_agents.models.thesis import InvestmentThesis

# ---------------------------------------------------------------------------
# ULID (stdlib, no dependency): 48-bit ms timestamp + 80 bits randomness,
# Crockford base32, 26 chars, lexicographically sortable by creation time.
# ---------------------------------------------------------------------------

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    ts = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")  # 80 bits
    value = (ts << 80) | rand
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class Watchlist(SQLModel, table=True):
    __tablename__ = "watchlist"
    ticker: str = Field(primary_key=True)
    added_at: str
    entry_thesis_path: str
    entry_conviction: float
    entry_price: float | None = None
    notes: str | None = None
    status: str = Field(default="active")  # active | paused | exited


class Run(SQLModel, table=True):
    __tablename__ = "runs"
    id: str = Field(primary_key=True)
    kind: str  # analyze | inspect | backtest | post_earnings | track_status
    theme: str | None = None
    ticker: str | None = None
    as_of: str | None = None
    started_at: str
    finished_at: str | None = None
    status: str  # running | success | failed | aborted
    cost_estimate_usd: float | None = None
    report_path: str | None = None
    error: str | None = None


class ThesisSnapshotRow(SQLModel, table=True):
    __tablename__ = "thesis_snapshots"
    id: str = Field(primary_key=True)
    ticker: str = Field(foreign_key="watchlist.ticker", index=True)
    run_id: str = Field(foreign_key="runs.id")
    taken_at: str
    conviction: float
    fundamentals_score: int | None = None
    balance_sheet_score: int | None = None
    management_score: int | None = None
    stress_test_score: int | None = None
    snapshot_path: str


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"
    id: str = Field(primary_key=True)
    kind: str  # earnings_diff | eight_k | run_failure | cost_warning
    ticker: str | None = None
    severity: str  # info | notice | important
    payload_path: str | None = None
    message: str
    created_at: str
    delivered_at: str | None = None
    acknowledged_at: str | None = None


class EightKSeen(SQLModel, table=True):
    __tablename__ = "eight_k_seen"
    accession_number: str = Field(primary_key=True)
    ticker: str
    filed_at: str
    item_numbers: str | None = None
    url: str


# ---------------------------------------------------------------------------
# Payload models (not tables)
# ---------------------------------------------------------------------------


class ThesisSnapshot(BaseModel):
    """The JSON blob written to disk for each snapshot.

    Always carries the synthesized :class:`InvestmentThesis`. The four analyst
    reports are present only when the snapshot came from a fresh inspect (a theme
    ``FinalReport`` discards them), enabling true red-flag diffing when available.
    """

    id: str
    ticker: str
    run_id: str
    taken_at: str
    thesis: InvestmentThesis
    fundamentals: FundamentalsReport | None = None
    balance_sheet: BalanceSheetReport | None = None
    management: ManagementReport | None = None
    stress_test: StressTestReport | None = None

    @property
    def has_analyst_reports(self) -> bool:
        return any([self.fundamentals, self.balance_sheet, self.management, self.stress_test])

    def red_flags(self) -> list[str]:
        """All red flags across analyst reports (empty if reports absent)."""
        flags: list[str] = []
        for rep in (self.fundamentals, self.balance_sheet, self.management):
            if rep is not None:
                flags.extend(getattr(rep, "red_flags", []) or [])
        return flags


class Diff(BaseModel):
    """Material-change detection between an entry snapshot and a new one."""

    ticker: str
    from_snapshot_id: str | None
    to_snapshot_id: str | None
    status: str = "ok"  # ok | cannot_evaluate

    conviction_from: float | None = None
    conviction_to: float | None = None
    conviction_delta: float | None = None

    # delta per component score (new - entry); positive = improved
    component_deltas: dict[str, int] = PydField(default_factory=dict)

    red_flags_available: bool = False
    new_red_flags: list[str] = PydField(default_factory=list)

    # entry falsifiers ("what would change my mind") that the new bear case touches
    falsifiers_referenced: list[str] = PydField(default_factory=list)

    material_reasons: list[str] = PydField(default_factory=list)

    @property
    def is_material(self) -> bool:
        return bool(self.material_reasons) or self.status == "cannot_evaluate"
