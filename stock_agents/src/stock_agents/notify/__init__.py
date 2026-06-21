"""Notification dispatch (v2 Phase 4).

``get_channels`` resolves the configured channels from ``ALERT_CHANNEL``;
``dispatch`` sends to the configured ones; ``emit_alert`` writes an alert row to
the DB and delivers it (marking ``delivered_at`` if any channel succeeds). Jobs
call ``emit_alert``; the CLI ``notify-test`` calls ``dispatch``.
"""

from __future__ import annotations

from stock_agents.config import settings
from stock_agents.notify import formatter
from stock_agents.notify.base import NotificationChannel
from stock_agents.notify.pushover import PushoverChannel
from stock_agents.notify.sendgrid import SendGridChannel

__all__ = [
    "NotificationChannel",
    "PushoverChannel",
    "SendGridChannel",
    "get_channels",
    "dispatch",
    "emit_alert",
    "formatter",
]


def get_channels() -> list[NotificationChannel]:
    """Channels selected by ALERT_CHANNEL (pushover | email | both)."""
    choice = (settings.alert_channel or "pushover").lower()
    channels: list[NotificationChannel] = []
    if choice in ("pushover", "both"):
        channels.append(PushoverChannel())
    if choice in ("email", "both"):
        channels.append(SendGridChannel())
    return channels


def dispatch(subject: str, short: str, html: str | None = None) -> dict[str, bool]:
    """Send to every configured selected channel. Returns {channel_name: ok}.

    Unconfigured channels report ``False`` (skipped, not an error).
    """
    results: dict[str, bool] = {}
    for ch in get_channels():
        results[ch.name] = ch.send(subject, short, html) if ch.configured() else False
    return results


def emit_alert(
    *,
    kind: str,
    severity: str,
    subject: str,
    short: str,
    html: str | None = None,
    ticker: str | None = None,
) -> dict[str, bool]:
    """Persist an alert row and attempt delivery. Marks delivered on any success.

    Imported lazily to avoid a hard dependency from notify -> track at import time.
    """
    from stock_agents.track import store

    alert = store.add_alert(kind=kind, severity=severity, message=subject, ticker=ticker)
    results = dispatch(subject, short, html)
    if any(results.values()):
        store.mark_alert_delivered(alert.id)
    return results
