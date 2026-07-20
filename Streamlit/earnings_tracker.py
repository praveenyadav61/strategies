from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


ROOT_DIR = Path(__file__).resolve().parents[1]
CALENDAR_SNAPSHOT_PATH = ROOT_DIR / "data" / "static" / "earnings_calendar.parquet"
CONTEXT_LOOKBACK_DAYS = 90


def _join_symbol(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.upper().str.removesuffix(".NS")


@st.cache_data(show_spinner=False)
def load_calendar_snapshot(path: Path, modified_time: float | None) -> pd.DataFrame:
    del modified_time
    if not path.exists():
        return pd.DataFrame()
    snapshot = pd.read_parquet(path)
    for column in ("Date", "fetched_at", "window_start", "window_end"):
        if column in snapshot.columns:
            snapshot[column] = pd.to_datetime(snapshot[column], errors="coerce")
    return snapshot


def enrich_with_static_data(events: pd.DataFrame, static_df: pd.DataFrame) -> pd.DataFrame:
    if events.empty or static_df.empty or "symbol" not in static_df.columns:
        return events.copy()

    static = static_df.copy()
    static["_join_symbol"] = _join_symbol(static["symbol"])
    fields = ["_join_symbol", "longName", "sector", "industry", "marketCap"]
    static = static[[column for column in fields if column in static.columns]]
    static = static.drop_duplicates("_join_symbol", keep="last")

    enriched = events.copy()
    enriched["_join_symbol"] = _join_symbol(enriched["Symbol"])
    enriched = enriched.merge(static, on="_join_symbol", how="left")
    if "marketCap" in enriched.columns:
        enriched["Market Cap (Cr)"] = (pd.to_numeric(enriched["marketCap"], errors="coerce") / 1e7).round(0)
    if "longName" in enriched.columns:
        enriched["Company"] = enriched["Company"].mask(
            enriched["Company"].eq(""), enriched["longName"]
        )
    return enriched.drop(columns=["_join_symbol", "longName", "marketCap"], errors="ignore")


def filter_company_context(
    df: pd.DataFrame,
    symbol: str,
    date_column: str,
    symbol_column: str,
    end_date: date,
) -> pd.DataFrame:
    if df.empty or date_column not in df.columns or symbol_column not in df.columns:
        return pd.DataFrame()

    result = df.copy()
    result[date_column] = pd.to_datetime(result[date_column], errors="coerce")
    target = str(symbol).strip().upper().removesuffix(".NS")
    symbols = _join_symbol(result[symbol_column])
    start_date = end_date - timedelta(days=CONTEXT_LOOKBACK_DAYS)
    result = result[
        symbols.eq(target)
        & result[date_column].dt.date.between(start_date, end_date)
    ]
    return result.sort_values(date_column, ascending=False, na_position="last")


@st.cache_data(show_spinner=False)
def load_quarterly_history(path: Path, modified_time: float | None) -> pd.DataFrame:
    del modified_time
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _render_context(
    selected: pd.Series,
    announcements_df: pd.DataFrame,
    bulk_deals_df: pd.DataFrame,
    block_deals_df: pd.DataFrame,
) -> None:
    symbol = selected["Symbol"]
    event_timestamp = pd.to_datetime(selected["Date"], errors="coerce")
    context_end = event_timestamp.date() if pd.notna(event_timestamp) else date.today()

    st.subheader(f"{symbol} context")
    if selected.get("Details"):
        st.info(selected["Details"])
    st.caption(f"Activity shown for the 90 days ending {context_end:%d %b %Y}.")

    announcement_rows = filter_company_context(
        announcements_df, symbol, "date", "symbol", context_end
    )
    bulk_rows = filter_company_context(bulk_deals_df, symbol, "Date", "Symbol", context_end)
    block_rows = filter_company_context(block_deals_df, symbol, "Date", "Symbol", context_end)

    announcement_tab, deals_tab, earnings_tab = st.tabs(
        ["Announcements", "Bulk / Block Deals", "Quarterly History"]
    )
    with announcement_tab:
        if announcement_rows.empty:
            st.info("No announcements found in this 90-day window.")
        else:
            preferred = ["date", "subject", "classification", "attachment_text", "attachment_url"]
            shown = announcement_rows[[c for c in preferred if c in announcement_rows.columns]]
            st.dataframe(
                shown,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "attachment_url": st.column_config.LinkColumn(
                        "Attachment URL", display_text="Open attachment"
                    )
                },
            )

    with deals_tab:
        deal_frames = []
        if not bulk_rows.empty:
            bulk_rows = bulk_rows.copy()
            bulk_rows.insert(0, "Deal Type", "Bulk")
            deal_frames.append(bulk_rows)
        if not block_rows.empty:
            block_rows = block_rows.copy()
            block_rows.insert(0, "Deal Type", "Block")
            deal_frames.append(block_rows)
        if not deal_frames:
            st.info("No bulk or block deals found in this 90-day window.")
        else:
            deals = pd.concat(deal_frames, ignore_index=True).sort_values("Date", ascending=False)
            st.dataframe(deals, use_container_width=True, hide_index=True)

    with earnings_tab:
        history_path = ROOT_DIR / "data" / "quarterly" / "earnings_12q_aggregated.parquet"
        modified = history_path.stat().st_mtime if history_path.exists() else None
        history = load_quarterly_history(history_path, modified)
        if not history.empty and "ticker" in history.columns:
            history = history[_join_symbol(history["ticker"]).eq(symbol)].copy()
        if history.empty:
            st.info("No quarterly earnings history found for this company.")
        else:
            sort_column = "quarter_sort_id" if "quarter_sort_id" in history.columns else "quarter_end_date"
            history = history.sort_values(sort_column, ascending=False).head(12)
            preferred = [
                "quarter_label", "quarter_end_date", "revenue", "operating_profit",
                "net_profit", "eps", "revenue_qoq", "revenue_yoy", "profit_qoq",
                "profit_yoy", "data_quality_status", "result_declared_date",
            ]
            st.dataframe(
                history[[c for c in preferred if c in history.columns]],
                use_container_width=True,
                hide_index=True,
            )


def render_earnings_tracker_page(
    static_df: pd.DataFrame,
    announcements_df: pd.DataFrame,
    bulk_deals_df: pd.DataFrame,
    block_deals_df: pd.DataFrame,
) -> None:
    st.title("Earnings Tracker")
    st.caption("Upcoming NSE financial-result meetings with recent company activity.")

    today = date.today()
    with st.form("earnings_tracker_form"):
        col1, col2 = st.columns(2)
        start_date = col1.date_input(
            "Start Date", value=today - timedelta(days=3), key="earnings_tracker_start"
        )
        end_date = col2.date_input(
            "End Date", value=today + timedelta(days=3), key="earnings_tracker_end"
        )
        submitted = st.form_submit_button("Show Earnings", type="primary")

    if submitted:
        if start_date > end_date:
            st.error("Start Date must be before or equal to End Date.")
            st.session_state.pop("earnings_tracker_results", None)
        else:
            modified = (
                CALENDAR_SNAPSHOT_PATH.stat().st_mtime
                if CALENDAR_SNAPSHOT_PATH.exists()
                else None
            )
            snapshot = load_calendar_snapshot(CALENDAR_SNAPSHOT_PATH, modified)
            if snapshot.empty:
                st.error(
                    "The earnings calendar snapshot is unavailable. Run "
                    "scripts/download_earnings_calendar.py to refresh it."
                )
                st.session_state.pop("earnings_tracker_results", None)
            else:
                events = snapshot[
                    snapshot["Date"].dt.date.between(start_date, end_date)
                ].copy()
                st.session_state.earnings_tracker_results = enrich_with_static_data(
                    events, static_df
                )
                st.session_state.earnings_tracker_range = (start_date, end_date)
                fetched = snapshot.get("fetched_at")
                st.session_state.earnings_tracker_fetched_at = (
                    fetched.dropna().max() if fetched is not None else None
                )

    results = st.session_state.get("earnings_tracker_results")
    if results is None:
        return
    if results.empty:
        st.info("No earnings meetings were found for the selected date range.")
        return

    fetched_at = st.session_state.get("earnings_tracker_fetched_at")
    if pd.notna(fetched_at):
        fetched_ist = pd.Timestamp(fetched_at)
        if fetched_ist.tzinfo is None:
            fetched_ist = fetched_ist.tz_localize("UTC")
        fetched_ist = fetched_ist.tz_convert("Asia/Kolkata")
        st.caption(f"Calendar last refreshed: {fetched_ist:%d %b %Y, %I:%M %p IST}")

    display_columns = [
        "Date", "Symbol", "Company", "Purpose", "Market Cap (Cr)",
        "sector", "industry", "Details",
    ]
    display = results[[column for column in display_columns if column in results.columns]]
    selected_event = st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={"Date": st.column_config.DateColumn("Date", format="DD-MMM-YYYY")},
    )
    st.caption(f"Showing {len(display)} earnings meetings. Select a row for company context.")

    if selected_event.selection.rows:
        selected = results.iloc[selected_event.selection.rows[0]]
        _render_context(selected, announcements_df, bulk_deals_df, block_deals_df)
