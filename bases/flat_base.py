import numpy as np

def detect_weekly_flat_base(df):

    df = df.copy()

    base_weeks = 8

    # Rolling high & low for base
    df["base_high"] = df["High"].rolling(base_weeks).max()
    df["base_low"] = df["Low"].rolling(base_weeks).min()

    # Range percentage
    df["range_pct"] = (df["base_high"] - df["base_low"]) / df["base_low"]

    # Tight range condition
    df["tight_range"] = df["range_pct"] < 0.15

    # 52-week high
    df["high_52w"] = df["High"].rolling(52).max()

    # Near 52-week high
    df["near_high"] = (
        (df["high_52w"] - df["Close"]) / df["high_52w"]
    ) < 0.05

    # Final flat base signal
    df["flat_base"] = df["tight_range"] & df["near_high"]

    return df