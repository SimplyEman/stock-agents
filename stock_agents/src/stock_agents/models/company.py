"""Company- and screening-level schemas.

These cover the universe-building stage: ETF candidates plus the raw financial
data structures returned by the data layer. Agent *output* schemas live in
:mod:`stock_agents.models.analysis` and :mod:`stock_agents.models.thesis`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Screening output (ETF screener agent)
# ---------------------------------------------------------------------------


class Candidate(BaseModel):
    ticker: str
    name: str
    market_cap_usd: float
    sector: str
    industry: str
    etf_appearances: list[str] = Field(
        default_factory=list, description="Tickers of ETFs holding this stock"
    )
    aggregate_weight: float = Field(
        default=0.0, description="Sum of weightings across the ETFs that hold it"
    )
    notes: str | None = None


class CandidateList(BaseModel):
    theme: str
    candidates: list[Candidate]
    excluded: list[dict] = Field(
        default_factory=list, description="{ticker, reason} for filtered-out names"
    )
    summary: str


# ---------------------------------------------------------------------------
# Raw data-layer structures (not LLM output — typed returns from clients)
# ---------------------------------------------------------------------------


class CompanyProfile(BaseModel):
    ticker: str
    name: str = ""
    sector: str = ""
    industry: str = ""
    market_cap_usd: float = 0.0
    ceo: str = ""
    description: str = ""
    country: str = ""
    exchange: str = ""
    cik: str | None = None


class FinancialPeriod(BaseModel):
    """A single annual (or quarterly) statement period.

    Fields use ``None`` when the data provider omits a line item so downstream
    ratio math can decide how to handle the gap rather than silently treating
    missing data as zero.
    """

    fiscal_year: int
    period: str = "FY"
    date: str = ""
    filed_date: str | None = Field(
        default=None,
        description="Date the statement was filed with the SEC; critical for point-in-time backtests",
    )
    reported_currency: str = "USD"
    line_items: dict[str, float | None] = Field(default_factory=dict)

    def get(self, key: str, default: float | None = None) -> float | None:
        return self.line_items.get(key, default)


class StatementSeries(BaseModel):
    """An ordered series of statement periods, most recent first."""

    ticker: str
    statement_type: str  # income | balance_sheet | cash_flow | ratios | key_metrics
    periods: list[FinancialPeriod] = Field(default_factory=list)

    def as_of(self, filed_before: str | None) -> StatementSeries:
        """Return a copy containing only periods filed before ``filed_before``.

        Used by the backtester to enforce point-in-time discipline. Periods
        with no ``filed_date`` are conservatively dropped when a cutoff is set.
        """
        if filed_before is None:
            return self
        kept = [p for p in self.periods if p.filed_date and p.filed_date < filed_before]
        return StatementSeries(
            ticker=self.ticker, statement_type=self.statement_type, periods=kept
        )


class PricePoint(BaseModel):
    date: str
    close: float
    adj_close: float | None = None


class InsiderTransaction(BaseModel):
    filer_name: str
    filer_title: str = ""
    transaction_date: str
    transaction_type: str = ""  # P (purchase), S (sale), etc.
    is_open_market: bool = True
    shares: float = 0.0
    price: float = 0.0
    value_usd: float = 0.0  # signed: positive = buy, negative = sell


class Filing(BaseModel):
    accession_number: str
    form_type: str
    filing_date: str
    primary_document: str = ""
    primary_doc_url: str = ""
    report_date: str | None = None
    item_numbers: str | None = None  # e.g. "2.02,9.01" for 8-Ks


class ETFHolding(BaseModel):
    ticker: str
    name: str = ""
    weight_pct: float = 0.0


class ETFHoldings(BaseModel):
    etf_ticker: str
    as_of: str | None = None
    holdings: list[ETFHolding] = Field(default_factory=list)
