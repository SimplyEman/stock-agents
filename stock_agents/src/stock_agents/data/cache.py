"""Filesystem cache wrapper around :mod:`diskcache`.

Every external API call routes through here. Cache keys are built from an
endpoint label plus its parameters, and (for daily-changing data) a date stamp
so the cache refreshes naturally without manual invalidation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable
from typing import Any, TypeVar

import diskcache

from stock_agents.config import settings

T = TypeVar("T")

# Common TTLs (seconds) referenced by the data clients.
TTL_FUNDAMENTALS = 24 * 60 * 60  # 24 hours
TTL_PRICES = 7 * 24 * 60 * 60  # 7 days
TTL_FILINGS = 24 * 60 * 60
TTL_ETF = 24 * 60 * 60

_cache: diskcache.Cache | None = None


def get_cache() -> diskcache.Cache:
    """Return the process-wide diskcache instance."""
    global _cache
    if _cache is None:
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        _cache = diskcache.Cache(str(settings.cache_dir))
    return _cache


def make_key(endpoint: str, params: dict[str, Any], *, datestamp: bool = True) -> str:
    """Build a stable cache key from an endpoint and its params.

    When ``datestamp`` is True the current UTC date is folded in, so a daily TTL
    is reinforced by a key that rolls over at midnight UTC. Backtest calls pass
    ``datestamp=False`` because their result depends on the as-of date encoded
    in params, not on wall-clock time.
    """
    payload = {"endpoint": endpoint, "params": _normalize(params)}
    if datestamp:
        payload["_date"] = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    blob = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode()).hexdigest()[:24]
    return f"{endpoint}:{digest}"


def _normalize(params: dict[str, Any]) -> dict[str, Any]:
    """Drop None values so equivalent calls collapse to the same key."""
    return {k: v for k, v in sorted(params.items()) if v is not None}


def cached_call(
    endpoint: str,
    params: dict[str, Any],
    producer: Callable[[], T],
    *,
    ttl: int = TTL_FUNDAMENTALS,
    datestamp: bool = True,
) -> T:
    """Return a cached value or compute, store, and return it.

    ``producer`` is only invoked on a cache miss. Values must be picklable
    (Pydantic models and plain JSON-able structures both are).
    """
    cache = get_cache()
    key = make_key(endpoint, params, datestamp=datestamp)
    sentinel = object()
    hit = cache.get(key, default=sentinel)
    if hit is not sentinel:
        return hit  # type: ignore[return-value]
    value = producer()
    cache.set(key, value, expire=ttl)
    return value


def clear() -> None:
    get_cache().clear()
