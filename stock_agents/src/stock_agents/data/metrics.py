"""Derived-metric helpers.

These compute the deterministic numbers (CAGRs, margins, Rule of 40, leverage)
from raw statement series so the tool layer can hand agents *pre-computed*
figures alongside the raw data. Keeping the arithmetic in Python — not in the
model — makes every number reproducible and auditable.

All helpers tolerate missing line items by returning ``None`` rather than
raising, since data providers omit fields unpredictably.
"""

from __future__ import annotations

from stock_agents.models.company import StatementSeries


def _cagr(begin: float | None, end: float | None, years: int) -> float | None:
    if begin is None or end is None or begin <= 0 or years <= 0:
        return None
    return ((end / begin) ** (1 / years) - 1) * 100.0


def _latest(series: StatementSeries, key: str) -> float | None:
    for p in series.periods:  # periods are most-recent-first
        v = p.get(key)
        if v is not None:
            return v
    return None


def revenue_cagr(income: StatementSeries, years: int) -> float | None:
    """CAGR over ``years`` using the most recent period vs the one ``years`` back."""
    if len(income.periods) <= years:
        return None
    end = income.periods[0].get("revenue")
    begin = income.periods[years].get("revenue")
    return _cagr(begin, end, years)


def margin(numerator_key: str, income: StatementSeries) -> float | None:
    num = _latest(income, numerator_key)
    rev = _latest(income, "revenue")
    if num is None or not rev:
        return None
    return num / rev * 100.0


def fcf_conversion(cash_flow: StatementSeries) -> float | None:
    fcf = _latest(cash_flow, "free_cash_flow")
    ni = _latest(cash_flow, "net_income")
    if fcf is None or not ni:
        return None
    return fcf / ni


def rule_of_40(income: StatementSeries, cash_flow: StatementSeries) -> float | None:
    growth = revenue_cagr(income, 1) or revenue_cagr(income, 3)
    fcf = _latest(cash_flow, "free_cash_flow")
    rev = _latest(income, "revenue")
    if growth is None or fcf is None or not rev:
        return None
    fcf_margin = fcf / rev * 100.0
    return growth + fcf_margin


def shares_cagr(income: StatementSeries, years: int = 3) -> float | None:
    if len(income.periods) <= years:
        return None
    end = income.periods[0].get("weighted_shares_diluted")
    begin = income.periods[years].get("weighted_shares_diluted")
    return _cagr(begin, end, years)


def sbc_pct_revenue(cash_flow: StatementSeries, income: StatementSeries) -> float | None:
    sbc = _latest(cash_flow, "stock_based_compensation")
    rev = _latest(income, "revenue")
    if sbc is None or not rev:
        return None
    return sbc / rev * 100.0


def net_debt_to_ebitda(balance: StatementSeries, income: StatementSeries) -> float | None:
    debt = _latest(balance, "total_debt")
    cash = _latest(balance, "cash_and_equivalents") or 0.0
    sti = _latest(balance, "short_term_investments") or 0.0
    ebitda = _latest(income, "ebitda")
    if debt is None or not ebitda:
        return None
    return (debt - cash - sti) / ebitda


def interest_coverage(income: StatementSeries) -> float | None:
    op = _latest(income, "operating_income")
    interest = _latest(income, "interest_expense")
    if op is None or not interest:
        return None
    return op / abs(interest)


def current_ratio(balance: StatementSeries) -> float | None:
    ca = _latest(balance, "total_current_assets")
    cl = _latest(balance, "total_current_liabilities")
    if ca is None or not cl:
        return None
    return ca / cl


def goodwill_pct_assets(balance: StatementSeries) -> float | None:
    gw = _latest(balance, "goodwill") or _latest(balance, "goodwill_and_intangibles")
    assets = _latest(balance, "total_assets")
    if gw is None or not assets:
        return None
    return gw / assets * 100.0


def fcf_vs_netincome_gap_pct(cash_flow: StatementSeries) -> float | None:
    """Average |FCF - NI| / |NI| over up to 3 years, as a percentage."""
    gaps: list[float] = []
    for p in cash_flow.periods[:3]:
        fcf = p.get("free_cash_flow")
        ni = p.get("net_income")
        if fcf is not None and ni:
            gaps.append(abs(fcf - ni) / abs(ni) * 100.0)
    if not gaps:
        return None
    return sum(gaps) / len(gaps)


def summarize(
    income: StatementSeries,
    balance: StatementSeries,
    cash_flow: StatementSeries,
) -> dict[str, float | None]:
    """Bundle the common derived metrics into one dict for the tool layer."""
    return {
        "revenue_cagr_3y": revenue_cagr(income, 3),
        "revenue_cagr_5y": revenue_cagr(income, 5),
        "gross_margin_latest": margin("gross_profit", income),
        "operating_margin_latest": margin("operating_income", income),
        "fcf_conversion": fcf_conversion(cash_flow),
        "rule_of_40_score": rule_of_40(income, cash_flow),
        "shares_outstanding_cagr_3y": shares_cagr(income, 3),
        "sbc_pct_revenue": sbc_pct_revenue(cash_flow, income),
        "net_debt_to_ebitda": net_debt_to_ebitda(balance, income),
        "interest_coverage": interest_coverage(income),
        "current_ratio": current_ratio(balance),
        "goodwill_pct_assets": goodwill_pct_assets(balance),
        "fcf_vs_netincome_gap_pct": fcf_vs_netincome_gap_pct(cash_flow),
    }
