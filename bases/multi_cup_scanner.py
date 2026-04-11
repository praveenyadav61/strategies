import pandas as pd
import numpy as np
import os
from glob import glob

# ===============================
# ========= PARAMETERS ==========
# ===============================

DATA_FOLDER = "data/market_data"
OUTPUT_FILE = "cup_detection_output.xlsx"

MIN_WEEKS = 8
MAX_WEEKS = 52
ATR_WINDOW = 14

# ===============================
# ========= FILTER CONFIG =======
# ===============================

FILTERS = {
    "depth": False,
    "symmetry": False,
    "prior_trend": False,
    "recovery": False,
    "distance_to_peak": False,
    "atr_compression": False,
    "range_contraction": False,
    "volume_dryup": False,
}

# ===============================
# ========= DEBUG COUNTERS ======
# ===============================

DEBUG = {
    "total_windows": 0,
    "trend_filter_failed": 0,
    "trend_filter_passed": 0,
    "valid_structures": 0,
    "depth_failed": 0,
    "symmetry_failed": 0,
    "trend_failed": 0,
    "recovery_failed": 0,
    "distance_failed": 0,
    "atr_failed": 0,
    "range_failed": 0,
    "volume_failed": 0
}

# ===============================
# ===== HELPER FUNCTIONS ========
# ===============================

def resample_weekly(df):
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.loc[:, ~df.columns.duplicated()]

    weekly = df.resample('W').agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }).dropna()

    return weekly


def compute_atr(df, window):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window).mean()


# ===============================
# ===== FEATURE EXTRACTION ======
# ===============================

def extract_features(window):

    DEBUG["total_windows"] += 1

    if len(window) < MIN_WEEKS:
        return None

    try:
        window = window.copy()

        peak_search = window.iloc[:-int(len(window)*0.3)]
        if len(peak_search) < 5:
            return None

        peak_idx = peak_search['High'].idxmax()
        peak_price = window.loc[peak_idx, 'High']

        after_peak = window.loc[peak_idx:]
        if len(after_peak) < 5:
            return None

        bottom_idx = after_peak['Low'].idxmin()
        bottom_price = window.loc[bottom_idx, 'Low']

        current_price = window['Close'].iloc[-1]

        # ================= STRUCTURE =================
        depth = (peak_price - bottom_price) / peak_price

        left_duration = (bottom_idx - peak_idx).days / 7
        right_duration = (window.index[-1] - bottom_idx).days / 7

        if left_duration <= 0 or right_duration <= 0:
            return None

        symmetry = left_duration / right_duration
        recovery = (current_price - bottom_price) / (peak_price - bottom_price + 1e-6)
        distance_to_peak = (peak_price - current_price) / peak_price

        # ================= TREND =================
        peak_pos = window.index.get_loc(peak_idx)
        if peak_pos < 10:
            return None

        prior_price = window['Close'].iloc[peak_pos - 10]
        prior_trend = peak_price / prior_price
        right_trend = current_price / bottom_price

        # ================= VOLATILITY =================
        window['ATR'] = compute_atr(window, ATR_WINDOW)

        atr_start = window['ATR'].iloc[:int(len(window)*0.5)].mean()
        atr_end = window['ATR'].iloc[-10:].mean()
        atr_compression = atr_end / (atr_start + 1e-6)

        # ================= RANGE =================
        range_series = (window['High'] - window['Low']) / window['Close']

        range_start = range_series.iloc[:int(len(window)*0.5)].mean()
        range_end = range_series.iloc[-10:].mean()
        range_contraction = range_end / (range_start + 1e-6)

        # ================= VOLUME =================
        vol_start = window['Volume'].iloc[:int(len(window)*0.5)].mean()
        vol_end = window['Volume'].iloc[-10:].mean()
        volume_dryup = vol_end / (vol_start + 1e-6)

        # ================= FILTERS =================

        if FILTERS["depth"] and not (0.12 <= depth <= 0.65):
            DEBUG["depth_failed"] += 1
            return None

        if FILTERS["symmetry"] and not (0.5 <= symmetry <= 2):
            DEBUG["symmetry_failed"] += 1
            return None

        if FILTERS["prior_trend"] and prior_trend < 1.3:
            DEBUG["trend_failed"] += 1
            return None

        if FILTERS["recovery"] and recovery < 0.7:
            DEBUG["recovery_failed"] += 1
            return None

        if FILTERS["distance_to_peak"] and distance_to_peak > 0.1:
            DEBUG["distance_failed"] += 1
            return None

        if FILTERS["atr_compression"] and atr_compression > 0.8:
            DEBUG["atr_failed"] += 1
            return None

        if FILTERS["range_contraction"] and range_contraction > 0.8:
            DEBUG["range_failed"] += 1
            return None

        if FILTERS["volume_dryup"] and volume_dryup > 0.9:
            DEBUG["volume_failed"] += 1
            return None

        DEBUG["valid_structures"] += 1

        return {
            "start_date": window.index[0],
            "end_date": window.index[-1],
            "peak_idx": peak_idx,
            "bottom_idx": bottom_idx,

            "depth": depth,
            "left_duration": left_duration,
            "right_duration": right_duration,
            "symmetry": symmetry,
            "recovery": recovery,
            "distance_to_peak": distance_to_peak,

            "prior_trend": prior_trend,
            "right_trend": right_trend,

            "atr_compression": atr_compression,
            "range_contraction": range_contraction,
            "volume_dryup": volume_dryup
        }

    except Exception:
        return None
    


#################### ema #############################
def compute_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()
######################################################

def passes_trend_filter(df):

    if len(df) < 200:
        return False

    df = df.copy()

    # Handle MultiIndex / duplicate columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.loc[:, ~df.columns.duplicated()]

    df["EMA50"] = compute_ema(df["Close"], 50)
    df["EMA200"] = compute_ema(df["Close"], 200)

    last = df.iloc[-1]

    # Extract scalar values safely
    close = float(last["Close"])
    ema50 = float(last["EMA50"])
    ema200 = float(last["EMA200"])

    if np.isnan(ema50) or np.isnan(ema200):
        return False

    return (close > ema200) and (ema50 > ema200)


# ===============================
# ========= SCANNER ============
# ===============================

files = glob(os.path.join(DATA_FOLDER, "*.parquet"))
results = []

for file in files:
    stock = os.path.basename(file).replace(".parquet", "")

    try:
        df = pd.read_parquet(file)

        # ===============================
        # DAILY TREND FILTER
        # ===============================

        if not passes_trend_filter(df):
            DEBUG["trend_filter_failed"] += 1
            continue
        else:
            DEBUG["trend_filter_passed"] += 1

        # Now only strong stocks continue
        weekly = resample_weekly(df)

        if len(weekly) < MAX_WEEKS:
            continue

        end = len(weekly)

        for length in range(MIN_WEEKS, MAX_WEEKS + 1):
            start = end - length
            if start < 0:
                continue

            window = weekly.iloc[start:end]
            features = extract_features(window)

            if features:
                features["stock"] = stock
                results.append(features)

    except Exception as e:
        print(f"Error in {file}: {e}")


# ===============================
# ========= DATAFRAMES =========
# ===============================

df_raw = pd.DataFrame(results)

# Deduplicate cups
if not df_raw.empty:
    df_unique = (
        df_raw
        .sort_values("distance_to_peak")
        .groupby(["stock", "peak_idx", "bottom_idx"], as_index=False)
        .first()
    )
else:
    df_unique = df_raw

# Example filtered view
df_filtered = df_unique[
    (df_unique["distance_to_peak"] < 0.1) &
    (df_unique["atr_compression"] < 0.8)
]

# ===============================
# ========= DEBUG PRINT ========
# ===============================

print("\n===== DEBUG STATS =====")
for k, v in DEBUG.items():
    print(f"{k}: {v}")

print("\nRaw candidates:", len(df_raw))
print("Unique cups:", len(df_unique))
print("Filtered cups:", len(df_filtered))


# ===============================
# ========= SAVE TO EXCEL ======
# ===============================

with pd.ExcelWriter(OUTPUT_FILE) as writer:
    df_raw.to_excel(writer, sheet_name="raw", index=False)
    df_unique.to_excel(writer, sheet_name="unique", index=False)
    df_filtered.to_excel(writer, sheet_name="filtered", index=False)

print(f"\nSaved results to {OUTPUT_FILE}")