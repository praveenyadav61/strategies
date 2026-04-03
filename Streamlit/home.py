import streamlit as st
import pandas as pd
import os
# from Data_transformation import read_data
# from VCP_Scanner import run_vcp_scanner
# from sm_bg import run_full_scan, plot_cup_formation_smbg
# from base_formation import run_full_scan_base
from modular_base_scanner import CupScanner
from chart_plot import plot_cup_formation


def normalize_symbol_for_deals(symbol):
    """
    Daily price files use symbols like `ABC.NS`, while bulk/block deal files
    usually store them as `ABC`. Normalize once so both sources can be matched.
    """
    return str(symbol).replace(".NS", "").strip().upper()

# st.set_page_config(layout="wide")
## data read
# Load static data and merge it with scan results BEFORE displaying
static_data_path = 'data/static/static_data.parquet'
static_df = pd.read_parquet(static_data_path)
# Sidebar for navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio("Choose a page", ["Home", "Base Formation","Bulk_Block_Deal","Trend_Follower"])
m_cap =st.sidebar.number_input("Market Cap Filter (in Crores)", min_value=10, value=1000, step=1000000000)
if page == "Home":
    st.header("Stock Analysis")
    st.write("Welcome! Developed by Praveen nd Team.")
    


elif page == "Base Formation":
    st.title("Base Formation Pattern")
    st.info("This scanner identifies stocks forming a potential cup-shaped base on a weekly chart.")
    
    st.sidebar.header("Scanner Parameters")
    min_weeks = st.sidebar.number_input("Min Duration (Weeks)", min_value=1, value=8, step=1)
    max_weeks = st.sidebar.number_input("Max Duration (Weeks)", min_value=1, value=52, step=1)
    min_depth = st.sidebar.slider("Min Depth (%)", min_value=1, max_value=100, value=15)
    max_depth = st.sidebar.slider("Max Depth (%)", min_value=1, max_value=100, value=60)
    recovery_min = st.sidebar.slider("Min Recovery from Bottom (%)", min_value=1, max_value=150, value=60)
    recovery_max = st.sidebar.slider("Max Recovery from Bottom (%)", min_value=1, max_value=150, value=120)
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

    # if st.sidebar.button("Run Scan"):
    #     st.session_state.base_scan_results = run_full_scan_base(params)
    if st.sidebar.button("Run Scan"):
        scanner = CupScanner(params, debug=False)
        st.session_state.base_scan_results = scanner.run_scan()

    if 'base_scan_results' in st.session_state:
        bulk_df = st.session_state.base_scan_results
        if bulk_df.empty:
            st.warning("No stocks found for the given criteria. Try adjusting the parameters and running the scan again.")
        else:
            st.subheader("Stocks with Potential Cup Formations")
            
            display_df = bulk_df
            if os.path.exists(static_data_path):
                display_df = bulk_df.merge(static_df, left_on='Symbol', right_on='symbol', how='left')

                # Convert Market Cap to Crores for better readability and sorting
                if 'marketCap' in display_df.columns:
                    display_df['Market Cap (Cr)'] = (display_df['marketCap'] / 1_00_00_000).round(0)

                # Define the desired column order as requested
                # metrics_to_front = ['Tight Groups', 'Depth', 'Recovery']
                metrics_to_front = ['Tight Groups', 'Depth', 'Recovery', 'prior_uptrend', 'pivot']
                bulk_df_cols = [col for col in bulk_df.columns if col not in ['Symbol'] + metrics_to_front]
                static_cols_to_show = ['longName', 'industry', 'sector', 'Market Cap (Cr)']

                # Combine columns in the specified order
                # The original 'marketCap' will be excluded unless explicitly added back.
                ordered_cols = ['Symbol'] + static_cols_to_show + metrics_to_front + bulk_df_cols
                # Filter list to ensure all columns exist in the merged DataFrame
                final_cols = [col for col in ordered_cols if col in display_df.columns]
                display_df = display_df[final_cols]
                display_df = display_df[display_df['Market Cap (Cr)'] >= m_cap]  # Apply market cap filter

            event = st.dataframe(
                display_df,  # Display the merged DataFrame
                use_container_width=True,
                hide_index=False,
                on_select="rerun",
                selection_mode="single-row"
            )
            # Check if a row is selected to display the chart
            if event.selection.rows:
                selected_row_index = event.selection.rows[0]
                selected_symbol = display_df.iloc[selected_row_index]['Symbol']
                
                st.subheader(f"Chart for {selected_symbol}")
                
                try:
                    # Define the path to the data file
                    data_path = 'data/daily/'
                    if not os.path.exists(data_path):
                        data_path = '../data/daily/'
                    
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
                    
                    # Display static info for the selected symbol
                    st.write("Company Information")
                    static_info = static_df[static_df['symbol'] == selected_symbol].dropna(axis=1, how='all')
                    st.dataframe(static_info, use_container_width=True)
                    # Show bulk / block deals for the selected symbol after
                    # normalizing `.NS` style chart symbols to deal symbols.
                    bulk_path = 'data/deals_data/bulk_deals.parquet' 
                    block_path = 'data/deals_data/block_deals.parquet'
                    selected_deal_symbol = normalize_symbol_for_deals(selected_symbol)

                    if os.path.exists(bulk_path) and os.path.exists(block_path):
                        bulk_df = pd.read_parquet(bulk_path)
                        block_df = pd.read_parquet(block_path)
                        bulk_df.columns = bulk_df.columns.str.strip()
                        block_df.columns = block_df.columns.str.strip()

                        if 'Symbol' in bulk_df.columns:
                            bulk_df['Symbol'] = bulk_df['Symbol'].astype(str).str.strip().str.upper()
                        if 'Symbol' in block_df.columns:
                            block_df['Symbol'] = block_df['Symbol'].astype(str).str.strip().str.upper()

                        bulk_info = bulk_df[bulk_df['Symbol'] == selected_deal_symbol]
                        block_info = block_df[block_df['Symbol'] == selected_deal_symbol]

                        st.write(f"Bulk/Block Deals for {selected_deal_symbol}")
                        if not bulk_info.empty:
                            st.subheader("Bulk Deals")
                            st.dataframe(bulk_info, use_container_width=True, hide_index=True)
                        if not block_info.empty:
                            st.subheader("Block Deals")
                            st.dataframe(block_info, use_container_width=True, hide_index=True)
                        if bulk_info.empty and block_info.empty:
                            st.info(f"No bulk/block deals found for {selected_deal_symbol}.")



                    # Generate and display the plot
                    fig = plot_cup_formation(weekly_df, selected_symbol, params)
                    st.plotly_chart(fig, use_container_width=True)
                    
                except FileNotFoundError:
                    st.error(f"Could not find data file for {selected_symbol}.")
                except Exception as e:
                    st.error(f"An error occurred while plotting {selected_symbol}: {e}")

elif page == "Bulk_Block_Deal":
    st.title("Bulk Block Deal Scanner")
    st.info("This scanner identifies stocks with significant bulk block deals.")
    bulk_df= pd.read_parquet('data/deals_data/bulk_deals.parquet')
    block_df= pd.read_parquet('data/deals_data/block_deals.parquet')
    bulk_df['Symbol']= bulk_df['Symbol'].apply(normalize_symbol_for_deals())
    block_df['Symbol']= block_df['Symbol'].apply(normalize_symbol_for_deals())
    display_df = bulk_df.merge(static_df, left_on='Symbol', right_on='symbol', how='left')

    # Convert Market Cap to Crores for better readability and sorting
    if 'marketCap' in display_df.columns:
        display_df['Market Cap (Cr)'] = (display_df['marketCap'] / 1_00_00_000).round(0)

    # Define the desired column order as requested
    metrics_to_front = ['Tight Groups', 'Depth', 'Recovery']
    bulk_df_cols = [col for col in bulk_df.columns if col not in ['Symbol'] + metrics_to_front]
    static_cols_to_show = ['longName', 'industry', 'sector', 'Market Cap (Cr)']

    # Combine columns in the specified order
    # The original 'marketCap' will be excluded unless explicitly added back.
    ordered_cols = ['Symbol'] + static_cols_to_show + metrics_to_front + bulk_df_cols
    # Filter list to ensure all columns exist in the merged DataFrame
    final_cols = [col for col in ordered_cols if col in display_df.columns]
    display_df = display_df[final_cols]
    display_df = display_df[display_df['Market Cap (Cr)'] >= m_cap]  # Apply market cap filter
    st.subheader("Bulk Deals")
    st.dataframe(bulk_df, use_container_width=True)
    st.subheader("Block Deals")
    st.dataframe(block_df, use_container_width=True)

elif page == "Trend_Follower":
    st.title("Trend Follower Scanner")
    st.info("This scanner identifies stocks that are currently in a strong uptrend.")
