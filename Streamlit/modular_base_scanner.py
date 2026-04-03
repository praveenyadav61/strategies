import sys
import os
import logging
import pandas as pd
import numpy as np

from datetime import datetime

# ---------------- PATH SETUP ----------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_layer.data_engine import DataEngine

# ---------------- CONFIG ----------------
data_path = '../data/daily/'
if not os.path.exists(data_path):
    data_path = 'data/daily/'

DEFAULT_PARAMS = {
    'MIN_WEEKS': 8,
    'MAX_WEEKS': 52,
    'MIN_DEPTH': 0.15,
    'MAX_DEPTH': 0.40,
    'RECOVERY_MIN': 0.40,
    'RECOVERY_MAX': 1.20,
    'ATR_WINDOW': 14,
    'COMPRESSION_LOOKBACK': 10,
}

# ---------------- LOGGER ----------------
def get_logger(debug=False):
    level = logging.DEBUG if debug else logging.ERROR
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    return logging.getLogger("cup_scanner")

# ---------------- STATS ----------------
class ScanStats:
    def __init__(self):
        self.dma_filtered = []
        self.min_depth = []
        self.duration = []
        self.near_high = []
        self.prior_uptrend = []
        self.pivot = []

# ---------------- INDICATORS ----------------
def calculate_cup_metrics(df, params):
    df = df.copy()

    df['ma_10'] = df['Close'].rolling(10).mean()
    df['ma_40'] = df['Close'].rolling(40).mean()

    df['volume_ma_10'] = df['Volume'].rolling(10).mean()
    df['volume_ma_20'] = df['Volume'].rolling(20).mean()

    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(params['ATR_WINDOW']).mean()

    return df

# ---------------- HELPERS ----------------
def has_prior_uptrend(df, base_start_idx, left_high, bottom_price):
    window = df.iloc[max(0, base_start_idx - 12):base_start_idx]

    if len(window) < 2:
        return False

    depth_pct = (left_high - bottom_price) / left_high
    min_return = max(0.25, 1.5 * depth_pct)

    start_price = window["Low"].min()
    ret = (left_high - start_price) / start_price

    return ret >= min_return


def find_pivot(df, left_high, bottom_idx, bottom_price, logger=None):
    pivot = None
    pivot_idx = None

    for i in range(bottom_idx + 1, len(df) - 4):
        curr_high = df.iloc[i]["High"]

        if curr_high < left_high * 0.8:
            continue

        if not (curr_high > df.iloc[i-1]["High"] and curr_high > df.iloc[i+1]["High"]):
            continue

        future_lows = df.iloc[i+1:i+5]["Low"]
        drop = (curr_high - future_lows.min()) / curr_high

        if drop >= 0.05:
            pivot = curr_high
            pivot_idx = i

    if logger:
        logger.debug(f"Pivot: {pivot} at idx {pivot_idx}")

    return pivot, pivot_idx

# ---------------- CORE LOGIC ----------------
def check_cup_conditions(df, params, symbol, stats, logger):

    try:
        window = df[-params['MAX_WEEKS']:]

        peak_idx = window.iloc[:-params['MIN_WEEKS']]['High'].idxmax()
        peak_price = window.loc[peak_idx, 'High']

        after_peak = window.loc[peak_idx:]
        bottom_idx = after_peak['Low'].idxmin()
        bottom_price = after_peak.loc[bottom_idx, 'Low']

        # Depth
        depth = (peak_price - bottom_price) / peak_price
        if not (params['MIN_DEPTH'] <= depth <= params['MAX_DEPTH']):
            return None
        stats.min_depth.append(symbol)

        # Duration
        duration = (bottom_idx - peak_idx).days / 7
        if duration < params['MIN_WEEKS']:
            return None
        stats.duration.append(symbol)

        # Recovery
        recovery = (window['Close'].iloc[-1] - bottom_price) / (peak_price - bottom_price)
        if not (params['RECOVERY_MIN'] <= recovery <= params['RECOVERY_MAX']):
            return None
        stats.near_high.append(symbol)

        # Compression (ATR based)
        atr = window['atr']
        compression = atr.iloc[-params['COMPRESSION_LOOKBACK']:].mean() < atr.quantile(0.3)

        # 🔥 Tight Closing (ADDED BACK)
        close_window = window['Close'].iloc[-5:]
        tight_range = (close_window.max() - close_window.min()) / close_window.mean()
        tight_groups = int(tight_range < 0.05)   # 5% band

        # Prior uptrend
        bottom_idx_i = df.index.get_loc(bottom_idx)
        peak_idx_i = df.index.get_loc(peak_idx)

        prior_uptrend = has_prior_uptrend(df, peak_idx_i, peak_price, bottom_price)
        if prior_uptrend:
            stats.prior_uptrend.append(symbol)

        # Pivot
        pivot, _ = find_pivot(window, peak_price, bottom_idx_i, bottom_price, logger)
        if pivot:
            stats.pivot.append(symbol)

        # ✅ FINAL FLAT RETURN
        return {
            "Symbol": symbol,
            "Depth": float(depth),
            "Recovery": float(recovery),
            "Tight Groups": tight_groups,   # ✅ restored
            "compression": bool(compression),
            "prior_uptrend": bool(prior_uptrend),
            "pivot": bool(pivot is not None),
            "pivot_price": float(pivot) if pivot else None
        }

    except Exception as e:
        logger.debug(f"{symbol} failed in conditions: {e}")
        return None

# ---------------- SCANNER ----------------
class CupScanner:

    def __init__(self, params, debug=False):
        self.params = params
        self.logger = get_logger(debug)
        self.stats = ScanStats()
        self.data_engine = DataEngine()

    def scan_symbol(self, symbol):
        try:
            df = self.data_engine.get_symbol(symbol).tail(250)

            df.index = pd.to_datetime(df.index)
            df = df.sort_index()

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.loc[:, ~df.columns.duplicated()]

            # DMA FILTER
            close = df["Close"]
            ema200 = close.ewm(span=200).mean()
            ema50 = close.ewm(span=50).mean()

            if not (close.iloc[-1] > ema200.iloc[-1] and ema50.iloc[-1] > ema200.iloc[-1]):
                return None

            self.stats.dma_filtered.append(symbol)

            weekly = df.resample('W').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()

            if len(weekly) < self.params['MAX_WEEKS']:
                return None

            weekly = calculate_cup_metrics(weekly, self.params)

            return check_cup_conditions(
                weekly, self.params, symbol, self.stats, self.logger
            )

        except Exception as e:
            self.logger.debug(f"{symbol} failed: {e}")

        return None

    def run_scan(self):
        all_files = [f for f in os.listdir(data_path) if f.endswith('.parquet')]

        results = []

        for file in all_files:
            symbol = file.replace('.parquet', '')
            res = self.scan_symbol(symbol)

            if res:
                results.append(res)

        df = pd.DataFrame(results)

        if not df.empty:
            df = df.reset_index(drop=True)

        return df

# ---------------- MAIN ----------------
if __name__ == "__main__":

    DEBUG = True   # 🔥 toggle here

    scanner = CupScanner(DEFAULT_PARAMS, debug=DEBUG)

    df = scanner.run_scan()
    
    print("\n===== RESULTS =====")
    print("Total Found:", len(df))
    print(df.head(20))

    print("\n===== STATS =====")
    print("DMA filtered:", len(scanner.stats.dma_filtered))
    print("Min depth:", len(scanner.stats.min_depth))
    print("Duration:", len(scanner.stats.duration))
    print("Near high:", len(scanner.stats.near_high))
    print("Prior uptrend:", len(scanner.stats.prior_uptrend))
    print("Pivot:", len(scanner.stats.pivot))