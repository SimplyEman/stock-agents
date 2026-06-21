"""Application settings loaded from environment / .env.

All configuration funnels through :data:`settings`. Modules should import that
singleton rather than reading ``os.environ`` directly so tests can override
values in one place.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Model assignments per agent. Centralized so cost tuning happens in one spot.
# (See the spec: reasoning-heavy agents get Opus, structured analysts get Sonnet.)
MODEL_OPUS = "claude-opus-4-7"
MODEL_SONNET = "claude-sonnet-4-6"

AGENT_MODELS: dict[str, str] = {
    "orchestrator": MODEL_OPUS,
    "synthesizer": MODEL_OPUS,
    "stress_test": MODEL_OPUS,
    "etf_screener": MODEL_SONNET,
    "fundamentals": MODEL_SONNET,
    "balance_sheet": MODEL_SONNET,
    "management": MODEL_SONNET,
    # v2 Phase 2: structured analysts, not adversarial -> Sonnet.
    "peer_comparison": MODEL_SONNET,
    "macro_overlay": MODEL_SONNET,
}

# Per-million-token USD pricing. Update when Anthropic pricing changes; this is
# the single source of truth for the cost tracker.
MODEL_PRICING: dict[str, dict[str, float]] = {
    # input / output / cache-write (5m) / cache-read, USD per 1M tokens.
    "claude-opus-4-7": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.5},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {
        "input": 1.0,
        "output": 5.0,
        "cache_write": 1.25,
        "cache_read": 0.10,
    },
}


class Settings(BaseSettings):
    """Runtime configuration sourced from environment variables / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    fmp_api_key: str = Field(default="", alias="FMP_API_KEY")
    tiingo_api_key: str = Field(default="", alias="TIINGO_API_KEY")
    # v2 Phase 3: AlphaVantage earnings-call transcripts (free tier). Optional —
    # when unset, the transcript fetcher falls back to IR sites / SEC 8-K Item 2.02.
    alphavantage_api_key: str = Field(default="", alias="ALPHAVANTAGE_API_KEY")
    edgar_user_agent: str = Field(
        default="stock-agents research your.email@example.com",
        alias="EDGAR_USER_AGENT",
    )

    cache_dir: Path = Field(default=Path(".cache"), alias="CACHE_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    run_budget_usd: float = Field(default=5.0, alias="RUN_BUDGET_USD")

    # "anthropic" = metered Anthropic API (default; used by the offline test mocks).
    # "claude_code" = drive the `claude` CLI via the Agent SDK on a Claude
    # subscription (usage counts against the plan, not per-token API dollars).
    llm_backend: str = Field(default="anthropic", alias="LLM_BACKEND")

    audit_log_dir: Path = Field(default=Path("audit_logs"), alias="AUDIT_LOG_DIR")

    # v2: persistent workstation state. SQLite DB + JSON thesis snapshots live here.
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")

    # v2 Phase 4: notifications. All optional — unset channels are skipped.
    pushover_user_key: str = Field(default="", alias="PUSHOVER_USER_KEY")
    pushover_app_token: str = Field(default="", alias="PUSHOVER_APP_TOKEN")
    sendgrid_api_key: str = Field(default="", alias="SENDGRID_API_KEY")
    alert_email: str = Field(default="", alias="ALERT_EMAIL")
    alert_from_email: str = Field(default="", alias="ALERT_FROM_EMAIL")
    alert_channel: str = Field(default="pushover", alias="ALERT_CHANNEL")  # pushover|email|both

    # v2 Phase 4/5: per-job cost ceilings (metered-API budgets; advisory on Max).
    weekly_budget_usd: float = Field(default=40.0, alias="WEEKLY_BUDGET_USD")
    daily_post_earnings_budget_usd: float = Field(
        default=5.0, alias="DAILY_POST_EARNINGS_BUDGET_USD"
    )
    sunday_batch_budget_usd: float = Field(default=25.0, alias="SUNDAY_BATCH_BUDGET_USD")

    # v2 Phase 5: sunday_batch themes + candidate depth (comma-separated themes).
    batch_themes_raw: str = Field(
        default="AI infrastructure,biotech,cybersecurity", alias="BATCH_THEMES"
    )
    sunday_batch_max_candidates: int = Field(default=10, alias="SUNDAY_BATCH_MAX_CANDIDATES")

    @property
    def batch_themes(self) -> list[str]:
        return [t.strip() for t in self.batch_themes_raw.split(",") if t.strip()]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "stock_agents.db"

    @property
    def snapshots_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def fmp_base_url(self) -> str:
        # FMP deprecated the legacy /api/v3 surface on 2025-08-31 (returns 403
        # "Legacy Endpoint"). The current API lives under /stable.
        return "https://financialmodelingprep.com/stable"

    @property
    def edgar_data_url(self) -> str:
        return "https://data.sec.gov"

    @property
    def edgar_www_url(self) -> str:
        return "https://www.sec.gov"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()


settings = get_settings()
