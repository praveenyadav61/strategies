import streamlit as st
import pandas as pd
import numpy as np
import os
import plotly.graph_objects as go
from plotly.subplots import make_subplots

data_path = '../data/market_data/'
if not os.path.exists(data_path):
    data_path = 'data/market_data/'


# ===============================
# MAIN SCAN FUNCTION
# ===============================
def run_full_scan_base():

    all_files = [f for f in os.listdir(data_path) if f.endswith('.parquet')]
    results = []

    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, filename in enumerate(all_files):

        symbol = filename.replace('.parquet', '')
        status_text.text(f"Scanning {symbol} ({i+1}/{len(all_files)})")

        try:
            df = pd.read_parquet(os.path.join(data_path, filename))

            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)

            # FIX MULTIINDEX
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # ===== RESAMPLE TO WEEKLY =====
            df_weekly = df.resample('W').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()

            df_weekly = calculate_weekly_metrics(df_weekly)

            conditions, metrics = check_cup_conditions(df_weekly)

            if conditions and metrics and all(conditions.values()):
                stock_condition = {
                    'Symbol': symbol,
                    'Depth': f"{metrics['Depth']:.1%}"
                }
                stock_condition.update(conditions)
                results.append(stock_condition)

        except Exception as e:
            st.error(f"Error processing {symbol}: {e}")
        progress_bar.progress((i + 1) / len(all_files))

    status_text.text("Scan Complete!")
    # Return a DataFrame with symbols and the conditions that passed
    return pd.DataFrame(results)

# ===============================
# CALCULATE WEEKLY METRICS
# ===============================
def calculate_weekly_metrics(df):

    df = df.copy()

    # 20W and 40W moving averages (more relevant for weekly)
    df['ma_20'] = df['Close'].rolling(10).mean()
    df['ma_40'] = df['Close'].rolling(40).mean()

    # 52-week high
    df['52w_high'] = df['Close'].rolling(52).max()

    # Volume moving averages
    df['volume_ma_10'] = df['Volume'].rolling(10).mean()
    df['volume_ma_20'] = df['Volume'].rolling(20).mean()

    return df


# ===============================
# CUP DETECTION LOGIC
# ===============================
def check_cup_conditions(df):

    if len(df) < 60:  # need sufficient history
        return None, None

    latest = df.iloc[-1]

    # ===== PRIOR UPTREND =====
    trend_condition = (
        latest['Close'] > latest['ma_40'] and
        latest['ma_20'] > latest['ma_40']
    )

    # ===== LEFT PEAK =====
    left_peak = df['52w_high'].iloc[-1]
    if pd.isna(left_peak):
        return None, None

    # Find last occurrence of 52W high
    peak_idx = df[df['Close'] == left_peak].index
    if len(peak_idx) == 0:
        return None, None

    peak_idx = peak_idx[-1]

    df_after_peak = df.loc[peak_idx:]

    if len(df_after_peak) < 10:
        return None, None

    # ===== CUP LOW =====
    cup_low = df_after_peak['Close'].min()
    low_idx = df_after_peak['Close'].idxmin()

    depth = (left_peak - cup_low) / left_peak if left_peak > 0 else 0

    # ===== DURATION =====
    duration_weeks = (low_idx - peak_idx).days / 7

    # ===== ROUNDED BOTTOM PROXY =====
    near_low_weeks = df_after_peak[
        df_after_peak['Close'] <= cup_low * 1.05
    ]
    rounded_condition = len(near_low_weeks) >= 3

    # ===== RIGHT SIDE RECOVERY =====
    # Recovery level is current price as a percentage of the prior peak
    recovery_level = latest['Close'] / left_peak if left_peak > 0 else 0

    # ===== DEFINE CONDITIONS =====
    depth_condition = 0.18 <= depth <= 0.65
    duration_condition = duration_weeks >= 8
    recovery_condition = 0.65 <= recovery_level <= 1.10

    conditions = {
        "Uptrend": trend_condition,
        "Depth (18-65%)": depth_condition,
        "Duration (>=8W)": duration_condition,
        "Rounded Bottom": rounded_condition,
        "Recovery (85-110%)": recovery_condition
    }

    metrics = {
        "Depth": depth,
        "Recovery": recovery_level,
        "Duration (w)": duration_weeks
    }

    return conditions, metrics

def plot_cup_formation(df_weekly, symbol):
    """
    Generates a Plotly chart to visualize a cup formation on weekly data.
    """
    df = calculate_weekly_metrics(df_weekly.copy())

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                          vertical_spacing=0.05,
                          row_heights=[0.7, 0.3])

    # 1. Candlestick chart for weekly data
    fig.add_trace(go.Candlestick(x=df.index,
                    open=df['Open'],
                    high=df['High'],
                    low=df['Low'],
                    close=df['Close'],
                    name='Weekly Price'),
                    row=1, col=1)

    # 2. Add moving averages
    fig.add_trace(go.Scatter(x=df.index, y=df['ma_20'], name='20W MA', line=dict(color='orange')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['ma_40'], name='40W MA', line=dict(color='blue')), row=1, col=1)

    # 3. Logic to find and draw the cup pattern for visualization
    if len(df) >= 60:
        left_peak_price = df['52w_high'].iloc[-1]
        peak_idx_list = df[df['Close'] == left_peak_price].index
        if len(peak_idx_list) > 0:
            peak_idx = peak_idx_list[-1]
            df_after_peak = df.loc[peak_idx:]

            if len(df_after_peak) > 5:
                cup_low_price = df_after_peak['Close'].min()
                low_idx = df_after_peak['Close'].idxmin()

                # Draw horizontal line for the peak (resistance)
                fig.add_shape(type="line",
                    x0=peak_idx, y0=left_peak_price, x1=df.index[-1], y1=left_peak_price,
                    line=dict(color="Red", width=2, dash="dash"), row=1, col=1)
                fig.add_annotation(x=peak_idx, y=left_peak_price, text="Left Peak", showarrow=True, arrowhead=1, row=1, col=1)
                fig.add_annotation(x=low_idx, y=cup_low_price, text="Cup Low", showarrow=True, arrowhead=1, yshift=-10, row=1, col=1)

    # 4. Volume chart
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
