import requests
import pandas as pd
from datetime import datetime
import os

# -----------------------------
# CONFIG
# -----------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

BASE_URL = "https://www.nseindia.com"
HISTORICAL_DEALS_API = f"{BASE_URL}/api/historicalOR/bulk-block-short-deals"
LOOKBACK_MONTHS = 6

# The relative path "../data/deals_data/" can be confusing because it depends on
# where you run the script from. A more robust approach is to build an absolute
# path from the script's own location.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SAVE_PATH = os.path.join(PROJECT_ROOT, "data", "deals_data")

# -----------------------------
# SESSION
# -----------------------------
def create_session():
    session = requests.Session()
    session.get(BASE_URL, headers=HEADERS)
    return session

# -----------------------------
# FETCH CSV
# -----------------------------
def fetch_csv(session, url):
    try:
        response = session.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        df = pd.read_csv(pd.io.common.StringIO(response.text))
        return df
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return pd.DataFrame()

# -----------------------------
# PATH HELPERS
# -----------------------------
def get_parquet_path(name):
    return os.path.join(SAVE_PATH, f"{name}.parquet")


# -----------------------------
# DEAL CLEANUP
# -----------------------------
def normalize_deals(df, fetch_date=None):
    if df.empty:
        return df

    df = df.copy()
    df.columns = [
        str(col)
        .replace("\ufeff", "")
        .replace('ï»¿', "")
        .replace('"', "")
        .strip()
        for col in df.columns
    ]

    if "Buy/Sell" in df.columns:
        if "Buy / Sell" in df.columns:
            canonical_side = df["Buy / Sell"].where(
                df["Buy / Sell"].notna() & (df["Buy / Sell"].astype(str).str.strip() != ""),
                df["Buy/Sell"],
            )
            df = df.drop(columns=["Buy/Sell"])
            df["Buy / Sell"] = canonical_side
        else:
            df = df.rename(columns={"Buy/Sell": "Buy / Sell"})

    df = df.loc[:, ~df.columns.duplicated()].copy()

    if "Date" in df.columns:
        date_series = (
            df["Date"]
            .astype(str)
            .str.replace('"', "", regex=False)
            .str.strip()
            .str.upper()
        )
        parsed_dates = pd.to_datetime(date_series, format="%d-%b-%Y", errors="coerce")

        # When data is loaded back from parquet, Date may already look like
        # `YYYY-MM-DD`. Parse that fallback format too so repeated runs stay stable.
        missing_mask = parsed_dates.isna()
        if missing_mask.any():
            parsed_dates.loc[missing_mask] = pd.to_datetime(
                date_series.loc[missing_mask],
                format="%Y-%m-%d",
                errors="coerce",
            )

        df["Date"] = parsed_dates.dt.date

    for col in ["Quantity Traded", "Trade Price / Wght. Avg. Price"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "", regex=False), errors="coerce")

    if fetch_date is not None:
        df["fetch_date"] = pd.to_datetime(fetch_date).date()

    if "fetch_date" in df.columns:
        df["fetch_date"] = pd.to_datetime(df["fetch_date"], errors="coerce").dt.date

    return df


def remove_bulk_round_trip_trades(df):
    """
    For bulk deals only, remove Date + Symbol + Client Name groups where the
    same client appears on both BUY and SELL for the same day.
    """
    if df.empty:
        return df

    side_col = None
    for candidate in ["Buy / Sell", "Buy/Sell"]:
        if candidate in df.columns:
            side_col = candidate
            break

    required_cols = ["Date", "Symbol", "Client Name", side_col]
    if side_col is None or any(col not in df.columns for col in required_cols):
        return df

    df = df.copy()
    df[side_col] = df[side_col].astype(str).str.strip().str.upper()

    return (
        df.groupby(["Date", "Symbol", "Client Name"], group_keys=False)
        .filter(lambda x: x[side_col].nunique() == 1)
        .reset_index(drop=True)
    )


def deduplicate_deals(df, apply_bulk_trade_filter=False):
    if df.empty:
        return df

    df = normalize_deals(df)
    if apply_bulk_trade_filter:
        df = remove_bulk_round_trip_trades(df)

    subset_cols = [col for col in df.columns if col != "fetch_date"]
    if not subset_cols:
        return df

    return df.drop_duplicates(subset=subset_cols, keep="last").reset_index(drop=True)


# -----------------------------
# FETCH HISTORICAL DATA
# -----------------------------
def format_api_date(value):
    return pd.to_datetime(value).strftime("%d-%m-%Y")


def fetch_historical_deals(session, option_type, from_date, to_date):
    params = {
        "optionType": option_type,
        "from": format_api_date(from_date),
        "to": format_api_date(to_date),
        "csv": "true",
    }

    try:
        response = session.get(HISTORICAL_DEALS_API, params=params, headers=HEADERS, timeout=30)
        response.raise_for_status()
        df = pd.read_csv(pd.io.common.StringIO(response.text))
        return df
    except Exception as e:
        print(f"Error fetching {option_type} from {params['from']} to {params['to']}: {e}")
        return pd.DataFrame()


def fetch_last_six_months(as_of_date=None):
    session = create_session()
    as_of_date = pd.to_datetime(as_of_date or datetime.now().date()).date()
    from_date = (pd.Timestamp(as_of_date) - pd.DateOffset(months=LOOKBACK_MONTHS)).date()

    print(
        "Fetching historical bulk/block deals "
        f"from {from_date} to {as_of_date}"
    )

    bulk_df = fetch_historical_deals(session, "bulk_deals", from_date, as_of_date)
    block_df = fetch_historical_deals(session, "block_deals", from_date, as_of_date)

    if not bulk_df.empty:
        bulk_df = normalize_deals(bulk_df, fetch_date=as_of_date)
        bulk_df = deduplicate_deals(bulk_df, apply_bulk_trade_filter=True)
    else:
        print(f"No bulk data available for snapshot dated {as_of_date}")

    if not block_df.empty:
        block_df = normalize_deals(block_df, fetch_date=as_of_date)
        block_df = deduplicate_deals(block_df)
    else:
        print(f"No block data available for snapshot dated {as_of_date}")

    return bulk_df, block_df

# -----------------------------
# SAVE / APPEND PARQUET
# -----------------------------
def append_to_parquet(df, name):
    if df.empty:
        print(f"No data for {name}")
        return df

    os.makedirs(SAVE_PATH, exist_ok=True)

    file_path = get_parquet_path(name)
    if os.path.exists(file_path):
        existing_df = pd.read_parquet(file_path)
        df = pd.concat([existing_df, df], ignore_index=True)

    df = deduplicate_deals(df, apply_bulk_trade_filter=(name == "bulk_deals"))
    sort_cols = [col for col in ["Date", "Symbol", "fetch_date"] if col in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols).reset_index(drop=True)

    df.to_parquet(file_path, index=False)

    print(f"Saved {len(df)} rows to: {file_path}")
    return df

# -----------------------------
# DAILY PIPELINE
# -----------------------------
def run_daily_pipeline(fetch_date_str=None):
    fetch_date = pd.to_datetime(fetch_date_str or datetime.now().date()).date()

    print(f"Fetching latest 6 months of NSE bulk/block deals as of {fetch_date}")
    bulk_df, block_df = fetch_last_six_months(fetch_date)

    bulk_df = append_to_parquet(bulk_df, "bulk_deals")

    block_df = append_to_parquet(block_df, "block_deals")

    return bulk_df, block_df

if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")
    bulk_deals, block_deals = run_daily_pipeline(today_str)
    print("Bulk rows:", 0 if bulk_deals.empty else len(bulk_deals))
    print("Block rows:", 0 if block_deals.empty else len(block_deals))
