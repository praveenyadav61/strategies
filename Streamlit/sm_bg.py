import streamlit as st
import pandas as pd
import numpy as np
import os
import sys
import plotly.graph_objects as go
from plotly.subplots import make_subplots
# Ensure project-root imports work when this file is executed directly.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from data_layer.data_engine import DataEngine

#######DEFAULT PARAMETERS#######
default_params = {
        'MIN_WEEKS': 8,
        'MAX_WEEKS': 52,
        'MIN_DEPTH': 15 / 100.0,
        'MAX_DEPTH': 60 / 100.0,
        'RECOVERY_MIN': 65 / 100.0,
        'RECOVERY_MAX': 110 / 100.0,
        'ATR_WINDOW': 14,
        'COMPRESSION_LOOKBACK': 10,
    }


data_path = '../data/test_data/'
# Corrected path for Streamlit execution context
if not os.path.exists(data_path):
    data_path = 'data/test_data/'
def run_full_scan(params=default_params):
    all_files = [f for f in os.listdir(data_path) if f.endswith('.parquet')]
    all_stocks_conditions = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, filename in enumerate(all_files):
        symbol = filename.replace('.parquet', '')
        status_text.text(f"Scanning {symbol} ({i+1}/{len(all_files)})")
        
        try:
        # # ---------- FAST FILTER READ ----------
            data_engine = DataEngine()
            df_tail = data_engine.get_symbol(symbol).tail(250)

            df_tail.index = pd.to_datetime(df_tail.index)
            df_tail = df_tail.sort_index()

            if isinstance(df_tail.columns, pd.MultiIndex):
                df_tail.columns = df_tail.columns.get_level_values(0)

            df_tail = df_tail.loc[:, ~df_tail.columns.duplicated()]

            close = df_tail["Close"]

            ema200 = df["close"].ewm(span=200, adjust=False).mean()
            ema50 = df["close"].ewm(span=50, adjust=False).mean()

            last_close = close.iloc[-1]
            last_ema200 = ema200.iloc[-1]
            last_ema50 = ema50.iloc[-1]
            print(f"Processing {symbol}: Last Close={last_close}, EMA200={last_ema200}, EMA50={last_ema50}")
            if not (last_close > last_ema200 and last_ema50 > last_ema200):
                print(f"Skipping {symbol} due to DMA filter")
                continue
            data_engine = DataEngine()
            df = data_engine.get_symbol(symbol)
            # Resample to weekly, as per cup_scanner.py
            weekly_df = df.resample('W').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna()

            if len(weekly_df) < params['MAX_WEEKS']:
                continue

            weekly_df = calculate_cup_metrics(weekly_df, params)
            
            conditions = check_cup_conditions(weekly_df, params)

            if conditions:
                # Check if all conditions except the last one ("Volatility Compressed") are True.
                # This allows us to see stocks that are setting up but haven't yet passed the final test.
                all_but_last_conditions = list(conditions.values())[:-1]
                if all(all_but_last_conditions):
                    stock_condition = {'Symbol': symbol}
                    stock_condition.update(conditions)
                    all_stocks_conditions.append(stock_condition)
        except Exception as e:
            st.error(f"Could not process {symbol}: {e}")
        
        progress_bar.progress((i + 1) / len(all_files))
    status_text.text("Scan Complete!")
    print(f"Found {len(all_stocks_conditions)} stocks meeting the conditions.")
    print("Sample results:", all_stocks_conditions)
    return pd.DataFrame(all_stocks_conditions)


def check_cup_conditions(df, params):
    MIN_WEEKS = params['MIN_WEEKS']
    MAX_WEEKS = params['MAX_WEEKS']
    MIN_DEPTH = params['MIN_DEPTH']
    MAX_DEPTH = params['MAX_DEPTH']
    RECOVERY_MIN = params['RECOVERY_MIN']
    RECOVERY_MAX = params['RECOVERY_MAX']
    COMPRESSION_LOOKBACK = params['COMPRESSION_LOOKBACK']

    if len(df) < MAX_WEEKS:
        return None

    latest = df.iloc[-1]

    # # Condition from base_formation: Uptrend
    # if 'ma_40' not in df.columns or 'ma_10' not in df.columns or pd.isna(latest['ma_40']) or pd.isna(latest['ma_10']):
    #     return None
    # trend_condition = (
    #     latest['Close'] > latest['ma_40'] and
    #     latest['ma_10'] > latest['ma_40']
    # )

    window = df[-MAX_WEEKS:].copy()
    
    peak_search_window = window.iloc[:-MIN_WEEKS]

    peak_idx = peak_search_window['High'].idxmax()
    peak_price = window.loc[peak_idx, 'High']

    after_peak = window.loc[peak_idx:]

    after_peak = window.loc[peak_idx:]
    if len(after_peak) < MIN_WEEKS:
        return None

    bottom_idx = after_peak['Low'].idxmin()
    bottom_price = after_peak.loc[bottom_idx, 'Low']

    # Condition 1: Depth (from base_formation)
    depth = (peak_price - bottom_price) / peak_price if peak_price > 0 else 0
    depth_ok = MIN_DEPTH <= depth <= MAX_DEPTH

    # Condition 2: Duration (from base_formation)
    duration = (bottom_idx - peak_idx).days / 7
    duration_ok = duration >= MIN_WEEKS

    # Condition from base_formation: Rounded Bottom
    near_low_weeks = after_peak[
        after_peak['Close'] <= bottom_price * 1.05
    ]
    rounded_condition = len(near_low_weeks) >= 3

    # Condition 3: Recovery (from base_formation)
    current_price = window['Close'].iloc[-1]
    recovery_level = (current_price - bottom_price) / (peak_price - bottom_price) if (peak_price - bottom_price) > 0 else 0
    recovery_ok = RECOVERY_MIN <= recovery_level <= RECOVERY_MAX

    # Condition 4: Volatility Compression (from original sm_bg.py, kept for reference)
    recent_atr = window['atr'].iloc[-COMPRESSION_LOOKBACK:]
    compression_ok = False
    if not recent_atr.empty and not pd.isna(window['atr'].quantile(0.3)):
        recent_mean = recent_atr.mean()
        threshold = window['atr'].quantile(0.3)
        if recent_mean < threshold:
            compression_ok = True
    
    conditions = {
        # "Uptrend": trend_condition,
        f"Depth ({MIN_DEPTH:.0%}-{MAX_DEPTH:.0%})": depth_ok,
        f"Duration (>{MIN_WEEKS}w)": duration_ok,
        "Rounded Bottom": rounded_condition,
        f"Recovery ({RECOVERY_MIN:.0%}-{RECOVERY_MAX:.0%})": recovery_ok,
        "Volatility Compressed": compression_ok 
    }
    
    return conditions

def calculate_cup_metrics(df, params=default_params):
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



def plot_cup_formation_smbg(df_weekly, symbol, params):
    """
    Generates a Plotly chart to visualize a cup formation on weekly data.
    This function is designed to be consistent with the scanner logic in this file.
    """
    df = calculate_cup_metrics(df_weekly.copy(), params)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                          vertical_spacing=0.05,
                          row_heights=[0.7, 0.3])

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
    if len(df) >= MAX_WEEKS:
        window = df[-MAX_WEEKS:].copy()
        peak_idx = window['High'].idxmax()
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

    fig.update_layout(
        title=f'{symbol} - Cup Formation Analysis (Weekly)',
        xaxis_rangeslider_visible=False,
        height=700,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)

    return fig
run_full_scan()