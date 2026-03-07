import streamlit as st
import pandas as pd
import os
from Data_transformation import read_data
from VCP_Scanner import run_vcp_scanner
from sm_bg import run_full_scan,plot_cup_formation_smbg
from base_formation import run_full_scan_base, plot_cup_formation



# st.set_page_config(layout="wide")

# Sidebar for navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio("Choose a page", ["Home", "Base_formation"])

if page == "Home":
    st.header("Stock Analysis")
    st.write("This is the home page for basic stock analysis.")
    
    # Original content from home.py
    try:
        df = read_data("INDIGO.NS")
        st.subheader("Analysis for INDIGO.NS")
        st.dataframe(df.head())
    except FileNotFoundError:
        st.error("Could not find data for INDIGO.NS. Please make sure the data exists in 'data/market_data/'.")
    except Exception as e:
        st.error(f"An error occurred: {e}")


elif page == "Base_formation":
    st.title("Base Formation Pattern")
    st.info("This scanner identifies stocks forming a potential cup-shaped base on a weekly chart.")
    
    # Use session_state to store the scan results. This prevents the expensive
    # scan from re-running every time the user interacts with the page (e.g., selecting a row).
    # The scan will only run once per session or after a full page refresh.
    if 'base_scan_results' not in st.session_state:
        st.session_state.base_scan_results = run_full_scan()
    base_df = st.session_state.base_scan_results

    if base_df.empty:
        st.warning("No stocks currently match the base formation criteria.")
    else:
        st.subheader("Stocks with Potential Cup Formations")
        event = st.dataframe(
            base_df,
            use_container_width=True,
            hide_index=True,
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
                fig = plot_cup_formation_smbg(weekly_df, selected_symbol)
                st.plotly_chart(fig, use_container_width=True)

            except FileNotFoundError:
                st.error(f"Could not find data file for {selected_symbol}.")
            except Exception as e:
                st.error(f"An error occurred while plotting {selected_symbol}: {e}")