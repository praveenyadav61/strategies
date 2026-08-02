from pathlib import Path
import json

import pandas as pd
import streamlit as st

from lifecycle_dashboard_fields import (
    TODAY_STATUS_ORDER,
    derive_lifecycle_today_status,
    latest_tracking_date,
)
from base_structure_identity import consolidate_equivalent_bases
from tradingview_lifecycle_chart import render_tradingview_lifecycle_chart


ROOT_DIR = Path(__file__).resolve().parents[1]
TRACKING_DIR = ROOT_DIR / "data" / "base_lifecycle_tracking"
LIFECYCLE_BASELINE_DIR = (
    ROOT_DIR / "data" / "base_lifecycle_layers" / "baselines"
)
LIFECYCLE_PRODUCTION_DIR = (
    ROOT_DIR / "data" / "base_lifecycle_layers" / "production"
)


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


def tracking_state_from_history(history_df):
    """Derive current active/archive tables from an append-only history."""
    if history_df is None or history_df.empty:
        return {
            "active": pd.DataFrame(),
            "history": pd.DataFrame(),
            "archived": pd.DataFrame(),
        }
    history = history_df.copy()
    history["tracking_date"] = pd.to_datetime(
        history["tracking_date"], errors="coerce"
    )
    latest = (
        history.sort_values("tracking_date", kind="stable")
        .drop_duplicates("base_id", keep="last")
        .reset_index(drop=True)
    )
    archived_mask = latest.get(
        "tracking_state",
        pd.Series("ACTIVE", index=latest.index),
    ).eq("ARCHIVED")
    active = latest[~archived_mask].copy()
    archived = latest[archived_mask].copy()
    if not archived.empty and "archived_date" not in archived.columns:
        archived["archived_date"] = archived["tracking_date"]
    return {
        "active": active.reset_index(drop=True),
        "history": history.reset_index(drop=True),
        "archived": archived.reset_index(drop=True),
    }


def available_lifecycle_tracking_sources():
    """Return production plus validated incremental shadow histories."""
    sources = {
        "Production tracking": {
            "kind": "production",
            "tracking_dir": TRACKING_DIR,
            "caption": "Existing dashboard tracking files",
        }
    }
    if not LIFECYCLE_BASELINE_DIR.exists():
        baseline_dirs = []
    else:
        baseline_dirs = sorted(
            LIFECYCLE_BASELINE_DIR.iterdir(), reverse=True
        )
    for baseline_dir in baseline_dirs:
        shadow_dir = baseline_dir / "shadow_incremental"
        history_path = shadow_dir / "tracking_history.parquet"
        report_path = shadow_dir / "parity_report.json"
        if history_path.exists() and report_path.exists():
            try:
                with report_path.open(encoding="utf-8") as handle:
                    report = json.load(handle)
            except (OSError, ValueError):
                report = {}
            if bool(report.get("passed")) and int(
                report.get("total_mismatches", -1)
            ) == 0:
                label = f"Incremental Shadow · {baseline_dir.name} (validated)"
                sources[label] = {
                    "kind": "shadow",
                    "history_path": history_path,
                    "report_path": report_path,
                    "caption": (
                        f"{int(report.get('actual_rows', 0)):,} rows · "
                        f"{int(report.get('total_mismatches', 0))} parity mismatches"
                    ),
                }
    production_history = (
        LIFECYCLE_PRODUCTION_DIR / "views" / "tracking_history.parquet"
    )
    production_manifest = LIFECYCLE_PRODUCTION_DIR / "manifest.json"
    if production_history.exists() and production_manifest.exists():
        try:
            with production_manifest.open(encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (OSError, ValueError):
            manifest = {}
        if manifest.get("last_committed_date"):
            sources["Checkpoint Production"] = {
                "kind": "shadow",
                "history_path": production_history,
                "caption": (
                    f"Committed through {manifest['last_committed_date']}"
                ),
            }
    return sources


def preferred_lifecycle_tracking_source(sources=None):
    """Use checkpoint production automatically, with a legacy-data fallback."""
    sources = sources or available_lifecycle_tracking_sources()
    return sources.get("Checkpoint Production", sources["Production tracking"])


def load_tracking_state():
    source = preferred_lifecycle_tracking_source()
    if source["kind"] == "shadow":
        history = pd.read_parquet(source["history_path"])
        return tracking_state_from_history(history)

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


def ensure_journey_stage(df):
    """Populate the v2 primary stage when an older saved snapshot is loaded."""
    if df is None or df.empty:
        return df

    migrated = df.copy()

    def infer_stage(row):
        failed = row.get("lifecycle_phase") == "FAILED" or row.get("lifecycle_status") == "FAILED"
        if failed:
            return "FAILED"
        success_value = row.get("breakout_success", False)
        if pd.notna(success_value) and bool(success_value):
            return "SUCCESSFUL_BREAKOUT"
        if pd.notna(row.get("breakout_date")):
            return "BREAKOUT_CONSIDERATION"
        recovery = pd.to_numeric(row.get("recovery_pct"), errors="coerce")
        if pd.notna(recovery) and float(recovery) >= 0.85:
            return "BREAKOUT_CONSIDERATION"
        if pd.notna(recovery) and float(recovery) >= 0.40:
            return "RECOVERY_BUILDING"
        return "NOT_TRACKED"

    if "journey_stage" not in migrated.columns:
        migrated["journey_stage"] = migrated.apply(infer_stage, axis=1)
    if "base_window_weeks" not in migrated.columns and "scan_window_weeks" in migrated.columns:
        migrated["base_window_weeks"] = migrated["scan_window_weeks"]
    return migrated


def lifecycle_window_series(df):
    if df is None or df.empty:
        return pd.Series(dtype="float64")
    if "base_window_weeks" in df.columns:
        return pd.to_numeric(df["base_window_weeks"], errors="coerce")
    if "scan_window_weeks" in df.columns:
        return pd.to_numeric(df["scan_window_weeks"], errors="coerce")
    return pd.Series(float("nan"), index=df.index, dtype="float64")


def available_lifecycle_windows(*frames):
    available = set()
    for frame in frames:
        available.update(
            int(value)
            for value in lifecycle_window_series(frame).dropna().unique()
        )
    preferred_order = [104, 52, 26]
    return [window for window in preferred_order if window in available] + sorted(
        available.difference(preferred_order), reverse=True
    )


def render_lifecycle_window_filter(frames, key):
    options = available_lifecycle_windows(*frames)
    if not options:
        return []
    return st.multiselect(
        "Base Windows",
        options=options,
        default=options,
        key=key,
        format_func=lambda value: f"{int(value)} weeks",
        help="Show one or more independently detected 104W, 52W, and 26W bases.",
    )


def filter_lifecycle_windows(df, selected_windows):
    if df is None or df.empty:
        return df
    windows = lifecycle_window_series(df)
    if windows.isna().all():
        return df
    if not selected_windows:
        return df.iloc[0:0].copy()
    return df[windows.isin(selected_windows)].copy()


def collapse_equivalent_lifecycle_rows(df, date_column=None):
    """Hide duplicate window representations while preserving distinct bases."""
    if df is None or df.empty or "Symbol" not in df.columns:
        return df

    source = df.copy()
    group_columns = ["Symbol"]
    helper_date = None
    if date_column and date_column in source.columns:
        helper_date = "_equivalent_group_date"
        source[helper_date] = pd.to_datetime(
            source[date_column], errors="coerce"
        ).dt.normalize()
        group_columns.append(helper_date)

    consolidated = []
    for _, group in source.groupby(group_columns, dropna=False, sort=False):
        rows = group.drop(columns=[helper_date], errors="ignore").to_dict("records")
        consolidated.extend(consolidate_equivalent_bases(rows))
    return pd.DataFrame(consolidated).reset_index(drop=True)


def render_today_status_filter(df, key, label="Activity on selected date"):
    if df is None or df.empty or "today_status" not in df.columns:
        return df
    available = [
        status for status in TODAY_STATUS_ORDER if status in set(df["today_status"].dropna())
    ]
    if not available:
        return df
    selected = st.multiselect(
        label,
        options=available,
        default=available,
        key=key,
        help=(
            "NEW BASE was first detected on this date; NEW TO STAGE changed "
            "journey group on this date; CONTINUED remained in the same group."
        ),
    )
    return df[df["today_status"].isin(selected)].copy() if selected else df.iloc[0:0].copy()


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
        "today_status",
        "journey_stage",
        "recovery_pct",
        "base_window_weeks",
        "peak_to_low_weeks",
        "base_duration_weeks",
        "largest_single_week_move_to_depth_ratio",
        "equivalent_base_windows",
        "daily_handle_state",
        "daily_handle_candidate_pivot",
        "daily_handle_sessions_after_pivot",
        "pivot_source",
        "selected_pivot",
        "distance_from_pivot_pct",
        "breakout_range_low",
        "breakout_range_high",
    ]
    return [col for col in preferred_cols if col in df.columns]


JOURNEY_STAGE_PRIORITY = {
    "BREAKOUT_CONSIDERATION": 0,
    "RECOVERY_BUILDING": 1,
    "SUCCESSFUL_BREAKOUT": 2,
    "FAILED": 3,
    "NOT_TRACKED": 4,
}
TODAY_STATUS_PRIORITY = {status: index for index, status in enumerate(TODAY_STATUS_ORDER)}


def sort_lifecycle_for_review(df, view_key=""):
    """Sort rows for review without introducing a numerical strategy score."""
    if df.empty:
        return df

    sorted_df = df.copy()
    if "history" in view_key and "tracking_date" in sorted_df.columns:
        sorted_df["_review_activity"] = (
            sorted_df.get("today_status", pd.Series(index=sorted_df.index, dtype="object"))
            .map(TODAY_STATUS_PRIORITY)
            .fillna(99)
        )
        return sorted_df.sort_values(
            ["tracking_date", "_review_activity", "Symbol"],
            ascending=[False, True, True],
            na_position="last",
            kind="stable",
        ).drop(columns="_review_activity").reset_index(drop=True)
    if "archived" in view_key and "archived_date" in sorted_df.columns:
        return sorted_df.sort_values(
            ["archived_date", "Symbol"],
            ascending=[False, True],
            na_position="last",
            kind="stable",
        ).reset_index(drop=True)

    sorted_df["_review_priority"] = (
        sorted_df.get("journey_stage", pd.Series(index=sorted_df.index, dtype="object"))
        .map(JOURNEY_STAGE_PRIORITY)
        .fillna(99)
    )
    sorted_df["_review_activity"] = (
        sorted_df.get("today_status", pd.Series(index=sorted_df.index, dtype="object"))
        .map(TODAY_STATUS_PRIORITY)
        .fillna(99)
    )
    sorted_df["_review_recovery"] = pd.to_numeric(
        sorted_df.get("recovery_pct", pd.Series(float("nan"), index=sorted_df.index)),
        errors="coerce",
    )

    distance = pd.to_numeric(
        sorted_df.get(
            "distance_from_pivot_pct",
            pd.Series(float("nan"), index=sorted_df.index),
        ),
        errors="coerce",
    )
    sorted_df["_review_distance"] = distance.abs()

    sort_columns = [
        "_review_activity",
        "_review_priority",
        "_review_recovery",
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
                "_review_activity",
                "_review_recovery",
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
        "base_age_weeks",
        "base_end_date",
        "base_end_reason",
        "peak_to_low_weeks",
        "largest_single_week_move",
        "largest_single_week_move_date",
        "largest_single_week_move_to_depth_ratio",
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
        "handle_pivot_base_recovery",
        "pivot_min_price",
        "pivot_max_price",
        "daily_handle_state",
        "daily_handle_candidate_pivot",
        "daily_handle_candidate_date",
        "daily_handle_low",
        "daily_handle_low_date",
        "daily_handle_pullback_pct",
        "daily_handle_sessions_after_pivot",
        "daily_handle_confirmation_sessions",
        "daily_handle_confirmation_date",
        "daily_handle_valid",
        "daily_handle_breakout_eligible",
        "daily_handle_invalidated",
        "daily_handle_invalidation_date",
        "daily_base_low_date",
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


def render_selected_lifecycle_chart(symbol, result_row, key_prefix):
    """Render the lifecycle-specific price, volume, and RSI chart."""
    timeframe = st.radio(
        "Candles",
        options=["Daily", "Weekly"],
        index=0,
        horizontal=True,
        key=f"{key_prefix}_chart_timeframe",
        help="Daily shows handle/pivot precision; Weekly shows the complete base structure.",
    )
    try:
        daily_df = load_daily_price_data(symbol)
        render_tradingview_lifecycle_chart(
            daily_df,
            result_row=result_row,
            symbol=symbol,
            timeframe=timeframe,
        )
        st.caption(
            "Scroll or drag to navigate, use Fit to reset, or Fullscreen for detailed review."
        )
    except Exception as chart_error:
        st.error(f"The lifecycle chart could not be rendered: {chart_error}")


def render_lifecycle_table_with_chart(
    display_df,
    key_prefix,
    source_df=None,
    default_columns=None,
):
    if display_df.empty:
        st.info("No rows available for this view.")
        return

    review_df = sort_lifecycle_for_review(display_df, key_prefix)
    selected_columns = selectable_table_columns(
        review_df,
        key=f"{key_prefix}_columns",
        default_columns=default_columns,
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
        selected_window = selected_row.get(
            "base_window_weeks", selected_row.get("scan_window_weeks")
        )
        window_suffix = (
            f" — {int(selected_window)}W" if pd.notna(selected_window) else ""
        )
        st.subheader(f"Chart for {selected_symbol}{window_suffix}")
        try:
            result_row = selected_row.to_dict()
            render_selected_lifecycle_chart(
                selected_symbol,
                result_row=result_row,
                key_prefix=key_prefix,
            )
        except FileNotFoundError:
            st.error(f"Could not find data file for {selected_symbol}.")
        except Exception as e:
            st.error(f"An error occurred while plotting {selected_symbol}: {e}")
        render_lifecycle_selected_details(selected_row)


def load_current_journey_rows():
    """Load the latest checkpoint-backed row for every current base."""
    tracking_state = load_tracking_state()
    active_df = ensure_journey_stage(tracking_state.get("active", pd.DataFrame()))
    if active_df is None or active_df.empty:
        return pd.DataFrame()
    journey_df = active_df.copy()
    journey_df["Symbol"] = journey_df["Symbol"].astype(str).str.strip()
    history_df = ensure_journey_stage(tracking_state.get("history", pd.DataFrame()))
    return derive_lifecycle_today_status(
        journey_df.reset_index(drop=True),
        history_df,
        reference_date=latest_tracking_date(history_df),
    )


def build_failure_review_rows(tracking_state):
    """Build compact failed/pullback groups without a separate tracking page."""
    history = ensure_journey_stage(
        tracking_state.get("history", pd.DataFrame())
    )
    archived = ensure_journey_stage(
        tracking_state.get("archived", pd.DataFrame())
    )
    active = ensure_journey_stage(
        tracking_state.get("active", pd.DataFrame())
    )
    groups = []
    if archived is not None and not archived.empty:
        failed = archived.copy()
        def failure_category(row):
            success_flag = row.get("breakout_success", False)
            succeeded = (
                pd.notna(row.get("breakout_success_date"))
                or (pd.notna(success_flag) and bool(success_flag))
            )
            return (
                "FAILED_AFTER_SUCCESS"
                if succeeded
                else "FAILED_AFTER_BREAKOUT"
            )

        failed["failure_category"] = failed.apply(failure_category, axis=1)
        groups.append(failed)

    if (
        history is not None
        and not history.empty
        and active is not None
        and not active.empty
        and {"base_id", "journey_stage"}.issubset(history.columns)
    ):
        ever_considered = set(
            history.loc[
                history["journey_stage"].eq("BREAKOUT_CONSIDERATION"),
                "base_id",
            ].astype(str)
        )
        pullbacks = active[
            active["base_id"].astype(str).isin(ever_considered)
            & active["journey_stage"].isin(
                ["RECOVERY_BUILDING", "NOT_TRACKED"]
            )
        ].copy()
        if not pullbacks.empty:
            pullbacks["failure_category"] = "CONSIDERATION_PULLBACK"
            groups.append(pullbacks)
    return (
        pd.concat(groups, ignore_index=True, sort=False)
        if groups
        else pd.DataFrame()
    )


def render_failure_review(static_df, m_cap):
    failure_df = build_failure_review_rows(load_tracking_state())
    with st.expander(
        f"Failure Review ({len(failure_df)})",
        expanded=False,
    ):
        if failure_df.empty:
            st.info("No failed or consideration-pullback bases.")
            return
        labels = [
            ("Failed Before Success", "FAILED_AFTER_BREAKOUT"),
            ("Failed After Success", "FAILED_AFTER_SUCCESS"),
            ("Consideration Pullbacks", "CONSIDERATION_PULLBACK"),
        ]
        counts = failure_df["failure_category"].value_counts()
        metric_columns = st.columns(3)
        for metric, (label, category) in zip(metric_columns, labels):
            metric.metric(label, int(counts.get(category, 0)))
        selected_label = st.selectbox(
            "Failure group",
            options=[label for label, _ in labels],
            key="journey_failure_group",
        )
        category = dict(labels)[selected_label]
        selected = failure_df[
            failure_df["failure_category"].eq(category)
        ].copy()
        selected = add_lifecycle_display_columns(selected, static_df, m_cap)
        render_lifecycle_table_with_chart(
            selected,
            f"journey_failure_{category.lower()}",
            source_df=failure_df,
            default_columns=[
                "Symbol",
                "failure_category",
                "base_window_weeks",
                "selected_pivot",
                "breakout_date",
                "breakout_success_date",
                "hard_failure",
                "persistent_failure",
                "tracking_date",
            ],
        )


def render_lifecycle_journey_page(static_df, m_cap):
    """Render the simplified current journey as exactly three primary tables."""
    render_lifecycle_control_styles()
    st.title("Lifecycle Journey")
    st.caption(
        "Current stock journey in three review groups. Select a row to open its chart."
    )
    journey_df = load_current_journey_rows()
    if journey_df.empty:
        st.warning("No lifecycle journey data found. Run the replay script first.")
        return

    selected_windows = render_lifecycle_window_filter(
        [journey_df], "journey_base_windows"
    )
    journey_df = filter_lifecycle_windows(journey_df, selected_windows)
    journey_df = collapse_equivalent_lifecycle_rows(journey_df)
    journey_df = render_today_status_filter(journey_df, "journey_today_status")

    visible_stages = [
        "BREAKOUT_CONSIDERATION",
        "RECOVERY_BUILDING",
        "SUCCESSFUL_BREAKOUT",
    ]
    journey_df = journey_df[journey_df["journey_stage"].isin(visible_stages)].copy()
    journey_df = add_lifecycle_display_columns(journey_df, static_df, m_cap)

    counts = journey_df["journey_stage"].value_counts()
    metric_cols = st.columns(3)
    metric_cols[0].metric(
        "Breakout Consideration", int(counts.get("BREAKOUT_CONSIDERATION", 0))
    )
    metric_cols[1].metric(
        "Recovery Building", int(counts.get("RECOVERY_BUILDING", 0))
    )
    metric_cols[2].metric(
        "Successful Breakout", int(counts.get("SUCCESSFUL_BREAKOUT", 0))
    )

    default_columns = [
        "Symbol",
        "today_status",
        "recovery_pct",
        "latest_close",
        "base_window_weeks",
        "equivalent_base_windows",
        "peak_to_low_weeks",
        "base_duration_weeks",
        "largest_single_week_move_to_depth_ratio",
        "Depth",
        "daily_handle_state",
        "daily_handle_candidate_pivot",
        "daily_handle_sessions_after_pivot",
        "pivot_source",
        "selected_pivot",
        "distance_from_pivot_pct",
    ]
    stage_sections = [
        (
            "Breakout Consideration",
            "Stocks at 85%+ recovery or with a confirmed breakout.",
            "BREAKOUT_CONSIDERATION",
            "journey_consideration",
        ),
        (
            "Recovery Building",
            "Stocks currently between 40% and 85% recovery.",
            "RECOVERY_BUILDING",
            "journey_recovery",
        ),
        (
            "Successful Breakout",
            "Stocks that have reached the successful-breakout level.",
            "SUCCESSFUL_BREAKOUT",
            "journey_success",
        ),
    ]

    for title, caption, stage, key_prefix in stage_sections:
        stage_df = journey_df[journey_df["journey_stage"] == stage].copy()
        st.subheader(f"{title} ({len(stage_df)})")
        st.caption(caption)
        render_lifecycle_table_with_chart(
            stage_df,
            key_prefix,
            source_df=journey_df,
            default_columns=default_columns,
        )

    render_failure_review(static_df, m_cap)
