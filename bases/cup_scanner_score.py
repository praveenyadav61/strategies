import pandas as pd
import numpy as np
import os
from glob import glob

# ===============================
# ======== PARAMETERS ===========
# ===============================

DATA_FOLDER = "data/market_data"   # your folder
MIN_WEEKS = 30                     # minimum base duration
MAX_WEEKS = 65                     # maximum base duration
MIN_DEPTH = 0.15                   # 15%
MAX_DEPTH = 0.40                   # 40%
NEAR_HIGH_THRESHOLD = 0.10         # within 10% of old high
ATR_WINDOW = 14
COMPRESSION_LOOKBACK = 10

# ===============================
# ===== HELPER FUNCTIONS ========
# ===============================

def resample_weekly(df):
    # df['Date'] = pd.to_datetime(df['Date'])
    # df.set_index('Date', inplace=True)

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
    atr = tr.rolling(window).mean()

    return atr


def score_cup(df):
    result = {
        "valid_structure": 0,
        "depth": np.nan,
        "duration_weeks": np.nan,
        "near_high_pct": np.nan,
        "compression_ratio": np.nan,
        "symmetry_ratio": np.nan,
        "cup_score": 0
    }

    if len(df) < MAX_WEEKS:
        return result

    window = df[-MAX_WEEKS:].copy()

    peak_idx = window['High'].idxmax()
    peak_price = window.loc[peak_idx, 'High']

    after_peak = window.loc[peak_idx:]
    if len(after_peak) < MIN_WEEKS:
        return result

    bottom_idx = after_peak['Low'].idxmin()
    bottom_price = after_peak.loc[bottom_idx, 'Low']

    depth = (peak_price - bottom_price) / peak_price
    duration = (bottom_idx - peak_idx).days / 7

    current_price = window['Close'].iloc[-1]
    near_high = abs(current_price - peak_price) / peak_price

    # Volatility
    window['ATR'] = compute_atr(window, ATR_WINDOW)
    recent_atr = window['ATR'].iloc[-COMPRESSION_LOOKBACK:]
    compression_ratio = recent_atr.mean() / window['ATR'].mean()

    # Symmetry
    left_weeks = (bottom_idx - peak_idx).days / 7
    right_weeks = (window.index[-1] - bottom_idx).days / 7
    symmetry_ratio = min(left_weeks, right_weeks) / max(left_weeks, right_weeks)

    # Save metrics
    result.update({
        "valid_structure": 1,
        "depth": depth,
        "duration_weeks": duration,
        "near_high_pct": near_high,
        "compression_ratio": compression_ratio,
        "symmetry_ratio": symmetry_ratio
    })

    # =============================
    # ===== SCORING SECTION ======
    # =============================

    score = 0

    # Depth score (ideal ~25%)
    if MIN_DEPTH <= depth <= MAX_DEPTH:
        score += 20 * (1 - abs(depth - 0.25))

    # Duration score (longer bases stronger)
    if duration >= MIN_WEEKS:
        score += min(duration / MAX_WEEKS, 1) * 15

    # Near high score
    if near_high <= NEAR_HIGH_THRESHOLD:
        score += 20 * (1 - near_high)

    # Compression score
    if compression_ratio < 1:
        score += 25 * (1 - compression_ratio)

    # Symmetry score
    score += 20 * symmetry_ratio

    result["cup_score"] = round(score, 2)

    return result

# ===============================
# ========= SCANNER =============
# ===============================
results = []
step_counts = {
    "total": 0,
    "valid_structure": 0,
    "depth_pass": 0,
    "duration_pass": 0,
    "near_high_pass": 0,
    "compression_pass": 0
}

files = glob(os.path.join(DATA_FOLDER, "*.parquet"))

for file in files:
    step_counts["total"] += 1

    try:
        df = pd.read_parquet(file)
        weekly = resample_weekly(df)
        metrics = score_cup(weekly)

        stock = os.path.basename(file).replace(".parquet", "")
        metrics["stock"] = stock

        if metrics["valid_structure"]:
            step_counts["valid_structure"] += 1

        if MIN_DEPTH <= metrics["depth"] <= MAX_DEPTH:
            step_counts["depth_pass"] += 1

        if metrics["duration_weeks"] >= MIN_WEEKS:
            step_counts["duration_pass"] += 1

        if metrics["near_high_pct"] <= NEAR_HIGH_THRESHOLD:
            step_counts["near_high_pass"] += 1

        if metrics["compression_ratio"] < 1:
            step_counts["compression_pass"] += 1

        results.append(metrics)

    except Exception as e:
        print(f"Error in {file}: {e}")

results_df = pd.DataFrame(results)
results_df = results_df.sort_values("cup_score", ascending=False)

print("\n===== STEP COUNTS =====")
for k, v in step_counts.items():
    print(f"{k}: {v}")

print("\n===== TOP CUP SCORES =====")
print(results_df.head(20))