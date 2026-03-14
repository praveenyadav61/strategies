import pandas as pd
import numpy as np
import os
from glob import glob

# ===============================
# ======== PARAMETERS ===========
# ===============================

DATA_FOLDER = "data/daily"   # your folder
MIN_WEEKS = 8                      # minimum base duration 40
MAX_WEEKS = 52                     # maximum base duration
MIN_DEPTH = 0.15                   # 15%
MAX_DEPTH = 0.60                   # 40%
NEAR_HIGH_THRESHOLD = 0.2          # above 60% of depth
ATR_WINDOW = 14
COMPRESSION_LOOKBACK = 10

# ===============================
# ===== HELPER FUNCTIONS ========
# ===============================

def dma_filter(df):

    sma200 = df["close"].rolling(200).mean()
    sma50 = df["close"].rolling(50).mean()

    last_close = df["close"].iloc[-1]
    last_sma200 = sma200.iloc[-1]
    last_sma50 = sma50.iloc[-1]

    return (last_close > last_sma200) and (last_sma50 > last_sma200)


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
    near_high = abs(current_price - peak_price) / (peak_price - bottom_price)
    if near_high > NEAR_HIGH_THRESHOLD:
        return False

    # Volatility compression
    # window['ATR'] = compute_atr(window, ATR_WINDOW)
    # recent_atr = window['ATR'].iloc[-COMPRESSION_LOOKBACK:]

    # recent_mean = recent_atr.mean()
    # threshold = window['ATR'].quantile(0.3)
    # if recent_mean > threshold:
    #     return False
    
    # if recent_atr.mean() > window['ATR'].mean():
    #     return False

    return True


# ===============================
# ========= SCANNER =============
# ===============================

files = glob(os.path.join(DATA_FOLDER, "*.parquet"))

cup_stocks = []
dma_filtered_symbols = []

for file in files:
    try:
        stock = os.path.basename(file).replace(".parquet", "")

        # ---------- FAST FILTER READ ----------
        df_tail = pd.read_parquet(file).tail(250)

        df_tail.index = pd.to_datetime(df_tail.index)
        df_tail = df_tail.sort_index()

        if isinstance(df_tail.columns, pd.MultiIndex):
            df_tail.columns = df_tail.columns.get_level_values(0)

        df_tail = df_tail.loc[:, ~df_tail.columns.duplicated()]

        close = df_tail["Close"]

        sma200 = close.rolling(200).mean()
        sma50 = close.rolling(50).mean()

        last_close = close.iloc[-1]
        last_sma200 = sma200.iloc[-1]
        last_sma50 = sma50.iloc[-1]

        if not (last_close > last_sma200 and last_sma50 > last_sma200):
            continue

        # ---------- STORE FILTERED SYMBOL ----------
        dma_filtered_symbols.append(stock)

        # ---------- FULL DATA READ ----------
        df = pd.read_parquet(file)

        weekly = resample_weekly(df)

        if detect_cup(weekly):
            cup_stocks.append(stock)

    except Exception as e:
        print(f"Error in {file}: {e}")


# ---------- SAVE FILTERED SYMBOLS ----------
with open("dma_filtered_symbols.txt", "w") as f:
    for s in dma_filtered_symbols:
        f.write(s + "\n")


print("\n===== DMA FILTER PASSED =====")
print(f"Total: {len(dma_filtered_symbols)}")
# print(dma_filtered_symbols)

print("\n===== CUP PATTERN STOCKS =====")
print(f"Total Found: {len(cup_stocks)}")
print(cup_stocks)



#['ABB.NS', 'ANANDRATHI.NS', 'AUROPHARMA.NS', 'BIOCON.NS', 'IPCALAB.NS', 'KTKBANK.NS', 'NATCOPHARM.NS', 'SONACOMS.NS', 'TIMKEN.NS', 'TORNTPOWER.NS', 'WHEELS.NS']
#['ABB.NS', 'ANANDRATHI.NS', 'ARVIND.NS', 'AUROPHARMA.NS', 'BIOCON.NS', 'BLUESTARCO.NS', 'CHENNPETRO.NS', 'FLAIR.NS', 'GMRAIRPORT.NS', 'GODAVARIB.NS', 'IPCALAB.NS', 'KINGFA.NS', 'KTKBANK.NS', 'MACPOWER.NS', 'NATCOPHARM.NS', 'NLCINDIA.NS', 'PKTEA.NS', 'PREMIERPOL.NS', 'PRIVISCL.NS', 'RISHABH.NS', 'SATIN.NS', 'SKYGOLD.NS', 'SONACOMS.NS', 'SUKHJITS.NS', 'SUNTV.NS', 'SYRMA.NS', 'TIMKEN.NS', 'TORNTPOWER.NS', 'TRIVENI.NS', 'TVSHLTD.NS', 'UNIPARTS.NS', 'WHEELS.NS']
#['AARTIIND.NS', 'ANANDRATHI.NS', 'GRWRHITECH.NS', 'IPCALAB.NS', 'NLCINDIA.NS', 'PFC.NS', 'POWERGRID.NS', 'PREMIERPOL.NS', 'SKYGOLD.NS', 'SONACOMS.NS', 'TIMKEN.NS', 'TORNTPOWER.NS', 'WHEELS.NS']