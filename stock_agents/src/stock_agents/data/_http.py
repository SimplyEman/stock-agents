"""Shared HTTP plumbing: a rate limiter and a retry decorator.

Both EDGAR and FMP are flaky / rate-limited, so every client builds on these.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T")


class RateLimiter:
    """Simple thread-safe minimum-interval limiter.

    EDGAR allows up to 10 req/s; FMP's free tier is far stricter. We model both
    as "no more than one request every ``min_interval`` seconds" which is safe
    under parallel agent execution because the lock serializes the gate.
    """

    def __init__(self, max_per_second: float):
        self.min_interval = 1.0 / max_per_second if max_per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._last = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


# Retry transient network errors and 5xx / 429 responses, 3 attempts, exp backoff.
RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


def with_retries(fn: Callable[..., T]) -> Callable[..., T]:
    return retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(RETRYABLE),
    )(fn)


def raise_for_retryable_status(resp: httpx.Response) -> None:
    """Raise ``HTTPStatusError`` only for statuses worth retrying."""
    if resp.status_code in (429,) or 500 <= resp.status_code < 600:
        resp.raise_for_status()
