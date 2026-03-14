import pandas as pd
import numpy as np
import os
from glob import glob

# =============================
# PARAMETERS
# =============================

PARAMS = {

    "MIN_BASE_WEEKS": 5,
    "MAX_BASE_WEEKS": 65,

    "CUP_MIN_DEPTH": 0.12,
    "CUP_MAX_DEPTH": 0.40,
    "CUP_NEAR_HIGH": 0.10,

    "DB_MAX_BOTTOM_DIFF": 0.05,

    "FLAT_MAX_DEPTH": 0.15,
    "FLAT_MIN_WEEKS": 5,
    "FLAT_MAX_WEEKS": 8,

    "VCP_MIN_CONTRACTIONS": 3,

    "ATR_WINDOW": 14
}

DATA_FOLDER = "data/daily"


# =============================
# DATA HELPERS
# =============================

def resample_weekly(df):

    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.loc[:, ~df.columns.duplicated()]

    weekly = df.resample("W").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()

    return weekly


# =============================
# UTILS
# =============================

def base_window(df):
    return df.iloc[-PARAMS["MAX_BASE_WEEKS"]:].copy()


def depth(high, low):
    return (high - low) / high


# =============================
# CUP DETECTION
# =============================

def detect_cup(df):

    window = base_window(df)

    peak_idx = window["High"].idxmax()
    peak = window.loc[peak_idx]["High"]

    after_peak = window.loc[peak_idx:]

    bottom_idx = after_peak["Low"].idxmin()
    bottom = after_peak.loc[bottom_idx]["Low"]

    d = depth(peak, bottom)

    if not (PARAMS["CUP_MIN_DEPTH"] <= d <= PARAMS["CUP_MAX_DEPTH"]):
        return None

    current = window["Close"].iloc[-1]
    near_high = abs(current - peak) / peak

    if near_high > PARAMS["CUP_NEAR_HIGH"]:
        return None

    duration = (bottom_idx - peak_idx).days / 7

    return {
        "base_type": "cup",
        "depth": round(d, 3),
        "duration": duration,
        "resistance": peak,
        "bottom": bottom
    }


# =============================
# DOUBLE BOTTOM
# =============================

def detect_double_bottom(df):

    window = base_window(df)

    lows = window["Low"].nsmallest(2)

    if len(lows) < 2:
        return None

    l1, l2 = lows.iloc[0], lows.iloc[1]

    diff = abs(l1 - l2) / max(l1, l2)

    if diff > PARAMS["DB_MAX_BOTTOM_DIFF"]:
        return None

    pivot = window["High"].max()

    return {
        "base_type": "double_bottom",
        "bottom1": l1,
        "bottom2": l2,
        "pivot": pivot
    }


# =============================
# FLAT BASE
# =============================

def detect_flat_base(df):

    window = df.iloc[-PARAMS["FLAT_MAX_WEEKS"]:]

    if len(window) < PARAMS["FLAT_MIN_WEEKS"]:
        return None

    high = window["High"].max()
    low = window["Low"].min()

    d = depth(high, low)

    if d > PARAMS["FLAT_MAX_DEPTH"]:
        return None

    return {
        "base_type": "flat_base",
        "depth": d,
        "resistance": high
    }


# =============================
# VCP DETECTION
# =============================

def detect_vcp(df):

    window = base_window(df)

    ranges = (window["High"] - window["Low"]).rolling(3).mean()

    contractions = 0

    for i in range(1, len(ranges)):
        if ranges.iloc[i] < ranges.iloc[i - 1]:
            contractions += 1

    if contractions < PARAMS["VCP_MIN_CONTRACTIONS"]:
        return None

    return {
        "base_type": "vcp",
        "contractions": contractions
    }


# =============================
# BASE CLASSIFIER
# =============================

def classify_base(df):

    checks = [
        detect_cup,
        detect_double_bottom,
        detect_flat_base,
        detect_vcp
    ]

    for fn in checks:
        res = fn(df)
        if res:
            return res

    return None


# =============================
# SCANNER
# =============================

files = glob(os.path.join(DATA_FOLDER, "*.parquet"))

results = []

for file in files:

    try:

        df = pd.read_parquet(file)
        weekly = resample_weekly(df)

        base = classify_base(weekly)

        if base:
            stock = os.path.basename(file).replace(".parquet", "")
            base["stock"] = stock
            results.append(base)

    except Exception as e:
        print(file, e)

results = pd.DataFrame(results)

print("\n===== BASE DETECTION RESULTS =====")
print(results.head(50))

print("\nBase Type Counts")
print(results["base_type"].value_counts())