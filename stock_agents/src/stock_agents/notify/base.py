"""Notification channel interface (v2 Phase 4).

A channel is a thin transport: Pushover for short push messages, SendGrid for
full HTML email digests. Channels are optional — an unconfigured channel reports
``configured() == False`` and is skipped by the dispatcher.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class NotificationChannel(ABC):
    name: str = "channel"

    @abstractmethod
    def configured(self) -> bool:
        """True if the channel has the credentials it needs to send."""

    @abstractmethod
    def send(self, subject: str, short: str, html: str | None = None) -> bool:
        """Send a notification. ``short`` is the plain-text body (Pushover),
        ``html`` the rich body (email). Return True on success, False otherwise.
        Implementations must not raise on transport errors — return False."""
