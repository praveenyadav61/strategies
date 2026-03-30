import sys
import streamlit as st
import pandas as pd
import numpy as np
import os
import plotly.graph_objects as go
from plotly.subplots import make_subplots
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from data_layer.data_engine import DataEngine
data_path = '../data/daily/'
if not os.path.exists(data_path):
    data_path = 'data/daily/'
#######DEFAULT PARAMETERS#######
default_params = {
        'MIN_WEEKS': 8,
        'MAX_WEEKS': 52,
        'MIN_DEPTH': 15 / 100.0,
        'MAX_DEPTH': 60 / 100.0,
        'RECOVERY_MIN': 60 / 100.0,
        'RECOVERY_MAX': 120 / 100.0,
        'ATR_WINDOW': 14,
        'COMPRESSION_LOOKBACK': 10,
    }
# ===============================
# For QC and get stocks at each stage of the scan
cup_stocks = []
dma_filtered_symbols = []
min_week_stocks=[]
min_depth_stocks=[]
duration_stocks=[]
near_high_stocks=[]
# ===============================

def calculate_cup_metrics(df, params, symbol):
    df = df.copy()
    df = df.loc[:,~df.columns.duplicated()]
    
    # Add MAs for Uptrend condition from base_formation
    df['ma_10'] = df['Close'].rolling(10).mean()
    df['ma_40'] = df['Close'].rolling(40).mean()

    # Add Volume MAs for plotting
    df['volume_ma_10'] = df['Volume'].rolling(10).mean()
    df['volume_ma_20'] = df['Volume'].rolling(20).mean()

    # ATR Calculation from cup_scanner.py
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(params['ATR_WINDOW']).mean()
    
    return df


def get_tight_close_groups(after_peak, window=3, tolerance=0.01):
    """
    Detect contiguous tight-close groups on the post-peak section.

    A group begins when a rolling `window` of closes stays within `tolerance`,
    and expands to cover all weeks involved in that contiguous tight block.
    """
    empty_points = after_peak.iloc[0:0].copy()
    if len(after_peak) < window:
        return {
            "tight_closes_ok": False,
            "num_tight_groups": 0,
            "tight_points": empty_points,
            "block_ranges": [],
        }

    closes = after_peak["Close"]
    rolling_max = closes.rolling(window=window).max()
    rolling_min = closes.rolling(window=window).min()
    is_tight_window = (rolling_max - rolling_min) / rolling_min.replace(0, np.nan) <= tolerance
    is_tight_window = is_tight_window.fillna(False)

    if not is_tight_window.any():
        return {
            "tight_closes_ok": False,
            "num_tight_groups": 0,
            "tight_points": empty_points,
            "block_ranges": [],
        }

    block_starts = is_tight_window & ~is_tight_window.shift(1).fillna(False)
    block_ids = block_starts.cumsum().where(is_tight_window)

    tight_week_mask = pd.Series(False, index=after_peak.index)
    block_ranges = []

    for block_id in block_ids.dropna().unique():
        block_index = block_ids[block_ids == block_id].index
        block_start_label = block_index[0]
        block_end_label = block_index[-1]

        block_start_pos = max(0, after_peak.index.get_loc(block_start_label) - (window - 1))
        block_end_pos = after_peak.index.get_loc(block_end_label)
        tight_week_mask.iloc[block_start_pos:block_end_pos + 1] = True

        block_ranges.append(
            {
                "block_id": int(block_id),
                "start_idx": after_peak.index[block_start_pos],
                "end_idx": after_peak.index[block_end_pos],
            }
        )

    tight_points = after_peak.loc[tight_week_mask].copy()

    return {
        "tight_closes_ok": True,
        "num_tight_groups": int(len(block_ranges)),
        "tight_points": tight_points,
        "block_ranges": block_ranges,
    }

# ===============================
# MAIN SCAN FUNCTION
# ===============================
def run_full_scan_base(params=default_params):
    all_files = [f for f in os.listdir(data_path) if f.endswith('.parquet')]
    all_stocks_conditions = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, filename in enumerate(all_files):
        symbol = filename.replace('.parquet', '')
        status_text.text(f"Scanning {symbol} ({i+1}/{len(all_files)})")
        
        # try:
        # # ---------- FAST FILTER READ ----------
        data_engine = DataEngine()
        df_tail = data_engine.get_symbol(symbol).tail(250)

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

        if not (last_close > last_ema200 and last_ema50 > last_ema200):
            # print(f"Skipping {symbol} due to DMA filter")
            continue
        # ---------- STORE FILTERED SYMBOL ----------
        dma_filtered_symbols.append(symbol)
        df = data_engine.get_symbol(symbol)
        # Resample to weekly, as per cup_scanner.py
        weekly_df = df.resample('W').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()

        if len(weekly_df) < params['MAX_WEEKS']:
            continue

        weekly_df = calculate_cup_metrics(weekly_df, params,symbol)
        
        conditions,metrics = check_cup_conditions(weekly_df, params,symbol)

        if conditions:
            # Check if all conditions except the last one ("Volatility Compressed") are True.
            # This allows us to see stocks that are setting up but haven't yet passed the final test.
            all_but_last_conditions = list(conditions.values())[:-1]
            if all(all_but_last_conditions):
                stock_condition = {'Symbol': symbol}
                stock_condition.update(metrics)
                stock_condition.update(conditions)
                all_stocks_conditions.append(stock_condition)
                cup_stocks.append(symbol)
        # except Exception as e:
        #     st.error(f"Could not process {symbol}: {e}")
        
        progress_bar.progress((i + 1) / len(all_files))
    status_text.text("Scan Complete!")
    return pd.DataFrame(all_stocks_conditions)

# def calculate_weekly_metrics(df):

#     df = df.copy()

#     # 20W and 40W moving averages (more relevant for weekly)
#     df['ma_20'] = df['Close'].rolling(10).mean()
#     df['ma_40'] = df['Close'].rolling(40).mean()

#     # 52-week high
#     df['52w_high'] = df['Close'].rolling(52).max()

#     # Volume moving averages
#     df['volume_ma_10'] = df['Volume'].rolling(10).mean()
#     df['volume_ma_20'] = df['Volume'].rolling(20).mean()

#     #RSI Calculation
#     delta = df['Close'].diff()
#     gain = (delta.where(delta > 0, 0)).ewm(com=13, adjust=False).mean() # 14 period RSI
#     loss = (-delta.where(delta < 0, 0)).ewm(com=13, adjust=False).mean()
#     rs = gain / loss
#     df['rsi_14'] = 100 - (100 / (1 + rs))

#     return df


# ===============================
# CUP DETECTION LOGIC
# ===============================
def check_cup_conditions(df, params, symbol):
    MIN_WEEKS = params['MIN_WEEKS']
    MAX_WEEKS = params['MAX_WEEKS']
    MIN_DEPTH = params['MIN_DEPTH']
    MAX_DEPTH = params['MAX_DEPTH']
    RECOVERY_MIN = params['RECOVERY_MIN']
    RECOVERY_MAX = params['RECOVERY_MAX']
    COMPRESSION_LOOKBACK = params['COMPRESSION_LOOKBACK']
    if len(df) < MAX_WEEKS:
        return None, None

    latest = df.iloc[-1]
    window = df[-MAX_WEEKS:].copy()
    peak_search_window = window.iloc[:-MIN_WEEKS]
    peak_idx = peak_search_window['High'].idxmax()
    peak_price = window.loc[peak_idx, 'High']
    after_peak = window.loc[peak_idx:]
    if len(after_peak) < MIN_WEEKS:
        return None, None
    #################################
    min_week_stocks.append(symbol)
    #################################
    bottom_idx = after_peak['Low'].idxmin()
    bottom_price = after_peak.loc[bottom_idx, 'Low']

    # Condition 1: Depth (from base_formation)
    depth = (peak_price - bottom_price) / peak_price if peak_price > 0 else 0
    depth_ok = MIN_DEPTH <= depth <= MAX_DEPTH
    if not (MIN_DEPTH <= depth <= MAX_DEPTH):
        # print(f"Skipping {symbol} due to depth filter")
        return None, None
    #################################
    min_depth_stocks.append(symbol)
    #################################
    # Condition 2: Duration (from base_formation)
    duration = (bottom_idx - peak_idx).days / 7
    duration_ok = duration >= MIN_WEEKS
    if not duration_ok:
        # print(f"Skipping {symbol} due to duration filter")
        return None, None
    #################################
    duration_stocks.append(symbol)
    #################################
    # Condition from base_formation: Rounded Bottom
    near_low_weeks = after_peak[
        after_peak['Close'] <= bottom_price * 1.05
    ]
    rounded_condition = len(near_low_weeks) >= 3

    tight_group_info = get_tight_close_groups(after_peak, window=3, tolerance=0.01)
    tight_closes_ok = tight_group_info["tight_closes_ok"]
    num_tight_groups = tight_group_info["num_tight_groups"]

    # Condition 3: Recovery (from base_formation)
    current_price = window['Close'].iloc[-1]
    recovery_level = (current_price - bottom_price) / (peak_price - bottom_price) if (peak_price - bottom_price) > 0 else 0
    recovery_ok = RECOVERY_MIN <= recovery_level <= RECOVERY_MAX
    if not recovery_ok:
        # print(f"Skipping {symbol} and {current_price, recovery_level} due to recovery filter")
        return None, None
    #################################
    near_high_stocks.append(symbol)
    #################################
    # Condition 4: Volatility Compression (from original sm_bg.py, kept for reference)
    recent_atr = window['atr'].iloc[-COMPRESSION_LOOKBACK:]
    compression_ok = False
    if not recent_atr.empty and not pd.isna(window['atr'].quantile(0.3)):
        recent_mean = recent_atr.mean()
        threshold = window['atr'].quantile(0.3)
        if recent_mean < threshold:
            compression_ok = True
    # fetch RSI
    # df_rsi=calculate_weekly_metrics(df)
    # latest_rsi = df_rsi['rsi_14'].iloc[-1]
    conditions = {
        f"Depth ({MIN_DEPTH:.0%}-{MAX_DEPTH:.0%})": depth_ok,
        f"Duration (>{MIN_WEEKS}w)": duration_ok,
        # "3-Week Tight Close": tight_closes_ok,
        # "Rounded Bottom": rounded_condition,
        f"Recovery ({RECOVERY_MIN:.0%}-{RECOVERY_MAX:.0%})": recovery_ok,
        "Volatility Compressed": compression_ok 
    }
    metrics = {
        "Depth": depth,
        "Recovery": recovery_level,
        "Tight Groups": num_tight_groups
    }
    # "RSI_14 (w)": latest_rsi['rsi_14']}
    
    return conditions, metrics

def plot_cup_formation(df_weekly, symbol, params):
    """
    Generates a Plotly chart to visualize a cup formation on weekly data.
    This function is designed to be consistent with the scanner logic in this file.
    """
    df = calculate_cup_metrics(df_weekly.copy(), params, symbol)

    # Add RSI calculation here for plotting purposes
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(com=13, adjust=False).mean() # 14 period RSI
    loss = (-delta.where(delta < 0, 0)).ewm(com=13, adjust=False).mean()
    rs = gain / loss
    df['rsi_14'] = 100 - (100 / (1 + rs))

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                          vertical_spacing=0.05,
                          row_heights=[0.6, 0.2, 0.2])

    # 1. Price chart with Moving Averages
    fig.add_trace(go.Candlestick(x=df.index,
                    open=df['Open'],
                    high=df['High'],
                    low=df['Low'],
                    close=df['Close'],
                    name='Weekly Price'),
                    row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['ma_10'], name='10W MA', line=dict(color='orange')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['ma_40'], name='40W MA', line=dict(color='blue')), row=1, col=1)

    # 2. Logic to find and draw the cup pattern for visualization
    # This mirrors the logic in `check_cup_conditions` to ensure the plot is accurate.
    MAX_WEEKS = params['MAX_WEEKS']
    MIN_WEEKS = params['MIN_WEEKS']
    if len(df) >= MAX_WEEKS:
        window = df[-MAX_WEEKS:].copy()
        peak_search_window = window.iloc[:-MIN_WEEKS]

        peak_idx = peak_search_window['High'].idxmax()
        peak_price = window.loc[peak_idx, 'High']

        after_peak = window.loc[peak_idx:]

        if len(after_peak) > 1:
            bottom_idx = after_peak['Low'].idxmin()
            bottom_price = after_peak.loc[bottom_idx, 'Low']

                # Draw horizontal line for the peak (resistance)
            fig.add_shape(type="line",
                x0=peak_idx, y0=peak_price, x1=df.index[-1], y1=peak_price,
                line=dict(color="Red", width=2, dash="dash"), row=1, col=1)
            fig.add_annotation(x=peak_idx, y=peak_price, text="Peak", showarrow=True, arrowhead=1, row=1, col=1)
            fig.add_annotation(x=bottom_idx, y=bottom_price, text="Low", showarrow=True, arrowhead=1, yshift=-10, row=1, col=1)

    # 3. Volume chart with Moving Averages
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='Volume', marker_color='lightgrey'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['volume_ma_10'], name='10W Vol MA', line=dict(color='purple', width=1)), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['volume_ma_20'], name='20W Vol MA', line=dict(color='green', width=1)), row=2, col=1)

    # 4. RSI chart
    fig.add_trace(go.Scatter(x=df.index, y=df['rsi_14'], name='RSI (14)'), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="red", row=3, col=1)

    fig.update_layout(
        title=f'{symbol} - Cup Formation Analysis (Weekly)',
        xaxis_rangeslider_visible=False,
        height=800,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_yaxes(title_text="RSI", row=3, col=1)

    return fig

if __name__ == "__main__":
    # This block will only run when the script is executed directly,
    # not when it's imported by another script like home.py.
    run_full_scan_base()
    print("\n===== CUP PATTERN STOCKS =====")
    print(f"Total Found: {len(cup_stocks)}")
    print(cup_stocks)
    #########################################################
    print("dma_filtered_stocks :",len(dma_filtered_symbols))
    print("min_week_stocks :",len(min_week_stocks))
    print("min_depth_stocks :",len(min_depth_stocks))
    print("duration_stocks :",len(duration_stocks))
    print("near_high_stocks :",len(near_high_stocks))

    #########################################################
