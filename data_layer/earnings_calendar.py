from __future__ import annotations

from datetime import date
import logging

import pandas as pd
import requests


NSE_HOME_URL = "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar"
NSE_EVENT_URL = "https://www.nseindia.com/api/event-calendar"
REQUEST_TIMEOUT = 20
RESPONSE_PREVIEW_LENGTH = 300

LOGGER = logging.getLogger(__name__)


class NSEEventCalendarError(RuntimeError):
    """Raised when the NSE event calendar cannot be retrieved or decoded."""


def nse_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": NSE_HOME_URL,
    }


def response_diagnostic(response: requests.Response) -> str:
    content_type = response.headers.get("Content-Type", "unknown")
    preview = " ".join((response.text or "").split())[:RESPONSE_PREVIEW_LENGTH]
    if not preview:
        preview = "<empty response>"
    return (
        f"HTTP status: {response.status_code}\n"
        f"Content-Type: {content_type}\n"
        f"Final URL: {response.url}\n"
        f"Response preview: {preview}"
    )


def _extract_event_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "records", "events"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    raise NSEEventCalendarError("NSE returned an unexpected event-calendar response.")


def normalize_event_calendar(payload) -> pd.DataFrame:
    rows = _extract_event_rows(payload)
    if not rows:
        return pd.DataFrame(columns=["Date", "Symbol", "Company", "Purpose", "Details"])

    raw = pd.DataFrame(rows)
    aliases = {
        "Date": ("date", "bm_date", "meeting_date"),
        "Symbol": ("symbol", "sm_symbol"),
        "Company": ("company", "company_name", "sm_name"),
        "Purpose": ("purpose", "bm_purpose"),
        "Details": ("description", "details", "bm_desc"),
    }
    normalized = pd.DataFrame(index=raw.index)
    for target, candidates in aliases.items():
        source = next((column for column in candidates if column in raw.columns), None)
        normalized[target] = raw[source] if source else ""

    normalized["Date"] = pd.to_datetime(normalized["Date"], errors="coerce", dayfirst=True)
    normalized["Symbol"] = normalized["Symbol"].astype(str).str.strip().str.upper()
    for column in ("Company", "Purpose", "Details"):
        normalized[column] = normalized[column].fillna("").astype(str).str.strip()

    standalone_dividend = normalized["Purpose"].str.fullmatch(
        r"\s*dividend\s*", case=False, na=False
    )
    return (
        normalized.loc[~standalone_dividend]
        .drop_duplicates()
        .sort_values(["Date", "Symbol"], na_position="last")
        .reset_index(drop=True)
    )


def fetch_earnings_calendar(start_date: date, end_date: date) -> pd.DataFrame:
    session = requests.Session()
    session.headers.update(nse_headers())
    home_diagnostic = "Cookie bootstrap: not attempted"
    try:
        try:
            home_response = session.get(NSE_HOME_URL, timeout=REQUEST_TIMEOUT)
            home_diagnostic = (
                f"Cookie bootstrap: HTTP {home_response.status_code}; "
                f"cookies received: {len(session.cookies)}"
            )
        except requests.RequestException as exc:
            home_diagnostic = f"Cookie bootstrap failed: {type(exc).__name__}: {exc}"

        try:
            response = session.get(
                NSE_EVENT_URL,
                params={
                    "index": "equities",
                    "from_date": start_date.strftime("%d-%m-%Y"),
                    "to_date": end_date.strftime("%d-%m-%Y"),
                    "purpose": "Financial Results",
                },
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            message = (
                "NSE API network request failed.\n"
                f"{home_diagnostic}\n"
                f"Exception: {type(exc).__name__}: {exc}"
            )
            LOGGER.exception(message)
            raise NSEEventCalendarError(message) from exc

        if not response.ok:
            message = (
                "NSE API returned an unsuccessful response.\n"
                f"{home_diagnostic}\n{response_diagnostic(response)}"
            )
            LOGGER.error(message)
            raise NSEEventCalendarError(message)

        try:
            payload = response.json()
        except ValueError as exc:
            message = (
                "NSE API returned a response that was not valid JSON.\n"
                f"{home_diagnostic}\n{response_diagnostic(response)}\n"
                f"Exception: {type(exc).__name__}: {exc}"
            )
            LOGGER.exception(message)
            raise NSEEventCalendarError(message) from exc

        try:
            return normalize_event_calendar(payload)
        except NSEEventCalendarError as exc:
            message = (
                "NSE API returned an unexpected JSON structure.\n"
                f"{home_diagnostic}\n{response_diagnostic(response)}\n"
                f"Parser error: {exc}"
            )
            LOGGER.exception(message)
            raise NSEEventCalendarError(message) from exc
    finally:
        session.close()
