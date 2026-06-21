"""Tiingo news client (optional).

Used only when ``TIINGO_API_KEY`` is configured; otherwise callers get an empty
list. News is not part of the v1 scoring path — it's a convenience source for
the management agent's qualitative context.
"""

from __future__ import annotations

from typing import Any

import httpx

from stock_agents.config import settings
from stock_agents.data import cache
from stock_agents.data._http import RateLimiter, raise_for_retryable_status, with_retries

_limiter = RateLimiter(max_per_second=2.0)


def get_news(ticker: str, limit: int = 10) -> list[dict[str, Any]]:
    if not settings.tiingo_api_key:
        return []

    def _load() -> list[dict[str, Any]]:
        @with_retries
        def _do() -> list[dict[str, Any]]:
            _limiter.acquire()
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    "https://api.tiingo.com/tiingo/news",
                    params={"tickers": ticker, "limit": limit},
                    headers={"Authorization": f"Token {settings.tiingo_api_key}"},
                )
                raise_for_retryable_status(resp)
                if resp.status_code != 200:
                    return []
                return resp.json()

        return _do()

    return cache.cached_call(
        "tiingo_news", {"ticker": ticker, "limit": limit}, _load, ttl=cache.TTL_FUNDAMENTALS
    )
