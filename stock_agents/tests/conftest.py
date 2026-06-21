"""Shared test fixtures.

Tests run fully offline. The data-layer clients are exercised by monkeypatching
their single HTTP chokepoint (``_get``) to return canned fixtures, so we test the
parsing/normalization logic deterministically without network access.

Live integration tests (real Anthropic + FMP) are guarded by ``requires_keys``
and skipped unless the relevant environment variables are set. A ``vcr_config``
is provided for recording those against cassettes when keys are available.
"""

from __future__ import annotations

import os

import pytest

# Ensure the cache and audit logs land in a temp area during tests.
os.environ.setdefault("CACHE_DIR", ".cache_test")
os.environ.setdefault("AUDIT_LOG_DIR", "audit_logs_test")
os.environ.setdefault("FMP_API_KEY", "test-key")
os.environ.setdefault("EDGAR_USER_AGENT", "stock-agents tests test@example.com")


@pytest.fixture
def vcr_config():
    return {
        "filter_query_parameters": ["apikey", "token"],
        "filter_headers": ["authorization", "user-agent"],
        "record_mode": "none",  # never hit the network in CI
    }


requires_anthropic = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set; live agent test skipped",
)

requires_fmp = pytest.mark.skipif(
    os.environ.get("FMP_API_KEY", "test-key") == "test-key",
    reason="real FMP_API_KEY not set; live data test skipped",
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with a clean cache so monkeypatched fixtures aren't masked."""
    from stock_agents.data import cache

    cache.clear()
    yield
    cache.clear()


# --- fake Anthropic client (offline agent tests) ---------------------------


class _FakeUsage:
    input_tokens = 10
    output_tokens = 10
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


class _FakeText:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeResp:
    def __init__(self, text):
        self.content = [_FakeText(text)]
        self.stop_reason = "end_turn"
        self.usage = _FakeUsage()


class _FakeMessages:
    def __init__(self, text):
        self._text = text
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResp(self._text)


class FakeAnthropic:
    """Returns ``text`` as a single end_turn message for any create() call."""

    def __init__(self, text):
        self.messages = _FakeMessages(text)


def fake_anthropic_returning(text: str):
    """Factory usable to monkeypatch ``base.Anthropic`` so agents run offline."""
    return lambda *a, **k: FakeAnthropic(text)
