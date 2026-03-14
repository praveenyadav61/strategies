import pandas as pd
import numpy as np
import os
from glob import glob

DATA_FOLDER = "data/daily"

PARAMS = {

    "MA_FAST": 50,
    "MA_SLOW": 200,
    "MIN_RETURN_6M": 0.30,

    "ATR_WINDOW": 14,
    "ATR_PERCENTILE": 0.4,

    "BASE_LOOKBACK": 40,
    "MAX_BASE_DEPTH": 0.35,
    "MIN_BASE_WEEKS": 5,

    "TIGHT_RANGE_WEEKS": 3,
    "TIGHT_PERCENTILE": 0.3,

    "NEAR_HIGH_THRESHOLD": 0.10
}

# ======================
# DATA
# ======================

def resample_weekly(df):

    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.loc[:, ~df.columns.duplicated()]

    weekly = df.resample("W").agg({
        "Open":"first",
        "High":"max",
        "Low":"min",
        "Close":"last",
        "Volume":"sum"
    }).dropna()

    return weekly


# ======================
# ATR
# ======================

def compute_atr(df):

    high_low = df["High"] - df["Low"]
    high_close = abs(df["High"] - df["Close"].shift())
    low_close = abs(df["Low"] - df["Close"].shift())

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    return tr.rolling(PARAMS["ATR_WINDOW"]).mean()


# ======================
# TREND FILTER
# ======================

def trend_filter(df):

    df["MA50"] = df["Close"].rolling(PARAMS["MA_FAST"]).mean()
    df["MA200"] = df["Close"].rolling(PARAMS["MA_SLOW"]).mean()

    if len(df) < 200:
        return False

    price = df["Close"].iloc[-1]
    ma50 = df["MA50"].iloc[-1]
    ma200 = df["MA200"].iloc[-1]

    ret6m = df["Close"].pct_change(26).iloc[-1]

    return (
        price > ma200 and
        ma50 > ma200
        # ret6m > PARAMS["MIN_RETURN_6M"]
    )


# ======================
# ROLLING COMPRESSION
# ======================
def compression_in_window(df):

    df["ATR"] = compute_atr(df)

    atr = df["ATR"].dropna()

    if len(atr) < 20:
        return False

    recent = atr.iloc[-10:].mean()
    threshold = atr.quantile(PARAMS["ATR_PERCENTILE"])

    return recent < threshold

# ======================
# COMPRESSION
# ======================

def compression_filter(df):

    df["ATR"] = compute_atr(df)

    atr = df["ATR"].dropna()

    if len(atr) < 20:
        return False

    recent = atr.iloc[-10:].mean()
    threshold = atr.quantile(PARAMS["ATR_PERCENTILE"])

    return recent < threshold


# =========================
# ROLLING BASE WINDOW
# =========================
def find_base_windows(df):

    bases = []

    lookback = PARAMS["BASE_LOOKBACK"]

    for i in range(lookback, len(df)):

        window = df.iloc[i-lookback:i]

        high = window["High"].max()
        low = window["Low"].min()

        depth = (high - low) / high

        if depth > PARAMS["MAX_BASE_DEPTH"]:
            continue

        if len(window) < PARAMS["MIN_BASE_WEEKS"]:
            continue

        bases.append({
            "end_date": df.index[i],
            "depth": depth,
            "high": high,
            "low": low
        })

    return bases

# =======================
# COMBINED ROLLING DETECTOR
# =======================
def detect_recent_base(df):

    bases = find_base_windows(df)

    if not bases:
        return None

    latest_base = bases[-1]

    window = df.loc[:latest_base["end_date"]].tail(PARAMS["BASE_LOOKBACK"])

    if not compression_in_window(window):
        return None

    return latest_base

# ======================
# BASE STRUCTURE
# ======================

def base_structure(df):

    window = df.iloc[-PARAMS["BASE_LOOKBACK"]:]

    high = window["High"].max()
    low = window["Low"].min()

    depth = (high - low) / high

    duration = len(window)

    return (
        depth < PARAMS["MAX_BASE_DEPTH"] and
        duration >= PARAMS["MIN_BASE_WEEKS"]
    )


# ======================
# TIGHTNESS
# ======================

def tightness_filter(df):

    ranges = df["High"] - df["Low"]

    recent = ranges.iloc[-PARAMS["TIGHT_RANGE_WEEKS"]:].mean()

    threshold = ranges.quantile(PARAMS["TIGHT_PERCENTILE"])

    return recent < threshold


# ======================
# NEAR HIGH
# ======================

def near_high(df):

    high = df["High"].rolling(52).max().iloc[-1]
    price = df["Close"].iloc[-1]

    dist = abs(price - high) / high

    return dist < PARAMS["NEAR_HIGH_THRESHOLD"]


# ======================
# SCANNER
# ======================

files = glob(os.path.join(DATA_FOLDER, "*.parquet"))

trend_pass = []
compression_pass = []
base_pass = []
tight_pass = []
near_high_pass = []

for file in files:

    try:

        df = pd.read_parquet(file)
        weekly = resample_weekly(df)

        stock = os.path.basename(file).replace(".parquet","")

        if not trend_filter(weekly):
            continue

        trend_pass.append(stock)

        if not compression_filter(weekly):
            continue

        compression_pass.append(stock)

        # if not base_structure(weekly):
        #     continue
        if not detect_recent_base(weekly):
            continue

        base_pass.append(stock)

        if not tightness_filter(weekly):
            continue

        tight_pass.append(stock)

        if not near_high(weekly):
            continue

        near_high_pass.append(stock)

    except Exception as e:
        print(file, e)


# ======================
# OUTPUT
# ======================

print("\n===== PIPELINE SUMMARY =====")

print(f"Total Stocks: {len(files)}")
print(f"Trend Pass: {len(trend_pass)}")
print(f"Compression Pass: {len(compression_pass)}")
print(f"Base Pass: {len(base_pass)}")
print(f"Tightness Pass: {len(tight_pass)}")
print(f"Near High: {len(near_high_pass)}")


print("\nStocks Passing Compression (for inspection):")
print("compression pass : ", compression_pass[:50])
print("base_pass : ", base_pass[:50])
print("tight_pass : ", tight_pass[:50])
print("near_high_pass : ", near_high_pass[:50])



print("\nFinal Candidates:")
print(near_high_pass[:50])