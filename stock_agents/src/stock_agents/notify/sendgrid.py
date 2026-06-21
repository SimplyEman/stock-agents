"""SendGrid channel — full HTML email digests (v2 Phase 4).

Uses SendGrid's v3 HTTP API directly via httpx (no SMTP / aiosmtplib dependency).
Sends an HTML body when provided, otherwise the plain-text ``short`` body.
"""

from __future__ import annotations

import httpx

from stock_agents.config import settings
from stock_agents.notify.base import NotificationChannel

_ENDPOINT = "https://api.sendgrid.com/v3/mail/send"


class SendGridChannel(NotificationChannel):
    name = "email"

    def configured(self) -> bool:
        return bool(
            settings.sendgrid_api_key and settings.alert_email and settings.alert_from_email
        )

    def send(self, subject: str, short: str, html: str | None = None) -> bool:
        if not self.configured():
            return False
        content = (
            [{"type": "text/html", "value": html}]
            if html
            else [{"type": "text/plain", "value": short}]
        )
        body = {
            "personalizations": [{"to": [{"email": settings.alert_email}]}],
            "from": {"email": settings.alert_from_email},
            "subject": subject[:255],
            "content": content,
        }
        try:
            resp = httpx.post(
                _ENDPOINT,
                json=body,
                headers={"Authorization": f"Bearer {settings.sendgrid_api_key}"},
                timeout=20.0,
            )
            return 200 <= resp.status_code < 300
        except Exception:
            return False
