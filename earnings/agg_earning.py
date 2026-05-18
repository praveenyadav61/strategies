import json
import re
from pathlib import Path

import pandas as pd

# --- adjust these paths ---
QUARTER_FILES = [
    "data/quarterly/earnings/Q1_FY25.json",
    "data/quarterly/earnings/Q2_FY25.json",
    "data/quarterly/earnings/Q3_FY25.json",
    "data/quarterly/earnings/Q4_FY25.json",
    "data/quarterly/earnings/Q1_FY26.json",
    "data/quarterly/earnings/Q2_FY26.json",
    "data/quarterly/earnings/Q3_FY26.json",
    "data/quarterly/earnings/Q4_FY26.json",
    # add future quarter files here
]

OUTPUT_PARQUET = "data/quarterly/earnings_12q_aggregated.parquet"
OUTPUT_CSV = "data/quarterly/earnings_12q_aggregated.csv"
KEEP_LAST_N = 12


def parse_quarter_label(label: str):
    if not isinstance(label, str):
        return (0, 0)

    match = re.search(r"Q\s*([1-4])\s*FY\s*(\d{2}|\d{4})", label, re.IGNORECASE)
    if match:
        q = int(match.group(1))
        year = int(match.group(2))
        if year < 100:
            year += 2000
        return (year, q)

    match = re.search(r"FY\s*(\d{2}|\d{4})\s*Q\s*([1-4])", label, re.IGNORECASE)
    if match:
        year = int(match.group(1))
        q = int(match.group(2))
        if year < 100:
            year += 2000
        return (year, q)

    return (0, 0)


def load_quarter_json(path: Path) -> pd.DataFrame:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    rows = payload.get("data", {}).get("rows", [])
    if not rows:
        return pd.DataFrame()

    df = pd.json_normalize(rows)

    if "quarter_label" not in df.columns:
        df["quarter_label"] = ""

    df["quarter_source_file"] = str(path)
    df["quarter_sort_key"] = df["quarter_label"].apply(parse_quarter_label)

    return df


def keep_last_quarters(df: pd.DataFrame, n: int) -> pd.DataFrame:
    df = df.copy()
    df["quarter_sort_key"] = df["quarter_sort_key"].apply(
        lambda x: (x if isinstance(x, tuple) else (0, 0))
    )
    order = df.sort_values(
        by=["ticker", "quarter_sort_key"],
        key=lambda col: col,
        ascending=[True, False],
    )
    return order.groupby("ticker", as_index=False).head(n).reset_index(drop=True)


def build_aggregate(quoter_files):
    frames = []
    for path_str in quoter_files:
        p = Path(path_str)
        if not p.exists():
            print(f"WARNING: file not found: {p}")
            continue

        print(f"Loading {p}")
        df = load_quarter_json(p)
        if df.empty:
            continue

        frames.append(df)

    if not frames:
        raise ValueError("No quarter data loaded.")

    df = pd.concat(frames, ignore_index=True)

    # Keep the newest row for each ticker + quarter_label if duplicates exist.
    df = df.sort_values(
        by=["ticker", "quarter_label", "quarter_sort_key", "quarter_source_file"],
        ascending=[True, True, False, False],
    )
    df = df.drop_duplicates(subset=["ticker", "quarter_label"], keep="first")

    df = keep_last_quarters(df, KEEP_LAST_N)

    cols = [
        "ticker",
        # "company_id",
        "company_name",
        # "exchange",
        # "sector",
        # "industry",
        "quarter_label",
        "quarter_end_date",
        "revenue",
        "operating_profit",
        "net_profit",
        "eps",
        "revenue_qoq",
        "revenue_yoy",
        "profit_qoq",
        "profit_yoy",
        "data_quality_status",
        "fetched_at",
        # "filing_url",
        # "quarter_source_file",
    ]
    existing_cols = [c for c in cols if c in df.columns]
    return df[existing_cols]


def save_aggregated(df: pd.DataFrame):
    out_dir = Path("data")
    out_dir.mkdir(parents=True, exist_ok=True)

    df.to_parquet(OUTPUT_PARQUET, index=False)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved aggregated data to {OUTPUT_PARQUET} and {OUTPUT_CSV}")


if __name__ == "__main__":
    aggregated = build_aggregate(QUARTER_FILES)
    save_aggregated(aggregated)