"""Anthropic tool schemas.

Each constant is a dict matching Anthropic's tool-use schema. Handlers that
implement them live in :mod:`stock_agents.tools.handlers`; the agent runner maps
tool ``name`` -> handler. Agents are given only the subset they need.

The built-in web search tool is referenced via ``WEB_SEARCH`` and is handled
server-side by Anthropic (no local handler), so it's excluded from the handler
registry.
"""

from __future__ import annotations

GET_INCOME_STATEMENT = {
    "name": "get_income_statement",
    "description": (
        "Retrieve historical annual income statements for a ticker plus pre-computed "
        "derived metrics (revenue CAGRs, margins, Rule of 40, FCF conversion). Returns "
        "up to 10 years including revenue, gross profit, operating income, EBITDA, net "
        "income, R&D, and diluted share count."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Stock ticker, e.g., NVDA"},
            "years": {"type": "integer", "description": "Years of history", "default": 5},
        },
        "required": ["ticker"],
    },
}

GET_BALANCE_SHEET = {
    "name": "get_balance_sheet",
    "description": (
        "Retrieve historical annual balance sheets plus derived leverage and capital "
        "structure metrics (net debt/EBITDA, current ratio, goodwill % of assets)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "years": {"type": "integer", "default": 5},
        },
        "required": ["ticker"],
    },
}

GET_CASH_FLOW_STATEMENT = {
    "name": "get_cash_flow_statement",
    "description": (
        "Retrieve historical annual cash flow statements: operating cash flow, capex, "
        "free cash flow, stock-based compensation, buybacks, dividends, acquisitions, "
        "plus dilution and SBC-as-%-of-revenue metrics."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "years": {"type": "integer", "default": 5},
        },
        "required": ["ticker"],
    },
}

GET_COMPANY_PROFILE = {
    "name": "get_company_profile",
    "description": (
        "Get a company profile: name, sector, industry, market cap, CEO name, exchange, "
        "country, and business description."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"ticker": {"type": "string"}},
        "required": ["ticker"],
    },
}

GET_PEER_COMPARISON = {
    "name": "get_peer_comparison",
    "description": (
        "Get up to 5 sector peers for a ticker with their key valuation and margin "
        "metrics for side-by-side comparison."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"ticker": {"type": "string"}},
        "required": ["ticker"],
    },
}

GET_KEY_METRICS = {
    "name": "get_key_metrics",
    "description": (
        "Retrieve annual key valuation/efficiency metrics from the data provider: "
        "P/E, EV/EBITDA, ROIC, ROE, FCF yield, etc., for up to 10 years."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "years": {"type": "integer", "default": 5},
        },
        "required": ["ticker"],
    },
}

SEARCH_THEMATIC_ETFS = {
    "name": "search_thematic_etfs",
    "description": (
        "Given an investment theme (e.g. 'AI infrastructure', 'biotech'), return a "
        "basket of relevant ETF tickers spanning mainstream and specialist funds."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"theme": {"type": "string"}},
        "required": ["theme"],
    },
}

GET_ETF_HOLDINGS = {
    "name": "get_etf_holdings",
    "description": (
        "Retrieve the top holdings of an ETF with each position's portfolio weight (%)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "etf_ticker": {"type": "string"},
            "top_n": {"type": "integer", "default": 25},
        },
        "required": ["etf_ticker"],
    },
}

GET_INSIDER_TRANSACTIONS = {
    "name": "get_insider_transactions",
    "description": (
        "Retrieve Form 4 insider transactions over a lookback period. Returns net "
        "dollar buying/selling by officers and directors, distinguishing open-market "
        "purchases (high signal) from option exercises (low signal)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "months": {"type": "integer", "default": 24},
        },
        "required": ["ticker"],
    },
}

SEARCH_EDGAR_FILINGS = {
    "name": "search_edgar_filings",
    "description": (
        "Search SEC EDGAR for filings of a given type. Form types: 10-K (annual), "
        "10-Q (quarterly), DEF 14A (proxy / exec comp), 8-K (material events), "
        "4 (insider transactions). Returns accession numbers and filing dates."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "form_type": {
                "type": "string",
                "enum": ["10-K", "10-Q", "DEF 14A", "8-K", "4"],
            },
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["ticker", "form_type"],
    },
}

FETCH_FILING_CONTENT = {
    "name": "fetch_filing_content",
    "description": (
        "Fetch the cleaned text of a specific filing by accession number, optionally "
        "narrowed to a section. Text is truncated to fit context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Ticker the filing belongs to"},
            "accession_number": {"type": "string"},
            "section": {
                "type": "string",
                "enum": ["full", "mda", "risk_factors", "exec_comp", "auditor_report"],
                "default": "full",
            },
        },
        "required": ["ticker", "accession_number"],
    },
}

GET_ANALYST_ESTIMATES = {
    "name": "get_analyst_estimates",
    "description": "Retrieve forward analyst revenue and EPS estimates for a ticker.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "years": {"type": "integer", "default": 3},
        },
        "required": ["ticker"],
    },
}

GET_EARNINGS_TRANSCRIPT = {
    "name": "get_earnings_transcript",
    "description": (
        "Retrieve the most recent earnings call transcript or earnings press release "
        "for a ticker. Sources, in order: AlphaVantage (full Q&A transcript), company "
        "IR site, or the SEC 8-K Item 2.02 exhibit (prepared remarks). Returns the "
        "source used, the text, and the quarter. Use to assess Q&A vagueness, "
        "executive evasion, and consistency with prior quarters."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "quarter": {"type": "string", "description": "e.g. 'Q3-2025'; omit for most recent"},
        },
        "required": ["ticker"],
    },
}

GET_SHORT_INTEREST = {
    "name": "get_short_interest",
    "description": (
        "Retrieve short interest context for a ticker. Note: free-tier coverage is "
        "limited and the tool flags when data is unavailable."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"ticker": {"type": "string"}},
        "required": ["ticker"],
    },
}

COMPARE_RISK_FACTORS = {
    "name": "compare_risk_factors",
    "description": (
        "Diff the Risk Factors section of a company's two most recent 10-Ks. Returns "
        "added, removed, and substantially modified risk-factor passages year-over-year, "
        "plus the accession numbers of both filings. Use this to detect new risks "
        "management disclosed or risks they quietly dropped."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "recent_count": {"type": "integer", "default": 2},
        },
        "required": ["ticker"],
    },
}

# Anthropic server-side web search. No local handler — passed straight through.
WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search"}


ALL_TOOLS = [
    GET_INCOME_STATEMENT,
    GET_BALANCE_SHEET,
    GET_CASH_FLOW_STATEMENT,
    GET_COMPANY_PROFILE,
    GET_PEER_COMPARISON,
    GET_KEY_METRICS,
    SEARCH_THEMATIC_ETFS,
    GET_ETF_HOLDINGS,
    GET_INSIDER_TRANSACTIONS,
    SEARCH_EDGAR_FILINGS,
    FETCH_FILING_CONTENT,
    GET_ANALYST_ESTIMATES,
    GET_SHORT_INTEREST,
    GET_EARNINGS_TRANSCRIPT,
    COMPARE_RISK_FACTORS,
]
