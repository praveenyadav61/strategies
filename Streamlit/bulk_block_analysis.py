from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st


LOOKBACK_OPTIONS = {
    "3M": pd.DateOffset(months=3),
    "6M": pd.DateOffset(months=6),
    "1Y": pd.DateOffset(years=1),
    "2Y": pd.DateOffset(years=2),
}


def normalize_client_name(series: pd.Series) -> pd.Series:
    """
    Conservative client-name normalization.

    We only normalize casing and spacing so we do not accidentally merge
    different legal entities that happen to look similar.
    """
    return (
        series.astype(str)
        .str.upper()
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )


def prepare_bulk_fund_data(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    prepared = df.copy()
    prepared.columns = prepared.columns.str.strip()

    if "Date" in prepared.columns:
        prepared["Date"] = pd.to_datetime(prepared["Date"], errors="coerce")
    if "Symbol" in prepared.columns:
        prepared["Symbol"] = prepared["Symbol"].astype(str).str.strip().str.upper()
    if "Client Name" in prepared.columns:
        prepared["Client Name"] = prepared["Client Name"].astype(str).str.strip()
        prepared["Normalized Client Name"] = normalize_client_name(prepared["Client Name"])
    else:
        prepared["Normalized Client Name"] = ""

    if "Buy / Sell" in prepared.columns:
        prepared["Buy / Sell"] = prepared["Buy / Sell"].astype(str).str.strip().str.upper()

    return prepared


def get_lookback_start(end_date: date, lookback_label: str) -> pd.Timestamp:
    offset = LOOKBACK_OPTIONS[lookback_label]
    return pd.Timestamp(end_date) - offset


def filter_deals_by_window(df: pd.DataFrame, start_date: date, end_date: date, selected_symbol: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    filtered = df.copy()
    if "Date" in filtered.columns:
        filtered = filtered[filtered["Date"].notna()]
        filtered = filtered[
            filtered["Date"].dt.date.between(start_date, end_date)
        ]

    if selected_symbol != "All" and "Symbol" in filtered.columns:
        filtered = filtered[filtered["Symbol"] == selected_symbol]

    return filtered


def exclude_buy_sell_mix(df: pd.DataFrame) -> pd.DataFrame:
    """
    Exclude client-symbol pairs that have both BUY and SELL within the current
    analysis window.
    """
    if df.empty:
        return df.copy()

    group_cols = ["Symbol", "Normalized Client Name"]
    required = group_cols + ["Buy / Sell"]
    if any(col not in df.columns for col in required):
        return df.copy()

    clean_df = df.copy()
    side_counts = clean_df.groupby(group_cols)["Buy / Sell"].nunique()
    valid_pairs = side_counts[side_counts == 1].index

    if len(valid_pairs) == 0:
        return clean_df.iloc[0:0].copy()

    valid_index = pd.MultiIndex.from_frame(clean_df[group_cols])
    return clean_df[valid_index.isin(valid_pairs)].copy()


def get_fresh_buy_table(df: pd.DataFrame, lookback_label: str, end_date: date) -> pd.DataFrame:
    """
    Fresh buy = first BUY for Client + Symbol in the stored history.

    We compute the first BUY across all available history, then filter the
    resulting first-buy rows to the selected lookback for easier review.
    """
    if df.empty:
        return pd.DataFrame()

    prepared = prepare_bulk_fund_data(df)
    buy_df = prepared[prepared["Buy / Sell"] == "BUY"].copy()
    if buy_df.empty:
        return pd.DataFrame()

    first_buy = (
        buy_df.sort_values("Date")
        .groupby(["Symbol", "Normalized Client Name"], as_index=False)
        .first()
    )

    lookback_start = get_lookback_start(end_date, lookback_label)
    first_buy = first_buy[first_buy["Date"] >= lookback_start].copy()

    preferred_cols = [
        "Date",
        "Symbol",
        "Security Name",
        "Client Name",
        "Quantity Traded",
        "Trade Price / Wght. Avg. Price",
        "Remarks",
        "fetch_date",
    ]
    final_cols = [col for col in preferred_cols if col in first_buy.columns]
    return first_buy[final_cols].sort_values("Date", ascending=False).reset_index(drop=True)


def get_repeated_buy_table(df: pd.DataFrame, lookback_label: str, end_date: date, min_buy_count: int) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    prepared = prepare_bulk_fund_data(df)
    lookback_start = get_lookback_start(end_date, lookback_label)
    window_df = prepared[prepared["Date"] >= lookback_start].copy()
    if window_df.empty:
        return pd.DataFrame()

    window_df = exclude_buy_sell_mix(window_df)
    buy_df = window_df[window_df["Buy / Sell"] == "BUY"].copy()
    if buy_df.empty:
        return pd.DataFrame()

    repeated = (
        buy_df.groupby(["Symbol", "Normalized Client Name"], as_index=False)
        .agg(
            **{
                "Security Name": ("Security Name", "first"),
                "Client Name": ("Client Name", "first"),
                "Buy Count": ("Date", lambda s: s.dt.normalize().nunique()),
                "First Buy Date": ("Date", "min"),
                "Latest Buy Date": ("Date", "max"),
                "Total Quantity": ("Quantity Traded", "sum"),
            }
        )
    )

    repeated = repeated[repeated["Buy Count"] >= min_buy_count].copy()
    if repeated.empty:
        return repeated

    display_cols = [
        "Symbol",
        "Security Name",
        "Client Name",
        "Buy Count",
        "First Buy Date",
        "Latest Buy Date",
        "Total Quantity",
    ]
    return repeated[display_cols].sort_values(
        ["Buy Count", "Latest Buy Date", "Symbol"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def get_symbol_options(*frames: pd.DataFrame) -> list[str]:
    symbols: set[str] = set()
    for df in frames:
        if not df.empty and "Symbol" in df.columns:
            symbols.update(df["Symbol"].dropna().astype(str).str.strip().tolist())
    return ["All"] + sorted(symbol for symbol in symbols if symbol)


def render_bulk_block_page(bulk_deals_df: pd.DataFrame, block_deals_df: pd.DataFrame) -> None:
    st.title("Bulk Block Deal Scanner")
    st.info("Track raw bulk/block deals and analyze fresh or repeated bulk-buy activity by funds/clients.")

    default_start_date = date(2026, 1, 1)
    default_end_date = date.today()

    bulk_df = prepare_bulk_fund_data(bulk_deals_df)
    block_df = prepare_bulk_fund_data(block_deals_df)

    tab_raw, tab_activity = st.tabs(["Bulk/Block Deals", "Fund Activity"])

    with tab_raw:
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            start_date = st.date_input("Start Date", value=default_start_date, key="bulk_block_start_date")
        with filter_col2:
            end_date = st.date_input("End Date", value=default_end_date, key="bulk_block_end_date")
        with filter_col3:
            selected_symbol = st.selectbox(
                "Select Symbol",
                options=get_symbol_options(bulk_df, block_df),
                key="bulk_block_symbol",
            )

        filtered_bulk = filter_deals_by_window(bulk_df, start_date, end_date, selected_symbol)
        filtered_block = filter_deals_by_window(block_df, start_date, end_date, selected_symbol)

        st.caption(f"Bulk deals: {len(filtered_bulk)} | Block deals: {len(filtered_block)}")

        st.subheader("Bulk Deals")
        if filtered_bulk.empty:
            st.info("No bulk deals found for the selected filters.")
        else:
            st.dataframe(
                filtered_bulk.sort_values(by="Date", ascending=False),
                use_container_width=True,
                hide_index=True,
            )

        st.subheader("Block Deals")
        if filtered_block.empty:
            st.info("No block deals found for the selected filters.")
        else:
            st.dataframe(
                filtered_block.sort_values(by="Date", ascending=False),
                use_container_width=True,
                hide_index=True,
            )

    with tab_activity:
        control_col1, control_col2, control_col3 = st.columns(3)
        with control_col1:
            analysis_mode = st.radio(
                "Analysis",
                options=["Fresh Buy", "Repeated Buy"],
                horizontal=True,
                key="bulk_fund_analysis_mode",
            )
        with control_col2:
            lookback_label = st.selectbox(
                "Lookback Window",
                options=list(LOOKBACK_OPTIONS.keys()),
                index=1,
                key="bulk_fund_lookback",
            )
        with control_col3:
            min_buy_count = st.number_input(
                "Min Buy Count",
                min_value=2,
                value=3,
                step=1,
                key="bulk_repeated_min_count",
            )

        if analysis_mode == "Fresh Buy":
            fresh_buy_df = get_fresh_buy_table(bulk_df, lookback_label, date.today())
            st.caption(f"Showing {len(fresh_buy_df)} fresh-buy rows within {lookback_label}, based on first buys across stored history.")
            if fresh_buy_df.empty:
                st.info("No fresh buys found for the selected window.")
            else:
                st.dataframe(fresh_buy_df, use_container_width=True, hide_index=True)
        else:
            repeated_buy_df = get_repeated_buy_table(
                bulk_df,
                lookback_label,
                date.today(),
                min_buy_count,
            )
            st.caption(
                f"Showing {len(repeated_buy_df)} repeated-buy rows in {lookback_label} "
                f"with at least {min_buy_count} distinct buy dates."
            )
            if repeated_buy_df.empty:
                st.info("No repeated buys found for the selected filters.")
            else:
                st.dataframe(repeated_buy_df, use_container_width=True, hide_index=True)
