"""Response/request schemas for the FastAPI backend (v2 Phase 6)."""

from __future__ import annotations

from pydantic import BaseModel


class WatchlistView(BaseModel):
    ticker: str
    status: str
    entry_conviction: float
    current_conviction: float | None
    delta: float | None
    entry_price: float | None
    notes: str | None
    added_at: str


class AddWatchlistBody(BaseModel):
    ticker: str
    thesis_path: str | None = None
    entry_price: float | None = None
    notes: str | None = None


class SnapshotView(BaseModel):
    id: str
    taken_at: str
    conviction: float
    fundamentals_score: int | None
    balance_sheet_score: int | None
    management_score: int | None
    stress_test_score: int | None
    run_id: str


class RunView(BaseModel):
    id: str
    kind: str
    theme: str | None
    ticker: str | None
    status: str
    started_at: str
    finished_at: str | None
    cost_estimate_usd: float | None
    report_path: str | None
    error: str | None


class AlertView(BaseModel):
    id: str
    kind: str
    ticker: str | None
    severity: str
    message: str
    created_at: str
    delivered_at: str | None
    acknowledged_at: str | None


class ThemeView(BaseModel):
    theme: str
    etfs: list[str]
    last_analyzed: str | None = None
    top5: list[str] = []


class RunIdResponse(BaseModel):
    run_id: str
    status: str


class SettingsView(BaseModel):
    keys_configured: dict[str, bool]
    batch_themes: list[str]
    alert_channel: str
    weekly_budget_usd: float
    daily_post_earnings_budget_usd: float
    sunday_batch_budget_usd: float
    llm_backend: str


class SettingsUpdate(BaseModel):
    batch_themes: list[str] | None = None
    alert_channel: str | None = None
    weekly_budget_usd: float | None = None
    daily_post_earnings_budget_usd: float | None = None
    sunday_batch_budget_usd: float | None = None
