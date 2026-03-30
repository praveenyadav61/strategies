import pandas as pd
import numpy as np
import os
from glob import glob

# ===============================
# ======== PARAMETERS ===========
# ===============================

DATA_FOLDER = "data/daily"   # your folder
MIN_WEEKS = 8                      # minimum base duration 40
MAX_WEEKS = 104                     # maximum base duration
MIN_DEPTH = 0.15                   # 15%
MAX_DEPTH = 0.60                   # 40%
NEAR_HIGH_THRESHOLD = 0.6          # above 60% of depth
ATR_WINDOW = 14
COMPRESSION_LOOKBACK = 10


################GLOBAL VARIABLES################
min_week_stocks=[]
min_depth_stocks=[]
duration_stocks=[]
near_high_stocks=[]

################################################

# ===============================
# ===== HELPER FUNCTIONS ========
# ===============================

def dma_filter(df):

    ema200 = df["close"].ewm(span=200, adjust=False).mean()
    ema50 = df["close"].ewm(span=50, adjust=False).mean()

    last_close = df["close"].iloc[-1]
    last_ema200 = ema200.iloc[-1]
    last_ema50 = ema50.iloc[-1]

    return (last_close > last_ema200) and (last_ema50 > last_ema200)


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

def detect_cup(df,stock):
    print("yes")
    if len(df) < MAX_WEEKS:
        return False
    window = df[-MAX_WEEKS:]
    print("last closing price :",window['Close'].iloc[-1])
    # Peak must occur before the last MIN_WEEKS
    peak_search_window = window.iloc[:-MIN_WEEKS]

    peak_idx = peak_search_window['High'].idxmax()
    peak_price = window.loc[peak_idx, 'High']

    after_peak = window.loc[peak_idx:]
    print(f"{stock} - Peak at {peak_price} on {peak_idx.date()}, Weeks after peak: {len(after_peak)}")
    if len(after_peak) < MIN_WEEKS:
        return False
    #################################
    min_week_stocks.append(stock)
    #################################
    bottom_idx = after_peak['Low'].idxmin()
    bottom_price = after_peak.loc[bottom_idx, 'Low']

    depth = (peak_price - bottom_price) / peak_price
    if not (MIN_DEPTH <= depth <= MAX_DEPTH):
        return False
    #################################
    min_depth_stocks.append(stock)
    #################################
    duration = (bottom_idx - peak_idx).days / 7
    if duration < MIN_WEEKS:
        return False
    #################################
    duration_stocks.append(stock)
    #################################

    current_price = window['Close'].iloc[-1]
    near_high = abs(current_price - peak_price) / (peak_price - bottom_price)
    if near_high > NEAR_HIGH_THRESHOLD:
        return False
    #################################
    near_high_stocks.append(stock)
    #################################

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
        # print(f"Processing {stock} - Last 5 rows:\n{df_tail.tail()}\n")
        df_tail.index = pd.to_datetime(df_tail.index)
        df_tail = df_tail.sort_index()

        if isinstance(df_tail.columns, pd.MultiIndex):
            df_tail.columns = df_tail.columns.get_level_values(0)

        df_tail = df_tail.loc[:, ~df_tail.columns.duplicated()]

        close = df_tail["Close"]

        ema200 = close.ewm(span=200, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()

        last_close = close.iloc[-1]
        last_ema200 = ema200.iloc[-1]
        last_ema50 = ema50.iloc[-1]
        # print("Checking", stock, "Close:", last_close, "EMA200:", last_ema200, "EMA50:", last_ema50)

        if not (last_close > last_ema200 and last_ema50 > last_ema200):
            continue

        # ---------- STORE FILTERED SYMBOL ----------
        dma_filtered_symbols.append(stock)

        # ---------- FULL DATA READ ----------
        df = pd.read_parquet(file)

        weekly = resample_weekly(df)

        if detect_cup(weekly,stock):
            cup_stocks.append(stock)

    except Exception as e:
        print(f"Error in {file}: {e}")


# ---------- SAVE FILTERED SYMBOLS ----------
with open("dma_filtered_symbols.txt", "w") as f:
    for s in dma_filtered_symbols:
        f.write(s + "\n")


print("\n===== DMA FILTER PASSED =====")
print(f"Total: {len(dma_filtered_symbols)}")

#########################################################
print("dma_filtered_stocks :",len(dma_filtered_symbols))
print("min_week_stocks :",len(min_week_stocks))
print("min_depth_stocks :",len(min_depth_stocks))
print("duration_stocks :",len(duration_stocks))
print("near_high_stocks :",len(near_high_stocks))

#########################################################


print("\n===== CUP PATTERN STOCKS =====")
print(f"Total Found: {len(cup_stocks)}")
print(cup_stocks)



#['ABB.NS', 'ANANDRATHI.NS', 'AUROPHARMA.NS', 'BIOCON.NS', 'IPCALAB.NS', 'KTKBANK.NS', 'NATCOPHARM.NS', 'SONACOMS.NS', 'TIMKEN.NS', 'TORNTPOWER.NS', 'WHEELS.NS']
#['ABB.NS', 'ANANDRATHI.NS', 'ARVIND.NS', 'AUROPHARMA.NS', 'BIOCON.NS', 'BLUESTARCO.NS', 'CHENNPETRO.NS', 'FLAIR.NS', 'GMRAIRPORT.NS', 'GODAVARIB.NS', 'IPCALAB.NS', 'KINGFA.NS', 'KTKBANK.NS', 'MACPOWER.NS', 'NATCOPHARM.NS', 'NLCINDIA.NS', 'PKTEA.NS', 'PREMIERPOL.NS', 'PRIVISCL.NS', 'RISHABH.NS', 'SATIN.NS', 'SKYGOLD.NS', 'SONACOMS.NS', 'SUKHJITS.NS', 'SUNTV.NS', 'SYRMA.NS', 'TIMKEN.NS', 'TORNTPOWER.NS', 'TRIVENI.NS', 'TVSHLTD.NS', 'UNIPARTS.NS', 'WHEELS.NS']
#['AARTIIND.NS', 'ANANDRATHI.NS', 'GRWRHITECH.NS', 'IPCALAB.NS', 'NLCINDIA.NS', 'PFC.NS', 'POWERGRID.NS', 'PREMIERPOL.NS', 'SKYGOLD.NS', 'SONACOMS.NS', 'TIMKEN.NS', 'TORNTPOWER.NS', 'WHEELS.NS']