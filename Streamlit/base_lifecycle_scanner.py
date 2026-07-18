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

DEFAULT_PARAMS = {
    "MIN_WEEKS": 8,
    "MAX_WEEKS": 52,
    "BASE_WINDOWS": [26, 52, 104],
    "MIN_WEEKLY_BARS_REQUIRED": 10,
    "MIN_DEPTH": 0.15,
    "MAX_DEPTH": 0.60,
    "RECOVERY_MIN": 0.60,
    "TRACKING_ELIGIBLE_RECOVERY_MIN": 0.85,
    "MIN_PRIOR_UPTREND_PCT": 0.20,
    "PRIOR_UPTREND_DEPTH_MULTIPLIER": 1.0,
    "PRIOR_UPTREND_LOOKBACK_RATIO": 0.50,
    "PRIOR_UPTREND_MIN_LOOKBACK_WEEKS": 12,
    "PRIOR_UPTREND_MAX_LOOKBACK_WEEKS": 52,
    "PRIOR_UPTREND_MIN_ADVANCE_WEEKS": 4,
    "MIN_PEAK_TO_LOW_WEEKS": 1,
    "ATR_WINDOW": 14,
    "COMPRESSION_LOOKBACK": 10,
    "TRACKING_HANDLE_LOOKBACK_WEEKS": 10,
    "TRACKING_HANDLE_MIN_PULLBACK_PCT": 0.03,
    "HANDLE_MIN_DURATION_WEEKS": 2,
    "PIVOT_MIN_LEFT_HIGH_RATIO": 0.85,
    "PIVOT_MAX_LEFT_HIGH_RATIO": 1.05,
    "HANDLE_MAJOR_MERGE_TOLERANCE_PCT": 0.02,
    "BREAKOUT_PRICE_BUFFER_PCT": 0.005,
    "BREAKOUT_ATR_BUFFER_MULTIPLIER": 0.20,
    "FAILURE_PRICE_BUFFER_PCT": 0.01,
    "FAILURE_ATR_BUFFER_MULTIPLIER": 0.25,
    "BREAKOUT_RANGE_PCT": 0.10,
    "BREAKOUT_STALL_WEEKS": 10,
}


def get_logger(debug=False):
    level = logging.DEBUG if debug else logging.ERROR
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")
    return logging.getLogger("base_lifecycle_scanner")


def normalize_stock_symbol(symbol):
    return str(symbol).strip().removesuffix(".NS")


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


def calculate_base_score(
    depth,
    recovery_pct,
    distance_from_pivot_pct,
    prior_uptrend,
    compression,
    tight_groups,
    pivot_detected,
):
    score = 0.0
    score += min(max(recovery_pct, 0.0), 1.5) / 1.5 * 25.0

    depth_quality = max(0.0, 1.0 - abs(depth - 0.30) / 0.30)
    score += depth_quality * 20.0

    if distance_from_pivot_pct <= 0:
        score += max(0.0, 1.0 - abs(distance_from_pivot_pct) / 0.15) * 20.0
    else:
        score += max(0.0, 1.0 - distance_from_pivot_pct / 0.25) * 15.0

    if prior_uptrend:
        score += 10.0
    if compression:
        score += 10.0
    if tight_groups:
        score += 5.0
    if pivot_detected:
        score += 10.0

    return round(min(score, 100.0), 2)


def check_lifecycle_conditions(df, params, symbol, stats, logger, ath, scan_window_weeks, stage_results=None):
    try:
        stock_symbol = normalize_stock_symbol(symbol)
        window = df.tail(scan_window_weeks).copy()
        latest_close = float(window["Close"].iloc[-1])
        base_stage_row = {
            "Symbol": stock_symbol,
            "scan_window_weeks": int(scan_window_weeks),
            "latest_close": latest_close,
        }
        peak_search_window = window.iloc[:-params["MIN_WEEKS"]]
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
        base_duration_weeks = (window.index[-1] - peak_idx).days / 7
        peak_to_low_weeks = (bottom_idx - peak_idx).days / 7
        evaluated_row = {
            **base_stage_row,
            "left_high": float(peak_price),
            "left_high_index": peak_idx,
            "base_low": float(bottom_price),
            "base_low_index": bottom_idx,
            "base_duration_weeks": round(float(base_duration_weeks), 1),
            "peak_to_low_weeks": round(float(peak_to_low_weeks), 1),
            "ATH": float(ath),
        }

        stats.ath_filtered.append(symbol)

        if peak_to_low_weeks < params.get("MIN_PEAK_TO_LOW_WEEKS", 1):
            record_stage(
                stage_results,
                "rejected",
                {
                    **evaluated_row,
                    "failure_reason": "base_low_too_close_to_left_high",
                    "min_peak_to_low_weeks": float(params.get("MIN_PEAK_TO_LOW_WEEKS", 1)),
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

        recovery_pct = (window["Close"].iloc[-1] - bottom_price) / (peak_price - bottom_price)
        if recovery_pct < params["RECOVERY_MIN"]:
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
            return None
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

        tracking_eligible = bool(recovery_pct >= params.get("TRACKING_ELIGIBLE_RECOVERY_MIN", 0.85))
        pivot_lifecycle = calculate_pivot_lifecycle(
            window,
            float(peak_price),
            peak_idx,
            bottom_idx_i,
            depth,
            params,
            tracking_eligible=tracking_eligible,
        )
        pivot = float(pivot_lifecycle["selected_pivot"])
        pivot_date = pd.to_datetime(pivot_lifecycle.get("selected_pivot_date"), errors="coerce")
        pivot_idx_i = (
            int(window.index.get_indexer([pivot_date], method="nearest")[0])
            if pd.notna(pivot_date)
            else peak_idx_i
        )
        pivot_detected = bool(pivot_lifecycle.get("pivot_source") != "LEFT_HIGH")
        distance_from_left_high_pct = (latest_close - peak_price) / peak_price
        distance_from_pivot_pct = float(pivot_lifecycle["distance_from_pivot_pct"])
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

        score = calculate_base_score(
            depth,
            recovery_pct,
            distance_from_pivot_pct,
            prior_uptrend,
            compression,
            tight_groups,
            pivot_detected,
        )

        result = {
            "Symbol": stock_symbol,
            "scan_window_weeks": int(scan_window_weeks),
            "base_duration_weeks": round(float(base_duration_weeks), 1),
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
            "score": float(score),
            "tracking_eligible_recovery_min": float(params.get("TRACKING_ELIGIBLE_RECOVERY_MIN", 0.85)),
            "tracking_eligible": tracking_eligible,
            "ATH": float(ath),
            **pivot_lifecycle,
        }
        result["setup_reason"] = build_setup_reason(result)
        record_stage(stage_results, "final_candidates", result)
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
    current["score_delta"] = pd.NA

    if previous_df.empty or "Symbol" not in previous_df.columns:
        return current, pd.DataFrame()

    if "Symbol" not in current.columns:
        dropped = previous_df.copy()
        dropped["weekly_change"] = "Dropped"
        return current, dropped

    previous = previous_df.drop_duplicates("Symbol").set_index("Symbol")
    for idx, row in current.iterrows():
        symbol = row["Symbol"]
        if symbol not in previous.index:
            continue

        prev_row = previous.loc[symbol]
        current_score = row.get("score", pd.NA)
        previous_score = prev_row.get("score", pd.NA)
        score_delta = (
            current_score - previous_score
            if pd.notna(current_score) and pd.notna(previous_score)
            else pd.NA
        )
        current.at[idx, "score_delta"] = score_delta

        previous_status = prev_row.get("lifecycle_status")
        current_status = row.get("lifecycle_status")
        if previous_status != current_status:
            current.at[idx, "weekly_change"] = f"{previous_status} -> {current_status}"
        elif pd.notna(score_delta) and score_delta >= 5:
            current.at[idx, "weekly_change"] = "Improved"
        elif pd.notna(score_delta) and score_delta <= -5:
            current.at[idx, "weekly_change"] = "Weakened"
        else:
            current.at[idx, "weekly_change"] = "Continued"

    dropped = previous_df[~previous_df["Symbol"].isin(set(current["Symbol"]))].copy()
    if not dropped.empty:
        dropped["weekly_change"] = "Dropped"

    return current, dropped


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
    return "|".join([normalize_stock_symbol(row.get("Symbol")), *date_parts])


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
        "breakout_success_date",
    ]
    normalized = df.copy()
    for column in date_columns:
        if column in normalized.columns:
            normalized[column] = pd.to_datetime(normalized[column], errors="coerce")
    return normalized


def prepare_new_tracking_rows(results_df, as_of_date, active_df, archived_df):
    if results_df is None or results_df.empty or "Symbol" not in results_df.columns:
        return pd.DataFrame()

    existing_ids = set()
    for existing_df in [active_df, archived_df]:
        if existing_df is not None and not existing_df.empty and "base_id" in existing_df.columns:
            existing_ids.update(existing_df["base_id"].dropna().astype(str))
        if existing_df is not None and not existing_df.empty:
            for _, existing_row in existing_df.iterrows():
                existing_ids.add(build_base_id(existing_row.to_dict()))

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

    return pd.DataFrame(new_rows)


def load_weekly_for_tracking(symbol, as_of_date, data_engine):
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
    return df_full.resample("W").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna()


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


def calculate_pivot_candidate_snapshot(source, left_high, left_high_date, base_depth, params):
    """Select one actionable pivot: a valid handle, otherwise the left high."""
    pivot_min = float(left_high) * float(params.get("PIVOT_MIN_LEFT_HIGH_RATIO", 0.85))
    pivot_max = float(left_high) * float(params.get("PIVOT_MAX_LEFT_HIGH_RATIO", 1.05))
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
        candidates.update(handle)
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


def calculate_pivot_lifecycle(
    window,
    left_high,
    left_high_date,
    bottom_idx_i,
    base_depth,
    params,
    tracking_eligible=False,
):
    """Run the single-pivot lifecycle using a valid handle or the left high."""
    latest_close = float(window["Close"].iloc[-1])
    empty_source = window.iloc[0:0]
    pre_current_snapshot = calculate_pivot_candidate_snapshot(
        empty_source, left_high, left_high_date, base_depth, params
    )
    frozen_snapshot = None
    breakout_date = pd.NaT
    breakout_atr = np.nan

    start_pos = max(int(bottom_idx_i) + 2, 1)
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

    handle_invalidated = bool(
        pd.isna(breakout_date)
        and selected.get("pivot_source") == "HANDLE"
        and pd.notna(selected.get("handle_low"))
        and latest_close < float(selected["handle_low"])
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
        window, selected_pivot, breakout_date
    )
    post_breakout = (
        window.loc[breakout_date:].copy()
        if pd.notna(breakout_date)
        else window.iloc[0:0].copy()
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
        elif selected.get("pivot_source") == "HANDLE":
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
        weekly = load_weekly_for_tracking(updated["Symbol"], scan_date, data_engine)
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

        latest_close = float(track_window["Close"].iloc[-1])
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
        base_depth = float(updated.get("Depth", updated.get("depth")))
        pivot_lifecycle = calculate_pivot_lifecycle(
            track_window,
            left_high,
            left_high_date,
            bottom_idx_i,
            base_depth,
            params,
            tracking_eligible=True,
        )
        lifecycle_status = pivot_lifecycle["lifecycle_status"]
        selected_pivot = float(pivot_lifecycle["selected_pivot"])

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
        current_keys = set(zip(tracked_df["base_id"].astype(str), tracked_df["tracking_date"].astype(str)))
        history_df = history_df[
            ~history_df.apply(
                lambda row: (str(row.get("base_id")), str(row.get("tracking_date"))) in current_keys,
                axis=1,
            )
        ]
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

            weekly = df.resample("W").agg(
                {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
            ).dropna()
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
            for scan_window_weeks in self.params.get("BASE_WINDOWS", []):
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

            window_results = sorted(
                window_results,
                key=lambda row: (
                    row.get("score", 0),
                    row.get("pivot_detected", False),
                    row.get("scan_window_weeks", 0),
                ),
                reverse=True,
            )
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
                best_result, window_results = res
                results.append(best_result)
                all_window_results.extend(window_results)

        df = pd.DataFrame(results)
        self.all_window_results = pd.DataFrame(all_window_results)
        self.stage_results = stage_results_to_frames(self.stage_results)
        if not df.empty:
            df = df.sort_values("score", ascending=False).reset_index(drop=True)
            df["rank"] = range(1, len(df) + 1)
        return df


def run_tracking_replay(
    params,
    start_date,
    end_date,
    frequency="weekly_friday",
    data_path=DATA_PATH,
    debug=False,
    update_tracking=True,
):
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    if start_ts > end_ts:
        raise ValueError("start_date must be before or equal to end_date")

    frequency_map = {
        "daily": "D",
        "weekly_friday": "W-FRI",
    }
    if frequency not in frequency_map:
        raise ValueError(f"Unsupported replay frequency: {frequency}")

    replay_dates = pd.date_range(start_ts, end_ts, freq=frequency_map[frequency])
    if frequency == "daily" and (len(replay_dates) == 0 or replay_dates[0].normalize() != start_ts.normalize()):
        replay_dates = pd.DatetimeIndex([start_ts]).append(replay_dates)
    if len(replay_dates) == 0 or replay_dates[-1].normalize() != end_ts.normalize():
        replay_dates = replay_dates.append(pd.DatetimeIndex([end_ts]))

    summaries = []
    for replay_date in replay_dates:
        replay_params = {**params, "AS_OF_DATE": replay_date}
        scanner = BaseLifecycleScanner(replay_params, data_path=data_path, debug=debug)
        results_df = scanner.run_scan()
        save_info = save_scan_snapshot(
            results_df,
            scanner.all_window_results,
            scanner.stage_results,
            scan_date_label=replay_date.strftime("%Y-%m-%d"),
        )
        tracking_info = (
            update_tracking_store(
                results_df,
                replay_date,
                data_path=data_path,
                params=params,
            )
            if update_tracking
            else {}
        )
        summaries.append(
            {
                "scan_as_of_date": replay_date.date().isoformat(),
                "candidates": len(results_df),
                "all_window_rows": len(scanner.all_window_results),
                "stage_rows": sum(len(stage_df) for stage_df in scanner.stage_results.values()),
                "tracked_active": tracking_info.get("active_count", pd.NA),
                "tracked_archived": tracking_info.get("archived_count", pd.NA),
                "new_tracked_bases": tracking_info.get("new_bases", pd.NA),
                "latest_path": save_info["latest_path"],
                "results_path": save_info["results_path"],
            }
        )

    return pd.DataFrame(summaries)


if __name__ == "__main__":
    scanner = BaseLifecycleScanner(debug=True)
    result_df = scanner.run_scan()
    print("Total Found:", len(result_df))
    print(result_df.head(20))
