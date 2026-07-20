from datetime import date

import pandas as pd

from Streamlit.earnings_tracker import (
    enrich_with_static_data,
    filter_company_context,
    normalize_event_calendar,
)


def test_normalize_keeps_combined_purpose_and_excludes_dividend_only():
    payload = [
        {
            "symbol": "AAA",
            "company": "A Limited",
            "purpose": "Financial Results/Dividend",
            "description": "Quarterly results",
            "date": "20-Jul-2026",
        },
        {
            "symbol": "BBB",
            "company": "B Limited",
            "purpose": "Dividend",
            "description": "Dividend only",
            "date": "21-Jul-2026",
        },
    ]

    result = normalize_event_calendar(payload)

    assert result["Symbol"].tolist() == ["AAA"]
    assert result.iloc[0]["Purpose"] == "Financial Results/Dividend"


def test_static_enrichment_matches_ns_suffix():
    events = pd.DataFrame(
        [{"Date": pd.Timestamp("2026-07-20"), "Symbol": "AAA", "Company": "", "Purpose": "Financial Results", "Details": ""}]
    )
    static = pd.DataFrame(
        [{"symbol": "AAA.NS", "longName": "A Limited", "sector": "Industrials", "industry": "Tools", "marketCap": 25_000_000_000}]
    )

    result = enrich_with_static_data(events, static)

    assert result.iloc[0]["Company"] == "A Limited"
    assert result.iloc[0]["Market Cap (Cr)"] == 2500


def test_context_is_90_days_and_newest_first():
    announcements = pd.DataFrame(
        {
            "symbol": ["AAA.NS", "AAA", "AAA", "BBB"],
            "date": ["2026-07-19", "2026-04-22", "2026-04-20", "2026-07-20"],
        }
    )

    result = filter_company_context(
        announcements, "AAA", "date", "symbol", date(2026, 7, 20)
    )

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-07-19", "2026-04-22"]
