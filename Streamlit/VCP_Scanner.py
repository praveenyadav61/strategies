import streamlit as st
import pandas as pd
import os
import plotly.graph_objects as go
from plotly.subplots import make_subplots



def calculate_vcp_metrics(df):
    # Remove duplicate columns to prevent errors if a parquet file has them
    df = df.loc[:,~df.columns.duplicated()]
    
    # Stage 1 – Trend
    df['ema_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['ema_200'] = df['Close'].ewm(span=200, adjust=False).mean()
    
    # Stage 2 – Prior Strength
    df['6m_return'] = df['Close'].pct_change(periods=126).fillna(0)
    df['52w_low'] = df['Close'].rolling(window=252).min()
    df['price_vs_52w_low'] = (df['Close'] - df['52w_low']) / df['52w_low']

    # Stage 3 – Volatility Contraction
    df['rolling_std_20'] = df['Close'].rolling(window=20).std()
    
    # ATR Calculation
    df['high-low'] = df['High'] - df['Low']
    df['high-prev_close'] = abs(df['High'] - df['Close'].shift(1))
    df['low-prev_close'] = abs(df['Low'] - df['Close'].shift(1))
    df['tr'] = df[['high-low', 'high-prev_close', 'low-prev_close']].max(axis=1)
    df['atr_14'] = df['tr'].rolling(window=14).mean()

    df['20_day_range'] = df['High'].rolling(window=20).max() - df['Low'].rolling(window=20).min()
    df['40_day_range'] = df['High'].rolling(window=40).max() - df['Low'].rolling(window=40).min()

    # Stage 4 – Volume Dry-Up
    df['volume_20dma'] = df['Volume'].rolling(window=20).mean()
    df['volume_50dma'] = df['Volume'].rolling(window=50).mean()
    
    return df

def check_vcp_conditions(df):
    if len(df) < 252:
        return None

    latest = df.iloc[-1]
    
    conditions = {
        "Close > 200 EMA": latest['Close'] > latest['ema_200'],
        "50 EMA > 200 EMA": latest['ema_50'] > latest['ema_200'],
        # "6M Return > 30%": latest['6m_return'] > 0.30,
        # "Price > 61% of 52W Low": latest['price_vs_52w_low'] > 0.61,
        # "Rolling Std(20) Decreasing": df['rolling_std_20'].iloc[-5:].is_monotonic_decreasing,
        # "ATR(14) Decreasing": df['atr_14'].iloc[-5:].is_monotonic_decreasing,
        # "20d Range < 40d Range": latest['20_day_range'] < latest['40_day_range'],
        # "20DMA Volume < 50DMA Volume": latest['volume_20dma'] < latest['volume_50dma']
    }
    
    return conditions

def plot_stock_data(df, symbol):
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                          vertical_spacing=0.03, 
                          row_heights=[0.6, 0.2, 0.2])

    # Candlestick chart
    fig.add_trace(go.Candlestick(x=df.index,
                    open=df['Open'],
                    high=df['High'],
                    low=df['Low'],
                    close=df['Close'],
                    name='Candlestick'),
                    row=1, col=1)
    
    fig.add_trace(go.Scatter(x=df.index, y=df['ema_50'], name='50 EMA', line=dict(color='orange', width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['ema_200'], name='200 EMA', line=dict(color='blue', width=1)), row=1, col=1)


    # Volume chart
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='Volume'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['volume_20dma'], name='Volume 20DMA', line=dict(color='purple', width=1)), row=2, col=1)
    
    # Rolling Std Dev chart
    fig.add_trace(go.Scatter(x=df.index, y=df['rolling_std_20'], name='20-Day Rolling Std Dev'), row=3, col=1)

    fig.update_layout(
        title=f'{symbol} - VCP Analysis',
        xaxis_rangeslider_visible=False,
        height=800
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_yaxes(title_text="Rolling Std Dev", row=3, col=1)

    return fig

def run_vcp_scanner():
    st.title("Volatility Contraction Pattern (VCP) Scanner")

    data_path = '../data/market_data/'
    # Corrected path for Streamlit execution context
    if not os.path.exists(data_path):
        data_path = 'data/market_data/'

    @st.cache_data
    def run_full_scan():
        all_files = [f for f in os.listdir(data_path) if f.endswith('.parquet')]
        all_stocks_conditions = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, filename in enumerate(all_files):
            symbol = filename.replace('.parquet', '')
            status_text.text(f"Scanning {symbol} ({i+1}/{len(all_files)})")
            
            try:
                df = pd.read_parquet(os.path.join(data_path, filename))
                if 'Date' in df.columns:
                    df.set_index('Date', inplace=True)
                
                df = calculate_vcp_metrics(df)
                conditions = check_vcp_conditions(df)

                if conditions:
                    stock_condition = {'Symbol': symbol}
                    stock_condition.update(conditions)
                    all_stocks_conditions.append(stock_condition)
                    
            except Exception as e:
                st.error(f"Could not process {symbol}: {e}")
            
            progress_bar.progress((i + 1) / len(all_files))
        
        status_text.text("Scan Complete!")
        return pd.DataFrame(all_stocks_conditions)

    full_df = run_full_scan()

    if full_df.empty:
        st.warning("Could not scan any stocks. Please check the data directory.")
        return

    st.subheader("VCP Stage Analysis")
    
    # Define the order of columns to ensure consistent display
    condition_cols = [
        "Close > 200 EMA",
        "50 EMA > 200 EMA",
        "6M Return > 30%",
        "Price > 61% of 52W Low",
        "Rolling Std(20) Decreasing",
        "ATR(14) Decreasing",
        "20d Range < 40d Range",
        "20DMA Volume < 50DMA Volume",
    ]
    display_cols = ['Symbol'] + condition_cols
    full_df = full_df[display_cols]
    
    st.info("Select the conditions below to filter for stocks that meet them.")
    selected_conditions = st.multiselect(
        "Filter by conditions:",
        options=condition_cols,
        default=condition_cols[:2] # Default to first two trend conditions
    )

    filtered_df = full_df.copy()
    if selected_conditions:
        for condition in selected_conditions:
            filtered_df = filtered_df[filtered_df[condition] == True]

    st.dataframe(filtered_df)

    if not filtered_df.empty:
        st.subheader("Chart Analysis")
        selected_stock = st.selectbox("Select a stock to view details:", filtered_df['Symbol'].tolist())

        if selected_stock:
            stock_df = pd.read_parquet(os.path.join(data_path, f"{selected_stock}.parquet"))
            if 'Date' in stock_df.columns:
                stock_df.set_index('Date', inplace=True)
            stock_df_processed = calculate_vcp_metrics(stock_df)
            
            st.plotly_chart(plot_stock_data(stock_df_processed, selected_stock), use_container_width=True)
    else:
        st.warning("No stocks match the selected filter criteria.")

# --- Main execution for direct run ---
if __name__ == "__main__":
    run_vcp_scanner()
