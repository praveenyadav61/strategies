import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

# =========================================================
# CONFIG
# =========================================================

BASE_API_URL = "https://earnings.thecore.in/api/dashboard"

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data" / "quarterly"

AGG_PARQUET = DATA_DIR / "earnings_12q_aggregated.parquet"
AGG_CSV = DATA_DIR / "earnings_12q_aggregated.csv"

MASTER_UNIVERSE_FILE = BASE_DIR / "earnings" / "thecore_tickers_list.txt"


KEEP_LAST_N = 12

REQUEST_TIMEOUT = 30

# =========================================================
# QUARTER HELPERS
# =========================================================


def get_previous_quarter():
    """
    Automatically determine latest completed quarter.

    Example:
    Jan-May   -> Q4 previous FY
    Jun-Aug   -> Q1 current FY
    Sep-Nov   -> Q2 current FY
    Dec-Feb   -> Q3 current FY
    """

    now = datetime.utcnow()

    year = now.year
    month = now.month

    # -----------------------------------------------------
    # Indian FY logic
    # FY starts in April
    # -----------------------------------------------------

    if month in [4, 5, 6]:
        quarter = 4
        fy = year

    elif month in [7, 8, 9]:
        quarter = 1
        fy = year + 1

    elif month in [10, 11, 12]:
        quarter = 2
        fy = year + 1

    else:
        # Jan-Feb-Mar
        quarter = 3
        fy = year

    fy_short = str(fy)[-2:]

    quarter_label = f"Q{quarter} FY{fy_short}"

    quarter_sort_id = int(f"{fy}{quarter:02d}")

    return quarter_label, quarter_sort_id


CURRENT_QUARTER, CURRENT_QUARTER_ID = get_previous_quarter()

API_URL = f"{BASE_API_URL}?quarter={CURRENT_QUARTER.replace(' ', '%20')}"

print("API URL:", API_URL)

# =========================================================
# FINAL COLUMNS
# =========================================================

FINAL_COLUMNS = [
    "ticker",
    "company_name",
    "quarter_label",
    "quarter_sort_id",
    "quarter_end_date",
    "status",
    "revenue",
    "operating_profit",
    "net_profit",
    "eps",
    "revenue_qoq",
    "revenue_yoy",
    "profit_qoq",
    "profit_yoy",
    "data_quality_status",
    "result_declared_date",
    "fetched_at",
    "updated_at",
]

# =========================================================
# LOAD AGGREGATE
# =========================================================

def load_existing_aggregate():
    if Path(AGG_PARQUET).exists():
        print(f"[INFO] Loading aggregate: {AGG_PARQUET}")
        return pd.read_parquet(AGG_PARQUET)

    print("[WARN] Aggregate not found. Creating new dataset.")
    return pd.DataFrame(columns=FINAL_COLUMNS)


# =========================================================
# LOAD MASTER TICKERS
# =========================================================

def load_master_universe():
    with open(MASTER_UNIVERSE_FILE, "r") as f:
        tickers = [
            line.strip()
            for line in f
            if line.strip()
        ]

    master_df = pd.DataFrame({
        "ticker": tickers
    })

    return master_df


# =========================================================
# FETCH API
# =========================================================


def fetch_api_data():
    print(f"[INFO] Fetching earnings for {CURRENT_QUARTER}")

    response = requests.get(
        API_URL,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    payload = response.json()

    rows = payload.get("data", {}).get("rows", [])

    print(f"[INFO] Declared companies fetched: {len(rows)}")

    return rows


# =========================================================
# NORMALIZE DECLARED ROWS
# =========================================================


def normalize_declared_rows(rows):
    if not rows:
        return pd.DataFrame(columns=FINAL_COLUMNS)

    df = pd.json_normalize(rows)

    now_ts = datetime.utcnow().isoformat()

    df["ticker"] = df["ticker"].astype(str).str.strip()

    df["quarter_label"] = CURRENT_QUARTER
    df["quarter_sort_id"] = CURRENT_QUARTER_ID

    df["data_quality_status"] = "DECLARED"

    df["result_declared_date"] = datetime.utcnow().date().isoformat()

    df["updated_at"] = now_ts

    if "fetched_at" not in df.columns:
        df["fetched_at"] = now_ts

    # -----------------------------------------------------
    # Ensure all columns exist
    # -----------------------------------------------------

    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = None

    return df[FINAL_COLUMNS]


# =========================================================
# CREATE PENDING ROWS
# =========================================================


def create_pending_rows(master_df, declared_df):
    declared_tickers = set(declared_df["ticker"].unique())

    pending_df = master_df[
        ~master_df["ticker"].isin(declared_tickers)
    ].copy()

    now_ts = datetime.utcnow().isoformat()

    pending_df["quarter_label"] = CURRENT_QUARTER
    pending_df["quarter_sort_id"] = CURRENT_QUARTER_ID

    pending_df["quarter_end_date"] = None
    pending_df["status"] = "awaiting"

    pending_df["revenue"] = None
    pending_df["operating_profit"] = None
    pending_df["net_profit"] = None
    pending_df["eps"] = None

    pending_df["revenue_qoq"] = None
    pending_df["revenue_yoy"] = None

    pending_df["profit_qoq"] = None
    pending_df["profit_yoy"] = None

    pending_df["data_quality_status"] = "PENDING_RESULT"

    pending_df["result_declared_date"] = None

    pending_df["fetched_at"] = now_ts
    pending_df["updated_at"] = now_ts

    for col in FINAL_COLUMNS:
        if col not in pending_df.columns:
            pending_df[col] = None

    return pending_df[FINAL_COLUMNS]


# =========================================================
# REMOVE CURRENT QUARTER
# =========================================================


def remove_existing_current_quarter(df):
    if df.empty:
        return df

    return df[
        df["quarter_label"] != CURRENT_QUARTER
    ].copy()


# =========================================================
# KEEP LAST N QUARTERS
# =========================================================


def keep_last_n_quarters(df):
    df = df.sort_values(
        by=["ticker", "quarter_sort_id"],
        ascending=[True, False],
    )

    return (
        df.groupby("ticker", as_index=False)
        .head(KEEP_LAST_N)
        .reset_index(drop=True)
    )


# =========================================================
# SAVE
# =========================================================


def save_outputs(df):
    output_dir = Path("data/quarterly")
    output_dir.mkdir(parents=True, exist_ok=True)

    df.to_parquet(AGG_PARQUET, index=False)
    df.to_csv(AGG_CSV, index=False)

    print(f"[INFO] Saved parquet -> {AGG_PARQUET}")
    print(f"[INFO] Saved csv     -> {AGG_CSV}")


# =========================================================
# MAIN
# =========================================================


def main():
    print("=" * 60)
    print(f"Updating aggregate for {CURRENT_QUARTER}")
    print("=" * 60)

    # -----------------------------------------------------
    # Historical aggregate
    # -----------------------------------------------------

    existing_df = load_existing_aggregate()

    # -----------------------------------------------------
    # Remove current quarter
    # -----------------------------------------------------

    existing_df = remove_existing_current_quarter(
        existing_df
    )

    # -----------------------------------------------------
    # Load universe
    # -----------------------------------------------------

    master_df = load_master_universe()

    # -----------------------------------------------------
    # Fetch API data
    # -----------------------------------------------------

    api_rows = fetch_api_data()

    # -----------------------------------------------------
    # Normalize declared rows
    # -----------------------------------------------------

    declared_df = normalize_declared_rows(api_rows)

    # -----------------------------------------------------
    # Create pending rows
    # -----------------------------------------------------

    pending_df = create_pending_rows(
        master_df,
        declared_df,
    )

    # -----------------------------------------------------
    # Combine quarter rows
    # -----------------------------------------------------

    current_quarter_df = pd.concat(
        [declared_df, pending_df],
        ignore_index=True,
    )

    # -----------------------------------------------------
    # Merge with historical
    # -----------------------------------------------------

    final_df = pd.concat(
        [existing_df, current_quarter_df],
        ignore_index=True,
    )

    # -----------------------------------------------------
    # Remove duplicates
    # -----------------------------------------------------

    final_df = final_df.sort_values(
        by=["ticker", "quarter_sort_id", "updated_at"],
        ascending=[True, False, False],
    )

    final_df = final_df.drop_duplicates(
        subset=["ticker", "quarter_label"],
        keep="first",
    )

    # -----------------------------------------------------
    # Keep latest quarters
    # -----------------------------------------------------

    # final_df = keep_last_n_quarters(final_df)

    # -----------------------------------------------------
    # Save
    # -----------------------------------------------------

    save_outputs(final_df)

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------
    pending_statuses = ["awaiting", "scheduled"]

    pending_count = len(
        current_quarter_df[
            current_quarter_df["status"].isin(pending_statuses)
        ]
    )

    declared_count = len(current_quarter_df) - pending_count

    print("=" * 60)
    print("UPDATE COMPLETE")
    print("=" * 60)

    print(f"Quarter            : {CURRENT_QUARTER}")
    print(f"Declared Companies : {declared_count}")
    print(f"Pending Companies  : {pending_count}")
    print(f"Total Companies    : {len(current_quarter_df)}")


# =========================================================
# ENTRY
# =========================================================

if __name__ == "__main__":
    main()