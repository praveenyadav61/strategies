"""Pure daily pivot/handle state transitions for the base lifecycle.

This module deliberately knows nothing about parquet files, scanners, Streamlit,
or symbol discovery.  It owns the path-dependent daily state only:

    previous state + one completed daily candle -> new state + events

Historical reconstruction and future incremental processing must both use
``advance_daily_handle_state``.  Keeping one transition function prevents the
two execution modes from slowly developing different trading rules.
"""

from copy import deepcopy

import numpy as np
import pandas as pd


def _level_buffer(price, atr, price_pct, atr_multiplier):
    price_buffer = float(price) * float(price_pct)
    atr_buffer = (
        float(atr) * float(atr_multiplier)
        if pd.notna(atr)
        else 0.0
    )
    return max(price_buffer, atr_buffer)


def _crossed(previous_close, current_close, level):
    return bool(
        pd.notna(previous_close)
        and pd.notna(current_close)
        and pd.notna(level)
        and float(previous_close) <= float(level)
        and float(current_close) > float(level)
    )


def _pivot_zone(left_high, base_low, params):
    depth_price = float(left_high) - float(base_low)
    minimum_recovery = float(params.get("PIVOT_MIN_BASE_RECOVERY", 0.85))
    maximum_recovery = float(params.get("PIVOT_MAX_BASE_RECOVERY", 1.10))
    return {
        "implied_base_low": float(base_low),
        "base_depth_price": float(depth_price),
        "pivot_min_price": float(base_low + minimum_recovery * depth_price),
        "pivot_max_price": float(base_low + maximum_recovery * depth_price),
        "pivot_min_base_recovery": minimum_recovery,
        "pivot_max_base_recovery": maximum_recovery,
    }


def initialize_daily_handle_state(
    *,
    left_high,
    left_high_date,
    base_low,
    base_depth,
    resolved_base_low_date,
    left_setup_atr,
    first_candle=None,
    params=None,
):
    """Create the serializable state before processing subsequent candles."""
    params = params or {}
    left_high = float(left_high)
    base_low = float(base_low)
    maximum_pullback = float(base_depth) / 3.0
    confirmation_sessions = int(
        params.get("DAILY_HANDLE_CONFIRMATION_SESSIONS", 5)
    )
    zone = _pivot_zone(left_high, base_low, params)
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
        "setup_atr": float(left_setup_atr) if pd.notna(left_setup_atr) else np.nan,
        "handle_pivot_base_recovery": np.nan,
        **zone,
    }
    metrics = {
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
        "daily_base_low_date": pd.to_datetime(
            resolved_base_low_date, errors="coerce"
        ),
        "daily_handle_invalidated": False,
        "daily_handle_invalidation_date": pd.NaT,
    }
    first_date = (
        pd.to_datetime(first_candle.get("date"), errors="coerce")
        if first_candle is not None
        else pd.NaT
    )
    first_close = (
        float(first_candle.get("Close"))
        if first_candle is not None and pd.notna(first_candle.get("Close"))
        else np.nan
    )
    return {
        "schema_version": 1,
        "left_high": left_high,
        "base_low": base_low,
        "base_depth": float(base_depth),
        "pivot_zone": zone,
        "left_snapshot": left_snapshot,
        "active_snapshot": deepcopy(left_snapshot),
        "candidate": None,
        "handle_state": "LEFT_HIGH_ACTIVE",
        "breakout_date": pd.NaT,
        "breakout_atr": np.nan,
        "selected_at_breakout": None,
        "metrics": metrics,
        "last_close": first_close,
        "last_processed_date": first_date,
        "processed_candles": 1 if first_candle is not None else 0,
    }


def _active_is_handle(state):
    return state["active_snapshot"].get("pivot_source") == "DAILY_HANDLE"


def _resting_state(state):
    return "HANDLE_READY" if _active_is_handle(state) else "LEFT_HIGH_ACTIVE"


def _pending_state(state):
    return (
        "HANDLE_REPLACEMENT_PENDING"
        if _active_is_handle(state)
        else "HANDLE_CANDIDATE"
    )


def _pivot_trigger(snapshot, params):
    pivot = float(snapshot["selected_pivot"])
    return pivot + _level_buffer(
        pivot,
        snapshot.get("setup_atr", np.nan),
        params.get("BREAKOUT_PRICE_BUFFER_PCT", 0.005),
        params.get("BREAKOUT_ATR_BUFFER_MULTIPLIER", 0.20),
    )


def _new_candidate(state, candle):
    current_high = float(candle["High"])
    left_high = float(state["left_high"])
    base_low = float(state["base_low"])
    recovery = (
        (current_high - base_low) / (left_high - base_low)
        if left_high > base_low
        else np.nan
    )
    zone = state["pivot_zone"]
    if pd.isna(recovery) or not (
        zone["pivot_min_base_recovery"]
        <= float(recovery)
        <= zone["pivot_max_base_recovery"]
    ):
        return None
    if (
        _active_is_handle(state)
        and current_high <= float(state["active_snapshot"]["selected_pivot"])
    ):
        return None
    return {
        "price": current_high,
        "date": pd.to_datetime(candle["date"]),
        "atr": (
            float(candle.get("daily_atr_14"))
            if pd.notna(candle.get("daily_atr_14"))
            else np.nan
        ),
        "recovery": float(recovery),
        "sessions_after_pivot": 0,
        "low": np.nan,
        "low_date": pd.NaT,
    }


def _update_pending_metrics(state, candidate, handle_state, **extra):
    state["metrics"].update(
        {
            "daily_handle_state": handle_state,
            "daily_handle_candidate_pivot": float(candidate["price"]),
            "daily_handle_candidate_date": candidate["date"],
            "daily_handle_sessions_after_pivot": int(
                candidate.get("sessions_after_pivot", 0)
            ),
            "daily_handle_valid": _active_is_handle(state),
            "daily_handle_breakout_eligible": True,
            **extra,
        }
    )


def _confirm_breakout(state, candle):
    state["breakout_date"] = pd.to_datetime(candle["date"])
    state["breakout_atr"] = (
        float(candle.get("daily_atr_14"))
        if pd.notna(candle.get("daily_atr_14"))
        else np.nan
    )
    state["selected_at_breakout"] = deepcopy(state["active_snapshot"])
    state["handle_state"] = "BREAKOUT_CONFIRMED"
    state["metrics"].update(
        {
            "daily_handle_state": "BREAKOUT_CONFIRMED",
            "daily_handle_valid": _active_is_handle(state),
            "daily_handle_breakout_eligible": False,
        }
    )


def advance_daily_handle_state(previous_state, candle, params=None):
    """Advance a daily handle state using exactly one completed candle.

    The input state is not mutated.  Returned events are observational and do
    not influence the transition, which makes them safe for append-only audit
    storage later.
    """
    params = params or {}
    state = deepcopy(previous_state)
    events = []
    if pd.notna(state.get("breakout_date")):
        return state, events

    current_date = pd.to_datetime(candle["date"])
    previous_close = state.get("last_close", np.nan)
    current_close = float(candle["Close"])
    current_high = float(candle["High"])
    current_low = float(candle["Low"])
    maximum_pullback = float(state["base_depth"]) / 3.0

    # Breakout is always tested against the one confirmed active pivot first.
    if _crossed(
        previous_close,
        current_close,
        _pivot_trigger(state["active_snapshot"], params),
    ):
        _confirm_breakout(state, candle)
        events.append(
            {
                "event_type": "BREAKOUT_CONFIRMED",
                "event_date": current_date,
                "pivot_source": state["active_snapshot"]["pivot_source"],
                "pivot_price": float(state["active_snapshot"]["selected_pivot"]),
            }
        )
        state["last_close"] = current_close
        state["last_processed_date"] = current_date
        state["processed_candles"] += 1
        return state, events

    # A confirmed handle is invalidated only by the pullback after that handle.
    if _active_is_handle(state):
        active = state["active_snapshot"]
        active_date = pd.to_datetime(active["selected_pivot_date"], errors="coerce")
        if current_date > active_date:
            previous_low = active.get("handle_low", np.nan)
            if pd.isna(previous_low) or current_low < float(previous_low):
                active["handle_low"] = current_low
                active["handle_low_date"] = current_date
            active_pullback = (
                float(active["selected_pivot"]) - float(active["handle_low"])
            ) / float(active["selected_pivot"])
            active["handle_pullback_pct"] = float(active_pullback)
            if active_pullback > maximum_pullback:
                invalidated_pivot = float(active["selected_pivot"])
                state["metrics"].update(
                    {
                        "daily_handle_invalidated": True,
                        "daily_handle_invalidation_date": current_date,
                        "daily_handle_valid": False,
                    }
                )
                state["active_snapshot"] = deepcopy(state["left_snapshot"])
                state["candidate"] = None
                state["handle_state"] = "LEFT_HIGH_ACTIVE"
                events.append(
                    {
                        "event_type": "HANDLE_INVALIDATED",
                        "event_date": current_date,
                        "pivot_price": invalidated_pivot,
                    }
                )

                # The left-high fallback is effective on this same candle.
                if _crossed(
                    previous_close,
                    current_close,
                    _pivot_trigger(state["active_snapshot"], params),
                ):
                    _confirm_breakout(state, candle)
                    events.append(
                        {
                            "event_type": "BREAKOUT_CONFIRMED",
                            "event_date": current_date,
                            "pivot_source": "LEFT_HIGH",
                            "pivot_price": float(
                                state["active_snapshot"]["selected_pivot"]
                            ),
                        }
                    )
                    state["last_close"] = current_close
                    state["last_processed_date"] = current_date
                    state["processed_candles"] += 1
                    return state, events

    candidate = state.get("candidate")
    if candidate is None:
        candidate = _new_candidate(state, candle)
        state["candidate"] = candidate
        if candidate is not None:
            state["handle_state"] = _pending_state(state)
            _update_pending_metrics(
                state,
                candidate,
                state["handle_state"],
                daily_handle_low=np.nan,
                daily_handle_low_date=pd.NaT,
                daily_handle_pullback_pct=np.nan,
            )
            events.append(
                {
                    "event_type": "HANDLE_CANDIDATE_STARTED",
                    "event_date": current_date,
                    "pivot_price": float(candidate["price"]),
                }
            )
        else:
            state["handle_state"] = _resting_state(state)
            state["metrics"].update(
                {
                    "daily_handle_state": state["handle_state"],
                    "daily_handle_valid": _active_is_handle(state),
                    "daily_handle_breakout_eligible": True,
                }
            )
    elif current_high > float(candidate["price"]):
        replacement = _new_candidate(state, candle)
        if replacement is None:
            state["candidate"] = None
            state["handle_state"] = _resting_state(state)
            state["metrics"].update(
                {
                    "daily_handle_state": state["handle_state"],
                    "daily_handle_valid": _active_is_handle(state),
                    "daily_handle_breakout_eligible": True,
                }
            )
            events.append(
                {
                    "event_type": "HANDLE_CANDIDATE_REJECTED",
                    "event_date": current_date,
                }
            )
        else:
            state["candidate"] = replacement
            state["handle_state"] = _pending_state(state)
            _update_pending_metrics(
                state,
                replacement,
                state["handle_state"],
                daily_handle_low=np.nan,
                daily_handle_low_date=pd.NaT,
                daily_handle_pullback_pct=np.nan,
            )
            events.append(
                {
                    "event_type": "HANDLE_CANDIDATE_REPLACED",
                    "event_date": current_date,
                    "pivot_price": float(replacement["price"]),
                }
            )
    else:
        candidate["sessions_after_pivot"] += 1
        if pd.isna(candidate.get("low")) or current_low < float(candidate["low"]):
            candidate["low"] = current_low
            candidate["low_date"] = current_date
        pullback_pct = (
            float(candidate["price"]) - float(candidate["low"])
        ) / float(candidate["price"])
        state["handle_state"] = _pending_state(state)
        _update_pending_metrics(
            state,
            candidate,
            state["handle_state"],
            daily_handle_low=float(candidate["low"]),
            daily_handle_low_date=candidate["low_date"],
            daily_handle_pullback_pct=float(pullback_pct),
        )

        if pullback_pct > maximum_pullback:
            state["candidate"] = None
            state["handle_state"] = _resting_state(state)
            state["metrics"].update(
                {
                    "daily_handle_state": state["handle_state"],
                    "daily_handle_valid": _active_is_handle(state),
                    "daily_handle_breakout_eligible": True,
                }
            )
            events.append(
                {
                    "event_type": "HANDLE_CANDIDATE_REJECTED",
                    "event_date": current_date,
                }
            )
        elif candidate["sessions_after_pivot"] >= int(
            state["metrics"]["daily_handle_confirmation_sessions"]
        ):
            state["active_snapshot"] = {
                **deepcopy(state["left_snapshot"]),
                "handle_high_pivot": float(candidate["price"]),
                "handle_high_date": candidate["date"],
                "handle_low": float(candidate["low"]),
                "handle_low_date": candidate["low_date"],
                "handle_pullback_pct": float(pullback_pct),
                "handle_duration_weeks": round(
                    candidate["sessions_after_pivot"] / 5.0, 1
                ),
                "selected_pivot": float(candidate["price"]),
                "selected_pivot_date": candidate["date"],
                "pivot_source": "DAILY_HANDLE",
                "major_pivot": float(candidate["price"]),
                "major_pivot_date": candidate["date"],
                "setup_atr": float(candidate["atr"]),
                "handle_pivot_base_recovery": float(candidate["recovery"]),
            }
            confirmed_pivot = float(candidate["price"])
            state["candidate"] = None
            state["handle_state"] = "HANDLE_READY"
            state["metrics"].update(
                {
                    "daily_handle_state": "HANDLE_READY",
                    "daily_handle_confirmation_date": current_date,
                    "daily_handle_valid": True,
                    "daily_handle_breakout_eligible": True,
                    "daily_handle_invalidated": False,
                }
            )
            events.append(
                {
                    "event_type": "HANDLE_CONFIRMED",
                    "event_date": current_date,
                    "pivot_price": confirmed_pivot,
                }
            )

    state["last_close"] = current_close
    state["last_processed_date"] = current_date
    state["processed_candles"] += 1
    return state, events


def daily_handle_result(state, daily_event_window=None):
    """Return the compatibility result consumed by the existing lifecycle."""
    selected = state.get("selected_at_breakout") or state["active_snapshot"]
    metrics = deepcopy(state["metrics"])
    metrics["daily_handle_state"] = state["handle_state"]
    if state.get("selected_at_breakout") is None:
        metrics["daily_handle_valid"] = _active_is_handle(state)
        metrics["daily_handle_breakout_eligible"] = True
    return {
        **deepcopy(selected),
        **metrics,
        "daily_breakout_date": state.get("breakout_date", pd.NaT),
        "daily_breakout_atr": state.get("breakout_atr", np.nan),
        "daily_event_window": (
            daily_event_window
            if daily_event_window is not None
            else pd.DataFrame()
        ),
    }

