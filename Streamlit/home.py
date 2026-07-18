import streamlit as st
st.set_page_config(page_title="Strategies Dashboard", layout="wide")

import pandas as pd
import os
import sys
from pathlib import Path
from datetime import date
# from Data_transformation import read_data
# from VCP_Scanner import run_vcp_scanner
# from sm_bg import run_full_scan, plot_cup_formation_smbg
# from base_formation import run_full_scan_base

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from modular_base_scanner import CupScanner
from base_lifecycle_pages import render_base_phase_page, render_tracking_phase_page
from chart_plot import plot_cup_formation, plot_custom_ohlcv_chart, plot_trend_follower_chart
from trend_follower.final_trend_follower import EMAScanner
from audio import build_transcript_pdf, load_saved_records, process_audio_request
from Streamlit.earnings_summary import render_earnings_summary_page
from Streamlit.bulk_block_analysis import render_bulk_block_page


def normalize_symbol_for_deals(symbol):
    """
    Daily price files use symbols like `ABC.NS`, while bulk/block deal files
    usually store them as `ABC`. Normalize once so both sources can be matched.
    """
    return str(symbol).replace(".NS", "").strip().upper()


def first_existing_path(*candidates):
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def get_config_value(name):
    value = os.getenv(name)
    if value:
        return value

    try:
        return st.secrets[name]
    except Exception:
        return None


def google_drive_csv_url(value):
    value = str(value).strip()
    if not value:
        return value

    if "drive.google.com" not in value:
        return f"https://drive.google.com/uc?export=download&id={value}"

    if "/file/d/" in value:
        file_id = value.split("/file/d/", 1)[1].split("/", 1)[0]
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    if "id=" in value:
        file_id = value.split("id=", 1)[1].split("&", 1)[0]
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    return value


# @st.cache_data(show_spinner=False)
def load_static_data():
    static_path = first_existing_path(
        ROOT_DIR / "data" / "static" / "static_data.parquet",
        "data/static/static_data.parquet",
        "../data/static/static_data.parquet",
    )
    if static_path is None:
        return pd.DataFrame()

    static_df = pd.read_parquet(static_path)
    if "symbol" in static_df.columns:
        static_df["symbol"] = static_df["symbol"].astype(str).str.strip()
    return static_df


# @st.cache_data(show_spinner=False)
def load_deals_data():
    bulk_path = first_existing_path(
        ROOT_DIR / "data" / "deals_data" / "bulk_deals.parquet",
        "data/deals_data/bulk_deals.parquet",
        "../data/deals_data/bulk_deals.parquet",
    )
    block_path = first_existing_path(
        ROOT_DIR / "data" / "deals_data" / "block_deals.parquet",
        "data/deals_data/block_deals.parquet",
        "../data/deals_data/block_deals.parquet",
    )

    bulk_df = pd.DataFrame()
    block_df = pd.DataFrame()

    if bulk_path is not None:
        bulk_df = pd.read_parquet(bulk_path)
        bulk_df.columns = bulk_df.columns.str.strip()
        if "Symbol" in bulk_df.columns:
            bulk_df["Symbol"] = bulk_df["Symbol"].astype(str).str.strip().str.upper()
        if "Date" in bulk_df.columns:
            bulk_df["Date"] = pd.to_datetime(bulk_df["Date"], errors="coerce")

    if block_path is not None:
        block_df = pd.read_parquet(block_path)
        block_df.columns = block_df.columns.str.strip()
        if "Symbol" in block_df.columns:
            block_df["Symbol"] = block_df["Symbol"].astype(str).str.strip().str.upper()
        if "Date" in block_df.columns:
            block_df["Date"] = pd.to_datetime(block_df["Date"], errors="coerce")

    return bulk_df, block_df


# @st.cache_data(show_spinner=False)
def load_announcements_data():
    announcement_path = first_existing_path(
        ROOT_DIR / "data" / "Announcements" / "announcements.parquet",
        "data/Announcements/announcements.parquet",
        "../data/Announcements/announcements.parquet",
    )
    if announcement_path is None:
        return pd.DataFrame()

    announcement_df = pd.read_parquet(announcement_path)
    announcement_df.columns = announcement_df.columns.str.strip()

    if "symbol" in announcement_df.columns:
        announcement_df["symbol"] = (
            announcement_df["symbol"].astype(str).str.strip().str.upper()
        )

    if "date" in announcement_df.columns:
        announcement_df["date"] = pd.to_datetime(announcement_df["date"], errors="coerce")

    return announcement_df


@st.cache_data(show_spinner=False)
def load_custom_data_center():
    drive_source = (
        get_config_value("CUSTOM_DATA_CENTER_CSV_URL")
        or get_config_value("CUSTOM_DATA_CENTER_GOOGLE_DRIVE_FILE_ID")
    )
    custom_path = ROOT_DIR / "data" / "static" / "custom_data_center.csv"
    source_label = str(custom_path)

    if drive_source:
        source_label = "Google Drive custom data center CSV"
        custom_df = pd.read_csv(google_drive_csv_url(drive_source))
    else:
        if not custom_path.exists():
            raise FileNotFoundError(
                "Custom data center CSV was not found locally and no Google Drive "
                "source was configured. Set CUSTOM_DATA_CENTER_CSV_URL or "
                "CUSTOM_DATA_CENTER_GOOGLE_DRIVE_FILE_ID in Streamlit secrets."
            )
        custom_df = pd.read_csv(custom_path)

    if custom_df.empty:
        raise ValueError(f"{source_label} is empty.")

    custom_df.columns = custom_df.columns.str.strip()
    required_cols = ["date", "index_symbol", "open", "high", "low", "close", "volume"]
    missing_cols = [col for col in required_cols if col not in custom_df.columns]
    if missing_cols:
        raise ValueError(f"{source_label} is missing required columns: {missing_cols}")

    custom_df["Date"] = pd.to_datetime(
        custom_df["date"].astype(str),
        format="%Y%m%d",
        errors="coerce",
    )
    if custom_df["Date"].isna().any():
        bad_dates = custom_df.loc[custom_df["Date"].isna(), "date"].head(5).tolist()
        raise ValueError(f"{source_label} has invalid date values: {bad_dates}")

    custom_df = custom_df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )

    ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in ohlcv_cols:
        custom_df[col] = pd.to_numeric(custom_df[col], errors="coerce")

    if custom_df[ohlcv_cols].isna().any().any():
        raise ValueError(f"{source_label} has non-numeric OHLCV values.")

    custom_df["index_symbol"] = custom_df["index_symbol"].astype(str).str.strip()
    if "turnover" in custom_df.columns:
        custom_df["turnover"] = pd.to_numeric(custom_df["turnover"], errors="coerce")

    custom_df = custom_df.set_index("Date").sort_index()
    return custom_df


@st.cache_data(show_spinner=False)
def load_nasdaq_comparison(start_date, end_date):
    import yfinance as yf

    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date) + pd.Timedelta(days=1)
    nasdaq_df = yf.download(
        "^IXIC",
        start=start_ts,
        end=end_ts,
        interval="1d",
        progress=False,
    )

    if nasdaq_df is None or nasdaq_df.empty:
        raise FileNotFoundError("No Nasdaq Composite data returned from yfinance.")

    if isinstance(nasdaq_df.columns, pd.MultiIndex):
        nasdaq_df.columns = nasdaq_df.columns.get_level_values(0)

    required_cols = ["Open", "High", "Low", "Close", "Volume"]
    missing_cols = [col for col in required_cols if col not in nasdaq_df.columns]
    if missing_cols:
        raise ValueError(f"Nasdaq data is missing required columns: {missing_cols}")

    nasdaq_df = nasdaq_df[required_cols].dropna(subset=["Close"])
    nasdaq_df.index = pd.to_datetime(nasdaq_df.index).normalize()
    nasdaq_df = nasdaq_df[~nasdaq_df.index.duplicated(keep="last")].sort_index()
    return nasdaq_df


def format_announcements_table(announcement_df):
    if announcement_df.empty:
        return announcement_df

    announcement_info = announcement_df.sort_values(
        by="date", ascending=False, na_position="last"
    ).copy()
    preferred_cols = [
        "date",
        "symbol",
        "company_name",
        "attachment_text",
        "attachment_url",
    ]
    available_cols = [col for col in preferred_cols if col in announcement_info.columns]
    return announcement_info[available_cols] if available_cols else announcement_info


def get_audio_recording_announcements(announcement_df, limit=200):
    if announcement_df.empty:
        return announcement_df

    filtered_df = announcement_df.copy()

    required_cols = {"subject", "attachment_text", "attachment_url"}
    if not required_cols.intersection(filtered_df.columns):
        return pd.DataFrame()

    subject_series = (
        filtered_df["subject"].astype(str).str.strip().str.lower()
        if "subject" in filtered_df.columns
        else pd.Series("", index=filtered_df.index)
    )
    attachment_text_series = (
        filtered_df["attachment_text"].astype(str).str.strip().str.lower()
        if "attachment_text" in filtered_df.columns
        else pd.Series("", index=filtered_df.index)
    )
    attachment_url_series = (
        filtered_df["attachment_url"].astype(str).str.strip().str.lower()
        if "attachment_url" in filtered_df.columns
        else pd.Series("", index=filtered_df.index)
    )

    combined_text = (
        subject_series.fillna("")
        + " "
        + attachment_text_series.fillna("")
        + " "
        + attachment_url_series.fillna("")
    )

    has_audio = combined_text.str.contains("audio", na=False)
    has_link = combined_text.str.contains("link", na=False) | attachment_url_series.str.startswith(("http://", "https://"), na=False)

    mask = has_audio & has_link

    filtered_df = filtered_df[mask].sort_values(by="date", ascending=False)
    preferred_cols = [
        "date",
        "symbol",
        "company_name",
        "attachment_text",
        "attachment_url",
    ]
    available_cols = [col for col in preferred_cols if col in filtered_df.columns]
    if available_cols:
        filtered_df = filtered_df[available_cols]

    return filtered_df.head(limit)


def filter_by_date_and_symbol(df, date_col, symbol_col, start_date, end_date, selected_symbol, selected_classification=None):
    if df.empty:
        return df

    filtered_df = df.copy()

    if date_col in filtered_df.columns:
        filtered_df = filtered_df[filtered_df[date_col].notna()]
        filtered_df = filtered_df[
            filtered_df[date_col].dt.date.between(start_date, end_date)
        ]

    if selected_symbol != "All" and symbol_col in filtered_df.columns:
        filtered_df = filtered_df[filtered_df[symbol_col] == selected_symbol]

    if (
        selected_classification is not None
        and selected_classification != "All"
        and "classification" in filtered_df.columns
    ):
        filtered_df = filtered_df[
            filtered_df["classification"] == selected_classification
        ]

    return filtered_df


def get_symbol_options(*frames, symbol_col):
    symbols = set()
    for df in frames:
        if not df.empty and symbol_col in df.columns:
            symbols.update(
                df[symbol_col].dropna().astype(str).str.strip().tolist()
            )
    return ["All"] + sorted(symbol for symbol in symbols if symbol)


def get_column_options(df, column_name):
    if df.empty or column_name not in df.columns:
        return ["All"]

    values = (
        df[column_name]
        .dropna()
        .astype(str)
        .str.strip()
        .tolist()
    )
    return ["All"] + sorted(value for value in set(values) if value)


def load_daily_price_data(symbol):
    """Load a daily parquet file and normalize the date index."""
    symbol = str(symbol).strip()
    candidate_symbols = [symbol]
    if not symbol.endswith(".NS"):
        candidate_symbols.append(f"{symbol}.NS")

    data_candidates = [
        path
        for candidate_symbol in candidate_symbols
        for path in [
            ROOT_DIR / "data" / "daily" / f"{candidate_symbol}.parquet",
            Path("data/daily") / f"{candidate_symbol}.parquet",
            Path("../data/daily") / f"{candidate_symbol}.parquet",
        ]
    ]

    for path in data_candidates:
        if path.exists():
            daily_df = pd.read_parquet(path)
            if isinstance(daily_df.columns, pd.MultiIndex):
                daily_df.columns = daily_df.columns.get_level_values(0)
            if "Date" in daily_df.columns:
                daily_df["Date"] = pd.to_datetime(daily_df["Date"])
                daily_df.set_index("Date", inplace=True)
            elif not isinstance(daily_df.index, pd.DatetimeIndex):
                daily_df.index = pd.to_datetime(daily_df.index)
            return daily_df.sort_index()

    raise FileNotFoundError(f"Could not find daily data for {symbol}")


## data read
# Load shared data once through cached helpers so all tabs reuse it.
static_df = load_static_data()
bulk_deals_df, block_deals_df = load_deals_data()
announcements_df = load_announcements_data()

# Sidebar for navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio(
    "Choose a page",
    [
        "Home",
        "Base Formation",
        "Base Phase",
        "Tracking Phase",
        "Announcements",
        "Earnings Summary",
        "Bulk_Block_Deal",
        "Trend_Follower",
        "Custom Data Center",
        "Audio Transcript",
    ],
)
m_cap =st.sidebar.number_input("Market Cap Filter (in Crores)", min_value=10, value=1000, step=1000000000)
if page == "Home":
    st.header("Stock Analysis")
    st.write("Welcome!!! Please select a scanner from the sidebar to get started.")
    


elif page == "Base Formation":
    st.title("Base Formation Pattern")
    st.info("This scanner identifies stocks forming a potential cup-shaped base on a weekly chart.")
    
    st.sidebar.header("Scanner Parameters")
    min_weeks = st.sidebar.number_input("Min Duration (Weeks)", min_value=1, value=8, step=1)
    max_weeks = st.sidebar.number_input("Max Duration (Weeks)", min_value=1, value=52, step=1)
    min_depth = st.sidebar.slider("Min Depth (%)", min_value=1, max_value=100, value=15)
    max_depth = st.sidebar.slider("Max Depth (%)", min_value=1, max_value=100, value=60)
    recovery_min = st.sidebar.slider("Min Recovery from Bottom (%)", min_value=1, max_value=150, value=60)
    atr_window = st.sidebar.number_input("ATR Window", min_value=1, value=14, step=1)
    compression_lookback = st.sidebar.number_input("Compression Lookback (Weeks)", min_value=1, value=10, step=1)

    params = {
        'MIN_WEEKS': min_weeks,
        'MAX_WEEKS': max_weeks,
        'MIN_WEEKLY_BARS_REQUIRED': min_weeks + 2,
        'MIN_DEPTH': min_depth / 100.0,
        'MAX_DEPTH': max_depth / 100.0,
        'RECOVERY_MIN': recovery_min / 100.0,
        'ATR_WINDOW': atr_window,
        'COMPRESSION_LOOKBACK': compression_lookback,
    }

    # if st.sidebar.button("Run Scan"):
    #     st.session_state.base_scan_results = run_full_scan_base(params)
    if st.sidebar.button("Run Scan"):
        scanner = CupScanner(params, debug=False)
        st.session_state.base_scan_results = scanner.run_scan()
        st.session_state.base_scan_stats = {
            "DMA Filtered": scanner.stats.dma_filtered,
            "ATH Filtered": scanner.stats.ath_filtered,
            "Min Depth": scanner.stats.min_depth,
            "Duration": scanner.stats.duration,
            "Recovery": scanner.stats.recovery,
            "Prior Uptrend": scanner.stats.prior_uptrend,
        }

    if 'base_scan_results' in st.session_state:
        bulk_df = st.session_state.base_scan_results
        if bulk_df.empty:
            st.warning("No stocks found for the given criteria. Try adjusting the parameters and running the scan again.")
        else:
            st.subheader("Stocks with Potential Cup Formations")
            show_only_prior_uptrend = st.checkbox(
                "Show only prior uptrend stocks",
                value=False,
                key="base_show_only_prior_uptrend",
            )

            if "base_scan_stats" in st.session_state:
                stats_df = pd.DataFrame(
                    [
                        {"Stage": stage, "Count": len(symbols), "Symbols": ", ".join(symbols)}
                        for stage, symbols in st.session_state.base_scan_stats.items()
                    ]
                )
                with st.expander("Scanner Stage Details"):
                    st.dataframe(stats_df, use_container_width=True, hide_index=True)
            
            display_df = bulk_df
            if not static_df.empty:
                display_df = bulk_df.merge(static_df, left_on='Symbol', right_on='symbol', how='left')

                # Convert Market Cap to Crores for better readability and sorting
                if 'marketCap' in display_df.columns:
                    display_df['Market Cap (Cr)'] = (display_df['marketCap'] / 1_00_00_000).round(0)

                # Define the desired column order as requested
                metrics_to_front = ['Tight Groups', 'Depth', 'recovery_pct', 'prior_uptrend_pct', 'min_prior_uptrend_pct', 'prior_uptrend', 'pivot']
                bulk_df_cols = [col for col in bulk_df.columns if col not in ['Symbol'] + metrics_to_front]
                static_cols_to_show = ['longName', 'industry', 'sector', 'Market Cap (Cr)']

                # Combine columns in the specified order
                # The original 'marketCap' will be excluded unless explicitly added back.
                ordered_cols = ['Symbol'] + static_cols_to_show + metrics_to_front + bulk_df_cols
                # Filter list to ensure all columns exist in the merged DataFrame
                final_cols = [col for col in ordered_cols if col in display_df.columns]
                display_df = display_df[final_cols]
                if 'Market Cap (Cr)' in display_df.columns:
                    before_market_cap_filter = len(display_df)
                    display_df = display_df[
                        (display_df['Market Cap (Cr)'] >= m_cap)
                        | display_df['Market Cap (Cr)'].isna()
                    ]
                    st.caption(
                        f"Showing {len(display_df)} of {before_market_cap_filter} final candidates "
                        f"after the {m_cap} Cr market-cap filter. Rows with unknown market cap are kept."
                    )

            if show_only_prior_uptrend and "prior_uptrend" in display_df.columns:
                display_df = display_df[display_df["prior_uptrend"] == True]

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
                    selected_deal_symbol = normalize_symbol_for_deals(selected_symbol)

                    if not bulk_deals_df.empty or not block_deals_df.empty:
                        bulk_info = bulk_deals_df[bulk_deals_df['Symbol'] == selected_deal_symbol]
                        block_info = block_deals_df[block_deals_df['Symbol'] == selected_deal_symbol]

                        st.write(f"Bulk/Block Deals for {selected_deal_symbol}")
                        if not bulk_info.empty:
                            st.subheader("Bulk Deals")
                            st.dataframe(bulk_info, use_container_width=True, hide_index=True)
                        if not block_info.empty:
                            st.subheader("Block Deals")
                            st.dataframe(block_info, use_container_width=True, hide_index=True)
                        if bulk_info.empty and block_info.empty:
                            st.info(f"No bulk/block deals found for {selected_deal_symbol}.")

                    if not announcements_df.empty:
                        st.write(f"Announcements for {selected_deal_symbol}")
                        with st.expander(f"📋 View Announcements for {selected_deal_symbol}"):
                            announcement_info = announcements_df[
                                announcements_df['symbol'] == selected_deal_symbol
                            ].copy()
                            if announcement_info.empty:
                                st.info(f"No announcements found for {selected_deal_symbol}.")
                            else:
                                announcement_info = format_announcements_table(announcement_info)
                                st.dataframe(
                                    announcement_info,
                                    use_container_width=True,
                                    hide_index=True,
                                    column_config={
                                        'attachment_url': st.column_config.LinkColumn(
                                            'Attachment URL',
                                            display_text='Open attachment',
                                        )
                                    },
                                )
                    else:
                        st.info("Announcement data file was not found.")

                    # Get the result row for the selected symbol
                    result_row = bulk_df[bulk_df['Symbol'] == selected_symbol].iloc[0].to_dict() if not bulk_df.empty else None

                    # Generate and display the plot
                    fig = plot_cup_formation(weekly_df, selected_symbol, params, result_row=result_row)
                    st.plotly_chart(fig, use_container_width=True)
                    
                except FileNotFoundError:
                    st.error(f"Could not find data file for {selected_symbol}.")
                except Exception as e:
                    st.error(f"An error occurred while plotting {selected_symbol}: {e}")

elif page == "Tracking Phase":
    render_tracking_phase_page(static_df, m_cap)

elif page == "Base Phase":
    render_base_phase_page(static_df, m_cap)

elif page == "Announcements":
    st.title("Announcements")
    st.info("This page shows all available corporate announcements sorted by latest date first.")
    default_start_date = date(2026, 1, 1)
    default_end_date = date.today()

    if announcements_df.empty:
        st.warning("Announcement data file was not found or contains no rows.")
    else:
        filter_col1, filter_col2, filter_col3,filter_col4 = st.columns(4)
        with filter_col1:
            start_date = st.date_input("Start Date", value=default_start_date, key="announcements_start_date")
        with filter_col2:
            end_date = st.date_input("End Date", value=default_end_date, key="announcements_end_date")
        with filter_col3:
            selected_symbol = st.selectbox(
                "Select Symbol",
                options=get_symbol_options(announcements_df, symbol_col="symbol"),
                key="announcements_symbol",
            )
        with filter_col4:
            selected_classification = st.selectbox(
                "Select Classification",
                options=get_column_options(announcements_df, "classification"),
                key="announcements_classification",
            )

        display_announcements_df = filter_by_date_and_symbol(
            announcements_df,
            date_col="date",
            symbol_col="symbol",
            start_date=start_date,
            end_date=end_date,
            selected_symbol=selected_symbol,
            selected_classification=selected_classification

        )
        display_announcements_df = format_announcements_table(display_announcements_df)
        st.caption(f"Showing {len(display_announcements_df)} announcements.")
        if display_announcements_df.empty:
            st.info("No announcements found for the selected filters.")
        else:
            st.dataframe(
                display_announcements_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "attachment_url": st.column_config.LinkColumn(
                        "Attachment URL",
                        display_text="Open attachment",
                    )
                },
            )

elif page == "Earnings Summary":
    render_earnings_summary_page()

elif page == "Audio Transcript":
    st.title("Audio Transcript")
    st.info("Use Gemini to generate a cleaned transcript and structured summary from an NSE audio or mp4 link.")

    st.subheader("Recent Audio Recording Announcements")
    if announcements_df.empty:
        st.info("Announcement data file was not found.")
    else:
        audio_announcements_df = get_audio_recording_announcements(announcements_df, limit=200)
        st.caption(f"Showing {len(audio_announcements_df)} recent audio-related announcements.")
        if audio_announcements_df.empty:
            st.info("No audio recording announcements matched the configured filter.")
        else:
            st.dataframe(
                audio_announcements_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "attachment_url": st.column_config.LinkColumn(
                        "Attachment URL",
                        display_text="Open attachment",
                    )
                },
            )

    with st.form("audio_transcript_form"):
        gemini_api_key = st.text_input("Gemini API Key", type="password")
        symbol = st.text_input("Symbol", placeholder="For example, HAL.NS")
        company_name = st.text_input("Company Name", placeholder="For example, Hindustan Aeronautics")
        audio_url = st.text_input("NSE Audio URL", placeholder="Paste mp3, wav, m4a, or mp4 link")
        submitted = st.form_submit_button("Generate Transcript and Summary")

    log_placeholder = st.empty()
    logs_key = "audio_transcript_logs"

    def ui_progress(message: str) -> None:
        logs = st.session_state.setdefault(logs_key, [])
        logs.append(message)
        st.session_state[logs_key] = logs[-80:]
        log_placeholder.code("\n".join(st.session_state[logs_key]), language="text")

    if submitted:
        st.session_state[logs_key] = []
        try:
            with st.spinner("Processing audio with Gemini..."):
                result = process_audio_request(
                    gemini_api_key=gemini_api_key,
                    symbol=symbol,
                    company_name=company_name,
                    audio_url=audio_url,
                    progress_callback=ui_progress,
                )

            record = result["record"]
            if result["was_cached"]:
                st.success("Loaded saved transcript and summary for this audio URL.")
            else:
                st.success("Transcript and summary generated successfully.")

            st.caption(f"Saved to {result['save_path']}")

            pdf_bytes = build_transcript_pdf(record)
            pdf_name_symbol = (record.get("symbol") or "transcript").replace("/", "_")
            st.download_button(
                "Download PDF",
                data=pdf_bytes,
                file_name=f"{pdf_name_symbol}_transcript_summary.pdf",
                mime="application/pdf",
                use_container_width=False,
            )

            with st.expander("Transcript", expanded=True):
                st.code(record["transcript"], language="markdown")

            with st.expander("Summary", expanded=True):
                st.code(record["summary"], language="markdown")
        except Exception as e:
            st.error(f"Audio processing failed: {e}")

    if symbol.strip():
        try:
            saved_payload = load_saved_records(symbol)
            saved_records = saved_payload.get("records", [])
            if saved_records:
                st.subheader(f"Saved records for {saved_payload['symbol']}")
                records_df = pd.DataFrame(saved_records)
                display_cols = [
                    col for col in ["company_name", "audio_url", "created_at", "model"] if col in records_df.columns
                ]
                st.dataframe(records_df[display_cols], use_container_width=True, hide_index=True)
        except Exception as e:
            st.warning(f"Could not load saved records: {e}")

elif page == "Custom Data Center":
    st.title("Custom Data Center")

    try:
        custom_df = load_custom_data_center()
    except Exception as e:
        st.error(f"Could not load custom data center CSV: {e}")
        custom_df = pd.DataFrame()

    if not custom_df.empty:
        symbols = sorted(custom_df["index_symbol"].dropna().unique().tolist())
        selected_symbol = st.selectbox(
            "Select Symbol",
            options=symbols,
            index=0,
            key="custom_data_center_symbol",
        )

        symbol_df = custom_df[custom_df["index_symbol"] == selected_symbol].copy()
        min_date = symbol_df.index.min().date()
        max_date = symbol_df.index.max().date()

        metrics = st.columns(5)
        metrics[0].metric("Symbol", selected_symbol)
        metrics[1].metric("Start", min_date.isoformat())
        metrics[2].metric("End", max_date.isoformat())
        metrics[3].metric("Rows", f"{len(symbol_df):,}")
        metrics[4].metric("Latest Close", f"{symbol_df['Close'].iloc[-1]:,.2f}")

        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            start_date = st.date_input(
                "Start Date",
                value=min_date,
                min_value=min_date,
                max_value=max_date,
                key="custom_data_center_start_date",
            )
        with filter_col2:
            end_date = st.date_input(
                "End Date",
                value=max_date,
                min_value=min_date,
                max_value=max_date,
                key="custom_data_center_end_date",
            )

        ma_col1, ma_col2, ma_col3, ma_col4 = st.columns(4)
        enabled_mas = []
        with ma_col1:
            if st.checkbox("EMA 10", value=True, key="custom_data_center_ema10"):
                enabled_mas.append("ema10")
        with ma_col2:
            if st.checkbox("EMA 20", value=True, key="custom_data_center_ema20"):
                enabled_mas.append("ema20")
        with ma_col3:
            if st.checkbox("SMA 50", value=True, key="custom_data_center_sma50"):
                enabled_mas.append("sma50")
        with ma_col4:
            if st.checkbox("SMA 200", value=True, key="custom_data_center_sma200"):
                enabled_mas.append("sma200")

        show_nasdaq_comparison = st.checkbox(
            "NASDAQ comparison",
            value=True,
            key="custom_data_center_nasdaq_comparison",
        )

        if start_date > end_date:
            st.error("Start Date must be before or equal to End Date.")
        else:
            filtered_df = symbol_df[
                symbol_df.index.date >= start_date
            ]
            filtered_df = filtered_df[
                filtered_df.index.date <= end_date
            ]

            st.caption(f"Showing {len(filtered_df):,} rows from {start_date} to {end_date}.")
            if filtered_df.empty:
                st.info("No custom data center rows found for the selected date range.")
            else:
                nasdaq_df = None
                if show_nasdaq_comparison:
                    try:
                        nasdaq_df = load_nasdaq_comparison(start_date, end_date)
                    except Exception as e:
                        st.warning(f"Could not load Nasdaq comparison data: {e}")

                fig = plot_custom_ohlcv_chart(
                    filtered_df,
                    selected_symbol,
                    enabled_mas=enabled_mas,
                    comparison_df=nasdaq_df,
                    comparison_label="NASDAQ Composite",
                )
                st.plotly_chart(fig, use_container_width=True)

                with st.expander("Raw Data"):
                    raw_cols = [
                        col
                        for col in ["date", "index_symbol", "Open", "High", "Low", "Close", "Volume", "turnover"]
                        if col in filtered_df.columns
                    ]
                    st.dataframe(
                        filtered_df[raw_cols],
                        use_container_width=True,
                    )

elif page == "Bulk_Block_Deal":
    render_bulk_block_page(bulk_deals_df, block_deals_df, static_df, m_cap)

elif page == "Trend_Follower":
    st.title("Trend Follower Scanner")
    st.info("This scanner identifies stocks that are currently in a strong uptrend.")

    st.sidebar.header("Trend Follower")
    trend_results_path = ROOT_DIR / "ema_trend_follower.csv"

    col1, col2 = st.columns([1, 1])
    with col1:
        run_scan = st.button("Run Trend Scan")
    with col2:
        load_latest = st.button("Load Saved Results")

    if run_scan:
        with st.spinner("Running trend follower scan..."):
            scanner = EMAScanner(str(ROOT_DIR / "data" / "daily"))
            st.session_state.trend_scan_results = scanner.scan()
            st.session_state.trend_scan_results_source = "live"

    if load_latest and trend_results_path.exists():
        st.session_state.trend_scan_results = pd.read_csv(trend_results_path)
        st.session_state.trend_scan_results_source = "saved"

    if "trend_scan_results" not in st.session_state and trend_results_path.exists():
        st.session_state.trend_scan_results = pd.read_csv(trend_results_path)
        st.session_state.trend_scan_results_source = "saved"

    if "trend_scan_results" not in st.session_state:
        st.warning("No trend follower results available yet. Run the scan or load the saved results.")
    else:
        trend_df = st.session_state.trend_scan_results.copy()

        if trend_df.empty:
            st.warning("No stocks matched the trend follower criteria.")
        else:
            display_df = trend_df.merge(static_df, left_on="symbol", right_on="symbol", how="left")

            if "marketCap" in display_df.columns:
                display_df["Market Cap (Cr)"] = (display_df["marketCap"] / 1_00_00_000).round(0)
                display_df = display_df[display_df["Market Cap (Cr)"] >= m_cap]

            preferred_cols = [
                "symbol",
                "longName",
                "sector",
                "industry",
                "Market Cap (Cr)",
                "followers",
                "close",
                "crossover_10_20",
                "duration_ema10",
                "duration_ema21",
                "efficiency",
                "dist_ema10",
                "dist_ema21",
                "slope_ema10",
                "slope_ema21",
                "z_ema10",
                "z_ema21",
            ]
            display_cols = [col for col in preferred_cols if col in display_df.columns]
            display_df = display_df[display_cols]
            display_df = display_df.sort_values(
                by=["efficiency", "duration_ema10", "duration_ema21"],
                ascending=[False, False, False],
            )

            source_label = st.session_state.get("trend_scan_results_source", "saved")
            st.caption(f"Showing {len(display_df)} trend follower candidates from {source_label} results.")

            event = st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
            )

            if event.selection.rows:
                selected_row_index = event.selection.rows[0]
                selected_row = display_df.iloc[selected_row_index]
                selected_symbol = selected_row["symbol"]

                st.subheader(f"Trend Follower Chart for {selected_symbol}")

                try:
                    daily_df = load_daily_price_data(selected_symbol)
                    fig = plot_trend_follower_chart(daily_df, selected_symbol, result_row=selected_row)
                    st.plotly_chart(fig, use_container_width=True)

                    static_info = static_df[static_df["symbol"] == selected_symbol].dropna(axis=1, how="all")
                    if not static_info.empty:
                        st.write("Company Information")
                        st.dataframe(static_info, use_container_width=True, hide_index=True)
                except FileNotFoundError:
                    st.error(f"Could not find data file for {selected_symbol}.")
                except Exception as e:
                    st.error(f"An error occurred while plotting {selected_symbol}: {e}")
