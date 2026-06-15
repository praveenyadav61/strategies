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
FUND_HOUSE_LOOKBACK_LABEL = "6M"
BULK_HOUSE_LOOKBACK_LABEL = "1Y"

FUND_HOUSE_REGEX_PATTERNS = [
    ("BARODA BNP PARIBAS", [r"BARODA\s+BNP\s+PARIBAS"]),
    ("ADITYA BIRLA SUN LIFE", [r"ADITYA\s+BIRLA\s+SUN\s+LIFE", r"ADITYA\s+BIRLA\s+SUNLIFE"]),
    ("ICICI PRUDENTIAL", [r"ICICI\s+PRUDENTIAL"]),
    ("KOTAK MAHINDRA", [r"KOTAK\s+MAHINDRA"]),
    ("MOTILAL OSWAL", [r"MOTILAL\s+OSWAL"]),
    ("NIPPON INDIA", [r"NIPPON\s+INDIA"]),
    ("MIRAE ASSET", [r"MIRAE\s+ASSET"]),
    ("FRANKLIN TEMPLETON", [r"FRANKLIN\s+TEMPLETON"]),
    ("MAHINDRA MANULIFE", [r"MAHINDRA\s+MANULIFE"]),
    ("WHITEOAK CAPITAL", [r"WHITEOAK\s+CAPITAL"]),
    ("BANK OF INDIA", [r"BANK\s+OF\s+INDIA"]),
    ("CANARA ROBECO", [r"CANARA\s+ROBECO"]),
    ("BNP PARIBAS", [r"\bBNP\s+PARIBAS\b"]),
    ("BANK OF AMERICA", [r"BANK\s+OF\s+AMERICA", r"\bBOFA\b"]),
    ("MERRILL LYNCH", [r"MERRILL\s+LYNCH"]),
    ("GOLDMAN SACHS", [r"GOLDMAN"]),
    ("MORGAN STANLEY", [r"MORGAN\s+STANLEY"]),
    ("SOCIETE GENERALE", [r"SOCIETE\s+GENERALE"]),
    ("J.P. MORGAN", [r"J\s*P\s*MORGAN", r"JP\s*MORGAN"]),
    ("GOVERNMENT OF SINGAPORE", [r"GOVERNMENT\s+OF\s+SINGAPORE"]),
    ("MONETARY AUTHORITY OF SINGAPORE", [r"MONETARY\s+AUTHORITY\s+OF\s+SINGAPORE"]),
    ("NORGES BANK", [r"NORGES\s+BANK"]),
    ("T. ROWE PRICE", [r"T\s*ROWE\s*PRICE"]),
    ("APMS INVESTMENT FUND", [r"APMS\s+INVESTMENT\s+FUND"]),
    ("LIGHTHOUSE FUNDS", [r"LIGHTHOUSE\s+FUNDS"]),
    ("STEADVIEW CAPITAL", [r"STEADVIEW\s+CAPITAL"]),
    ("ELARA CAPITAL", [r"ELARA\s+CAPITAL"]),
    ("NALANDA CAPITAL", [r"NALANDA\s+CAPITAL"]),
    ("AMANSA CAPITAL", [r"AMANSA\s+CAPITAL"]),
    ("ARES MANAGEMENT", [r"ARES\s+MANAGEMENT"]),
    ("FIDELITY", [r"FIDELITY"]),
    ("VANGUARD", [r"VANGUARD"]),
    ("NOMURA", [r"NOMURA"]),
    ("UBS", [r"\bUBS\b"]),
    ("CITIGROUP", [r"CITIGROUP", r"\bCITI\b"]),
    ("INVESCO", [r"\bINVESCO\b"]),
    ("MINERVA", [r"MINERVA"]),
    ("HDFC", [r"\bHDFC\b"]),
    ("SBI", [r"\bSBI\b"]),
    ("QUANT", [r"\bQUANT\b"]),
    ("DSP", [r"\bDSP\b"]),
    ("BANDHAN", [r"\bBANDHAN\b"]),
    ("AXIS", [r"\bAXIS\b"]),
    ("TATA", [r"\bTATA\b"]),
    ("PPFAS", [r"\bPPFAS\b", r"PARAG\s+PARIKH"]),
    ("HSBC", [r"\bHSBC\b"]),
    ("SUNDARAM", [r"\bSUNDARAM\b"]),
    ("UTI", [r"\bUTI\b"]),
    ("EDELWEISS", [r"\bEDELWEISS\b"]),
    ("DESERET", [r"\bDESERET\b"]),
    ("BAJAJ FINSERV", [r"BAJAJ\s+FINSERV"]),
    ("RELIANCE", [r"\bRELIANCE\b"]),
    ("LIC", [r"\bLIC\b"]),
]


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


def extract_fund_house_name(client_name: str) -> str | None:
    """
    Map raw client names to curated canonical fund / investment house names.
    """
    normalized = normalize_client_name(pd.Series([client_name])).iloc[0]
    for canonical_name, patterns in FUND_HOUSE_REGEX_PATTERNS:
        for pattern in patterns:
            if pd.Series([normalized]).str.contains(pattern, regex=True, na=False).iloc[0]:
                return canonical_name
    return None


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


def apply_market_cap_filter(df: pd.DataFrame, static_df: pd.DataFrame, min_market_cap_cr: float) -> pd.DataFrame:
    if df.empty or static_df.empty or "Symbol" not in df.columns or "symbol" not in static_df.columns:
        return df

    merge_df = df.copy()
    merge_df["Merge Symbol"] = merge_df["Symbol"].astype(str).str.strip().str.upper()

    static_merge = static_df.copy()
    static_merge["Merge Symbol"] = (
        static_merge["symbol"]
        .astype(str)
        .str.replace(".NS", "", regex=False)
        .str.strip()
        .str.upper()
    )

    merged = merge_df.merge(static_merge, on="Merge Symbol", how="left")
    if "marketCap" in merged.columns:
        merged["Market Cap (Cr)"] = (merged["marketCap"] / 1_00_00_000).round(0)
        merged = merged[merged["Market Cap (Cr)"] >= min_market_cap_cr]

    return merged


def attach_fund_house(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Client Name" not in df.columns:
        return pd.DataFrame()

    enriched = df.copy()
    enriched["Fund House"] = enriched["Client Name"].apply(extract_fund_house_name)
    enriched = enriched[enriched["Fund House"].notna()].copy()
    return enriched


def format_ticker_list(group: pd.DataFrame, date_col: str) -> str:
    ordered = group.sort_values(by=date_col, ascending=False).drop_duplicates(subset=["Symbol"])
    tickers = ordered["Symbol"].astype(str).tolist()
    return "[" + ", ".join(tickers) + "]"


def format_recent_ticker_list(group: pd.DataFrame, date_col: str, recent_days: int = 7) -> str:
    latest_date = group[date_col].max()
    if pd.isna(latest_date):
        return "[]"

    recent_cutoff = latest_date - pd.Timedelta(days=recent_days - 1)
    recent_group = group[group[date_col] >= recent_cutoff].copy()
    if recent_group.empty:
        return "[]"

    ordered = recent_group.sort_values(by=date_col, ascending=False).drop_duplicates(subset=["Symbol"])
    tickers = ordered["Symbol"].astype(str).tolist()
    return "[" + ", ".join(tickers) + "]"


def summarize_by_fund_house(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Fund House", "Latest Buy Date", "Stock Count", "Tickers", "Recent 7D Stocks"])

    enriched = attach_fund_house(df)
    if enriched.empty:
        return pd.DataFrame(columns=["Fund House", "Latest Buy Date", "Stock Count", "Tickers", "Recent 7D Stocks"])

    records = []
    for fund_house, group in enriched.groupby("Fund House", sort=False):
        records.append(
            {
                "Fund House": fund_house,
                "Latest Buy Date": group[date_col].max(),
                "Stock Count": group["Symbol"].nunique(),
                "Tickers": format_ticker_list(group, date_col),
                "Recent 7D Stocks": format_recent_ticker_list(group, date_col),
            }
        )

    return pd.DataFrame(records).sort_values(
        ["Latest Buy Date", "Stock Count", "Fund House"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def format_fund_house_list(group: pd.DataFrame, date_col: str) -> str:
    ordered = group.sort_values(by=date_col, ascending=False).drop_duplicates(subset=["Fund House"])
    houses = ordered["Fund House"].astype(str).tolist()
    return "[" + ", ".join(houses) + "]"


def format_recent_fund_house_list(group: pd.DataFrame, date_col: str, recent_days: int = 7) -> str:
    latest_date = group[date_col].max()
    if pd.isna(latest_date):
        return "[]"

    recent_cutoff = latest_date - pd.Timedelta(days=recent_days - 1)
    recent_group = group[group[date_col] >= recent_cutoff].copy()
    if recent_group.empty:
        return "[]"

    ordered = recent_group.sort_values(by=date_col, ascending=False).drop_duplicates(subset=["Fund House"])
    houses = ordered["Fund House"].astype(str).tolist()
    return "[" + ", ".join(houses) + "]"


def summarize_by_ticker(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """
    Reverse of summarize_by_fund_house:
    for each ticker, show which fund houses bought it and the latest buy date.
    """
    if df.empty:
        return pd.DataFrame(columns=["Symbol", "Latest Buy Date", "Fund House Count", "Fund Houses", "Recent 7D Fund Houses"])

    enriched = attach_fund_house(df)
    if enriched.empty:
        return pd.DataFrame(columns=["Symbol", "Latest Buy Date", "Fund House Count", "Fund Houses", "Recent 7D Fund Houses"])

    records = []
    for symbol, group in enriched.groupby("Symbol", sort=False):
        records.append(
            {
                "Symbol": symbol,
                "Latest Buy Date": group[date_col].max(),
                "Fund House Count": group["Fund House"].nunique(),
                "Fund Houses": format_fund_house_list(group, date_col),
                "Recent 7D Fund Houses": format_recent_fund_house_list(group, date_col),
            }
        )

    return pd.DataFrame(records).sort_values(
        ["Latest Buy Date", "Fund House Count", "Symbol"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def render_bulk_block_page(
    bulk_deals_df: pd.DataFrame,
    block_deals_df: pd.DataFrame,
    static_df: pd.DataFrame,
    min_market_cap_cr: float,
) -> None:
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
        stock_view_tab, house_view_tab = st.tabs(["Stock View", "Fund House View"])

        with stock_view_tab:
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
                fresh_buy_df = apply_market_cap_filter(fresh_buy_df, static_df, min_market_cap_cr)
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
                repeated_buy_df = apply_market_cap_filter(repeated_buy_df, static_df, min_market_cap_cr)
                st.caption(
                    f"Showing {len(repeated_buy_df)} repeated-buy rows in {lookback_label} "
                    f"with at least {min_buy_count} distinct buy dates."
                )
                if repeated_buy_df.empty:
                    st.info("No repeated buys found for the selected filters.")
                else:
                    st.dataframe(repeated_buy_df, use_container_width=True, hide_index=True)

        with house_view_tab:
            house_col1, house_col2 = st.columns(2)
            with house_col1:
                house_analysis_mode = st.radio(
                    "House Analysis",
                    options=["Fresh Buy", "Repeated Buy"],
                    horizontal=True,
                    key="bulk_house_analysis_mode",
                )
            with house_col2:
                house_min_buy_count = st.number_input(
                    "House Min Buy Count",
                    min_value=2,
                    value=3,
                    step=1,
                    key="bulk_house_min_count",
                )

            

            if house_analysis_mode == "Fresh Buy":
                house_base_df = get_fresh_buy_table(bulk_df, FUND_HOUSE_LOOKBACK_LABEL, date.today())
                # st.write(f"Identified {len(house_base_df)} fresh buy rows within {FUND_HOUSE_LOOKBACK_LABEL} for fund-house analysis, based on first buys across stored history.")
                # house_base_df = apply_market_cap_filter(house_base_df, static_df, min_market_cap_cr)
                fund_house_df = summarize_by_fund_house(house_base_df, "Date")
                if fund_house_df.empty:
                    st.info("No fund-house fresh buys found for the current 1Y view.")
                else:
                    st.caption("Fund-house view uses a fixed 6M lookback and is sorted by latest buy date.")
                    st.dataframe(fund_house_df, use_container_width=True, hide_index=True)
                    st.subheader("Ticker View")
                    ticker_summary_df = summarize_by_ticker(house_base_df, "Date")
                    if ticker_summary_df.empty:
                        st.info("No ticker-wise fund-house summary found for these fresh buys.")
                    else:
                        st.dataframe(ticker_summary_df, use_container_width=True, hide_index=True)
            else:
                house_base_df = get_repeated_buy_table(
                    bulk_df,
                    BULK_HOUSE_LOOKBACK_LABEL,
                    date.today(),
                    house_min_buy_count,
                )
                # house_base_df = apply_market_cap_filter(house_base_df, static_df, min_market_cap_cr)
                fund_house_df = summarize_by_fund_house(house_base_df, "Latest Buy Date")
                if fund_house_df.empty:
                    st.info("No fund-house repeated buys found for the current 1Y view.")
                else:
                    st.caption("Fund-house view uses a fixed 1Y lookback and is sorted by latest buy date.")
                    st.dataframe(fund_house_df, use_container_width=True, hide_index=True)
                    st.subheader("Ticker View")
                    ticker_summary_df = summarize_by_ticker(fund_house_df, "Latest Buy Date")
                    if ticker_summary_df.empty:
                        st.info("No ticker-wise fund-house summary found for these repeated buys.")
                    else:
                        st.dataframe(ticker_summary_df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    df=pd.read_parquet("/Users/shrinivasdachawar/Downloads/My_docccc/zzti/strategies/data/deals_data/bulk_deals.parquet")
    df=df.sort_values(by="Date", ascending=False).reset_index(drop=True)
    house_base_df = get_fresh_buy_table(df, FUND_HOUSE_LOOKBACK_LABEL, date.today())
    fund_house_df = summarize_by_fund_house(house_base_df, "Date")
    # fund_house_df.to_csv("/Users/shrinivasdachawar/Downloads/My_docccc/zzti/strategies/data/deals_data/fund_house_fresh_buy_summary.csv", index=False)
