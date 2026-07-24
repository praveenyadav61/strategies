import logging
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_layer.data_engine import DataEngine
from base_structure_identity import bases_are_equivalent, consolidate_equivalent_bases
from lifecycle_state_machine import (
    advance_daily_handle_state,
    daily_handle_result,
    initialize_daily_handle_state,
)
from modular_base_scanner import ScanStats, calculate_cup_metrics


DATA_PATH = os.path.join(PROJECT_ROOT, "data", "daily")
if not os.path.exists(DATA_PATH):
    DATA_PATH = os.path.join(PROJECT_ROOT, "data", "test_data")

SCAN_HISTORY_DIR = os.path.join(PROJECT_ROOT, "data", "base_lifecycle_scans")
TRACKING_DIR = os.path.join(PROJECT_ROOT, "data", "base_lifecycle_tracking")
ACTIVE_TRACKING_FILE = "active_tracked_bases.parquet"
TRACKING_HISTORY_FILE = "tracking_history.parquet"
ARCHIVED_TRACKING_FILE = "archived_tracked_bases.parquet"
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

# Handle highs are eligible from 85% through 110% recovery of base depth.
# These are strategy constants, not replay command-line controls.
PIVOT_MIN_BASE_RECOVERY = 0.85
PIVOT_MAX_BASE_RECOVERY = 1.10

DEFAULT_PARAMS = {
    "MIN_WEEKS": 8,
    "MIN_BASE_DURATION_WEEKS": 12,
    "MAX_WEEKS": 104,
    "BASE_WINDOWS": [104, 52, 26],
    "MIN_WEEKLY_BARS_REQUIRED": 10,
    "MIN_DEPTH": 0.15,
    "MAX_DEPTH": 0.60,
    "MAX_SINGLE_WEEK_MOVE_TO_DEPTH_RATIO": 0.50,
    "RECOVERY_MIN": 0.40,
    "TRACKING_ELIGIBLE_RECOVERY_MIN": 0.40,
    "BREAKOUT_CONSIDERATION_RECOVERY_MIN": 0.85,
    "STRATEGY_VERSION": "base_lifecycle_v5_daily_handle",
    "MIN_PRIOR_UPTREND_PCT": 0.20,
    "PRIOR_UPTREND_DEPTH_MULTIPLIER": 1.0,
    "PRIOR_UPTREND_LOOKBACK_RATIO": 0.50,
    "PRIOR_UPTREND_MIN_LOOKBACK_WEEKS": 12,
    "PRIOR_UPTREND_MAX_LOOKBACK_WEEKS": 52,
    "PRIOR_UPTREND_MIN_ADVANCE_WEEKS": 4,
    "MIN_PEAK_TO_LOW_WEEKS": 6,
    "EQUIVALENT_BASE_LEFT_HIGH_MAX_WEEKS": 2,
    "EQUIVALENT_BASE_LOW_MAX_WEEKS": 1,
    "EQUIVALENT_BASE_LEFT_HIGH_PRICE_TOLERANCE_PCT": 0.05,
    "EQUIVALENT_BASE_LOW_PRICE_TOLERANCE_PCT": 0.03,
    "ATR_WINDOW": 14,
    "COMPRESSION_LOOKBACK": 10,
    "TRACKING_HANDLE_LOOKBACK_WEEKS": 10,
    "TRACKING_HANDLE_MIN_PULLBACK_PCT": 0.03,
    "HANDLE_MIN_DURATION_WEEKS": 2,
    "DAILY_HANDLE_CONFIRMATION_SESSIONS": 5,
    "PIVOT_MIN_BASE_RECOVERY": PIVOT_MIN_BASE_RECOVERY,
    "PIVOT_MAX_BASE_RECOVERY": PIVOT_MAX_BASE_RECOVERY,
    "HANDLE_MAJOR_MERGE_TOLERANCE_PCT": 0.02,
    "BREAKOUT_PRICE_BUFFER_PCT": 0.005,
    "BREAKOUT_ATR_BUFFER_MULTIPLIER": 0.20,
    "FAILURE_PRICE_BUFFER_PCT": 0.01,
    "FAILURE_ATR_BUFFER_MULTIPLIER": 0.25,
    "BREAKOUT_RANGE_PCT": 0.10,
    "BREAKOUT_STALL_WEEKS": 10,
}


def determine_journey_stage(
    recovery_pct,
    breakout_confirmed=False,
    breakout_success=False,
    failed=False,
    discovery_recovery_min=0.40,
    consideration_recovery_min=0.85,
):
    """Return the primary lifecycle stage while preserving historical outcomes."""
    if bool(failed):
        return "FAILED"
    if bool(breakout_success):
        return "SUCCESSFUL_BREAKOUT"
    if bool(breakout_confirmed):
        return "BREAKOUT_CONSIDERATION"
    if pd.notna(recovery_pct) and float(recovery_pct) >= float(consideration_recovery_min):
        return "BREAKOUT_CONSIDERATION"
    if pd.notna(recovery_pct) and float(recovery_pct) >= float(discovery_recovery_min):
        return "RECOVERY_BUILDING"
    return "NOT_TRACKED"


def get_logger(debug=False):
    level = logging.DEBUG if debug else logging.ERROR
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")
    return logging.getLogger("base_lifecycle_scanner")


def normalize_stock_symbol(symbol):
    return str(symbol).strip().removesuffix(".NS")


def latest_completed_week_end(as_of_date):
    """Return the Friday whose completed weekly candle is valid as of a signal date."""
    signal_date = pd.to_datetime(as_of_date).normalize()
    days_since_friday = (signal_date.weekday() - 4) % 7
    return signal_date - pd.Timedelta(days=days_since_friday)


def resample_completed_weekly(daily_df, as_of_date=None):
    """Build Friday-labelled weekly bars and exclude the incomplete current week."""
    if daily_df is None or daily_df.empty:
        return pd.DataFrame()
    weekly = daily_df.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna()
    cutoff = pd.to_datetime(as_of_date if as_of_date is not None else daily_df.index[-1])
    return weekly[weekly.index <= cutoff].copy()


def ordered_base_windows(params):
    """Return unique base windows in largest-first discovery order."""
    return sorted(
        {int(window) for window in params.get("BASE_WINDOWS", [104, 52, 26])},
        reverse=True,
    )


def resolve_base_end(left_high_date, pivot_lifecycle, current_structure_date):
    """Resolve the structural right edge used to measure actual base width."""
    left_high_date = pd.to_datetime(left_high_date, errors="coerce")
    current_structure_date = pd.to_datetime(current_structure_date, errors="coerce")
    pivot_source = pivot_lifecycle.get("pivot_source")
    pivot_date = pd.to_datetime(
        pivot_lifecycle.get("selected_pivot_date"), errors="coerce"
    )
    breakout_date = pd.to_datetime(
        pivot_lifecycle.get("breakout_date"), errors="coerce"
    )

    if (
        pivot_source == "HANDLE"
        and pd.notna(pivot_date)
        and pd.notna(left_high_date)
        and pivot_date > left_high_date
    ):
        return pivot_date, "HANDLE_PIVOT"
    if (
        pd.notna(breakout_date)
        and pd.notna(left_high_date)
        and breakout_date > left_high_date
    ):
        return breakout_date, "BREAKOUT"
    return current_structure_date, "CURRENT_STRUCTURE"


def calculate_single_week_move_metrics(
    base_window,
    base_depth_price,
    excluded_end_date=None,
):
    """Measure the largest weekly true range as a share of total base depth."""
    if base_window is None or base_window.empty or base_depth_price <= 0:
        return {
            "largest_single_week_move": np.nan,
            "largest_single_week_move_date": pd.NaT,
            "largest_single_week_move_to_depth_ratio": np.nan,
        }

    measured = base_window.copy()
    excluded_end_date = pd.to_datetime(excluded_end_date, errors="coerce")
    if pd.notna(excluded_end_date):
        measured = measured[measured.index < excluded_end_date]
    if measured.empty:
        return {
            "largest_single_week_move": np.nan,
            "largest_single_week_move_date": pd.NaT,
            "largest_single_week_move_to_depth_ratio": np.nan,
        }

    previous_close = measured["Close"].shift(1)
    true_range = pd.concat(
        [
            measured["High"] - measured["Low"],
            (measured["High"] - previous_close).abs(),
            (measured["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    largest_date = true_range.idxmax()
    largest_move = float(true_range.loc[largest_date])
    return {
        "largest_single_week_move": largest_move,
        "largest_single_week_move_date": largest_date,
        "largest_single_week_move_to_depth_ratio": largest_move / float(base_depth_price),
    }


def empty_stage_results():
    return {stage: [] for stage in STAGE_KEYS}


def record_stage(stage_results, stage, row):
    if stage_results is None:
        return
    stage_results.setdefault(stage, []).append(row)


def stage_results_to_frames(stage_results):
    return {
        stage: rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        for stage, rows in stage_results.items()
    }


def stage_results_to_long_frame(stage_results):
    frames = []
    for stage, rows in stage_results.items():
        df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        if df.empty:
            continue
        frames.append(df.assign(stage=stage))

    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def long_frame_to_stage_results(stage_df):
    if stage_df is None or stage_df.empty or "stage" not in stage_df.columns:
        return {stage: pd.DataFrame() for stage in STAGE_KEYS}

    return {
        stage: stage_df[stage_df["stage"] == stage].drop(columns=["stage"]).reset_index(drop=True)
        for stage in STAGE_KEYS
    }


def resolve_prior_uptrend_lookback(scan_window_weeks, params):
    lookback = int(round(scan_window_weeks * params.get("PRIOR_UPTREND_LOOKBACK_RATIO", 0.50)))
    return int(
        min(
            params.get("PRIOR_UPTREND_MAX_LOOKBACK_WEEKS", 52),
            max(params.get("PRIOR_UPTREND_MIN_LOOKBACK_WEEKS", 12), lookback),
        )
    )


def calculate_lifecycle_prior_uptrend(weekly_df, peak_idx, peak_price, scan_window_weeks, params):
    lookback_weeks = resolve_prior_uptrend_lookback(scan_window_weeks, params)
    min_advance_weeks = int(params.get("PRIOR_UPTREND_MIN_ADVANCE_WEEKS", 4))
    result = {
        "prior_uptrend_pct": np.nan,
        "prior_uptrend_lookback_weeks": int(lookback_weeks),
        "prior_uptrend_low_date": pd.NaT,
        "prior_uptrend_low_price": np.nan,
        "prior_uptrend_advance_weeks": np.nan,
    }

    if weekly_df.empty or pd.isna(peak_idx) or pd.isna(peak_price) or peak_price <= 0:
        return result

    if peak_idx not in weekly_df.index:
        peak_positions = weekly_df.index.get_indexer([peak_idx], method="nearest")
        if not len(peak_positions) or peak_positions[0] < 0:
            return result
        peak_pos = int(peak_positions[0])
    else:
        peak_pos = int(weekly_df.index.get_loc(peak_idx))

    prior_end_pos = peak_pos - min_advance_weeks
    if prior_end_pos < 0:
        return result

    prior_start_pos = max(0, peak_pos - lookback_weeks)
    prior_window = weekly_df.iloc[prior_start_pos:prior_end_pos + 1].copy()
    if prior_window.empty:
        return result

    low_date = prior_window["Low"].idxmin()
    low_price = float(prior_window.loc[low_date, "Low"])
    if low_price <= 0:
        return result

    advance_weeks = (pd.to_datetime(peak_idx) - pd.to_datetime(low_date)).days / 7
    result.update(
        {
            "prior_uptrend_pct": float((peak_price - low_price) / low_price),
            "prior_uptrend_low_date": low_date,
            "prior_uptrend_low_price": low_price,
            "prior_uptrend_advance_weeks": round(float(advance_weeks), 1),
        }
    )
    return result


def build_setup_reason(row):
    parts = []
    window = row.get("scan_window_weeks")
    depth = row.get("Depth")
    recovery = row.get("recovery_pct")
    status = row.get("lifecycle_status")
    pivot_source = row.get("pivot_source")
    distance = row.get("distance_from_pivot_pct")
    prior_pct = row.get("prior_uptrend_pct")

    if pd.notna(window):
        parts.append(f"{int(window)}W base")
    if pd.notna(depth):
        parts.append(f"{float(depth) * 100:.0f}% depth")
    if pd.notna(recovery):
        parts.append(f"{float(recovery) * 100:.0f}% recovery")
    if pd.notna(distance):
        parts.append(f"{float(distance) * 100:.1f}% from pivot")
    if pd.notna(pivot_source):
        parts.append(f"{pivot_source} pivot")
    if pd.notna(prior_pct):
        parts.append(f"{float(prior_pct) * 100:.0f}% prior trend")
    if pd.notna(status):
        parts.append(str(status).replace("_", " ").title())

    return ", ".join(parts)


def check_lifecycle_conditions(
    df,
    params,
    symbol,
    stats,
    logger,
    ath,
    scan_window_weeks,
    stage_results=None,
    signal_close=None,
    signal_as_of_date=None,
    daily_df=None,
):
    try:
        stock_symbol = normalize_stock_symbol(symbol)
        window = df.tail(scan_window_weeks).copy()
        weekly_structure_close = float(window["Close"].iloc[-1])
        latest_close = (
            float(signal_close)
            if signal_close is not None and pd.notna(signal_close)
            else weekly_structure_close
        )
        base_stage_row = {
            "Symbol": stock_symbol,
            "scan_window_weeks": int(scan_window_weeks),
            "latest_close": latest_close,
        }
        minimum_base_duration = int(params.get("MIN_BASE_DURATION_WEEKS", 12))
        peak_exclusion_weeks = max(int(params["MIN_WEEKS"]), minimum_base_duration)
        peak_search_window = window.iloc[:-peak_exclusion_weeks]
        if peak_search_window.empty:
            record_stage(
                stage_results,
                "rejected",
                {**base_stage_row, "failure_reason": "no_valid_window"},
            )
            return None

        peak_idx = peak_search_window["High"].idxmax()
        peak_price = window.loc[peak_idx, "High"]
        after_peak = window.loc[peak_idx:]
        bottom_idx = after_peak["Low"].idxmin()
        bottom_price = after_peak.loc[bottom_idx, "Low"]
        base_age_weeks = (window.index[-1] - peak_idx).days / 7
        peak_to_low_weeks = (bottom_idx - peak_idx).days / 7
        evaluated_row = {
            **base_stage_row,
            "left_high": float(peak_price),
            "left_high_index": peak_idx,
            "base_low": float(bottom_price),
            "base_low_index": bottom_idx,
            "base_age_weeks": round(float(base_age_weeks), 1),
            "peak_to_low_weeks": round(float(peak_to_low_weeks), 1),
            "ATH": float(ath),
        }

        stats.ath_filtered.append(symbol)

        if peak_to_low_weeks < params.get("MIN_PEAK_TO_LOW_WEEKS", 6):
            record_stage(
                stage_results,
                "rejected",
                {
                    **evaluated_row,
                    "failure_reason": "base_low_too_close_to_left_high",
                    "min_peak_to_low_weeks": float(params.get("MIN_PEAK_TO_LOW_WEEKS", 6)),
                },
            )
            return None

        depth = (peak_price - bottom_price) / peak_price
        if not (params["MIN_DEPTH"] <= depth <= params["MAX_DEPTH"]):
            failure_reason = "depth_too_shallow" if depth < params["MIN_DEPTH"] else "depth_too_deep"
            record_stage(
                stage_results,
                "rejected",
                {
                    **evaluated_row,
                    "Depth": float(depth),
                    "failure_reason": failure_reason,
                    "min_depth": float(params["MIN_DEPTH"]),
                    "max_depth": float(params["MAX_DEPTH"]),
                },
            )
            return None
        stats.min_depth.append(symbol)
        record_stage(stage_results, "depth_passed", {**evaluated_row, "Depth": float(depth)})

        stats.duration.append(symbol)

        recovery_pct = (latest_close - bottom_price) / (peak_price - bottom_price)
        meets_discovery_recovery = recovery_pct >= params["RECOVERY_MIN"]
        if not meets_discovery_recovery:
            record_stage(
                stage_results,
                "rejected",
                {
                    **evaluated_row,
                    "Depth": float(depth),
                    "recovery_pct": float(recovery_pct),
                    "failure_reason": "recovery_too_low",
                    "recovery_min": float(params["RECOVERY_MIN"]),
                },
            )
        else:
            stats.recovery.append(symbol)
            record_stage(
                stage_results,
                "recovery_passed",
                {**evaluated_row, "Depth": float(depth), "recovery_pct": float(recovery_pct)},
            )

        atr = window["atr"]
        compression = atr.iloc[-params["COMPRESSION_LOOKBACK"]:].mean() < atr.quantile(0.3)
        close_window = window["Close"].iloc[-5:]
        tight_range = (close_window.max() - close_window.min()) / close_window.mean()
        tight_groups = int(tight_range < 0.05)

        bottom_idx_i = window.index.get_loc(bottom_idx)
        peak_idx_i = window.index.get_loc(peak_idx)
        prior_metrics = calculate_lifecycle_prior_uptrend(df, peak_idx, peak_price, scan_window_weeks, params)
        prior_uptrend_pct = prior_metrics["prior_uptrend_pct"]
        min_prior_uptrend_pct = max(
            params.get("MIN_PRIOR_UPTREND_PCT", 0.20),
            params.get("PRIOR_UPTREND_DEPTH_MULTIPLIER", 1.0) * depth,
        )
        prior_uptrend = pd.notna(prior_uptrend_pct) and prior_uptrend_pct >= min_prior_uptrend_pct
        if not prior_uptrend:
            record_stage(
                stage_results,
                "rejected",
                {
                    **evaluated_row,
                    "Depth": float(depth),
                    "recovery_pct": float(recovery_pct),
                    "prior_uptrend_pct": float(prior_uptrend_pct),
                    "min_prior_uptrend_pct": float(min_prior_uptrend_pct),
                    "prior_uptrend_lookback_weeks": int(prior_metrics["prior_uptrend_lookback_weeks"]),
                    "prior_uptrend_low_date": prior_metrics["prior_uptrend_low_date"],
                    "prior_uptrend_low_price": float(prior_metrics["prior_uptrend_low_price"]),
                    "prior_uptrend_advance_weeks": float(prior_metrics["prior_uptrend_advance_weeks"]),
                    "failure_reason": "prior_uptrend_too_low",
                },
            )
            return None
        stats.prior_uptrend.append(symbol)
        record_stage(
            stage_results,
            "prior_uptrend_passed",
            {
                **evaluated_row,
                "Depth": float(depth),
                "recovery_pct": float(recovery_pct),
                "prior_uptrend_pct": float(prior_uptrend_pct),
                "min_prior_uptrend_pct": float(min_prior_uptrend_pct),
                "prior_uptrend_lookback_weeks": int(prior_metrics["prior_uptrend_lookback_weeks"]),
                "prior_uptrend_low_date": prior_metrics["prior_uptrend_low_date"],
                "prior_uptrend_low_price": float(prior_metrics["prior_uptrend_low_price"]),
                "prior_uptrend_advance_weeks": float(prior_metrics["prior_uptrend_advance_weeks"]),
            },
        )

        tracking_eligible = bool(recovery_pct >= params.get("TRACKING_ELIGIBLE_RECOVERY_MIN", 0.40))
        pivot_lifecycle = calculate_pivot_lifecycle(
            window,
            float(peak_price),
            peak_idx,
            bottom_idx_i,
            depth,
            params,
            tracking_eligible=tracking_eligible,
            daily_window=daily_df,
            base_low=float(bottom_price),
            base_low_date=bottom_idx,
        )
        base_end_date, base_end_reason = resolve_base_end(
            peak_idx,
            pivot_lifecycle,
            window.index[-1],
        )
        base_duration_weeks = (base_end_date - peak_idx).days / 7
        if base_duration_weeks < minimum_base_duration:
            record_stage(
                stage_results,
                "rejected",
                {
                    **evaluated_row,
                    "Depth": float(depth),
                    "base_age_weeks": round(float(base_age_weeks), 1),
                    "base_duration_weeks": round(float(base_duration_weeks), 1),
                    "base_end_date": base_end_date,
                    "base_end_reason": base_end_reason,
                    "failure_reason": "base_duration_too_short",
                    "min_base_duration_weeks": minimum_base_duration,
                },
            )
            return None
        base_move_window = window.loc[peak_idx:base_end_date].copy()
        single_week_metrics = calculate_single_week_move_metrics(
            base_move_window,
            float(peak_price - bottom_price),
            excluded_end_date=(
                base_end_date if base_end_reason == "BREAKOUT" else None
            ),
        )
        largest_move_ratio = single_week_metrics[
            "largest_single_week_move_to_depth_ratio"
        ]
        max_single_week_ratio = float(
            params.get("MAX_SINGLE_WEEK_MOVE_TO_DEPTH_RATIO", 0.50)
        )
        if pd.notna(largest_move_ratio) and largest_move_ratio > max_single_week_ratio:
            record_stage(
                stage_results,
                "rejected",
                {
                    **evaluated_row,
                    "Depth": float(depth),
                    "base_duration_weeks": round(float(base_duration_weeks), 1),
                    "base_end_date": base_end_date,
                    "base_end_reason": base_end_reason,
                    **single_week_metrics,
                    "failure_reason": "single_week_move_too_large",
                    "max_single_week_move_to_depth_ratio": max_single_week_ratio,
                },
            )
            return None
        pivot = float(pivot_lifecycle["selected_pivot"])
        pivot_date = pd.to_datetime(pivot_lifecycle.get("selected_pivot_date"), errors="coerce")
        pivot_idx_i = (
            int(window.index.get_indexer([pivot_date], method="nearest")[0])
            if pd.notna(pivot_date)
            else peak_idx_i
        )
        pivot_detected = bool(pivot_lifecycle.get("pivot_source") != "LEFT_HIGH")
        distance_from_left_high_pct = (latest_close - peak_price) / peak_price
        distance_from_pivot_pct = (latest_close - pivot) / pivot
        failed = bool(pivot_lifecycle.get("lifecycle_phase") == "FAILED")
        breakout_confirmed = bool(pd.notna(pivot_lifecycle.get("breakout_date")))
        breakout_success = bool(pivot_lifecycle.get("breakout_success", False))
        journey_stage = determine_journey_stage(
            recovery_pct,
            breakout_confirmed=breakout_confirmed,
            breakout_success=breakout_success,
            failed=failed,
            discovery_recovery_min=params.get("RECOVERY_MIN", 0.40),
            consideration_recovery_min=params.get(
                "BREAKOUT_CONSIDERATION_RECOVERY_MIN", 0.85
            ),
        )
        pivot_row = {
            **evaluated_row,
            "Depth": float(depth),
            "recovery_pct": float(recovery_pct),
            "prior_uptrend_pct": float(prior_uptrend_pct),
            "min_prior_uptrend_pct": float(min_prior_uptrend_pct),
            "prior_uptrend_lookback_weeks": int(prior_metrics["prior_uptrend_lookback_weeks"]),
            "prior_uptrend_low_date": prior_metrics["prior_uptrend_low_date"],
            "prior_uptrend_low_price": float(prior_metrics["prior_uptrend_low_price"]),
            "prior_uptrend_advance_weeks": float(prior_metrics["prior_uptrend_advance_weeks"]),
            "pivot_price": float(pivot),
            "pivot_detected": bool(pivot_detected),
            "pivot_index": window.index[pivot_idx_i],
            "pivot_index_pos": int(pivot_idx_i),
            "distance_from_left_high_pct": float(distance_from_left_high_pct),
            "distance_from_pivot_pct": float(distance_from_pivot_pct),
            **pivot_lifecycle,
        }
        record_stage(stage_results, "pivot_evaluated", pivot_row)

        result = {
            "Symbol": stock_symbol,
            "scan_window_weeks": int(scan_window_weeks),
            "base_duration_weeks": round(float(base_duration_weeks), 1),
            "base_age_weeks": round(float(base_age_weeks), 1),
            "base_end_date": base_end_date,
            "base_end_reason": base_end_reason,
            **single_week_metrics,
            "max_single_week_move_to_depth_ratio": max_single_week_ratio,
            "Depth": float(depth),
            "recovery_pct": float(recovery_pct),
            "distance_from_left_high_pct": float(distance_from_left_high_pct),
            "distance_from_pivot_pct": float(distance_from_pivot_pct),
            "Tight Groups": tight_groups,
            "compression": bool(compression),
            "prior_uptrend": bool(prior_uptrend),
            "prior_uptrend_pct": float(prior_uptrend_pct),
            "min_prior_uptrend_pct": float(min_prior_uptrend_pct),
            "prior_uptrend_lookback_weeks": int(prior_metrics["prior_uptrend_lookback_weeks"]),
            "prior_uptrend_low_date": prior_metrics["prior_uptrend_low_date"],
            "prior_uptrend_low_price": float(prior_metrics["prior_uptrend_low_price"]),
            "prior_uptrend_advance_weeks": float(prior_metrics["prior_uptrend_advance_weeks"]),
            "pivot_price": float(pivot),
            "pivot_detected": bool(pivot_detected),
            "pivot_index": window.index[pivot_idx_i],
            "pivot_index_pos": int(pivot_idx_i),
            "left_high": float(peak_price),
            "left_high_index": peak_idx,
            "base_low": float(bottom_price),
            "base_low_index": bottom_idx,
            "peak_to_low_weeks": round(float(peak_to_low_weeks), 1),
            "latest_close": float(latest_close),
            "weekly_structure_close": float(weekly_structure_close),
            "structure_as_of_date": window.index[-1],
            "signal_as_of_date": pd.to_datetime(signal_as_of_date, errors="coerce"),
            "journey_stage": journey_stage,
            "strategy_version": params.get(
                "STRATEGY_VERSION", "base_lifecycle_v5_daily_handle"
            ),
            "base_window_weeks": int(scan_window_weeks),
            "tracking_eligible_recovery_min": float(params.get("TRACKING_ELIGIBLE_RECOVERY_MIN", 0.40)),
            "tracking_eligible": tracking_eligible,
            "ATH": float(ath),
            **pivot_lifecycle,
        }
        pivot_row.update(
            {
                "latest_close": float(latest_close),
                "distance_from_left_high_pct": float(distance_from_left_high_pct),
                "distance_from_pivot_pct": float(distance_from_pivot_pct),
                "journey_stage": journey_stage,
                "base_window_weeks": int(scan_window_weeks),
            }
        )
        result["distance_from_left_high_pct"] = float(distance_from_left_high_pct)
        result["distance_from_pivot_pct"] = float(distance_from_pivot_pct)
        result["base_id"] = build_base_id(result)
        result["setup_reason"] = build_setup_reason(result)
        return result

    except Exception as exc:
        logger.debug(f"{symbol} failed lifecycle conditions: {exc}")
        record_stage(
            stage_results,
            "rejected",
            {
                "Symbol": symbol,
                "scan_window_weeks": int(scan_window_weeks),
                "failure_reason": "condition_error",
                "error": str(exc),
            },
        )
        return None


def load_previous_snapshot(scan_dir=SCAN_HISTORY_DIR, current_date_label=None):
    if not os.path.exists(scan_dir):
        return pd.DataFrame()

    snapshots = sorted(
        os.path.join(scan_dir, file_name)
        for file_name in os.listdir(scan_dir)
        if file_name.startswith("base_lifecycle_") and file_name.endswith(".parquet")
        and not file_name.startswith("base_lifecycle_windows_")
        and not file_name.startswith("base_lifecycle_stages_")
    )
    if current_date_label:
        snapshots = [
            path for path in snapshots
            if not os.path.splitext(os.path.basename(path))[0].endswith(current_date_label)
        ]
    if not snapshots:
        return pd.DataFrame()
    return pd.read_parquet(snapshots[-1])


def compare_snapshots(current_df, previous_df):
    current = current_df.copy()
    current["weekly_change"] = "New"

    if previous_df.empty or "Symbol" not in previous_df.columns:
        return current, pd.DataFrame()

    if "Symbol" not in current.columns:
        dropped = previous_df.copy()
        dropped["weekly_change"] = "Dropped"
        return current, dropped

    current["_snapshot_key"] = current.apply(
        lambda row: build_base_id(row.to_dict()), axis=1
    )
    previous_df = previous_df.copy()
    previous_df["_snapshot_key"] = previous_df.apply(
        lambda row: build_base_id(row.to_dict()), axis=1
    )
    previous = previous_df.drop_duplicates("_snapshot_key").set_index("_snapshot_key")
    for idx, row in current.iterrows():
        snapshot_key = row["_snapshot_key"]
        if snapshot_key not in previous.index:
            continue

        prev_row = previous.loc[snapshot_key]
        previous_stage = prev_row.get("journey_stage")
        current_stage = row.get("journey_stage")
        if previous_stage != current_stage:
            current.at[idx, "weekly_change"] = f"{previous_stage} -> {current_stage}"
        else:
            current.at[idx, "weekly_change"] = "Continued"

    dropped = previous_df[
        ~previous_df["_snapshot_key"].isin(set(current["_snapshot_key"]))
    ].copy()
    if not dropped.empty:
        dropped["weekly_change"] = "Dropped"

    return (
        current.drop(columns="_snapshot_key"),
        dropped.drop(columns="_snapshot_key"),
    )


def save_scan_snapshot(results_df, all_windows_df, stage_results=None, scan_dir=SCAN_HISTORY_DIR, scan_date_label=None):
    os.makedirs(scan_dir, exist_ok=True)
    scan_date_label = scan_date_label or datetime.now().strftime("%Y-%m-%d")

    results_path = os.path.join(scan_dir, f"base_lifecycle_{scan_date_label}.parquet")
    latest_path = os.path.join(scan_dir, "latest.parquet")
    results_df.to_parquet(results_path, index=False)
    results_df.to_parquet(latest_path, index=False)

    if all_windows_df is not None and not all_windows_df.empty:
        windows_path = os.path.join(scan_dir, f"base_lifecycle_windows_{scan_date_label}.parquet")
        latest_windows_path = os.path.join(scan_dir, "latest_windows.parquet")
        all_windows_df.to_parquet(windows_path, index=False)
        all_windows_df.to_parquet(latest_windows_path, index=False)

    stage_results_df = stage_results_to_long_frame(stage_results or {})
    if not stage_results_df.empty:
        stage_path = os.path.join(scan_dir, f"base_lifecycle_stages_{scan_date_label}.parquet")
        latest_stage_path = os.path.join(scan_dir, "latest_stage_results.parquet")
        stage_results_df.to_parquet(stage_path, index=False)
        stage_results_df.to_parquet(latest_stage_path, index=False)

    return {"scan_date": scan_date_label, "results_path": results_path, "latest_path": latest_path}


def tracking_paths(tracking_dir=TRACKING_DIR):
    return {
        "active": os.path.join(tracking_dir, ACTIVE_TRACKING_FILE),
        "history": os.path.join(tracking_dir, TRACKING_HISTORY_FILE),
        "archived": os.path.join(tracking_dir, ARCHIVED_TRACKING_FILE),
    }


def load_tracking_state(tracking_dir=TRACKING_DIR):
    paths = tracking_paths(tracking_dir)
    return {
        key: pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame()
        for key, path in paths.items()
    }


def build_base_id(row):
    left_high_date = pd.to_datetime(row.get("left_high_index"), errors="coerce")
    base_low_date = pd.to_datetime(row.get("base_low_index"), errors="coerce")
    date_parts = [
        value.strftime("%Y%m%d") if pd.notna(value) else "na"
        for value in [left_high_date, base_low_date]
    ]
    window_value = row.get("base_window_weeks", row.get("scan_window_weeks"))
    numeric_window = pd.to_numeric(window_value, errors="coerce")
    window_part = str(int(numeric_window)) if pd.notna(numeric_window) else "na"
    return "|".join(
        [normalize_stock_symbol(row.get("Symbol")), f"{window_part}W", *date_parts]
    )


def normalize_tracking_dates(df):
    if df.empty:
        return df

    date_columns = [
        "first_detected_date",
        "last_tracked_date",
        "scan_as_of_date",
        "tracking_date",
        "archived_date",
        "left_high_index",
        "base_low_index",
        "pivot_index",
        "breakout_date",
        "selected_pivot_date",
        "left_high_pivot_date",
        "handle_high_date",
        "handle_low_date",
        "daily_handle_candidate_date",
        "daily_handle_low_date",
        "daily_handle_confirmation_date",
        "daily_handle_invalidation_date",
        "daily_base_low_date",
        "breakout_success_date",
        "structure_as_of_date",
        "signal_as_of_date",
    ]
    normalized = df.copy()
    for column in date_columns:
        if column in normalized.columns:
            normalized[column] = pd.to_datetime(normalized[column], errors="coerce")
    return normalized


def remove_replaced_history_rows(history_df, tracked_df):
    """Remove rows whose normalized base/date key is present in tracked_df."""
    if (
        history_df is None
        or history_df.empty
        or tracked_df is None
        or tracked_df.empty
        or not {"base_id", "tracking_date"}.issubset(history_df.columns)
        or not {"base_id", "tracking_date"}.issubset(tracked_df.columns)
    ):
        return history_df
    history_ids = history_df["base_id"].astype(str)
    history_dates = pd.to_datetime(
        history_df["tracking_date"], errors="coerce"
    ).dt.normalize()
    current_ids = tracked_df["base_id"].astype(str)
    current_dates = pd.to_datetime(
        tracked_df["tracking_date"], errors="coerce"
    ).dt.normalize()
    current_keys = pd.MultiIndex.from_arrays([current_ids, current_dates])
    history_keys = pd.MultiIndex.from_arrays([history_ids, history_dates])
    return history_df[~history_keys.isin(current_keys)]


def consolidate_tracking_structures(df, params=None):
    """Remove duplicate active/archive rows produced by overlapping windows."""
    if df is None or df.empty or "Symbol" not in df.columns:
        return df
    consolidated = []
    for _, symbol_rows in df.groupby("Symbol", dropna=False, sort=False):
        consolidated.extend(
            consolidate_equivalent_bases(
                symbol_rows.to_dict("records"), params=params
            )
        )
    return pd.DataFrame(consolidated).reset_index(drop=True)


def prepare_new_tracking_rows(results_df, as_of_date, active_df, archived_df):
    if results_df is None or results_df.empty or "Symbol" not in results_df.columns:
        return pd.DataFrame()

    existing_ids = set()
    existing_structures = []
    for existing_df in [active_df, archived_df]:
        if existing_df is not None and not existing_df.empty and "base_id" in existing_df.columns:
            existing_ids.update(existing_df["base_id"].dropna().astype(str))
        if existing_df is not None and not existing_df.empty:
            for _, existing_row in existing_df.iterrows():
                existing_ids.add(build_base_id(existing_row.to_dict()))
                existing_structures.append(existing_row.to_dict())

    new_rows = []
    scan_date = pd.to_datetime(as_of_date)
    for _, result_row in results_df.iterrows():
        row = result_row.to_dict()
        recovery_pct = row.get("recovery_pct", np.nan)
        tracking_recovery_min = row.get(
            "tracking_eligible_recovery_min",
            DEFAULT_PARAMS["TRACKING_ELIGIBLE_RECOVERY_MIN"],
        )
        if pd.isna(recovery_pct) or float(recovery_pct) < float(tracking_recovery_min):
            continue

        row["Symbol"] = normalize_stock_symbol(row.get("Symbol"))
        base_id = build_base_id(row)
        if base_id in existing_ids:
            continue
        if any(bases_are_equivalent(existing, row) for existing in existing_structures):
            continue
        row.update(
            {
                "base_id": base_id,
                "first_detected_date": scan_date,
                "last_tracked_date": pd.NaT,
                "tracking_state": "ACTIVE",
                "archive_reason": pd.NA,
                "review_status": "watch",
                "setup_rating": pd.NA,
                "notes": pd.NA,
                "last_reviewed_date": pd.NaT,
            }
        )
        row["setup_reason"] = build_setup_reason(row)
        new_rows.append(row)
        existing_ids.add(base_id)
        existing_structures.append(row)

    return pd.DataFrame(new_rows)


def load_daily_for_tracking(symbol, as_of_date, data_engine):
    data_symbol = str(symbol).strip()
    try:
        df_full = data_engine.get_symbol(data_symbol)
    except FileNotFoundError:
        if data_symbol.endswith(".NS"):
            raise
        data_symbol = f"{data_symbol}.NS"
        df_full = data_engine.get_symbol(data_symbol)
    df_full.index = pd.to_datetime(df_full.index)
    df_full = df_full.sort_index()
    df_full = df_full[df_full.index <= pd.to_datetime(as_of_date)]
    if df_full.empty:
        return pd.DataFrame()

    if isinstance(df_full.columns, pd.MultiIndex):
        df_full.columns = df_full.columns.get_level_values(0)
    df_full = df_full.loc[:, ~df_full.columns.duplicated()]
    return df_full


def load_weekly_for_tracking(symbol, as_of_date, data_engine):
    daily = load_daily_for_tracking(symbol, as_of_date, data_engine)
    if daily.empty:
        return daily
    return resample_completed_weekly(daily, as_of_date)


def calculate_handle_pivot(
    window,
    lookback,
    min_pullback_pct,
    max_pullback_pct,
    min_duration_weeks=2,
):
    recent = window.tail(int(lookback)).copy()
    if len(recent) < 3:
        return {}

    latest_close = float(recent["Close"].iloc[-1])
    candidates = []
    for idx_pos in range(0, len(recent) - 1):
        high_price = float(recent["High"].iloc[idx_pos])
        after_high = recent.iloc[idx_pos + 1:]
        if after_high.empty or high_price <= 0:
            continue

        handle_low_date = after_high["Low"].idxmin()
        handle_low = float(after_high.loc[handle_low_date, "Low"])
        pullback_pct = (high_price - handle_low) / high_price
        duration_weeks = (recent.index[-1] - recent.index[idx_pos]).days / 7
        recovered_near_high = latest_close >= high_price * (1 - max_pullback_pct)
        if (
            duration_weeks >= float(min_duration_weeks)
            and min_pullback_pct <= pullback_pct <= max_pullback_pct
            and recovered_near_high
        ):
            candidates.append(
                {
                    "handle_high_pivot": high_price,
                    "handle_high_date": recent.index[idx_pos],
                    "handle_low": handle_low,
                    "handle_low_date": handle_low_date,
                    "handle_pullback_pct": float(pullback_pct),
                    "handle_duration_weeks": round(float(duration_weeks), 1),
                }
            )

    return candidates[-1] if candidates else {}


def calculate_level_buffer(price, atr, price_pct, atr_multiplier):
    """Return a frozen price/ATR buffer for confirmation or failure."""
    if pd.isna(price) or float(price) <= 0:
        return np.nan
    price_component = float(price) * float(price_pct)
    atr_component = (
        float(atr) * float(atr_multiplier)
        if pd.notna(atr) and float(atr) > 0
        else 0.0
    )
    return float(max(price_component, atr_component))


def crossed_confirmation_level(previous_close, current_close, confirmation_level):
    return bool(
        pd.notna(previous_close)
        and pd.notna(current_close)
        and pd.notna(confirmation_level)
        and float(previous_close) <= float(confirmation_level)
        and float(current_close) > float(confirmation_level)
    )


def calculate_pivot_zone(left_high, base_depth, params):
    """Return the valid pivot band as recovery multiples of base depth."""
    left_high = float(left_high)
    base_depth_price = left_high * float(base_depth)
    base_low = left_high - base_depth_price
    minimum_recovery = float(
        params.get("PIVOT_MIN_BASE_RECOVERY", PIVOT_MIN_BASE_RECOVERY)
    )
    maximum_recovery = float(
        params.get("PIVOT_MAX_BASE_RECOVERY", PIVOT_MAX_BASE_RECOVERY)
    )
    return {
        "base_depth_price": float(base_depth_price),
        "implied_base_low": float(base_low),
        "pivot_min_price": float(base_low + minimum_recovery * base_depth_price),
        "pivot_max_price": float(base_low + maximum_recovery * base_depth_price),
        "pivot_min_base_recovery": minimum_recovery,
        "pivot_max_base_recovery": maximum_recovery,
    }


def calculate_pivot_candidate_snapshot(source, left_high, left_high_date, base_depth, params):
    """Select one actionable pivot: a valid handle, otherwise the left high."""
    pivot_zone = calculate_pivot_zone(left_high, base_depth, params)
    pivot_min = pivot_zone["pivot_min_price"]
    pivot_max = pivot_zone["pivot_max_price"]
    handle_max_pullback_pct = float(base_depth) / 3.0
    candidates = {
        "left_high_pivot": float(left_high),
        "left_high_pivot_date": left_high_date,
        "handle_high_pivot": np.nan,
        "handle_high_date": pd.NaT,
        "handle_low": np.nan,
        "handle_low_date": pd.NaT,
        "handle_pullback_pct": np.nan,
        "handle_max_pullback_pct": float(handle_max_pullback_pct),
        "handle_duration_weeks": np.nan,
        "selected_pivot": float(left_high),
        "selected_pivot_date": left_high_date,
        "pivot_source": "LEFT_HIGH",
        # Compatibility aliases used by charts and existing saved-state code.
        "major_pivot": float(left_high),
        "major_pivot_date": left_high_date,
        "setup_atr": np.nan,
        "handle_pivot_base_recovery": np.nan,
        **pivot_zone,
    }
    if source is None or source.empty:
        return candidates

    handle = calculate_handle_pivot(
        source,
        params.get("TRACKING_HANDLE_LOOKBACK_WEEKS", 10),
        params.get("TRACKING_HANDLE_MIN_PULLBACK_PCT", 0.03),
        handle_max_pullback_pct,
        params.get("HANDLE_MIN_DURATION_WEEKS", 2),
    )
    handle_price = handle.get("handle_high_pivot", np.nan)
    if pd.notna(handle_price) and pivot_min <= float(handle_price) <= pivot_max:
        handle_recovery = (
            (float(handle_price) - pivot_zone["implied_base_low"])
            / pivot_zone["base_depth_price"]
        )
        candidates.update(handle)
        candidates["handle_pivot_base_recovery"] = float(handle_recovery)
        merge_tolerance = float(params.get("HANDLE_MAJOR_MERGE_TOLERANCE_PCT", 0.02))
        if abs(float(handle_price) - float(left_high)) / float(left_high) <= merge_tolerance:
            candidates["pivot_source"] = "LEFT_HIGH_HANDLE_MERGED"
        else:
            candidates.update(
                {
                    "selected_pivot": float(handle_price),
                    "selected_pivot_date": candidates["handle_high_date"],
                    "pivot_source": "HANDLE",
                    "major_pivot": float(handle_price),
                    "major_pivot_date": candidates["handle_high_date"],
                }
            )

    if "atr" in source.columns and pd.notna(source["atr"].iloc[-1]):
        candidates["setup_atr"] = float(source["atr"].iloc[-1])
    return candidates


def calculate_breakout_metrics_from_date(window, pivot_price, breakout_date):
    latest_close = float(window["Close"].iloc[-1])
    metrics = {
        "breakout_date": pd.NaT,
        "days_since_breakout": np.nan,
        "weeks_since_breakout": np.nan,
        "breakout_close": np.nan,
        "breakout_volume_ratio": np.nan,
        "gain_since_breakout_pct": np.nan,
        "max_gain_after_breakout_pct": np.nan,
        "max_drawdown_after_breakout_pct": np.nan,
        "pullback_from_post_breakout_high_pct": np.nan,
        "holding_pivot": bool(latest_close >= pivot_price),
    }
    if pd.isna(breakout_date) or pivot_price <= 0 or breakout_date not in window.index:
        return metrics

    breakout_row = window.loc[breakout_date]
    if isinstance(breakout_row, pd.DataFrame):
        breakout_row = breakout_row.iloc[0]
    post_breakout = window.loc[breakout_date:].copy()
    breakout_close = float(breakout_row["Close"])
    volume_ma_10 = breakout_row.get("volume_ma_10", np.nan)
    volume_ratio = (
        float(breakout_row["Volume"] / volume_ma_10)
        if pd.notna(volume_ma_10) and volume_ma_10 > 0
        else np.nan
    )
    highest_high = float(post_breakout["High"].max())
    lowest_low = float(post_breakout["Low"].min())
    metrics.update(
        {
            "breakout_date": breakout_date,
            "days_since_breakout": int((window.index[-1] - breakout_date).days),
            "weeks_since_breakout": round((window.index[-1] - breakout_date).days / 7, 1),
            "breakout_close": breakout_close,
            "breakout_volume_ratio": volume_ratio,
            "gain_since_breakout_pct": (latest_close - breakout_close) / breakout_close,
            "max_gain_after_breakout_pct": (highest_high - breakout_close) / breakout_close,
            "max_drawdown_after_breakout_pct": (lowest_low - breakout_close) / breakout_close,
            "pullback_from_post_breakout_high_pct": (latest_close - highest_high) / highest_high,
            "holding_pivot": bool(latest_close >= pivot_price),
        }
    )
    return metrics


def prepare_daily_handle_window(daily_window, base_low_date, atr_window=14):
    """Return completed daily bars after the actual low inside the base-low week."""
    if daily_window is None or daily_window.empty:
        return pd.DataFrame(), pd.NaT

    daily = daily_window.copy()
    daily.index = pd.to_datetime(daily.index)
    daily = daily.sort_index()
    if isinstance(daily.columns, pd.MultiIndex):
        daily.columns = daily.columns.get_level_values(0)
    daily = daily.loc[:, ~daily.columns.duplicated()]
    required = {"High", "Low", "Close"}
    if not required.issubset(daily.columns):
        return pd.DataFrame(), pd.NaT

    previous_close = daily["Close"].shift(1)
    true_range = pd.concat(
        [
            daily["High"] - daily["Low"],
            (daily["High"] - previous_close).abs(),
            (daily["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    daily["daily_atr_14"] = true_range.rolling(
        int(atr_window), min_periods=1
    ).mean()

    weekly_low_date = pd.to_datetime(base_low_date, errors="coerce")
    if pd.isna(weekly_low_date):
        return daily, daily.index[0]
    base_low_week = daily.loc[
        (daily.index >= weekly_low_date - pd.Timedelta(days=6))
        & (daily.index <= weekly_low_date)
    ]
    if base_low_week.empty:
        eligible = daily[daily.index <= weekly_low_date]
        resolved_low_date = eligible.index[-1] if not eligible.empty else daily.index[0]
    else:
        resolved_low_date = base_low_week["Low"].idxmin()
    return daily[daily.index >= resolved_low_date].copy(), resolved_low_date


def _calculate_daily_handle_state_legacy(
    daily_window,
    left_high,
    left_high_date,
    base_low,
    base_low_date,
    base_depth,
    params,
):
    """Replay daily candles with exactly one confirmed, breakout-eligible pivot."""
    pivot_zone = calculate_pivot_zone(left_high, base_depth, params)
    daily, resolved_base_low_date = prepare_daily_handle_window(
        daily_window,
        base_low_date,
        atr_window=params.get("ATR_WINDOW", 14),
    )
    left_high = float(left_high)
    base_low = float(base_low)
    confirmation_sessions = int(
        params.get("DAILY_HANDLE_CONFIRMATION_SESSIONS", 5)
    )
    maximum_pullback = float(base_depth) / 3.0

    left_atr_rows = daily[daily.index <= pd.to_datetime(left_high_date, errors="coerce")]
    left_setup_atr = (
        float(left_atr_rows["daily_atr_14"].iloc[-1])
        if not left_atr_rows.empty
        else (
            float(daily["daily_atr_14"].iloc[0])
            if not daily.empty
            else np.nan
        )
    )
    left_snapshot = {
        "left_high_pivot": left_high,
        "left_high_pivot_date": pd.to_datetime(left_high_date, errors="coerce"),
        "handle_high_pivot": np.nan,
        "handle_high_date": pd.NaT,
        "handle_low": np.nan,
        "handle_low_date": pd.NaT,
        "handle_pullback_pct": np.nan,
        "handle_max_pullback_pct": maximum_pullback,
        "handle_duration_weeks": np.nan,
        "selected_pivot": left_high,
        "selected_pivot_date": pd.to_datetime(left_high_date, errors="coerce"),
        "pivot_source": "LEFT_HIGH",
        "major_pivot": left_high,
        "major_pivot_date": pd.to_datetime(left_high_date, errors="coerce"),
        "setup_atr": left_setup_atr,
        "handle_pivot_base_recovery": np.nan,
        **pivot_zone,
    }
    state_fields = {
        "daily_handle_state": "LEFT_HIGH_ACTIVE",
        "daily_handle_candidate_pivot": np.nan,
        "daily_handle_candidate_date": pd.NaT,
        "daily_handle_low": np.nan,
        "daily_handle_low_date": pd.NaT,
        "daily_handle_pullback_pct": np.nan,
        "daily_handle_sessions_after_pivot": 0,
        "daily_handle_confirmation_sessions": confirmation_sessions,
        "daily_handle_confirmation_date": pd.NaT,
        "daily_handle_valid": False,
        "daily_handle_breakout_eligible": True,
        "daily_base_low_date": resolved_base_low_date,
    }
    if daily.empty or len(daily) < 2:
        return {
            **left_snapshot,
            **state_fields,
            "daily_breakout_date": pd.NaT,
            "daily_breakout_atr": np.nan,
            "daily_event_window": daily,
        }

    candidate = None
    active_snapshot = left_snapshot.copy()
    handle_state = "LEFT_HIGH_ACTIVE"
    breakout_date = pd.NaT
    breakout_atr = np.nan
    selected_at_breakout = None
    latest_candidate_metrics = {
        **state_fields,
        "daily_handle_invalidated": False,
        "daily_handle_invalidation_date": pd.NaT,
    }

    def active_is_handle():
        return active_snapshot.get("pivot_source") == "DAILY_HANDLE"

    def resting_state():
        return "HANDLE_READY" if active_is_handle() else "LEFT_HIGH_ACTIVE"

    def pending_state():
        return (
            "HANDLE_REPLACEMENT_PENDING"
            if active_is_handle()
            else "HANDLE_CANDIDATE"
        )

    def pivot_trigger(snapshot):
        pivot = float(snapshot["selected_pivot"])
        buffer = calculate_level_buffer(
            pivot,
            snapshot.get("setup_atr", np.nan),
            params.get("BREAKOUT_PRICE_BUFFER_PCT", 0.005),
            params.get("BREAKOUT_ATR_BUFFER_MULTIPLIER", 0.20),
        )
        return pivot + float(buffer)

    def new_candidate(current_pos, current_high, current):
        recovery = (
            (current_high - base_low) / (left_high - base_low)
            if left_high > base_low
            else np.nan
        )
        if pd.isna(recovery):
            return None
        if not (
            pivot_zone["pivot_min_base_recovery"]
            <= float(recovery)
            <= pivot_zone["pivot_max_base_recovery"]
        ):
            return None
        if active_is_handle() and current_high <= float(active_snapshot["selected_pivot"]):
            return None
        return {
            "price": float(current_high),
            "date": daily.index[current_pos],
            "position": int(current_pos),
            "atr": float(current.get("daily_atr_14", np.nan)),
            "recovery": float(recovery),
        }

    def update_pending_metrics(candidate_value, state, **extra):
        latest_candidate_metrics.update(
            {
                "daily_handle_state": state,
                "daily_handle_candidate_pivot": float(candidate_value["price"]),
                "daily_handle_candidate_date": candidate_value["date"],
                "daily_handle_sessions_after_pivot": 0,
                "daily_handle_valid": active_is_handle(),
                # One confirmed pivot is always eligible, even while a
                # replacement candidate is being evaluated.
                "daily_handle_breakout_eligible": True,
                **extra,
            }
        )

    for current_pos in range(1, len(daily)):
        current = daily.iloc[current_pos]
        current_date = daily.index[current_pos]
        previous_close = float(daily["Close"].iloc[current_pos - 1])
        current_close = float(current["Close"])
        current_high = float(current["High"])

        # The first operation for every completed candle is always the same:
        # test the one active, confirmed pivot. Candidate state cannot disable
        # or redirect this check.
        if crossed_confirmation_level(
            previous_close,
            current_close,
            pivot_trigger(active_snapshot),
        ):
            breakout_date = current_date
            breakout_atr = float(current.get("daily_atr_14", np.nan))
            selected_at_breakout = active_snapshot.copy()
            handle_state = "BREAKOUT_CONFIRMED"
            latest_candidate_metrics.update(
                {
                    "daily_handle_state": handle_state,
                    "daily_handle_valid": active_is_handle(),
                    "daily_handle_breakout_eligible": False,
                }
            )
            break

        # A confirmed handle is invalidated only by its own post-handle
        # pullback. Failure of a replacement candidate never deletes it.
        if active_is_handle():
            active_date = pd.to_datetime(
                active_snapshot.get("selected_pivot_date"), errors="coerce"
            )
            after_active = daily.loc[
                (daily.index > active_date) & (daily.index <= current_date)
            ]
            if not after_active.empty:
                active_low_date = after_active["Low"].idxmin()
                active_low = float(after_active.loc[active_low_date, "Low"])
                active_pullback = (
                    float(active_snapshot["selected_pivot"]) - active_low
                ) / float(active_snapshot["selected_pivot"])
                active_snapshot.update(
                    {
                        "handle_low": active_low,
                        "handle_low_date": active_low_date,
                        "handle_pullback_pct": float(active_pullback),
                    }
                )
                if active_pullback > maximum_pullback:
                    latest_candidate_metrics.update(
                        {
                            "daily_handle_invalidated": True,
                            "daily_handle_invalidation_date": current_date,
                            "daily_handle_valid": False,
                        }
                    )
                    active_snapshot = left_snapshot.copy()
                    candidate = None
                    handle_state = "LEFT_HIGH_ACTIVE"

                    # The fallback pivot becomes effective on this completed
                    # candle, so do not lose an exact left-high crossing.
                    if crossed_confirmation_level(
                        previous_close,
                        current_close,
                        pivot_trigger(active_snapshot),
                    ):
                        breakout_date = current_date
                        breakout_atr = float(current.get("daily_atr_14", np.nan))
                        selected_at_breakout = active_snapshot.copy()
                        handle_state = "BREAKOUT_CONFIRMED"
                        latest_candidate_metrics.update(
                            {
                                "daily_handle_state": handle_state,
                                "daily_handle_breakout_eligible": False,
                            }
                        )
                        break

        if candidate is None:
            candidate = new_candidate(current_pos, current_high, current)
            if candidate is not None:
                handle_state = pending_state()
                update_pending_metrics(
                    candidate,
                    handle_state,
                    daily_handle_low=np.nan,
                    daily_handle_low_date=pd.NaT,
                    daily_handle_pullback_pct=np.nan,
                )
            else:
                handle_state = resting_state()
                latest_candidate_metrics.update(
                    {
                        "daily_handle_state": handle_state,
                        "daily_handle_valid": active_is_handle(),
                        "daily_handle_breakout_eligible": True,
                    }
                )
            continue

        if current_high > float(candidate["price"]):
            replacement = new_candidate(current_pos, current_high, current)
            if replacement is None:
                # The pending structure failed, but the current confirmed
                # pivot remains untouched and eligible.
                candidate = None
                handle_state = resting_state()
                latest_candidate_metrics.update(
                    {
                        "daily_handle_state": handle_state,
                        "daily_handle_valid": active_is_handle(),
                        "daily_handle_breakout_eligible": True,
                    }
                )
                continue
            candidate = replacement
            handle_state = pending_state()
            update_pending_metrics(
                candidate,
                handle_state,
                daily_handle_low=np.nan,
                daily_handle_low_date=pd.NaT,
                daily_handle_pullback_pct=np.nan,
            )
            continue

        after_candidate = daily.iloc[int(candidate["position"]) + 1 : current_pos + 1]
        sessions_after_pivot = current_pos - int(candidate["position"])
        handle_low_date = after_candidate["Low"].idxmin()
        handle_low = float(after_candidate.loc[handle_low_date, "Low"])
        pullback_pct = (float(candidate["price"]) - handle_low) / float(
            candidate["price"]
        )
        handle_state = pending_state()
        update_pending_metrics(
            candidate,
            handle_state,
            daily_handle_low=handle_low,
            daily_handle_low_date=handle_low_date,
            daily_handle_pullback_pct=float(pullback_pct),
            daily_handle_sessions_after_pivot=int(sessions_after_pivot),
        )

        if pullback_pct > maximum_pullback:
            candidate = None
            handle_state = resting_state()
            latest_candidate_metrics.update(
                {
                    "daily_handle_state": handle_state,
                    "daily_handle_valid": active_is_handle(),
                    "daily_handle_breakout_eligible": True,
                }
            )
            continue

        if sessions_after_pivot >= confirmation_sessions:
            confirmation_date = current_date
            active_snapshot = {
                **left_snapshot,
                "handle_high_pivot": float(candidate["price"]),
                "handle_high_date": candidate["date"],
                "handle_low": handle_low,
                "handle_low_date": handle_low_date,
                "handle_pullback_pct": float(pullback_pct),
                "handle_duration_weeks": round(sessions_after_pivot / 5.0, 1),
                "selected_pivot": float(candidate["price"]),
                "selected_pivot_date": candidate["date"],
                "pivot_source": "DAILY_HANDLE",
                "major_pivot": float(candidate["price"]),
                "major_pivot_date": candidate["date"],
                "setup_atr": float(candidate["atr"]),
                "handle_pivot_base_recovery": float(candidate["recovery"]),
            }
            candidate = None
            handle_state = "HANDLE_READY"
            latest_candidate_metrics.update(
                {
                    "daily_handle_state": handle_state,
                    "daily_handle_confirmation_date": confirmation_date,
                    "daily_handle_valid": True,
                    "daily_handle_breakout_eligible": True,
                    "daily_handle_invalidated": False,
                }
            )

    selected = selected_at_breakout or active_snapshot
    latest_candidate_metrics["daily_handle_state"] = handle_state
    if selected_at_breakout is None:
        latest_candidate_metrics["daily_handle_valid"] = active_is_handle()
        latest_candidate_metrics["daily_handle_breakout_eligible"] = True
    return {
        **selected,
        **latest_candidate_metrics,
        "daily_breakout_date": breakout_date,
        "daily_breakout_atr": breakout_atr,
        "daily_event_window": daily,
    }


def calculate_daily_handle_state(
    daily_window,
    left_high,
    left_high_date,
    base_low,
    base_low_date,
    base_depth,
    params,
):
    """Reconstruct daily state by folding the shared one-candle transition."""
    daily, resolved_base_low_date = prepare_daily_handle_window(
        daily_window,
        base_low_date,
        atr_window=params.get("ATR_WINDOW", 14),
    )
    left_atr_rows = daily[
        daily.index <= pd.to_datetime(left_high_date, errors="coerce")
    ]
    left_setup_atr = (
        float(left_atr_rows["daily_atr_14"].iloc[-1])
        if not left_atr_rows.empty
        else (
            float(daily["daily_atr_14"].iloc[0])
            if not daily.empty
            else np.nan
        )
    )
    first_candle = None
    if not daily.empty:
        first_candle = {
            **daily.iloc[0].to_dict(),
            "date": daily.index[0],
        }
    state = initialize_daily_handle_state(
        left_high=left_high,
        left_high_date=left_high_date,
        base_low=base_low,
        base_depth=base_depth,
        resolved_base_low_date=resolved_base_low_date,
        left_setup_atr=left_setup_atr,
        first_candle=first_candle,
        params=params,
    )
    for candle_date, candle_row in daily.iloc[1:].iterrows():
        candle = {**candle_row.to_dict(), "date": candle_date}
        state, _events = advance_daily_handle_state(state, candle, params)
        if pd.notna(state.get("breakout_date")):
            break
    result = daily_handle_result(state, daily_event_window=daily)
    # Preserve the historical short-window schema exactly.  The internal state
    # still carries these fields so incremental processing can continue safely.
    if len(daily) < 2:
        result.pop("daily_handle_invalidated", None)
        result.pop("daily_handle_invalidation_date", None)
    return result


def calculate_pivot_lifecycle(
    window,
    left_high,
    left_high_date,
    bottom_idx_i,
    base_depth,
    params,
    tracking_eligible=False,
    daily_window=None,
    base_low=None,
    base_low_date=None,
):
    """Run the single-pivot lifecycle using a valid handle or the left high."""
    use_daily_handle = daily_window is not None and not daily_window.empty
    event_window = daily_window if use_daily_handle else window
    latest_close = float(event_window["Close"].iloc[-1])
    daily_handle_fields = {}

    if use_daily_handle:
        daily_state = calculate_daily_handle_state(
            daily_window,
            left_high,
            left_high_date,
            base_low,
            base_low_date,
            base_depth,
            params,
        )
        selected = {
            key: value
            for key, value in daily_state.items()
            if not key.startswith("daily_")
        }
        daily_handle_fields = {
            key: value
            for key, value in daily_state.items()
            if key.startswith("daily_") and key != "daily_event_window"
        }
        breakout_date = daily_state["daily_breakout_date"]
        breakout_atr = daily_state["daily_breakout_atr"]
        event_window = daily_state["daily_event_window"]
    else:
        empty_source = window.iloc[0:0]
        pre_current_snapshot = calculate_pivot_candidate_snapshot(
            empty_source, left_high, left_high_date, base_depth, params
        )
        frozen_snapshot = None
        breakout_date = pd.NaT
        breakout_atr = np.nan

        # Compatibility path for callers that provide weekly candles only.
        start_pos = max(int(bottom_idx_i) + 1, 1)
        for current_pos in range(start_pos, len(window)):
            source = window.iloc[int(bottom_idx_i) + 1:current_pos].copy()
            snapshot = calculate_pivot_candidate_snapshot(
                source, left_high, left_high_date, base_depth, params
            )
            selected_pivot = float(snapshot["selected_pivot"])
            breakout_buffer = calculate_level_buffer(
                selected_pivot,
                snapshot.get("setup_atr", np.nan),
                params.get("BREAKOUT_PRICE_BUFFER_PCT", 0.005),
                params.get("BREAKOUT_ATR_BUFFER_MULTIPLIER", 0.20),
            )
            confirmation_level = selected_pivot + float(breakout_buffer)
            if crossed_confirmation_level(
                window["Close"].iloc[current_pos - 1],
                window["Close"].iloc[current_pos],
                confirmation_level,
            ):
                frozen_snapshot = snapshot.copy()
                breakout_date = window.index[current_pos]
                current_atr = window.iloc[current_pos].get("atr", np.nan)
                breakout_atr = (
                    float(current_atr)
                    if pd.notna(current_atr)
                    else snapshot.get("setup_atr", np.nan)
                )
                break
            pre_current_snapshot = snapshot

        if frozen_snapshot is not None:
            selected = frozen_snapshot
        else:
            if len(window) > int(bottom_idx_i) + 1:
                selected = calculate_pivot_candidate_snapshot(
                    window.iloc[int(bottom_idx_i) + 1:-1].copy(),
                    left_high,
                    left_high_date,
                    base_depth,
                    params,
                )
            else:
                selected = pre_current_snapshot

    daily_handle_state = daily_handle_fields.get("daily_handle_state")
    handle_invalidated = bool(
        daily_handle_fields.get("daily_handle_invalidated", False)
        or daily_handle_state == "HANDLE_INVALIDATED"
        or (
            pd.isna(breakout_date)
            and selected.get("pivot_source") == "HANDLE"
            and pd.notna(selected.get("handle_low"))
            and latest_close < float(selected["handle_low"])
        )
    )
    if handle_invalidated:
        selected.update(
            {
                "selected_pivot": float(left_high),
                "selected_pivot_date": left_high_date,
                "pivot_source": "LEFT_HIGH",
                "major_pivot": float(left_high),
                "major_pivot_date": left_high_date,
            }
        )

    selected_pivot = float(selected["selected_pivot"])
    setup_atr = selected.get("setup_atr", np.nan)
    breakout_buffer = calculate_level_buffer(
        selected_pivot,
        setup_atr,
        params.get("BREAKOUT_PRICE_BUFFER_PCT", 0.005),
        params.get("BREAKOUT_ATR_BUFFER_MULTIPLIER", 0.20),
    )
    confirmation_level = selected_pivot + float(breakout_buffer)
    left_high_buffer = calculate_level_buffer(
        left_high,
        setup_atr,
        params.get("BREAKOUT_PRICE_BUFFER_PCT", 0.005),
        params.get("BREAKOUT_ATR_BUFFER_MULTIPLIER", 0.20),
    )
    left_high_confirmation = float(left_high) + float(left_high_buffer)

    breakout_range_pct = float(params.get("BREAKOUT_RANGE_PCT", 0.10))
    breakout_range_low = selected_pivot * (1.0 - breakout_range_pct)
    breakout_range_high = selected_pivot * (1.0 + breakout_range_pct)
    success_level = max(breakout_range_high, left_high_confirmation)

    failure_atr = breakout_atr if pd.notna(breakout_atr) else setup_atr
    failure_buffer = calculate_level_buffer(
        selected_pivot,
        failure_atr,
        params.get("FAILURE_PRICE_BUFFER_PCT", 0.01),
        params.get("FAILURE_ATR_BUFFER_MULTIPLIER", 0.25),
    )
    hard_failure_level = breakout_range_low - float(failure_buffer)

    breakout_metrics = calculate_breakout_metrics_from_date(
        event_window, selected_pivot, breakout_date
    )
    post_breakout = (
        event_window.loc[breakout_date:].copy()
        if pd.notna(breakout_date)
        else event_window.iloc[0:0].copy()
    )
    success_rows = post_breakout[post_breakout["Close"] > success_level]
    success_date = success_rows.index[0] if not success_rows.empty else pd.NaT
    success_close = (
        float(success_rows.iloc[0]["Close"])
        if not success_rows.empty
        else np.nan
    )
    breakout_success = bool(pd.notna(success_date))

    hard_failure = False
    persistent_failure = False
    if pd.notna(breakout_date):
        post_breakout_closes = post_breakout["Close"]
        hard_failure = bool((post_breakout_closes < hard_failure_level).any())
        persistent_failure = bool(
            len(post_breakout_closes) >= 2
            and (
                (post_breakout_closes < breakout_range_low)
                & (post_breakout_closes.shift(1) < breakout_range_low)
            ).any()
        )
    failed = bool(hard_failure or persistent_failure)
    range_breach = bool(
        pd.notna(breakout_date)
        and latest_close < breakout_range_low
        and not failed
    )

    if pd.isna(breakout_date):
        historical_phase = "FORMING"
        current_zone = "PRE_BREAKOUT"
    else:
        if latest_close < breakout_range_low:
            current_zone = "BELOW_RANGE"
        elif latest_close < selected_pivot:
            current_zone = "RETEST_RANGE"
        elif latest_close <= breakout_range_high:
            current_zone = "BUY_RANGE"
        else:
            current_zone = "ABOVE_BUY_RANGE"

        if failed:
            historical_phase = "FAILED"
        elif breakout_success:
            historical_phase = "BREAKOUT_SUCCESS"
        else:
            historical_phase = "BREAKOUT_CONFIRMED"

    weeks_since_breakout = breakout_metrics.get("weeks_since_breakout", np.nan)
    breakout_stalled = bool(
        historical_phase == "BREAKOUT_CONFIRMED"
        and pd.notna(weeks_since_breakout)
        and float(weeks_since_breakout) >= float(params.get("BREAKOUT_STALL_WEEKS", 10))
    )
    post_success_reentry = bool(
        breakout_success
        and not failed
        and current_zone in {"RETEST_RANGE", "BUY_RANGE"}
    )
    distance_from_pivot_pct = (latest_close - selected_pivot) / selected_pivot

    if failed:
        lifecycle_status = "FAILED"
    elif breakout_stalled:
        lifecycle_status = "BREAKOUT_STALLED"
    elif post_success_reentry:
        lifecycle_status = "POST_SUCCESS_REENTRY_RANGE"
    elif historical_phase == "BREAKOUT_SUCCESS":
        lifecycle_status = "BREAKOUT_SUCCESS"
    elif range_breach:
        lifecycle_status = "BREAKOUT_RANGE_BREACH"
    elif current_zone == "RETEST_RANGE":
        lifecycle_status = "BREAKOUT_RETEST_RANGE"
    elif current_zone == "BUY_RANGE":
        lifecycle_status = "BREAKOUT_BUY_RANGE"
    elif pd.isna(breakout_date):
        if handle_invalidated:
            lifecycle_status = "RESETTING"
        elif selected.get("pivot_source") in {"HANDLE", "DAILY_HANDLE"}:
            lifecycle_status = "HANDLE_READY"
        elif -0.05 <= distance_from_pivot_pct <= 0:
            lifecycle_status = "NEAR_PIVOT"
        elif tracking_eligible:
            lifecycle_status = "RESETTING" if distance_from_pivot_pct < -0.15 else "TRACKING"
        else:
            lifecycle_status = "BASE_FORMING"
    else:
        lifecycle_status = "BREAKOUT_CONFIRMED"

    return {
        **selected,
        "pivot_price": selected_pivot,
        "pivot_index": selected.get("selected_pivot_date", left_high_date),
        "distance_from_pivot_pct": float(distance_from_pivot_pct),
        "breakout_buffer": float(breakout_buffer),
        "confirmation_level": float(confirmation_level),
        "left_high_confirmation_level": float(left_high_confirmation),
        "breakout_range_pct": float(breakout_range_pct),
        "breakout_range_low": float(breakout_range_low),
        "breakout_range_high": float(breakout_range_high),
        "success_level": float(success_level),
        "failure_buffer": float(failure_buffer),
        "hard_failure_level": float(hard_failure_level),
        "lifecycle_phase": historical_phase,
        # Compatibility alias for snapshots produced before lifecycle_phase.
        "historical_phase": historical_phase,
        "current_zone": current_zone,
        "breakout_success": breakout_success,
        "breakout_success_date": success_date,
        "breakout_success_close": success_close,
        "post_success_reentry": post_success_reentry,
        "breakout_stalled": breakout_stalled,
        "range_breach": range_breach,
        "handle_invalidated": handle_invalidated,
        "left_high_cleared": bool(latest_close > left_high_confirmation),
        "hard_failure": hard_failure,
        "persistent_failure": persistent_failure,
        "lifecycle_status": lifecycle_status,
        # Compatibility aliases for existing charts/snapshots.
        "major_breakout_buffer": float(breakout_buffer),
        "major_confirmation_level": float(confirmation_level),
        "major_failure_buffer": float(failure_buffer),
        "major_failure_level": float(hard_failure_level),
        **daily_handle_fields,
        **breakout_metrics,
    }


def update_tracking_row(row, as_of_date, data_engine, params=None):
    params = {**DEFAULT_PARAMS, **(params or {})}
    updated = row.copy()
    updated["Symbol"] = normalize_stock_symbol(updated.get("Symbol"))
    updated["base_id"] = build_base_id(updated)
    scan_date = pd.to_datetime(as_of_date)
    updated["scan_as_of_date"] = scan_date
    updated["last_tracked_date"] = scan_date

    try:
        daily = load_daily_for_tracking(updated["Symbol"], scan_date, data_engine)
        structure_cutoff = latest_completed_week_end(scan_date)
        weekly = resample_completed_weekly(daily, structure_cutoff)
        if weekly.empty:
            updated["tracking_state"] = "ACTIVE"
            updated["tracking_error"] = "no_data_as_of_date"
            return updated

        weekly = weekly.copy()
        weekly = calculate_cup_metrics(weekly, params)
        left_high_date = pd.to_datetime(updated.get("left_high_index"), errors="coerce")
        base_low_date = pd.to_datetime(updated.get("base_low_index"), errors="coerce")
        start_date = left_high_date
        track_window = weekly[weekly.index >= start_date].copy() if pd.notna(start_date) else weekly.copy()
        if track_window.empty:
            track_window = weekly.copy()

        latest_close = float(daily["Close"].iloc[-1])
        weekly_structure_close = float(track_window["Close"].iloc[-1])
        bottom_positions = (
            track_window.index.get_indexer([base_low_date], method="nearest")
            if pd.notna(base_low_date)
            else []
        )
        bottom_idx_i = (
            int(bottom_positions[0])
            if len(bottom_positions) and bottom_positions[0] >= 0
            else int(track_window["Low"].values.argmin())
        )
        left_high = float(updated.get("left_high", updated.get("left_high_pivot")))
        base_low = float(updated.get("base_low", updated.get("base_low_pivot")))
        base_depth = float(updated.get("Depth", updated.get("depth")))
        pivot_lifecycle = calculate_pivot_lifecycle(
            track_window,
            left_high,
            left_high_date,
            bottom_idx_i,
            base_depth,
            params,
            tracking_eligible=True,
            daily_window=daily,
            base_low=base_low,
            base_low_date=base_low_date,
        )
        lifecycle_status = pivot_lifecycle["lifecycle_status"]
        selected_pivot = float(pivot_lifecycle["selected_pivot"])
        recovery_pct = (
            (latest_close - base_low) / (left_high - base_low)
            if left_high > base_low
            else np.nan
        )
        failed = bool(pivot_lifecycle.get("lifecycle_phase") == "FAILED")
        breakout_confirmed = bool(pd.notna(pivot_lifecycle.get("breakout_date")))
        breakout_success = bool(pivot_lifecycle.get("breakout_success", False))
        journey_stage = determine_journey_stage(
            recovery_pct,
            breakout_confirmed=breakout_confirmed,
            breakout_success=breakout_success,
            failed=failed,
            discovery_recovery_min=params.get("RECOVERY_MIN", 0.40),
            consideration_recovery_min=params.get(
                "BREAKOUT_CONSIDERATION_RECOVERY_MIN", 0.85
            ),
        )
        base_end_date, base_end_reason = resolve_base_end(
            left_high_date,
            pivot_lifecycle,
            track_window.index[-1],
        )
        base_duration_weeks = (
            (base_end_date - left_high_date).days / 7
            if pd.notna(base_end_date) and pd.notna(left_high_date)
            else np.nan
        )
        base_move_window = track_window.loc[:base_end_date].copy()
        single_week_metrics = calculate_single_week_move_metrics(
            base_move_window,
            float(left_high - base_low),
            excluded_end_date=(
                base_end_date if base_end_reason == "BREAKOUT" else None
            ),
        )
        distance_from_pivot_pct = (latest_close - selected_pivot) / selected_pivot

        updated.update(
            {
                "latest_close": latest_close,
                "tracking_state": "ARCHIVED" if lifecycle_status == "FAILED" else "ACTIVE",
                "archive_reason": "confirmed_breakout_failed" if lifecycle_status == "FAILED" else pd.NA,
                "active_pivot_price": selected_pivot,
                "active_pivot_type": pivot_lifecycle.get("pivot_source"),
                "active_pivot_date": pivot_lifecycle.get("selected_pivot_date"),
                "active_pivot_confidence": pd.NA,
                "active_pivot_distance_pct": float(pivot_lifecycle["distance_from_pivot_pct"]),
                "active_pivot_reason": "frozen selected pivot lifecycle",
                **pivot_lifecycle,
                "latest_close": latest_close,
                "weekly_structure_close": weekly_structure_close,
                "structure_as_of_date": track_window.index[-1],
                "signal_as_of_date": daily.index[-1],
                "recovery_pct": float(recovery_pct),
                "distance_from_pivot_pct": float(distance_from_pivot_pct),
                "active_pivot_distance_pct": float(distance_from_pivot_pct),
                "journey_stage": journey_stage,
                "base_end_date": base_end_date,
                "base_end_reason": base_end_reason,
                "base_duration_weeks": float(base_duration_weeks),
                **single_week_metrics,
                "max_single_week_move_to_depth_ratio": float(
                    params.get("MAX_SINGLE_WEEK_MOVE_TO_DEPTH_RATIO", 0.50)
                ),
                "strategy_version": params.get(
                    "STRATEGY_VERSION", "base_lifecycle_v5_daily_handle"
                ),
                "base_window_weeks": int(
                    updated.get("base_window_weeks", updated.get("scan_window_weeks", 0))
                ),
            }
        )
        updated["setup_reason"] = build_setup_reason(updated)
        return updated
    except Exception as exc:
        updated["tracking_state"] = "ACTIVE"
        updated["tracking_error"] = str(exc)
        return updated


def update_tracking_store(results_df, as_of_date, data_path=DATA_PATH, tracking_dir=TRACKING_DIR, params=None):
    os.makedirs(tracking_dir, exist_ok=True)
    paths = tracking_paths(tracking_dir)
    state = load_tracking_state(tracking_dir)
    active_df = normalize_tracking_dates(state["active"])
    history_df = normalize_tracking_dates(state["history"])
    archived_df = normalize_tracking_dates(state["archived"])
    active_df = consolidate_tracking_structures(active_df, params=params)
    archived_df = consolidate_tracking_structures(archived_df, params=params)

    new_tracking_df = prepare_new_tracking_rows(results_df, as_of_date, active_df, archived_df)
    if not new_tracking_df.empty:
        active_df = pd.concat([active_df, new_tracking_df], ignore_index=True, sort=False)

    if active_df.empty:
        if len(active_df.columns) == 0:
            active_df = pd.DataFrame(columns=["base_id", "Symbol", "tracking_state"])
        active_df.to_parquet(paths["active"], index=False)
        return {
            "active_path": paths["active"],
            "history_path": paths["history"],
            "archived_path": paths["archived"],
            "active_count": 0,
            "archived_count": len(archived_df),
            "history_rows": len(history_df),
            "new_bases": len(new_tracking_df),
        }

    data_engine = DataEngine(data_path)
    tracked_rows = [
        update_tracking_row(row.to_dict(), as_of_date, data_engine, params=params)
        for _, row in active_df.iterrows()
    ]
    tracked_df = pd.DataFrame(tracked_rows)
    tracked_df["tracking_date"] = pd.to_datetime(as_of_date)

    if not history_df.empty and {"base_id", "tracking_date"}.issubset(history_df.columns):
        # Normalize both sides before key comparison.  String conversion can
        # represent the same date as either ``2026-07-22`` or
        # ``2026-07-22 00:00:00`` and previously allowed same-date duplicates.
        history_df = remove_replaced_history_rows(history_df, tracked_df)
    history_df = pd.concat([history_df, tracked_df], ignore_index=True, sort=False)

    newly_archived = tracked_df[tracked_df["tracking_state"] == "ARCHIVED"].copy()
    if not newly_archived.empty:
        newly_archived["archived_date"] = pd.to_datetime(as_of_date)
        if not archived_df.empty and "base_id" in archived_df.columns:
            archived_df = archived_df[~archived_df["base_id"].isin(set(newly_archived["base_id"]))]
        archived_df = pd.concat([archived_df, newly_archived], ignore_index=True, sort=False)

    active_next_df = tracked_df[tracked_df["tracking_state"] != "ARCHIVED"].copy()
    active_next_df.to_parquet(paths["active"], index=False)
    history_df.to_parquet(paths["history"], index=False)
    if not archived_df.empty:
        archived_df.to_parquet(paths["archived"], index=False)

    return {
        "active_path": paths["active"],
        "history_path": paths["history"],
        "archived_path": paths["archived"],
        "active_count": len(active_next_df),
        "archived_count": len(archived_df),
        "history_rows": len(history_df),
        "new_bases": len(new_tracking_df),
    }


class BaseLifecycleScanner:
    def __init__(self, params=None, data_path=DATA_PATH, debug=False):
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self.logger = get_logger(debug)
        self.stats = ScanStats()
        self.data_path = data_path
        self.data_engine = DataEngine(self.data_path)
        self.all_window_results = pd.DataFrame()
        self.stage_results = empty_stage_results()
        as_of_date = self.params.get("AS_OF_DATE")
        self.as_of_date = pd.to_datetime(as_of_date) if as_of_date else None

    def scan_symbol(self, symbol):
        data_symbol = symbol
        stock_symbol = normalize_stock_symbol(symbol)
        try:
            df_full = self.data_engine.get_symbol(data_symbol)
            df_full.index = pd.to_datetime(df_full.index)
            df_full = df_full.sort_index()
            if self.as_of_date is not None:
                df_full = df_full[df_full.index <= self.as_of_date]

            if df_full.empty:
                record_stage(
                    self.stage_results,
                    "rejected",
                    {
                        "Symbol": stock_symbol,
                        "data_symbol": data_symbol,
                        "failure_reason": "no_data_as_of_date",
                        "scan_as_of_date": self.as_of_date.date().isoformat() if self.as_of_date is not None else None,
                    },
                )
                return None

            ath_window = df_full.iloc[:-8] if len(df_full) > 8 else df_full
            ath = ath_window["High"].max()
            df = df_full.tail(1000)

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.loc[:, ~df.columns.duplicated()]

            close = df["Close"]
            ema200 = close.ewm(span=200).mean()
            ema50 = close.ewm(span=50).mean()
            if not (close.iloc[-1] > ema200.iloc[-1] and ema50.iloc[-1] > ema200.iloc[-1]):
                record_stage(
                    self.stage_results,
                    "rejected",
                    {
                        "Symbol": stock_symbol,
                        "data_symbol": data_symbol,
                        "failure_reason": "daily_trend_failed",
                        "latest_close": float(close.iloc[-1]),
                        "ema50": float(ema50.iloc[-1]),
                        "ema200": float(ema200.iloc[-1]),
                    },
                )
                return None
            self.stats.dma_filtered.append(symbol)
            record_stage(
                self.stage_results,
                "daily_trend_passed",
                {
                    "Symbol": stock_symbol,
                    "data_symbol": data_symbol,
                    "latest_close": float(close.iloc[-1]),
                    "ema50": float(ema50.iloc[-1]),
                    "ema200": float(ema200.iloc[-1]),
                },
            )

            weekly = resample_completed_weekly(
                df,
                latest_completed_week_end(
                    self.as_of_date if self.as_of_date is not None else df.index[-1]
                ),
            )
            min_weekly_bars_required = self.params.get(
                "MIN_WEEKLY_BARS_REQUIRED", self.params["MIN_WEEKS"] + 2
            )
            if len(weekly) < min_weekly_bars_required:
                self.logger.debug(f"{symbol} - Not enough weekly data: {len(weekly)} weeks")
                record_stage(
                    self.stage_results,
                    "rejected",
                    {
                        "Symbol": stock_symbol,
                        "data_symbol": data_symbol,
                        "weekly_bars": int(len(weekly)),
                        "required_weekly_bars": int(min_weekly_bars_required),
                        "failure_reason": "not_enough_weekly_data",
                    },
                )
                return None

            weekly = calculate_cup_metrics(weekly, self.params)
            window_results = []
            for scan_window_weeks in ordered_base_windows(self.params):
                if len(weekly) < scan_window_weeks:
                    record_stage(
                        self.stage_results,
                        "rejected",
                        {
                            "Symbol": stock_symbol,
                            "data_symbol": data_symbol,
                            "scan_window_weeks": int(scan_window_weeks),
                            "weekly_bars": int(len(weekly)),
                            "required_weekly_bars": int(scan_window_weeks),
                            "failure_reason": "not_enough_weekly_data",
                        },
                    )
                    continue
                record_stage(
                    self.stage_results,
                    "weekly_data_passed",
                    {
                        "Symbol": stock_symbol,
                        "data_symbol": data_symbol,
                        "scan_window_weeks": int(scan_window_weeks),
                        "weekly_bars": int(len(weekly)),
                    },
                )
                res = check_lifecycle_conditions(
                    weekly,
                    self.params,
                    stock_symbol,
                    self.stats,
                    self.logger,
                    ath,
                    scan_window_weeks,
                    stage_results=self.stage_results,
                    signal_close=float(close.iloc[-1]),
                    signal_as_of_date=df.index[-1],
                    daily_df=df,
                )
                if res:
                    window_results.append(res)

            if not window_results:
                record_stage(
                    self.stage_results,
                    "rejected",
                    {"Symbol": stock_symbol, "data_symbol": data_symbol, "failure_reason": "no_valid_window"},
                )
                return None

            # Smaller search windows are retained only when they reveal a
            # genuinely different base. Equivalent structures use the largest
            # matching search window as their canonical representation.
            window_results = consolidate_equivalent_bases(
                window_results, self.params
            )
            for result in window_results:
                if result.get("journey_stage") != "NOT_TRACKED":
                    record_stage(self.stage_results, "final_candidates", result)
            return window_results[0], window_results

        except Exception as exc:
            self.logger.debug(f"{data_symbol} failed: {exc}")
            return None

    def run_scan(self):
        self.stage_results = empty_stage_results()
        all_files = [file_name for file_name in os.listdir(self.data_path) if file_name.endswith(".parquet")]
        results = []
        all_window_results = []

        for file_name in all_files:
            symbol = file_name.replace(".parquet", "")
            res = self.scan_symbol(symbol)
            if res:
                _largest_result, window_results = res
                all_window_results.extend(window_results)
                results.extend(
                    row
                    for row in window_results
                    if row.get("journey_stage") != "NOT_TRACKED"
                )

        df = pd.DataFrame(results)
        self.all_window_results = pd.DataFrame(all_window_results)
        self.stage_results = stage_results_to_frames(self.stage_results)
        if not df.empty:
            df = df.sort_values(
                ["Symbol", "base_window_weeks"], ascending=[True, False]
            ).reset_index(drop=True)
        return df


def build_replay_dates(start_date, end_date, frequency="daily"):
    """Build business-daily or Friday replay dates without weekend duplicates."""
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    if start_ts > end_ts:
        raise ValueError("start_date must be before or equal to end_date")

    frequency_map = {"daily": "B", "weekly_friday": "W-FRI"}
    if frequency not in frequency_map:
        raise ValueError(f"Unsupported replay frequency: {frequency}")

    replay_dates = pd.date_range(
        start_ts.normalize(), end_ts.normalize(), freq=frequency_map[frequency]
    )
    if frequency == "weekly_friday" and (
        len(replay_dates) == 0 or replay_dates[-1].normalize() != end_ts.normalize()
    ):
        replay_dates = replay_dates.append(pd.DatetimeIndex([end_ts]))
    return replay_dates


def run_tracking_replay(
    params,
    start_date,
    end_date,
    frequency="weekly_friday",
    data_path=DATA_PATH,
    scan_dir=SCAN_HISTORY_DIR,
    tracking_dir=TRACKING_DIR,
    debug=False,
    update_tracking=True,
    progress_callback=None,
):
    replay_dates = build_replay_dates(start_date, end_date, frequency)

    summaries = []
    total_dates = len(replay_dates)
    for completed_dates, replay_date in enumerate(replay_dates, start=1):
        replay_params = {**params, "AS_OF_DATE": replay_date}
        scanner = BaseLifecycleScanner(replay_params, data_path=data_path, debug=debug)
        results_df = scanner.run_scan()
        save_info = save_scan_snapshot(
            results_df,
            scanner.all_window_results,
            scanner.stage_results,
            scan_dir=scan_dir,
            scan_date_label=replay_date.strftime("%Y-%m-%d"),
        )
        tracking_info = (
            update_tracking_store(
                results_df,
                replay_date,
                data_path=data_path,
                tracking_dir=tracking_dir,
                params=params,
            )
            if update_tracking
            else {}
        )
        summary = {
            "scan_as_of_date": replay_date.date().isoformat(),
            "weekly_structure_refresh": bool(replay_date.weekday() == 4),
            "candidates": len(results_df),
            "all_window_rows": len(scanner.all_window_results),
            "stage_rows": sum(len(stage_df) for stage_df in scanner.stage_results.values()),
            "tracked_active": tracking_info.get("active_count", pd.NA),
            "tracked_archived": tracking_info.get("archived_count", pd.NA),
            "new_tracked_bases": tracking_info.get("new_bases", pd.NA),
            "latest_path": save_info["latest_path"],
            "results_path": save_info["results_path"],
        }
        summaries.append(summary)
        if progress_callback is not None:
            progress_callback(completed_dates, total_dates, summary)

    return pd.DataFrame(summaries)


if __name__ == "__main__":
    scanner = BaseLifecycleScanner(debug=True)
    result_df = scanner.run_scan()
    print("Total Found:", len(result_df))
    print(result_df.head(20))
