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


def render_lifecycle_control_styles():
    """Keep lifecycle multiselect controls compact and theme-compatible."""
    st.markdown(
        """
        <style>
        /* Use nearly all available screen width on lifecycle pages. */
        [data-testid="stMainBlockContainer"] {
            max-width: 94vw !important;
            margin-left: auto !important;
            margin-right: auto !important;
            padding-left: 1.5rem !important;
            padding-right: 1.5rem !important;
        }
        [data-testid="stDataFrame"] {
            width: 100% !important;
        }
        /* Neutral compact pills for selected multiselect values. */
        [data-baseweb="select"] [data-baseweb="tag"] {
            background-color: var(--secondary-background-color) !important;
            color: var(--text-color) !important;
            border: 1px solid rgba(128, 128, 128, 0.35) !important;
            border-radius: 0.35rem !important;
            min-height: 1.25rem !important;
            height: 1.25rem !important;
            padding: 0 0.28rem !important;
            margin: 0.08rem !important;
        }
        [data-baseweb="select"] [data-baseweb="tag"] span {
            color: var(--text-color) !important;
            font-size: 0.70rem !important;
            line-height: 1rem !important;
        }
        [data-baseweb="select"] [data-baseweb="tag"] svg {
            color: var(--text-color) !important;
            fill: currentColor !important;
            width: 0.68rem !important;
            height: 0.68rem !important;
        }
        [data-baseweb="select"] > div {
            min-height: 2.05rem !important;
            font-size: 0.78rem !important;
        }
        li[role="option"][aria-selected="true"] {
            background-color: var(--secondary-background-color) !important;
            color: var(--text-color) !important;
            font-size: 0.78rem !important;
        }
        li[role="option"][aria-selected="true"] svg {
            color: var(--text-color) !important;
            fill: currentColor !important;
        }
        @media (max-width: 900px) {
            [data-testid="stMainBlockContainer"] {
                max-width: 100% !important;
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
    if status == "HANDLE_READY":
        return "Handle Ready"
    if status in ["BREAKOUT_BUY_RANGE", "BREAKOUT_RETEST_RANGE"]:
        return "Breakout Range"
    if status == "POST_SUCCESS_REENTRY_RANGE":
        return "Success Re-entry"
    if status == "BREAKOUT_SUCCESS":
        return "Successful Breakout"
    if status == "BREAKOUT_STALLED":
        return "Stalled"
    if status == "BREAKOUT_RANGE_BREACH":
        return "Range Breach"
    if status == "RESETTING":
        return "Resetting"
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


def lifecycle_default_columns(df):
    """Return the small decision set shown before optional columns are selected."""
    preferred_cols = [
        "Symbol",
        "lifecycle_status",
        "lifecycle_phase",
        "current_zone",
        "pivot_source",
        "selected_pivot",
        "distance_from_pivot_pct",
        "breakout_range_low",
        "breakout_range_high",
    ]
    return [col for col in preferred_cols if col in df.columns]


REVIEW_STATUS_PRIORITY = {
    "FAILED": 0,
    "BREAKOUT_RANGE_BREACH": 1,
    "POST_SUCCESS_REENTRY_RANGE": 2,
    "BREAKOUT_RETEST_RANGE": 3,
    "BREAKOUT_BUY_RANGE": 4,
    "BREAKOUT_CONFIRMED": 5,
    "HANDLE_READY": 6,
    "NEAR_PIVOT": 7,
    "BREAKOUT_SUCCESS": 8,
    "BREAKOUT_STALLED": 9,
    "RESETTING": 10,
    "TRACKING": 11,
    "BASE_FORMING": 12,
}


def sort_lifecycle_for_review(df, view_key=""):
    """Sort rows for review without introducing a numerical strategy score."""
    if df.empty:
        return df

    sorted_df = df.copy()
    if "history" in view_key and "tracking_date" in sorted_df.columns:
        return sorted_df.sort_values(
            ["tracking_date", "Symbol"],
            ascending=[False, True],
            na_position="last",
            kind="stable",
        ).reset_index(drop=True)
    if "archived" in view_key and "archived_date" in sorted_df.columns:
        return sorted_df.sort_values(
            ["archived_date", "Symbol"],
            ascending=[False, True],
            na_position="last",
            kind="stable",
        ).reset_index(drop=True)

    sorted_df["_review_priority"] = (
        sorted_df.get("lifecycle_status", pd.Series(index=sorted_df.index, dtype="object"))
        .map(REVIEW_STATUS_PRIORITY)
        .fillna(99)
    )

    weekly_change = sorted_df.get(
        "weekly_change",
        pd.Series("", index=sorted_df.index, dtype="object"),
    ).fillna("").astype(str)
    sorted_df["_review_change_priority"] = ~(
        weekly_change.eq("New") | weekly_change.str.contains("->", regex=False)
    )

    event_date = pd.Series(pd.NaT, index=sorted_df.index, dtype="datetime64[ns]")
    for date_column in [
        "breakout_success_date",
        "breakout_date",
        "last_tracked_date",
        "scan_as_of_date",
        "tracking_date",
        "archived_date",
    ]:
        if date_column in sorted_df.columns:
            event_date = event_date.fillna(
                pd.to_datetime(sorted_df[date_column], errors="coerce")
            )
    sorted_df["_review_event_date"] = event_date

    distance = pd.to_numeric(
        sorted_df.get(
            "distance_from_pivot_pct",
            pd.Series(float("nan"), index=sorted_df.index),
        ),
        errors="coerce",
    )
    sorted_df["_review_distance"] = distance.abs()

    sort_columns = [
        "_review_priority",
        "_review_change_priority",
        "_review_event_date",
        "_review_distance",
    ]
    ascending = [True, True, False, True]
    if "Symbol" in sorted_df.columns:
        sort_columns.append("Symbol")
        ascending.append(True)

    return (
        sorted_df.sort_values(
            sort_columns,
            ascending=ascending,
            na_position="last",
            kind="stable",
        )
        .drop(
            columns=[
                "_review_priority",
                "_review_change_priority",
                "_review_event_date",
                "_review_distance",
            ]
        )
        .reset_index(drop=True)
    )


def selectable_table_columns(df, key, default_columns=None, label="Table columns"):
    """Show important columns by default and allow optional fields on demand."""
    if df.empty:
        return []

    available_columns = list(df.columns)
    defaults = default_columns or lifecycle_default_columns(df)
    defaults = [column for column in defaults if column in available_columns]
    selected = st.multiselect(
        label,
        options=available_columns,
        default=defaults,
        key=key,
        help="Add structure, breakout, company, industry, or review fields only when needed.",
    )

    # Symbol remains visible because it identifies the row used to open the chart.
    if "Symbol" in available_columns and "Symbol" not in selected:
        selected.insert(0, "Symbol")
    return selected or (["Symbol"] if "Symbol" in available_columns else available_columns[:1])


def compact_table_column_config(columns):
    """Keep dynamic lifecycle columns narrow so more fit on wide screens."""
    return {
        column: st.column_config.Column(
            label=column.replace("_", " ").title(),
            width="small",
        )
        for column in columns
    }


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
        "Also Valid Windows",
        "base_duration_weeks",
        "peak_to_low_weeks",
        "pivot_detected",
        "selected_pivot_date",
        "breakout_buffer",
        "confirmation_level",
        "left_high_confirmation_level",
        "success_level",
        "failure_buffer",
        "hard_failure_level",
        "hard_failure",
        "persistent_failure",
        "range_breach",
        "breakout_stalled",
        "post_success_reentry",
        "breakout_success",
        "breakout_success_close",
        "left_high_cleared",
        "handle_invalidated",
        "left_high_pivot_date",
        "handle_high_date",
        "handle_low",
        "handle_low_date",
        "handle_pullback_pct",
        "handle_max_pullback_pct",
        "handle_duration_weeks",
        "weeks_since_breakout",
        "gain_since_breakout_pct",
        "max_gain_after_breakout_pct",
        "pullback_from_post_breakout_high_pct",
    ]

    company_df = lifecycle_selected_detail_frame(selected_row, company_and_tags)
    diagnostics_df = lifecycle_selected_detail_frame(selected_row, pivot_and_diagnostics)
    if company_df.empty and diagnostics_df.empty:
        return

    with st.expander("Selected stock details", expanded=False):
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

    review_df = sort_lifecycle_for_review(display_df, key_prefix)
    selected_columns = selectable_table_columns(
        review_df,
        key=f"{key_prefix}_columns",
        label="Visible columns",
    )
    table_df = review_df[selected_columns]
    event = st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        column_config=compact_table_column_config(selected_columns),
        on_select="rerun",
        selection_mode="single-row",
        key=f"{key_prefix}_table",
    )

    if event.selection.rows:
        selected_row = review_df.iloc[event.selection.rows[0]]
        selected_symbol = selected_row["Symbol"]
        st.subheader(f"Chart for {selected_symbol}")
        try:
            result_row = selected_row.to_dict()
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
        render_lifecycle_selected_details(selected_row)


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

        stage_df = sort_lifecycle_for_review(
            stage_df,
            view_key=f"review_{selected_stage}",
        )
        stage_default_cols = [
            "Symbol",
            "failure_reason",
            "lifecycle_status",
            "current_zone",
            "pivot_source",
            "selected_pivot",
            "distance_from_pivot_pct",
        ]
        stage_cols = selectable_table_columns(
            stage_df,
            key=f"lifecycle_review_{selected_stage}_columns",
            default_columns=stage_default_cols,
            label="Visible review columns",
        )
        stage_display_df = stage_df[stage_cols]
        stage_event = st.dataframe(
            stage_display_df,
            use_container_width=True,
            hide_index=True,
            column_config=compact_table_column_config(stage_cols),
            on_select="rerun",
            selection_mode="single-row",
            key="lifecycle_review_funnel_table",
        )

        if stage_event.selection.rows:
            # Use the complete source row for charts even when most table columns are hidden.
            selected_stage_row = stage_df.iloc[stage_event.selection.rows[0]]
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
    render_lifecycle_control_styles()
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
    metric_cols[3].metric("Handle Ready", int((lifecycle_df["lifecycle_status"] == "HANDLE_READY").sum()))
    successful_count = (
        int(lifecycle_df["breakout_success"].fillna(False).sum())
        if "breakout_success" in lifecycle_df.columns
        else 0
    )
    metric_cols[4].metric("Successful", successful_count)

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
        require_pivot = st.checkbox("Pivot detected only", value=True)

    display_df = lifecycle_df.copy()
    if selected_statuses:
        display_df = display_df[display_df["lifecycle_status"].isin(selected_statuses)]
    if selected_windows:
        display_df = display_df[display_df["scan_window_weeks"].isin(selected_windows)]
    if require_pivot:
        display_df = display_df[display_df["pivot_detected"] == True]

    display_df = add_lifecycle_display_columns(display_df, static_df, m_cap)

    st.caption(f"Showing {len(display_df)} lifecycle candidates after UI filters.")
    render_lifecycle_table_with_chart(display_df, "base_phase", source_df=lifecycle_df)

    if not all_windows_df.empty:
        with st.expander("All Window Results"):
            sorted_all_windows_df = sort_lifecycle_for_review(
                all_windows_df,
                view_key="base_phase_all_windows",
            )
            all_window_columns = selectable_table_columns(
                sorted_all_windows_df,
                key="base_phase_all_windows_columns",
                default_columns=[
                    "Symbol",
                    "scan_window_weeks",
                    "lifecycle_status",
                    "pivot_source",
                    "selected_pivot",
                    "distance_from_pivot_pct",
                ],
                label="Visible all-window columns",
            )
            st.dataframe(
                sorted_all_windows_df[all_window_columns],
                use_container_width=True,
                hide_index=True,
                column_config=compact_table_column_config(all_window_columns),
            )


def render_tracking_phase_page(static_df, m_cap):
    render_lifecycle_control_styles()
    st.title("Tracking Phase")
    st.info("Review active bases that are being carried forward after they became tracking-eligible.")

    tracking_state = load_tracking_state()
    active_tracking_df = tracking_state.get("active", pd.DataFrame())
    history_tracking_df = tracking_state.get("history", pd.DataFrame())
    archived_tracking_df = tracking_state.get("archived", pd.DataFrame())

    available_windows = sorted(
        {
            int(window)
            for frame in [active_tracking_df, history_tracking_df, archived_tracking_df]
            if "scan_window_weeks" in frame.columns
            for window in pd.to_numeric(
                frame["scan_window_weeks"], errors="coerce"
            ).dropna().unique()
        }
    )
    selected_windows = st.multiselect(
        "Base Window",
        options=available_windows,
        default=available_windows,
        key="tracking_base_windows",
        help="Filter Active, History, and Archived tracking rows by the original base window.",
    )

    def filter_tracking_windows(frame):
        if (
            frame.empty
            or not selected_windows
            or "scan_window_weeks" not in frame.columns
        ):
            return frame
        numeric_windows = pd.to_numeric(frame["scan_window_weeks"], errors="coerce")
        return frame[numeric_windows.isin(selected_windows)].copy()

    active_tracking_df = filter_tracking_windows(active_tracking_df)
    history_tracking_df = filter_tracking_windows(history_tracking_df)
    archived_tracking_df = filter_tracking_windows(archived_tracking_df)

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
