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

# NSE CSV endpoints
BULK_CSV_URL = "https://archives.nseindia.com/content/equities/bulk.csv"
BLOCK_CSV_URL = "https://archives.nseindia.com/content/equities/block.csv"

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
    df.columns = [str(col).strip() for col in df.columns]

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], format="%d-%b-%Y", errors="coerce").dt.date

    for col in ["Quantity Traded", "Trade Price / Wght. Avg. Price"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "", regex=False), errors="coerce")
            df.columns = [str(col).strip() for col in df.columns]
            df = df.loc[:, ~df.columns.duplicated()].copy()


    if fetch_date is not None:
        df["fetch_date"] = pd.to_datetime(fetch_date).date()

    if "fetch_date" in df.columns:
        df["fetch_date"] = pd.to_datetime(df["fetch_date"], errors="coerce").dt.date

    return df


def deduplicate_deals(df):
    if df.empty:
        return df

    df = normalize_deals(df)

    subset_cols = [col for col in df.columns if col != "fetch_date"]
    if not subset_cols:
        return df

    return df.drop_duplicates(subset=subset_cols, keep="last").reset_index(drop=True)


# -----------------------------
# FETCH LATEST SNAPSHOT
# -----------------------------
def fetch_latest_snapshot(as_of_date=None):
    session = create_session()
    as_of_date = pd.to_datetime(as_of_date or datetime.now().date()).date()

    bulk_df = fetch_csv(session, BULK_CSV_URL)
    block_df = fetch_csv(session, BLOCK_CSV_URL)

    if not bulk_df.empty:
        bulk_df = normalize_deals(bulk_df, fetch_date=as_of_date)
        bulk_df = deduplicate_deals(bulk_df)
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

    df = deduplicate_deals(df)
    sort_cols = [col for col in ["fetch_date", "Date", "Symbol"] if col in df.columns]
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

    print(f"Fetching latest NSE bulk/block snapshot for local date tag: {fetch_date}")
    bulk_df, block_df = fetch_latest_snapshot(fetch_date)

    bulk_df = append_to_parquet(bulk_df, "bulk_deals")

    block_df = append_to_parquet(block_df, "block_deals")

    return bulk_df, block_df

if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")
    bulk_deals, block_deals = run_daily_pipeline(today_str)
    print("Bulk rows:", 0 if bulk_deals.empty else len(bulk_deals))
    print("Block rows:", 0 if block_deals.empty else len(block_deals))
