"""
NSE Index Valuation History Fetcher
===================================
Fetches daily historical P/E, P/B, and dividend yield data for active NSE
indices configured in fetch_index_weightage.py.

Source:
    https://www.nseindia.com/api/historicalOR/indicesYield
"""

import argparse
import logging
import os
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

from fetch_index_weightage import build_index_category_map


BASE_URL = "https://www.nseindia.com"
HOME_URL = f"{BASE_URL}/"
REFERER_URL = f"{BASE_URL}/reports-indices-yield"
YIELD_ENDPOINT = f"{BASE_URL}/api/historicalOR/indicesYield"

DEFAULT_START_DATE = "2023-01-01"
DEFAULT_OUTPUT_PATH = "data/static/index_pe_history.parquet"
OUTPUT_COLUMNS = ["date", "index", "pe", "pb", "dividend_yield"]
BLOCK_STATUS_CODES = {401, 403, 429, 503}
# The endpoint rejects ranges over 365 calendar days and also silently caps
# responses near 70 rows. A 90-day window keeps normal trading-day responses
# under that row cap.
MAX_NSE_DATE_RANGE_DAYS = 90

# fetch_index_weightage.py uses NSE's shorter constituent API names. The yield
# endpoint expects the public display names used on the Historical Index Yield
# report page.
INDEX_NAME_ALIASES = {
    "NIFTY MID SELECT": "NIFTY MIDCAP SELECT",
    "NIFTY SMLCAP 100": "NIFTY SMALLCAP 100",
    "NIFTY SMLCAP 250": "NIFTY SMALLCAP 250",
    "NIFTY TOTAL MKT": "NIFTY TOTAL MARKET",
    "NIFTY MICROCAP250": "NIFTY MICROCAP 250",
    "NIFTY FIN SERVICE": "NIFTY FINANCIAL SERVICES",
    "NIFTY PVT BANK": "NIFTY PRIVATE BANK",
    "NIFTY HEALTHCARE": "NIFTY HEALTHCARE INDEX",
    "NIFTY CONSR DURBL": "NIFTY CONSUMER DURABLES",
    "NIFTY OIL AND GAS": "NIFTY OIL & GAS",
    "NIFTY CONSUMPTION": "NIFTY INDIA CONSUMPTION",
    "NIFTY INFRA": "NIFTY INFRASTRUCTURE",
    "NIFTY SERV SECTOR": "NIFTY SERVICES SECTOR",
    "NIFTY CAPITAL MKT": "NIFTY CAPITAL MARKETS",
    "NIFTY100 QUALTY30": "NIFTY100 QUALITY 30",
    "NIFTY200 QUALTY30": "NIFTY200 QUALITY 30",
    "NIFTY MS FIN SERV": "NIFTY MIDSMALL FINANCIAL SERVICES",
    "NIFTY MS IT TELCM": "NIFTY MIDSMALL IT & TELECOM",
    "NIFTY500 HEALTH": "NIFTY500 HEALTHCARE",
    "NIFTY MS IND CONS": "NIFTY MIDSMALL INDIA CONSUMPTION",
    "NIFTY200MOMENTM30": "NIFTY200 MOMENTUM 30",
    "NIFTYM150MOMNTM50": "NIFTY MIDCAP150 MOMENTUM 50",
    "NIFTY500MOMENTM50": "NIFTY500 MOMENTUM 50",
    "NIFTY IND DIGITAL": "NIFTY INDIA DIGITAL",
    "NIFTY INDIA MFG": "NIFTY INDIA MANUFACTURING",
    "NIFTY IND DEFENCE": "NIFTY INDIA DEFENCE",
    "NIFTY IND TOURISM": "NIFTY INDIA TOURISM",
    "NIFTY EV": "NIFTY EV & NEW AGE AUTOMOTIVE",
    "NIFTY NEW CONSUMP": "NIFTY INDIA NEW AGE CONSUMPTION",
    "NIFTY INTERNET": "NIFTY INDIA INTERNET",
    "NIFTY TRANS LOGIS": "NIFTY TRANSPORTATION & LOGISTICS",
    "NIFTY RAILWAYSPSU": "NIFTY INDIA RAILWAYS PSU",
    "NIFTY COREHOUSING": "NIFTY CORE HOUSING",
    "NIFTY NONCYC CONS": "NIFTY NON-CYCLICAL CONSUMER",
}

logger = logging.getLogger(__name__)


def nse_headers(referer: str = REFERER_URL) -> dict:
    """Headers close to a normal browser request; NSE often blocks bare clients."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Referer": referer,
        "Connection": "keep-alive",
        "X-Requested-With": "XMLHttpRequest",
    }


def get_session(timeout: int = 15) -> requests.Session:
    """
    Initialize an NSE session and warm cookies.

    NSE's homepage can occasionally reject non-browser traffic. We still hit it
    first as requested, then load the index yield report page because that page
    reliably sets the cookies needed by the yield API.
    """
    session = requests.Session()
    session.headers.update(nse_headers())

    browser_headers = nse_headers()
    browser_headers["Accept"] = (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    )
    browser_headers.pop("X-Requested-With", None)

    for warmup_url in (HOME_URL, REFERER_URL):
        try:
            response = session.get(warmup_url, headers=browser_headers, timeout=timeout)
            logger.info(
                "Warm-up %s returned %s with %s cookies.",
                warmup_url,
                response.status_code,
                len(session.cookies),
            )
        except requests.RequestException as exc:
            logger.warning("Warm-up failed for %s: %s", warmup_url, exc)

    session.headers.update(nse_headers())
    return session


def _format_nse_date(value: str | datetime | pd.Timestamp) -> str:
    return pd.to_datetime(value).strftime("%d-%m-%Y")


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def date_chunks(
    start_date: str | datetime | pd.Timestamp,
    end_date: str | datetime | pd.Timestamp,
    max_days: int = MAX_NSE_DATE_RANGE_DAYS,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Split long NSE date ranges because the API caps large responses."""
    start = pd.to_datetime(start_date).normalize()
    end = pd.to_datetime(end_date).normalize()

    if start > end:
        raise ValueError(f"start_date {start.date()} is after end_date {end.date()}")

    chunks = []
    current_start = start
    while current_start <= end:
        current_end = min(current_start + timedelta(days=max_days - 1), end)
        chunks.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)

    return chunks


def resolve_index_api_name(index_name: str) -> str:
    """Return the name NSE's yield API expects for a configured index."""
    normalized = str(index_name).strip().upper()
    return INDEX_NAME_ALIASES.get(normalized, normalized)


def fetch_index_data(
    index_name: str,
    session: requests.Session | None = None,
    start_date: str | datetime | pd.Timestamp = DEFAULT_START_DATE,
    end_date: str | datetime | pd.Timestamp | None = None,
    retries: int = 3,
    timeout: int = 20,
) -> pd.DataFrame:
    """
    Fetch daily P/E, P/B, and dividend yield history for one index.

    Returns an empty DataFrame if the index has no data or if NSE blocks the
    request after retries.
    """
    owns_session = session is None
    session = session or get_session()
    end_date = end_date or datetime.today()

    api_index_name = resolve_index_api_name(index_name)
    all_rows = []
    for chunk_start, chunk_end in date_chunks(start_date, end_date):
        params = {
            "indexType": api_index_name,
            "from": _format_nse_date(chunk_start),
            "to": _format_nse_date(chunk_end),
        }

        chunk_data = None
        for attempt in range(1, retries + 1):
            try:
                response = session.get(YIELD_ENDPOINT, params=params, timeout=timeout)

                if response.status_code in BLOCK_STATUS_CODES:
                    logger.warning(
                        "%s blocked/status %s for %s to %s on attempt %s/%s.",
                        index_name,
                        response.status_code,
                        params["from"],
                        params["to"],
                        attempt,
                        retries,
                    )
                    if attempt < retries:
                        session = get_session()
                        time.sleep(attempt)
                        continue
                    return _empty_frame()

                response.raise_for_status()
                payload = response.json()

                if isinstance(payload, dict) and payload.get("error"):
                    message = payload.get("showMessage") or payload.get("message") or payload
                    logger.warning("%s API error for %s to %s: %s", index_name, params["from"], params["to"], message)
                    chunk_data = []
                    break

                chunk_data = payload.get("data", []) if isinstance(payload, dict) else []
                break

            except (requests.RequestException, ValueError) as exc:
                logger.warning(
                    "%s failed for %s to %s on attempt %s/%s: %s",
                    index_name,
                    params["from"],
                    params["to"],
                    attempt,
                    retries,
                    exc,
                )
                if attempt < retries:
                    time.sleep(attempt)

        if chunk_data is None:
            return _empty_frame()
        all_rows.extend(chunk_data)

    if owns_session:
        session.close()

    if not all_rows:
        logger.warning("%s returned no valuation data.", index_name)
        return _empty_frame()

    raw_df = pd.DataFrame(all_rows)
    cleaned = clean_data(raw_df)
    cleaned["index"] = str(index_name).strip().upper()
    return cleaned[OUTPUT_COLUMNS]


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize NSE yield API rows to date/index/pe/pb/dividend_yield."""
    if df.empty:
        return _empty_frame()

    column_map = {
        "IY_DT": "date",
        "IY_INDEX": "index",
        "IY_PE": "pe",
        "IY_PB": "pb",
        "IY_DY": "dividend_yield",
    }

    cleaned = df.rename(columns=column_map).copy()
    for column in OUTPUT_COLUMNS:
        if column not in cleaned.columns:
            cleaned[column] = pd.NA

    cleaned = cleaned[OUTPUT_COLUMNS]
    cleaned["date"] = pd.to_datetime(cleaned["date"], errors="coerce", dayfirst=True)
    cleaned["index"] = cleaned["index"].astype(str).str.strip().str.upper()

    for column in ("pe", "pb", "dividend_yield"):
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    cleaned = cleaned.dropna(subset=["date", "index"])
    cleaned = cleaned.drop_duplicates(subset=["date", "index"], keep="last")
    cleaned = cleaned.sort_values(["index", "date"]).reset_index(drop=True)
    return cleaned


def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Return Friday weekly observations using the last available daily value."""
    if df.empty:
        return _empty_frame()

    cleaned = clean_data(df)
    weekly = (
        cleaned.set_index("date")
        .groupby("index", group_keys=True)[["pe", "pb", "dividend_yield"]]
        .resample("W-FRI")
        .last()
        .dropna(how="all")
        .reset_index()
    )
    return weekly[OUTPUT_COLUMNS].sort_values(["index", "date"]).reset_index(drop=True)


def fetch_all_indices(
    start_date: str | datetime | pd.Timestamp = DEFAULT_START_DATE,
    end_date: str | datetime | pd.Timestamp | None = None,
    output_path: str | None = DEFAULT_OUTPUT_PATH,
    sleep_seconds: float = 0.35,
) -> pd.DataFrame:
    """Fetch valuation history for all active indices and optionally save parquet."""
    index_to_category = build_index_category_map()
    indices = list(index_to_category)
    session = get_session()

    all_frames: list[pd.DataFrame] = []
    failed_indices: list[str] = []

    logger.info(
        "Fetching index valuation data for %s active indices from %s to %s.",
        len(indices),
        _format_nse_date(start_date),
        _format_nse_date(end_date or datetime.today()),
    )

    for count, index_name in enumerate(indices, start=1):
        logger.info("[%s/%s] Fetching %s", count, len(indices), index_name)
        df = fetch_index_data(
            index_name=index_name,
            session=session,
            start_date=start_date,
            end_date=end_date,
        )

        if df.empty:
            failed_indices.append(index_name)
        else:
            all_frames.append(df)

        if sleep_seconds:
            time.sleep(sleep_seconds)

    if not all_frames:
        logger.warning("No index valuation data fetched. NSE may be blocking requests.")
        return _empty_frame()

    final_df = clean_data(pd.concat(all_frames, ignore_index=True))

    if output_path:
        save_to_parquet(final_df, output_path)

    logger.info(
        "Fetched %s rows across %s indices. Skipped %s indices.",
        len(final_df),
        final_df["index"].nunique(),
        len(failed_indices),
    )
    if failed_indices:
        logger.warning("Skipped indices: %s", ", ".join(failed_indices))

    return final_df


def save_to_parquet(df: pd.DataFrame, output_path: str = DEFAULT_OUTPUT_PATH) -> None:
    cleaned = clean_data(df)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cleaned.to_parquet(output_path, index=False)
    logger.info("Saved %s rows to %s", len(cleaned), output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch NSE index P/E, P/B, and dividend yield history.")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="Start date, e.g. 2023-01-01.")
    parser.add_argument("--end-date", default=None, help="End date, defaults to today.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="Output parquet path.")
    parser.add_argument("--no-save", action="store_true", help="Fetch and print sample without saving.")
    parser.add_argument("--sleep", type=float, default=0.35, help="Pause between index requests.")
    parser.add_argument("--quiet", action="store_true", help="Only print warnings and errors.")
    return parser.parse_args()


def configure_logging(quiet: bool = False) -> None:
    level = logging.WARNING if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def main() -> pd.DataFrame:
    args = parse_args()
    configure_logging(quiet=args.quiet)

    final_df = fetch_all_indices(
        start_date=args.start_date,
        end_date=args.end_date,
        output_path=None if args.no_save else args.output,
        sleep_seconds=args.sleep,
    )

    if final_df.empty:
        logger.warning("Final DataFrame is empty.")
    else:
        print("\nSample data:")
        print(final_df.head(20).to_string(index=False))

    return final_df


if __name__ == "__main__":
    main()
