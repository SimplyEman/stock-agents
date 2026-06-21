"""Settings endpoints (v2 Phase 6).

GET returns a masked view (which secrets are configured, never their values) plus
the editable non-secret settings. POST persists non-secret edits to a small
``ui_settings.json`` overlay under ``data_dir``; GET merges it over the env
config. Secrets are never accepted or returned here.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from stock_agents.api.schemas import SettingsUpdate, SettingsView
from stock_agents.config import settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _overlay_path() -> Path:
    return settings.data_dir / "ui_settings.json"


def _read_overlay() -> dict:
    path = _overlay_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            return {}
    return {}


@router.get("")
def get_settings() -> SettingsView:
    overlay = _read_overlay()
    return SettingsView(
        keys_configured={
            "anthropic": bool(settings.anthropic_api_key),
            "fmp": bool(settings.fmp_api_key),
            "alphavantage": bool(settings.alphavantage_api_key),
            "pushover": bool(settings.pushover_user_key and settings.pushover_app_token),
            "sendgrid": bool(settings.sendgrid_api_key),
        },
        batch_themes=overlay.get("batch_themes", settings.batch_themes),
        alert_channel=overlay.get("alert_channel", settings.alert_channel),
        weekly_budget_usd=overlay.get("weekly_budget_usd", settings.weekly_budget_usd),
        daily_post_earnings_budget_usd=overlay.get(
            "daily_post_earnings_budget_usd", settings.daily_post_earnings_budget_usd
        ),
        sunday_batch_budget_usd=overlay.get(
            "sunday_batch_budget_usd", settings.sunday_batch_budget_usd
        ),
        llm_backend=settings.llm_backend,
    )


@router.post("")
def update_settings(body: SettingsUpdate) -> SettingsView:
    overlay = _read_overlay()
    for field, value in body.model_dump(exclude_none=True).items():
        overlay[field] = value
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _overlay_path().write_text(json.dumps(overlay, indent=2))
    return get_settings()
