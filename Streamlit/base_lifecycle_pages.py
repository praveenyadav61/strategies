from pathlib import Path

import pandas as pd
import streamlit as st

from chart_plot import plot_cup_formation


ROOT_DIR = Path(__file__).resolve().parents[1]
TRACKING_DIR = ROOT_DIR / "data" / "base_lifecycle_tracking"
STAGE_KEYS = [
    "daily_trend_passed",
    "weekly_data_passed",
    "depth_passed",
    "recovery_passed",
    "prior_uptrend_passed",
    "pivot_evaluated",
    "final_candidates",
    "rejected",
]
BASE_LIFECYCLE_DEFAULT_PARAMS = {
    "MIN_WEEKS": 8,
    "MAX_WEEKS": 104,
    "BASE_WINDOWS": [26, 52, 104],
    "MIN_WEEKLY_BARS_REQUIRED": 10,
    "MIN_DEPTH": 0.15,
    "MAX_DEPTH": 0.60,
    "RECOVERY_MIN": 0.60,
    "TRACKING_ELIGIBLE_RECOVERY_MIN": 0.85,
    "MIN_PRIOR_UPTREND_PCT": 0.20,
    "PRIOR_UPTREND_DEPTH_MULTIPLIER": 1.0,
    "ATR_WINDOW": 14,
    "COMPRESSION_LOOKBACK": 10,
}


def long_frame_to_stage_results(stage_df):
    if stage_df is None or stage_df.empty or "stage" not in stage_df.columns:
        return {stage: pd.DataFrame() for stage in STAGE_KEYS}

    return {
        stage: stage_df[stage_df["stage"] == stage].drop(columns=["stage"]).reset_index(drop=True)
        for stage in STAGE_KEYS
    }


def load_tracking_state():
    paths = {
        "active": TRACKING_DIR / "active_tracked_bases.parquet",
        "history": TRACKING_DIR / "tracking_history.parquet",
        "archived": TRACKING_DIR / "archived_tracked_bases.parquet",
    }
    return {
        key: pd.read_parquet(path) if path.exists() else pd.DataFrame()
        for key, path in paths.items()
    }


def load_daily_price_data(symbol):
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


def get_lifecycle_snapshot_dates():
    scan_dir = ROOT_DIR / "data" / "base_lifecycle_scans"
    if not scan_dir.exists():
        return []

    dates = []
    for path in scan_dir.glob("base_lifecycle_*.parquet"):
        if path.name.startswith("base_lifecycle_windows_") or path.name.startswith("base_lifecycle_stages_"):
            continue
        dates.append(path.stem.replace("base_lifecycle_", ""))
    return sorted(set(dates), reverse=True)


def select_lifecycle_snapshot_date(key):
    snapshot_dates = get_lifecycle_snapshot_dates()
    if not snapshot_dates:
        return None

    return st.sidebar.selectbox(
        "Lifecycle Snapshot Date",
        options=snapshot_dates,
        index=0,
        key=key,
    )


def load_lifecycle_saved_state(snapshot_date=None):
    scan_dir = ROOT_DIR / "data" / "base_lifecycle_scans"
    if snapshot_date:
        lifecycle_path = scan_dir / f"base_lifecycle_{snapshot_date}.parquet"
        windows_path = scan_dir / f"base_lifecycle_windows_{snapshot_date}.parquet"
        stage_path = scan_dir / f"base_lifecycle_stages_{snapshot_date}.parquet"
    else:
        lifecycle_path = scan_dir / "latest.parquet"
        windows_path = scan_dir / "latest_windows.parquet"
        stage_path = scan_dir / "latest_stage_results.parquet"

    lifecycle_df = pd.read_parquet(lifecycle_path) if lifecycle_path.exists() else pd.DataFrame()
    all_windows_df = pd.read_parquet(windows_path) if windows_path.exists() else pd.DataFrame()
    stage_results = long_frame_to_stage_results(pd.read_parquet(stage_path)) if stage_path.exists() else {}
    return lifecycle_df, all_windows_df, stage_results


def lifecycle_bucket(row):
    status = row.get("lifecycle_status")
    distance = row.get("distance_from_pivot_pct")
    breakout_date = row.get("breakout_date")

    if status == "NEAR_PIVOT":
        return "Near Pivot"
    if status in [
        "BREAKOUT_ATTEMPT",
        "BREAKOUT_CONFIRMED",
        "HANDLE_BREAKOUT_ATTEMPT",
        "HANDLE_BREAKOUT_CONFIRMED",
        "CLOSE_RESISTANCE_CLEARED",
    ]:
        return "Breakout Watch"
    if status in ["PULLBACK_TO_PIVOT", "PIVOT_RETEST_WEAK", "HOLDING_PIVOT", "RESETTING"]:
        return "Pullbacks"
    if status == "EXTENDED":
        return "Extended"
    if status == "FAILED":
        return "Failed"
    if pd.notna(distance) and distance > 0:
        return "Breakout Watch"
    return "Fresh Bases"


def add_lifecycle_display_columns(df, static_df, m_cap, all_windows_df=None):
    if df.empty:
        return df

    display_df = df.copy()
    display_df["Bucket"] = display_df.apply(lifecycle_bucket, axis=1)

    if (
        all_windows_df is not None
        and not all_windows_df.empty
        and {"Symbol", "scan_window_weeks"}.issubset(all_windows_df.columns)
    ):
        window_summary = (
            all_windows_df.groupby("Symbol")["scan_window_weeks"]
            .apply(lambda values: ", ".join(str(int(value)) for value in sorted(values.dropna().unique())))
            .rename("Also Valid Windows")
            .reset_index()
        )
        display_df = display_df.merge(window_summary, on="Symbol", how="left")

    if static_df is not None and not static_df.empty:
        display_df = display_df.merge(static_df, left_on="Symbol", right_on="symbol", how="left")
        if "marketCap" in display_df.columns:
            display_df["Market Cap (Cr)"] = (display_df["marketCap"] / 1_00_00_000).round(0)
            display_df = display_df[
                (display_df["Market Cap (Cr)"] >= m_cap)
                | display_df["Market Cap (Cr)"].isna()
            ]

    return display_df


def lifecycle_preferred_table(df):
    # Keep the scan list focused on the decision fields. Company metadata,
    # review tags, dates, and diagnostics are shown after a row is selected.
    preferred_cols = [
        "rank",
        "Symbol",
        "lifecycle_status",
        "tracking_state",
        "scan_window_weeks",
        "Depth",
        "recovery_pct",
        "prior_uptrend_pct",
        "distance_from_pivot_pct",
        "major_pivot",
        "left_high_pivot",
        "handle_high_pivot",
        "resistance_cluster_pivot",
        "range_high_pivot",
        "range_close_pivot",
        "tracking_eligible",
        "breakout_date",
        "holding_pivot",
    ]
    cols = [col for col in preferred_cols if col in df.columns]
    return df[cols]


def lifecycle_selected_detail_frame(row, columns):
    details = []
    for column in columns:
        if column not in row.index:
            continue
        value = row.get(column)
        if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
            continue
        details.append({"Field": column.replace("_", " ").title(), "Value": str(value)})
    return pd.DataFrame(details)


def render_lifecycle_selected_details(selected_row):
    company_and_tags = [
        "longName",
        "sector",
        "industry",
        "Market Cap (Cr)",
        "Bucket",
        "review_status",
        "setup_rating",
        "notes",
        "last_reviewed_date",
        "setup_reason",
    ]
    pivot_and_diagnostics = [
        "score",
        "score_delta",
        "weekly_change",
        "Also Valid Windows",
        "base_duration_weeks",
        "peak_to_low_weeks",
        "pivot_detected",
        "major_pivot_date",
        "major_pivot_validated",
        "major_breakout_buffer",
        "major_confirmation_level",
        "major_failure_buffer",
        "major_failure_level",
        "hard_failure",
        "persistent_failure",
        "left_high_pivot_date",
        "handle_high_date",
        "handle_pullback_pct",
        "resistance_cluster_touches",
        "resistance_cluster_start",
        "resistance_cluster_end",
        "range_high_pivot_date",
        "close_high_pivot_date",
        "range_close_pivot_date",
        "handle_pivot",
        "handle_breakout_buffer",
        "handle_confirmation_level",
        "handle_failure_buffer",
        "handle_failure_level",
        "handle_breakout_date",
        "handle_breakout_failed",
        "legacy_pivot_price",
        "legacy_pivot_detected",
        "active_pivot_price",
        "active_pivot_type",
        "active_pivot_distance_pct",
        "weeks_since_breakout",
        "gain_since_breakout_pct",
        "max_gain_after_breakout_pct",
        "pullback_from_post_breakout_high_pct",
    ]

    company_df = lifecycle_selected_detail_frame(selected_row, company_and_tags)
    diagnostics_df = lifecycle_selected_detail_frame(selected_row, pivot_and_diagnostics)
    if company_df.empty and diagnostics_df.empty:
        return

    with st.expander("Selected stock details", expanded=True):
        company_col, diagnostics_col = st.columns(2)
        with company_col:
            st.caption("Company and review tags")
            if company_df.empty:
                st.caption("No company or tagging data available.")
            else:
                st.dataframe(company_df, use_container_width=True, hide_index=True)
        with diagnostics_col:
            st.caption("Pivot and scan diagnostics")
            if diagnostics_df.empty:
                st.caption("No additional diagnostics available.")
            else:
                st.dataframe(diagnostics_df, use_container_width=True, hide_index=True)


def render_lifecycle_chart_for_symbol(symbol, result_row=None, max_weeks=None):
    daily_df = load_daily_price_data(symbol)
    weekly_df = daily_df.resample("W").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    ).dropna()

    chart_params = BASE_LIFECYCLE_DEFAULT_PARAMS.copy()
    chart_params["MAX_WEEKS"] = int(max_weeks) if pd.notna(max_weeks) else max(chart_params["BASE_WINDOWS"])
    return plot_cup_formation(weekly_df, symbol, chart_params, result_row=result_row)


def render_lifecycle_table_with_chart(display_df, key_prefix, source_df=None):
    if display_df.empty:
        st.info("No rows available for this view.")
        return

    event = st.dataframe(
        lifecycle_preferred_table(display_df),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"{key_prefix}_table",
    )

    if event.selection.rows:
        selected_row = display_df.iloc[event.selection.rows[0]]
        selected_symbol = selected_row["Symbol"]
        st.subheader(f"Chart for {selected_symbol}")
        render_lifecycle_selected_details(selected_row)
        try:
            result_lookup_df = source_df if source_df is not None and not source_df.empty else display_df
            result_row = (
                result_lookup_df[result_lookup_df["Symbol"] == selected_symbol].iloc[0].to_dict()
                if "Symbol" in result_lookup_df.columns
                and not result_lookup_df[result_lookup_df["Symbol"] == selected_symbol].empty
                else selected_row.to_dict()
            )
            fig = render_lifecycle_chart_for_symbol(
                selected_symbol,
                result_row=result_row,
                max_weeks=selected_row.get("scan_window_weeks"),
            )
            st.plotly_chart(fig, use_container_width=True)
        except FileNotFoundError:
            st.error(f"Could not find data file for {selected_symbol}.")
        except Exception as e:
            st.error(f"An error occurred while plotting {selected_symbol}: {e}")


def stage_labels():
    return [
        ("Final Candidates", "final_candidates"),
        ("Daily Trend", "daily_trend_passed"),
        ("Weekly Data", "weekly_data_passed"),
        ("Depth", "depth_passed"),
        ("Recovery", "recovery_passed"),
        ("Prior Uptrend", "prior_uptrend_passed"),
        ("Pivot Evaluated", "pivot_evaluated"),
        ("Rejected", "rejected"),
    ]


def render_review_funnel(stage_results, lifecycle_df):
    labels = stage_labels()
    stage_frames = {
        stage: frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
        for _, stage in labels
        for frame in [stage_results.get(stage, pd.DataFrame())]
    }
    with st.expander("Review Funnel", expanded=True):
        stage_summary_df = pd.DataFrame(
            [
                {
                    "Stage": label,
                    "Count": len(stage_frames[stage]),
                    "Unique Stocks": (
                        stage_frames[stage]["Symbol"].nunique()
                        if "Symbol" in stage_frames[stage].columns
                        else 0
                    ),
                    "Unique Windows": (
                        stage_frames[stage]["scan_window_weeks"].nunique()
                        if "scan_window_weeks" in stage_frames[stage].columns
                        else 0
                    ),
                }
                for label, stage in labels
            ]
        )
        st.dataframe(stage_summary_df, use_container_width=True, hide_index=True)

        selected_stage_label = st.selectbox(
            "Review Stage",
            options=[label for label, _ in labels],
            index=0,
            key="lifecycle_review_stage",
        )
        selected_stage = dict(labels)[selected_stage_label]
        stage_df = stage_frames.get(selected_stage, pd.DataFrame()).copy()
        if stage_df.empty:
            st.info(f"No rows available for {selected_stage_label}.")
            return

        stage_preferred_cols = [
            "Symbol",
            "scan_window_weeks",
            "failure_reason",
            "latest_close",
            "weekly_bars",
            "required_weekly_bars",
            "Depth",
            "recovery_pct",
            "prior_uptrend_pct",
            "min_prior_uptrend_pct",
            "prior_uptrend_lookback_weeks",
            "prior_uptrend_advance_weeks",
            "peak_to_low_weeks",
            "pivot_price",
            "pivot_detected",
            "distance_from_pivot_pct",
            "lifecycle_status",
            "setup_reason",
            "tracking_eligible",
            "score",
        ]
        stage_cols = [col for col in stage_preferred_cols if col in stage_df.columns]
        stage_display_df = stage_df[stage_cols]
        stage_event = st.dataframe(
            stage_display_df,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="lifecycle_review_funnel_table",
        )

        if stage_event.selection.rows:
            selected_stage_row = stage_display_df.iloc[stage_event.selection.rows[0]]
            selected_stage_symbol = selected_stage_row["Symbol"]
            st.subheader(f"Review Chart for {selected_stage_symbol}")
            try:
                result_row = selected_stage_row.to_dict()
                if "pivot_index" not in result_row and selected_stage_symbol in set(lifecycle_df.get("Symbol", [])):
                    result_row = lifecycle_df[lifecycle_df["Symbol"] == selected_stage_symbol].iloc[0].to_dict()
                fig = render_lifecycle_chart_for_symbol(
                    selected_stage_symbol,
                    result_row=result_row,
                    max_weeks=selected_stage_row.get("scan_window_weeks"),
                )
                st.plotly_chart(fig, use_container_width=True)
            except FileNotFoundError:
                st.error(f"Could not find data file for {selected_stage_symbol}.")
            except Exception as e:
                st.error(f"An error occurred while plotting {selected_stage_symbol}: {e}")


def render_base_phase_page(static_df, m_cap):
    st.title("Base Phase")
    st.info("Review saved base snapshots. Run scans from the command line while the engine logic is evolving.")

    selected_snapshot_date = select_lifecycle_snapshot_date("base_lifecycle_snapshot_date")
    lifecycle_df, all_windows_df, stage_results = load_lifecycle_saved_state(selected_snapshot_date)
    if selected_snapshot_date:
        st.caption(f"Showing Base Phase saved snapshot {selected_snapshot_date}.")

    if lifecycle_df.empty:
        st.warning("No lifecycle scan results found. Run the replay script first.")
        if stage_results:
            render_review_funnel(stage_results, lifecycle_df)
        return

    metric_cols = st.columns(5)
    metric_cols[0].metric("Candidates", len(lifecycle_df))
    metric_cols[1].metric("Near Pivot", int((lifecycle_df["lifecycle_status"] == "NEAR_PIVOT").sum()))
    metric_cols[2].metric("Breakout+", int(lifecycle_df["breakout_date"].notna().sum()))
    metric_cols[3].metric("Avg Score", f"{lifecycle_df['score'].mean():.1f}")
    metric_cols[4].metric("Pivot Detected", int(lifecycle_df["pivot_detected"].sum()))

    render_review_funnel(stage_results, lifecycle_df)

    filter_col1, filter_col2, filter_col3 = st.columns([3, 1.4, 1.2])
    with filter_col1:
        selected_statuses = st.multiselect(
            "Lifecycle Status",
            options=sorted(lifecycle_df["lifecycle_status"].dropna().unique()),
            default=sorted(lifecycle_df["lifecycle_status"].dropna().unique()),
        )
    with filter_col2:
        selected_windows = st.multiselect(
            "Window",
            options=sorted(lifecycle_df["scan_window_weeks"].dropna().unique()),
            default=sorted(lifecycle_df["scan_window_weeks"].dropna().unique()),
        )
    with filter_col3:
        require_pivot = st.checkbox("Pivot detected only", value=False)

    display_df = lifecycle_df.copy()
    if selected_statuses:
        display_df = display_df[display_df["lifecycle_status"].isin(selected_statuses)]
    if selected_windows:
        display_df = display_df[display_df["scan_window_weeks"].isin(selected_windows)]
    if require_pivot:
        display_df = display_df[display_df["pivot_detected"] == True]

    display_df = add_lifecycle_display_columns(display_df, static_df, m_cap)
    display_df = display_df.sort_values(
        by=[col for col in ["score", "rank"] if col in display_df.columns],
        ascending=[False, True][:len([col for col in ["score", "rank"] if col in display_df.columns])],
    )

    st.caption(f"Showing {len(display_df)} lifecycle candidates after UI filters.")
    render_lifecycle_table_with_chart(display_df, "base_phase", source_df=lifecycle_df)

    if not all_windows_df.empty:
        with st.expander("All Window Results"):
            st.dataframe(all_windows_df, use_container_width=True, hide_index=True)


def render_tracking_phase_page(static_df, m_cap):
    st.title("Tracking Phase")
    st.info("Review active bases that are being carried forward after they became tracking-eligible.")

    tracking_state = load_tracking_state()
    active_tracking_df = tracking_state.get("active", pd.DataFrame())
    history_tracking_df = tracking_state.get("history", pd.DataFrame())
    archived_tracking_df = tracking_state.get("archived", pd.DataFrame())

    metric_cols = st.columns(3)
    metric_cols[0].metric("Active Bases", len(active_tracking_df))
    metric_cols[1].metric("History Rows", len(history_tracking_df))
    metric_cols[2].metric("Archived Bases", len(archived_tracking_df))

    tracking_tabs = st.tabs(["Active", "History", "Archived"])
    tracking_frames = [
        active_tracking_df,
        history_tracking_df.sort_values("tracking_date", ascending=False)
        if "tracking_date" in history_tracking_df.columns
        else history_tracking_df,
        archived_tracking_df,
    ]

    for tab, label, frame in zip(tracking_tabs, ["Active", "History", "Archived"], tracking_frames):
        with tab:
            if frame.empty:
                st.info(f"No {label.lower()} tracking rows yet.")
                continue

            display_df = add_lifecycle_display_columns(
                frame,
                static_df,
                m_cap,
                frame if label == "Active" else None,
            )
            render_lifecycle_table_with_chart(display_df, f"tracking_{label.lower()}", source_df=frame)
