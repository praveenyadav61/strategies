import pandas as pd
import numpy as np
import glob
import os
import sys


def detect_weekly_flat_base(df):

    base_weeks = 8

    df["base_high"] = df["High"].rolling(base_weeks).max()
    df["base_low"] = df["Low"].rolling(base_weeks).min()

    df["range_pct"] = (
        (df["base_high"] - df["base_low"]) /
        df["base_low"]
    )

    df["tight_range"] = df["range_pct"] < 0.15

    df["high_52w"] = df["High"].rolling(52).max()

    df["near_high"] = (
        (df["high_52w"] - df["Close"]) /
        df["high_52w"]
    ) < 0.05

    df["flat_base"] = (
        df["tight_range"] &
        df["near_high"]
    )

    return df


# -----------------------------
# MAIN EXECUTION
# -----------------------------

data_path = "data/market_data"

# If ticker passed → use only that file
if len(sys.argv) > 1:
    ticker = sys.argv[1]
    files = [os.path.join(data_path, f"{ticker}.parquet")]
else:
    # No ticker passed → scan all
    files = glob.glob(os.path.join(data_path, "*.parquet"))


results = []

for file in files:

    symbol = os.path.basename(file).replace(".parquet", "")

    try:
        df = pd.read_parquet(file)

        # Fix index
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Resample to Weekly
        weekly = df.resample("W-FRI").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum"
        })

        weekly.dropna(inplace=True)

        if len(weekly) < 60:
            continue

        weekly = detect_weekly_flat_base(weekly)

        if weekly.iloc[-1]["flat_base"]:
            results.append(symbol)

    except Exception as e:
        print(f"Error processing {symbol}: {e}")


print("\nWeekly Flat Base Stocks:")
print(results)