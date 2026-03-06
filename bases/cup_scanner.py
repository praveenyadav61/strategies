import pandas as pd
import numpy as np
import os
from glob import glob

# ===============================
# ======== PARAMETERS ===========
# ===============================

DATA_FOLDER = "data/market_data"   # your folder
MIN_WEEKS = 20                     # minimum base duration 40
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

def detect_cup(df):
    if len(df) < MAX_WEEKS:
        return False
    window = df[-MAX_WEEKS:]
    
    peak_idx = window['High'].idxmax()
    peak_price = window.loc[peak_idx, 'High']

    after_peak = window.loc[peak_idx:]
    if len(after_peak) < MIN_WEEKS:
        return False

    bottom_idx = after_peak['Low'].idxmin()
    bottom_price = after_peak.loc[bottom_idx, 'Low']

    depth = (peak_price - bottom_price) / peak_price
    if not (MIN_DEPTH <= depth <= MAX_DEPTH):
        return False

    duration = (bottom_idx - peak_idx).days / 7
    if duration < MIN_WEEKS:
        return False

    current_price = window['Close'].iloc[-1]
    near_high = abs(current_price - peak_price) / peak_price
    if near_high > NEAR_HIGH_THRESHOLD:
        return False

    # Volatility compression
    window['ATR'] = compute_atr(window, ATR_WINDOW)
    recent_atr = window['ATR'].iloc[-COMPRESSION_LOOKBACK:]

    recent_mean = recent_atr.mean()
    threshold = window['ATR'].quantile(0.3)
    if recent_mean > threshold:
        return False
    
    # if recent_atr.mean() > window['ATR'].mean():
    #     return False

    return True


# ===============================
# ========= SCANNER =============
# ===============================

files = glob(os.path.join(DATA_FOLDER, "*.parquet"))
cup_stocks = []

for file in files:
    try:
        df = pd.read_parquet(file)
        weekly = resample_weekly(df)

        if detect_cup(weekly):
            stock = os.path.basename(file).replace(".parquet", "")
            cup_stocks.append(stock)

    except Exception as e:
        print(f"Error in {file}: {e}")

print("\n===== CUP PATTERN STOCKS =====")
print(f"Total Found: {len(cup_stocks)}")
print(cup_stocks)