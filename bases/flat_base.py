import pandas as pd
import numpy as np
import glob
import os

# =========================================
# PARAMETERS (TUNE HERE)
# =========================================

THREE_MONTH_RETURN = 0.20       # 20%
NEAR_HIGH_PCT = 0.88            # within 12% of 52W high
BASE_WINDOW_DAYS = 40           # base duration window
MAX_DEPTH = 0.15                # 15%
TIGHT_CLOSE_PCT = 0.015         # 1.5%
BB_TOLERANCE = 1.10             # within 10% of 20D low
MIN_DATA_DAYS = 260             # need at least 1Y data
DATA_PATH = "data/market_data/*.parquet"

# =========================================

files = glob.glob(DATA_PATH)

# Diagnostic containers
step1_uptrend = []
step2_strength = []
step3_depth = []
step4_tight = []
step5_bb = []
step6_volume = []
final_candidates = []

for file in files:

    symbol = os.path.basename(file).replace(".parquet", "")

    try:
        df = pd.read_parquet(file)

        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.loc[:, ~df.columns.duplicated()]

        if len(df) < MIN_DATA_DAYS:
            continue

        # Indicators
        df["52w_high"] = df["Close"].rolling(252).max()
        df["3m_return"] = df["Close"].pct_change(63)
        df["ma50"] = df["Close"].rolling(50).mean()
        df["ma200"] = df["Close"].rolling(200).mean()
        df["vol20"] = df["Volume"].rolling(20).mean()
        df["vol50"] = df["Volume"].rolling(50).mean()

        ma20 = df["Close"].rolling(20).mean()
        std20 = df["Close"].rolling(20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        df["bb_width"] = (upper - lower) / ma20

        df = df.dropna()

        if len(df) < BASE_WINDOW_DAYS:
            continue

        latest = df.iloc[-1]

        # ===============================
        # STEP 1: Uptrend
        # ===============================
        cond_uptrend = (
            # latest["3m_return"] >= THREE_MONTH_RETURN
            # and 
            latest["Close"] > latest["ma50"]
            and latest["ma50"] > latest["ma200"]
        )

        if not cond_uptrend:
            continue
        step1_uptrend.append(symbol)

        # ===============================
        # STEP 2: Near High
        # ===============================
        cond_strength = latest["Close"] >= NEAR_HIGH_PCT * latest["52w_high"]

        if not cond_strength:
            continue
        step2_strength.append(symbol)

        # ===============================
        # STEP 3: Depth
        # ===============================
        base_window = df.iloc[-BASE_WINDOW_DAYS:]
        max_high = base_window["High"].max()
        min_low = base_window["Low"].min()
        depth = (max_high - min_low) / max_high

        cond_depth = depth <= MAX_DEPTH

        if not cond_depth:
            continue
        step3_depth.append(symbol)

        # ===============================
        # STEP 4: Tight Close
        # ===============================
        last4 = df["Close"].iloc[-4:]
        cond_tight = (last4.max() - last4.min()) / last4.max() <= TIGHT_CLOSE_PCT

        if not cond_tight:
            continue
        step4_tight.append(symbol)

        # ===============================
        # STEP 5: BB Squeeze
        # ===============================
        recent_bb_min = df["bb_width"].iloc[-20:].min()
        cond_bb = latest["bb_width"] <= recent_bb_min * BB_TOLERANCE

        if not cond_bb:
            continue
        step5_bb.append(symbol)

        # ===============================
        # STEP 6: Volume
        # ===============================
        cond_volume = latest["vol20"] < latest["vol50"]

        if not cond_volume:
            continue
        step6_volume.append(symbol)

        # FINAL PASS
        final_candidates.append(symbol)

    except Exception as e:
        print(f"Error in {symbol}: {e}")

# =========================================
# PRINT DIAGNOSTICS
# =========================================

def print_step(name, lst):
    print(f"\n{name} ({len(lst)} stocks):")
    print(", ".join(lst))  # print first 20 only

print_step("STEP 1 - Uptrend", step1_uptrend)
print_step("STEP 2 - Near High", step2_strength)
print_step("STEP 3 - Depth OK", step3_depth)
print_step("STEP 4 - Tight Close", step4_tight)
print_step("STEP 5 - BB Squeeze", step5_bb)
print_step("STEP 6 - Volume Contraction", step6_volume)

print("\n==== FINAL FLAT BASE CANDIDATES ====")
print(final_candidates)
print(f"\nTotal Final Candidates: {len(final_candidates)}")