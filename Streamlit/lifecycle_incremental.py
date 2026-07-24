"""Incremental full lifecycle state built on the shared daily handle machine."""

from copy import deepcopy

import numpy as np
import pandas as pd

from lifecycle_state_machine import (
    advance_daily_handle_state,
    daily_handle_result,
    initialize_daily_handle_state,
)


CHECKPOINT_SCHEMA_VERSION = 1
LIFECYCLE_LOGIC_VERSION = "base_lifecycle_v5_incremental_shadow"


def _buffer(price, atr, price_pct, atr_multiplier):
    price_part = float(price) * float(price_pct)
    atr_part = float(atr) * float(atr_multiplier) if pd.notna(atr) else 0.0
    return max(price_part, atr_part)


def initialize_lifecycle_state(structure, first_candle, params):
    handle_state = initialize_daily_handle_state(
        left_high=float(structure["left_high"]),
        left_high_date=structure["left_high_index"],
        base_low=float(structure["base_low"]),
        base_depth=float(structure["Depth"]),
        resolved_base_low_date=structure["resolved_base_low_date"],
        left_setup_atr=first_candle.get("daily_atr_14", np.nan),
        first_candle=first_candle,
        params=params,
    )
    return {
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "logic_version": LIFECYCLE_LOGIC_VERSION,
        "base_id": str(structure["base_id"]),
        "Symbol": str(structure["Symbol"]),
        "left_high": float(structure["left_high"]),
        "left_high_index": pd.to_datetime(structure["left_high_index"]),
        "base_low": float(structure["base_low"]),
        "base_low_index": pd.to_datetime(structure["base_low_index"]),
        "base_depth": float(structure["Depth"]),
        "handle": handle_state,
        "post_breakout": None,
        "last_processed_date": pd.to_datetime(first_candle["date"]),
        "latest_close": float(first_candle["Close"]),
    }


def _initialize_post_breakout(state, candle, params):
    handle = state["handle"]
    selected = deepcopy(
        handle.get("selected_at_breakout") or handle["active_snapshot"]
    )
    pivot = float(selected["selected_pivot"])
    setup_atr = selected.get("setup_atr", np.nan)
    breakout_atr = handle.get("breakout_atr", np.nan)
    left_high = float(state["left_high"])
    breakout_range_pct = float(params.get("BREAKOUT_RANGE_PCT", 0.10))
    breakout_buffer = _buffer(
        pivot,
        setup_atr,
        params.get("BREAKOUT_PRICE_BUFFER_PCT", 0.005),
        params.get("BREAKOUT_ATR_BUFFER_MULTIPLIER", 0.20),
    )
    left_buffer = _buffer(
        left_high,
        setup_atr,
        params.get("BREAKOUT_PRICE_BUFFER_PCT", 0.005),
        params.get("BREAKOUT_ATR_BUFFER_MULTIPLIER", 0.20),
    )
    range_low = pivot * (1.0 - breakout_range_pct)
    range_high = pivot * (1.0 + breakout_range_pct)
    failure_atr = breakout_atr if pd.notna(breakout_atr) else setup_atr
    failure_buffer = _buffer(
        pivot,
        failure_atr,
        params.get("FAILURE_PRICE_BUFFER_PCT", 0.01),
        params.get("FAILURE_ATR_BUFFER_MULTIPLIER", 0.25),
    )
    close = float(candle["Close"])
    high = float(candle["High"])
    low = float(candle["Low"])
    breakout_date = pd.to_datetime(handle["breakout_date"])
    post = {
        "selected": selected,
        "breakout_date": breakout_date,
        "breakout_atr": breakout_atr,
        "breakout_close": close,
        "breakout_volume_ratio": np.nan,
        "breakout_buffer": float(breakout_buffer),
        "confirmation_level": pivot + float(breakout_buffer),
        "left_high_confirmation_level": left_high + float(left_buffer),
        "breakout_range_pct": breakout_range_pct,
        "breakout_range_low": float(range_low),
        "breakout_range_high": float(range_high),
        "success_level": float(max(range_high, left_high + float(left_buffer))),
        "failure_buffer": float(failure_buffer),
        "hard_failure_level": float(range_low - failure_buffer),
        "success_date": pd.NaT,
        "success_close": np.nan,
        "hard_failure": False,
        "persistent_failure": False,
        "previous_below_range": False,
        "highest_high": high,
        "lowest_low": low,
    }
    state["post_breakout"] = post
    return _advance_post_breakout(state, candle, include_extremes=False)


def _advance_post_breakout(state, candle, include_extremes=True):
    post = state["post_breakout"]
    close = float(candle["Close"])
    if include_extremes:
        post["highest_high"] = max(float(post["highest_high"]), float(candle["High"]))
        post["lowest_low"] = min(float(post["lowest_low"]), float(candle["Low"]))
    events = []
    candle_date = pd.to_datetime(candle["date"])
    if pd.isna(post["success_date"]) and close > float(post["success_level"]):
        post["success_date"] = candle_date
        post["success_close"] = close
        events.append(
            {
                "event_type": "BREAKOUT_SUCCESS",
                "event_date": candle_date,
                "price": close,
            }
        )
    if close < float(post["hard_failure_level"]) and not post["hard_failure"]:
        post["hard_failure"] = True
        events.append(
            {
                "event_type": "HARD_FAILURE",
                "event_date": candle_date,
                "price": close,
            }
        )
    below_range = close < float(post["breakout_range_low"])
    if (
        below_range
        and post["previous_below_range"]
        and not post["persistent_failure"]
    ):
        post["persistent_failure"] = True
        events.append(
            {
                "event_type": "PERSISTENT_FAILURE",
                "event_date": candle_date,
                "price": close,
            }
        )
    post["previous_below_range"] = bool(below_range)
    return events


def advance_lifecycle_state(previous_state, candle, params):
    """Advance the complete checkpoint by one completed daily candle."""
    state = deepcopy(previous_state)
    events = []
    if state["post_breakout"] is None:
        state["handle"], handle_events = advance_daily_handle_state(
            state["handle"], candle, params
        )
        events.extend(handle_events)
        if pd.notna(state["handle"].get("breakout_date")):
            events.extend(_initialize_post_breakout(state, candle, params))
    else:
        events.extend(_advance_post_breakout(state, candle))
        # The handle machine freezes at breakout by design. Keep checkpoint
        # timing at the full-lifecycle level for later incremental resumption.
        state["handle"]["last_processed_date"] = pd.to_datetime(candle["date"])
        state["handle"]["last_close"] = float(candle["Close"])
    state["last_processed_date"] = pd.to_datetime(candle["date"])
    state["latest_close"] = float(candle["Close"])
    for event in events:
        event["base_id"] = state["base_id"]
        event["Symbol"] = state["Symbol"]
    return state, events


def lifecycle_snapshot(state, params, tracking_eligible=True):
    """Project a checkpoint into the existing lifecycle compatibility fields."""
    handle_result = daily_handle_result(state["handle"])
    selected = {
        key: value
        for key, value in handle_result.items()
        if not key.startswith("daily_")
    }
    daily_fields = {
        key: value
        for key, value in handle_result.items()
        if key.startswith("daily_") and key != "daily_event_window"
    }
    latest_close = float(state["latest_close"])
    pivot = float(selected["selected_pivot"])
    setup_atr = selected.get("setup_atr", np.nan)
    breakout_buffer = _buffer(
        pivot,
        setup_atr,
        params.get("BREAKOUT_PRICE_BUFFER_PCT", 0.005),
        params.get("BREAKOUT_ATR_BUFFER_MULTIPLIER", 0.20),
    )
    left_confirmation = float(state["left_high"]) + _buffer(
        state["left_high"],
        setup_atr,
        params.get("BREAKOUT_PRICE_BUFFER_PCT", 0.005),
        params.get("BREAKOUT_ATR_BUFFER_MULTIPLIER", 0.20),
    )
    post = state["post_breakout"]
    if post is None:
        breakout_date = pd.NaT
        range_pct = float(params.get("BREAKOUT_RANGE_PCT", 0.10))
        range_low = pivot * (1.0 - range_pct)
        range_high = pivot * (1.0 + range_pct)
        success_level = max(range_high, left_confirmation)
        failure_buffer = _buffer(
            pivot,
            setup_atr,
            params.get("FAILURE_PRICE_BUFFER_PCT", 0.01),
            params.get("FAILURE_ATR_BUFFER_MULTIPLIER", 0.25),
        )
        hard_failure_level = range_low - failure_buffer
        success_date = pd.NaT
        success_close = np.nan
        hard_failure = persistent_failure = breakout_success = False
        current_zone = "PRE_BREAKOUT"
        lifecycle_phase = "FORMING"
        days_since = weeks_since = np.nan
        breakout_close = highest_high = lowest_low = np.nan
    else:
        selected = deepcopy(post["selected"])
        pivot = float(selected["selected_pivot"])
        breakout_date = pd.to_datetime(post["breakout_date"])
        range_pct = float(post["breakout_range_pct"])
        range_low = float(post["breakout_range_low"])
        range_high = float(post["breakout_range_high"])
        success_level = float(post["success_level"])
        failure_buffer = float(post["failure_buffer"])
        hard_failure_level = float(post["hard_failure_level"])
        breakout_buffer = float(post["breakout_buffer"])
        left_confirmation = float(post["left_high_confirmation_level"])
        success_date = pd.to_datetime(post["success_date"], errors="coerce")
        success_close = post["success_close"]
        hard_failure = bool(post["hard_failure"])
        persistent_failure = bool(post["persistent_failure"])
        breakout_success = bool(pd.notna(success_date))
        failed = hard_failure or persistent_failure
        if latest_close < range_low:
            current_zone = "BELOW_RANGE"
        elif latest_close < pivot:
            current_zone = "RETEST_RANGE"
        elif latest_close <= range_high:
            current_zone = "BUY_RANGE"
        else:
            current_zone = "ABOVE_BUY_RANGE"
        lifecycle_phase = (
            "FAILED"
            if failed
            else "BREAKOUT_SUCCESS"
            if breakout_success
            else "BREAKOUT_CONFIRMED"
        )
        days_since = int(
            (pd.to_datetime(state["last_processed_date"]) - breakout_date).days
        )
        weeks_since = round(days_since / 7, 1)
        breakout_close = float(post["breakout_close"])
        highest_high = float(post["highest_high"])
        lowest_low = float(post["lowest_low"])

    failed = bool(hard_failure or persistent_failure)
    range_breach = bool(
        pd.notna(breakout_date) and latest_close < range_low and not failed
    )
    breakout_stalled = bool(
        lifecycle_phase == "BREAKOUT_CONFIRMED"
        and pd.notna(weeks_since)
        and float(weeks_since) >= float(params.get("BREAKOUT_STALL_WEEKS", 10))
    )
    post_success_reentry = bool(
        breakout_success
        and not failed
        and current_zone in {"RETEST_RANGE", "BUY_RANGE"}
    )
    distance = (latest_close - pivot) / pivot
    handle_invalidated = bool(daily_fields.get("daily_handle_invalidated", False))
    if failed:
        lifecycle_status = "FAILED"
    elif breakout_stalled:
        lifecycle_status = "BREAKOUT_STALLED"
    elif post_success_reentry:
        lifecycle_status = "POST_SUCCESS_REENTRY_RANGE"
    elif lifecycle_phase == "BREAKOUT_SUCCESS":
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
        elif -0.05 <= distance <= 0:
            lifecycle_status = "NEAR_PIVOT"
        elif tracking_eligible:
            lifecycle_status = "RESETTING" if distance < -0.15 else "TRACKING"
        else:
            lifecycle_status = "BASE_FORMING"
    else:
        lifecycle_status = "BREAKOUT_CONFIRMED"

    recovery = (
        (latest_close - state["base_low"]) / (state["left_high"] - state["base_low"])
        if state["left_high"] > state["base_low"]
        else np.nan
    )
    if failed:
        journey_stage = "FAILED"
    elif breakout_success:
        journey_stage = "SUCCESSFUL_BREAKOUT"
    elif pd.notna(breakout_date) or recovery >= float(
        params.get("BREAKOUT_CONSIDERATION_RECOVERY_MIN", 0.85)
    ):
        journey_stage = "BREAKOUT_CONSIDERATION"
    elif recovery >= float(params.get("RECOVERY_MIN", 0.40)):
        journey_stage = "RECOVERY_BUILDING"
    else:
        journey_stage = "NOT_TRACKED"

    metrics = {
        "breakout_date": breakout_date,
        "days_since_breakout": days_since,
        "weeks_since_breakout": weeks_since,
        "breakout_close": breakout_close,
        "breakout_volume_ratio": np.nan,
        "gain_since_breakout_pct": (
            (latest_close - breakout_close) / breakout_close
            if pd.notna(breakout_close)
            else np.nan
        ),
        "max_gain_after_breakout_pct": (
            (highest_high - breakout_close) / breakout_close
            if pd.notna(highest_high)
            else np.nan
        ),
        "max_drawdown_after_breakout_pct": (
            (lowest_low - breakout_close) / breakout_close
            if pd.notna(lowest_low)
            else np.nan
        ),
        "pullback_from_post_breakout_high_pct": (
            (latest_close - highest_high) / highest_high
            if pd.notna(highest_high)
            else np.nan
        ),
        "holding_pivot": bool(latest_close >= pivot),
    }
    return {
        **selected,
        **daily_fields,
        "pivot_price": pivot,
        "pivot_index": selected.get("selected_pivot_date"),
        "distance_from_pivot_pct": float(distance),
        "breakout_buffer": float(breakout_buffer),
        "confirmation_level": pivot + float(breakout_buffer),
        "left_high_confirmation_level": float(left_confirmation),
        "breakout_range_pct": float(range_pct),
        "breakout_range_low": float(range_low),
        "breakout_range_high": float(range_high),
        "success_level": float(success_level),
        "failure_buffer": float(failure_buffer),
        "hard_failure_level": float(hard_failure_level),
        "lifecycle_phase": lifecycle_phase,
        "historical_phase": lifecycle_phase,
        "current_zone": current_zone,
        "breakout_success": breakout_success,
        "breakout_success_date": success_date,
        "breakout_success_close": success_close,
        "post_success_reentry": post_success_reentry,
        "breakout_stalled": breakout_stalled,
        "range_breach": range_breach,
        "handle_invalidated": handle_invalidated,
        "left_high_cleared": bool(latest_close > left_confirmation),
        "hard_failure": hard_failure,
        "persistent_failure": persistent_failure,
        "lifecycle_status": lifecycle_status,
        "major_breakout_buffer": float(breakout_buffer),
        "major_confirmation_level": pivot + float(breakout_buffer),
        "major_failure_buffer": float(failure_buffer),
        "major_failure_level": float(hard_failure_level),
        **metrics,
        "latest_close": latest_close,
        "recovery_pct": float(recovery),
        "journey_stage": journey_stage,
        "tracking_state": "ARCHIVED" if failed else "ACTIVE",
        "archive_reason": "confirmed_breakout_failed" if failed else pd.NA,
    }

