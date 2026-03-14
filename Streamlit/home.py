import streamlit as st
import pandas as pd
import os
from Data_transformation import read_data
from VCP_Scanner import run_vcp_scanner
from sm_bg import run_full_scan, plot_cup_formation_smbg
from base_formation import run_full_scan_base, plot_cup_formation



# st.set_page_config(layout="wide")

# Sidebar for navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio("Choose a page", ["Home", "Base_formation"])

if page == "Home":
    st.header("Stock Analysis")
    st.write("Welcome! Developed by Praveen nd Team.")
    


elif page == "Base_formation":
    st.title("Base Formation Pattern")
    st.info("This scanner identifies stocks forming a potential cup-shaped base on a weekly chart.")
    
    st.sidebar.header("Scanner Parameters")
    min_weeks = st.sidebar.number_input("Min Duration (Weeks)", min_value=1, value=8, step=1)
    max_weeks = st.sidebar.number_input("Max Duration (Weeks)", min_value=1, value=65, step=1)
    min_depth = st.sidebar.slider("Min Depth (%)", min_value=1, max_value=100, value=18)
    max_depth = st.sidebar.slider("Max Depth (%)", min_value=1, max_value=100, value=65)
    recovery_min = st.sidebar.slider("Min Recovery from Peak (%)", min_value=1, max_value=150, value=65)
    recovery_max = st.sidebar.slider("Max Recovery from Peak (%)", min_value=1, max_value=150, value=110)
    atr_window = st.sidebar.number_input("ATR Window", min_value=1, value=14, step=1)
    compression_lookback = st.sidebar.number_input("Compression Lookback (Weeks)", min_value=1, value=10, step=1)

    params = {
        'MIN_WEEKS': min_weeks,
        'MAX_WEEKS': max_weeks,
        'MIN_DEPTH': min_depth / 100.0,
        'MAX_DEPTH': max_depth / 100.0,
        'RECOVERY_MIN': recovery_min / 100.0,
        'RECOVERY_MAX': recovery_max / 100.0,
        'ATR_WINDOW': atr_window,
        'COMPRESSION_LOOKBACK': compression_lookback,
    }

    if st.sidebar.button("Run Scan"):
        st.session_state.base_scan_results = run_full_scan(params)

    if 'base_scan_results' in st.session_state:
        base_df = st.session_state.base_scan_results
        if base_df.empty:
            st.warning("No stocks found for the given criteria. Try adjusting the parameters and running the scan again.")
        else:
            st.subheader("Stocks with Potential Cup Formations")
            event = st.dataframe(
                base_df,
                use_container_width=True,
                hide_index=False,
                on_select="rerun",
                selection_mode="single-row"
            )

            # Check if a row is selected to display the chart
            if event.selection.rows:
                selected_row_index = event.selection.rows[0]
                selected_symbol = base_df.iloc[selected_row_index]['Symbol']
                
                st.subheader(f"Chart for {selected_symbol}")
                
                try:
                    # Define the path to the data file
                    data_path = 'data/market_data/'
                    if not os.path.exists(data_path):
                        data_path = '../data/market_data/'
                    
                    # Load daily data
                    daily_df = pd.read_parquet(os.path.join(data_path, f"{selected_symbol}.parquet"))
                                # FIX MULTIINDEX
                    if isinstance(daily_df.columns, pd.MultiIndex):
                        daily_df.columns = daily_df.columns.get_level_values(0)
                    if 'Date' in daily_df.columns:
                        daily_df['Date'] = pd.to_datetime(daily_df['Date'])
                        daily_df.set_index('Date', inplace=True)

                    # Resample to weekly, same as in the scanner
                    weekly_df = daily_df.resample('W').agg({
                        'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
                    }).dropna()

                    # Generate and display the plot
                    fig = plot_cup_formation_smbg(weekly_df, selected_symbol, params)
                    st.plotly_chart(fig, use_container_width=True)

                except FileNotFoundError:
                    st.error(f"Could not find data file for {selected_symbol}.")
                except Exception as e:
                    st.error(f"An error occurred while plotting {selected_symbol}: {e}")