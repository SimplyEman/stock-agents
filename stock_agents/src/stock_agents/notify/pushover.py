"""Pushover channel — short personal push notifications (v2 Phase 4).

Uses the Pushover HTTP API directly (no extra dependency). Free for personal use
($5 one-time per device). Messages are short; we cap title and body to its limits.
"""

from __future__ import annotations

import httpx

from stock_agents.config import settings
from stock_agents.notify.base import NotificationChannel

_ENDPOINT = "https://api.pushover.net/1/messages.json"
_TITLE_LIMIT = 250
_MESSAGE_LIMIT = 1024


class PushoverChannel(NotificationChannel):
    name = "pushover"

    def configured(self) -> bool:
        return bool(settings.pushover_user_key and settings.pushover_app_token)

    def send(self, subject: str, short: str, html: str | None = None) -> bool:
        if not self.configured():
            return False
        try:
            resp = httpx.post(
                _ENDPOINT,
                data={
                    "token": settings.pushover_app_token,
                    "user": settings.pushover_user_key,
                    "title": subject[:_TITLE_LIMIT],
                    "message": short[:_MESSAGE_LIMIT],
                },
                timeout=15.0,
            )
            return resp.status_code == 200
        except Exception:
            return False
