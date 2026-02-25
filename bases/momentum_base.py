import pandas as pd
import numpy as np
import glob
import os


# -----------------------------
# Momentum Base Logic (Weekly)
# -----------------------------
def detect_momentum_base(weekly):

    # --- 1️⃣ 52-week range position ---
    weekly["high_52"] = weekly["High"].rolling(52).max()
    weekly["low_52"] = weekly["Low"].rolling(52).min()

    weekly["range_52"] = weekly["high_52"] - weekly["low_52"]

    weekly["position_52"] = np.where(
        weekly["range_52"] > 0,
        (weekly["Close"] - weekly["low_52"]) / weekly["range_52"],
        0
    )

    # Must have reclaimed >61% of 52w range
    weekly["strong_position"] = weekly["position_52"] > 0.61


    # --- 2️⃣ Volatility Compression ---
    weekly["log_ret"] = np.log(
        weekly["Close"] / weekly["Close"].shift(1)
    )

    weekly["vol_6"] = weekly["log_ret"].rolling(6).std()
    weekly["vol_26"] = weekly["log_ret"].rolling(26).std()

    weekly["vol_ratio"] = weekly["vol_6"] / weekly["vol_26"]

    weekly["low_vol"] = weekly["vol_ratio"] < 0.85

    # Sustained compression (4 consecutive weeks)
    weekly["sustained_low_vol"] = (
        weekly["low_vol"]
        .rolling(3)#4
        .sum() == 3 #4
    )


    # --- 3️⃣ Tight 8-week range ---
    weekly["base_high_8"] = weekly["High"].rolling(8).max()
    weekly["base_low_8"] = weekly["Low"].rolling(8).min()

    weekly["range_8"] = (
        (weekly["base_high_8"] - weekly["base_low_8"]) /
        weekly["base_low_8"]
    )

    weekly["tight_range"] = weekly["range_8"] < 0.22 #0.15


    # --- 4️⃣ Final Momentum Base Condition ---
    weekly["momentum_base"] = (
        weekly["strong_position"] &
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

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Convert daily → weekly
        weekly = df.resample("W-FRI").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum"
        })

        weekly.dropna(inplace=True)

        # Require enough history
        if len(weekly) < 60:
            continue

        weekly = detect_momentum_base(weekly)

        # Check latest week
        if weekly.iloc[-1]["momentum_base"]:
            results.append(symbol)

    except Exception as e:
        print(f"Error processing {symbol}: {e}")


print("\nMomentum Base Stocks (Weekly):")
print(results)