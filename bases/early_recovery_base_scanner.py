import pandas as pd
import numpy as np
import glob
import os


# -----------------------------
# Early Recovery Base Logic
# -----------------------------
def detect_early_recovery_base(weekly):

    # --- 1️⃣ 52-week peak ---
    weekly["peak_52"] = weekly["High"].rolling(52).max()

    # --- 2️⃣ Drawdown from peak ---
    weekly["drawdown"] = (
        (weekly["peak_52"] - weekly["Close"]) /
        weekly["peak_52"]
    )

    # Prior meaningful correction (>25%)
    weekly["deep_correction"] = weekly["drawdown"] > 0.25

    # Still below highs (>10% below)
    weekly["below_high"] = weekly["drawdown"] > 0.10

    # --- 3️⃣ Volatility Compression ---
    weekly["log_ret"] = np.log(
        weekly["Close"] / weekly["Close"].shift(1)
    )

    weekly["vol_6"] = weekly["log_ret"].rolling(6).std()
    weekly["vol_26"] = weekly["log_ret"].rolling(26).std()

    weekly["vol_ratio"] = weekly["vol_6"] / weekly["vol_26"]

    weekly["low_vol"] = weekly["vol_ratio"] < 0.8

    # Sustained compression (4 consecutive weeks)
    weekly["sustained_low_vol"] = (
        weekly["low_vol"]
        .rolling(4)
        .sum() == 4
    )

    # --- 4️⃣ Range Stabilization ---
    weekly["base_high_8"] = weekly["High"].rolling(8).max()
    weekly["base_low_8"] = weekly["Low"].rolling(8).min()

    weekly["range_8"] = (
        (weekly["base_high_8"] - weekly["base_low_8"]) /
        weekly["base_low_8"]
    )

    weekly["tight_range"] = weekly["range_8"] < 0.20

    # --- 5️⃣ Final Early Recovery Base ---
    weekly["early_recovery_base"] = (
        weekly["deep_correction"] &
        weekly["below_high"] &
        weekly["sustained_low_vol"] &
        weekly["tight_range"]
    )

    return weekly


# -----------------------------
# Scan All Stocks
# -----------------------------

data_path = "data/market_data/*.parquet"
files = glob.glob(data_path)

results = []

for file in files:

    symbol = os.path.basename(file).replace(".parquet", "")

    try:
        df = pd.read_parquet(file)

        # Fix index
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        # Flatten MultiIndex if needed
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Convert to Weekly
        weekly = df.resample("W-FRI").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum"
        })

        weekly.dropna(inplace=True)

        # Need enough data
        if len(weekly) < 60:
            continue

        weekly = detect_early_recovery_base(weekly)

        # Check latest week
        if weekly.iloc[-1]["early_recovery_base"]:
            results.append(symbol)

    except Exception as e:
        print(f"Error processing {symbol}: {e}")


print("\nEarly Recovery Base Stocks (Weekly):")
print(results)