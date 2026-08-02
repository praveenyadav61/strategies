"""Date-oriented production orchestrator for the layered lifecycle pipeline."""

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from base_lifecycle_scanner import (
    BaseLifecycleScanner,
    latest_completed_week_end,
    load_daily_for_tracking,
    prepare_daily_handle_window,
)
from data_layer.data_engine import DataEngine
from lifecycle_checkpoints import (
    LifecycleCheckpointRepository,
    config_hash,
)
from lifecycle_incremental import (
    advance_lifecycle_state,
    initialize_lifecycle_state,
    lifecycle_snapshot,
    resolve_left_setup_atr,
)
from lifecycle_structure_registry import (
    StructureRegistryRepository,
    structures_from_tracking_history,
    upsert_discovered_structures,
)


PRODUCTION_SCHEMA_VERSION = 1
REFERENCE_SYMBOLS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS"]


def _atomic_json(payload, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
    os.replace(temporary, path)


def _atomic_parquet(frame, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp"
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def _read_manifest(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _relative(root, path):
    return os.path.relpath(path, root)


def _absolute(root, path):
    return path if os.path.isabs(path) else os.path.join(root, path)


def latest_available_market_date(data_path):
    """Use three liquid reference symbols to avoid a partially updated date."""
    latest_dates = []
    for symbol in REFERENCE_SYMBOLS:
        path = os.path.join(data_path, f"{symbol}.parquet")
        if not os.path.exists(path):
            continue
        frame = pd.read_parquet(path, columns=[])
        if len(frame.index):
            latest_dates.append(pd.to_datetime(frame.index[-1]).normalize())
    if not latest_dates:
        raise FileNotFoundError(
            "Could not determine market-data date from reference symbols."
        )
    return min(latest_dates)


def market_session_dates(data_path, start_date, end_date):
    """Return actual sessions from a reference symbol, excluding holidays."""
    start = pd.to_datetime(start_date).normalize()
    end = pd.to_datetime(end_date).normalize()
    if start > end:
        return pd.DatetimeIndex([])
    for symbol in REFERENCE_SYMBOLS:
        path = os.path.join(data_path, f"{symbol}.parquet")
        if not os.path.exists(path):
            continue
        frame = pd.read_parquet(path, columns=[])
        index = pd.DatetimeIndex(pd.to_datetime(frame.index)).normalize()
        return index[(index >= start) & (index <= end)]
    raise FileNotFoundError("No reference calendar is available.")


def _load_baseline_manifest(baseline_dir):
    path = os.path.join(baseline_dir, "manifest.json")
    manifest = _read_manifest(path)
    if manifest is None:
        raise FileNotFoundError(path)
    return manifest


def bootstrap_production(
    production_dir,
    baseline_dir,
    params,
):
    """Seed production registry/checkpoints/history from a validated shadow."""
    manifest_path = os.path.join(production_dir, "manifest.json")
    existing = _read_manifest(manifest_path)
    if existing is not None:
        return existing

    baseline_manifest = _load_baseline_manifest(baseline_dir)
    shadow_dir = os.path.join(baseline_dir, "shadow_incremental")
    report = _read_manifest(os.path.join(shadow_dir, "parity_report.json"))
    if not report or not report.get("passed") or report.get("total_mismatches") != 0:
        raise ValueError("A zero-mismatch shadow baseline is required.")

    source_history = pd.read_parquet(baseline_manifest["source_path"])
    shadow_history = pd.read_parquet(
        os.path.join(shadow_dir, "tracking_history.parquet")
    )
    baseline_end = pd.to_datetime(baseline_manifest["end_date"]).normalize()
    registry = structures_from_tracking_history(source_history, params)
    state_source = LifecycleCheckpointRepository(
        os.path.join(shadow_dir, "state"), params
    )
    states = state_source.load()
    if set(registry["base_id"].astype(str)) != set(states):
        raise ValueError("Baseline structures and checkpoints do not align.")

    bootstrap_dir = os.path.join(production_dir, "bootstrap")
    os.makedirs(bootstrap_dir, exist_ok=True)
    state_repo = LifecycleCheckpointRepository(
        os.path.join(bootstrap_dir, "state"), params
    )
    shadow_event_path = os.path.join(
        shadow_dir, "state", "lifecycle_events.parquet"
    )
    seed_events = (
        pd.read_parquet(shadow_event_path).to_dict("records")
        if os.path.exists(shadow_event_path)
        else []
    )
    state_repo.save(states, seed_events)
    structure_repo = StructureRegistryRepository(
        os.path.join(bootstrap_dir, "structures"), params
    )
    structure_repo.save(registry, as_of_date=baseline_end)
    seed_history_path = os.path.join(bootstrap_dir, "tracking_history.parquet")
    _atomic_parquet(shadow_history, seed_history_path)

    root_manifest = {
        "artifact_type": "base_lifecycle_layered_production",
        "schema_version": PRODUCTION_SCHEMA_VERSION,
        "strategy_config_hash": config_hash(params),
        "baseline_name": os.path.basename(os.path.normpath(baseline_dir)),
        "baseline_end_date": baseline_end.date().isoformat(),
        "last_committed_date": baseline_end.date().isoformat(),
        "last_structure_week_end": latest_completed_week_end(
            baseline_end
        ).date().isoformat(),
        "latest_checkpoint_dir": _relative(
            production_dir, os.path.join(bootstrap_dir, "state")
        ),
        "latest_structure_dir": _relative(
            production_dir, os.path.join(bootstrap_dir, "structures")
        ),
        "seed_history_path": _relative(production_dir, seed_history_path),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(root_manifest, manifest_path)
    materialize_production_views(production_dir, root_manifest)
    return root_manifest


def _load_latest_state(production_dir, manifest, params):
    checkpoint_dir = _absolute(
        production_dir, manifest["latest_checkpoint_dir"]
    )
    states = LifecycleCheckpointRepository(checkpoint_dir, params).load()
    structure_dir = _absolute(
        production_dir, manifest["latest_structure_dir"]
    )
    registry = StructureRegistryRepository(structure_dir, params).load()
    return states, registry


def _load_symbol_daily(engine, symbol, as_of_date):
    return load_daily_for_tracking(symbol, as_of_date, engine)


def _bootstrap_structure_state(structure, daily, as_of_date, params):
    prepared, resolved_low_date = prepare_daily_handle_window(
        daily,
        structure["base_low_index"],
        atr_window=params.get("ATR_WINDOW", 14),
    )
    prepared = prepared[prepared.index <= pd.to_datetime(as_of_date)]
    if prepared.empty:
        return None, []
    structure_payload = {
        **structure,
        "resolved_base_low_date": resolved_low_date,
    }
    first = {**prepared.iloc[0].to_dict(), "date": prepared.index[0]}
    state = initialize_lifecycle_state(
        structure_payload,
        first,
        params,
        left_setup_atr=resolve_left_setup_atr(
            prepared,
            structure["left_high_index"],
        ),
    )
    events = []
    for candle_date, candle_row in prepared.iloc[1:].iterrows():
        state, current_events = advance_lifecycle_state(
            state,
            {**candle_row.to_dict(), "date": candle_date},
            params,
        )
        events.extend(current_events)
    return state, events


def _advance_existing_state(state, daily, as_of_date, params):
    last_date = pd.to_datetime(state["last_processed_date"])
    missing = daily[
        (daily.index > last_date)
        & (daily.index <= pd.to_datetime(as_of_date))
    ]
    events = []
    for candle_date, candle_row in missing.iterrows():
        state, current_events = advance_lifecycle_state(
            state,
            {**candle_row.to_dict(), "date": candle_date},
            params,
        )
        events.extend(current_events)
    return state, events


def _tracking_row(structure, state, tracking_date, params):
    snapshot = lifecycle_snapshot(state, params, tracking_eligible=True)
    first_detected = structure.get("first_detected_date", pd.NaT)
    return {
        **structure,
        **snapshot,
        "base_id": str(structure["base_id"]),
        "Symbol": str(structure["Symbol"]).strip(),
        "tracking_date": pd.to_datetime(tracking_date).normalize(),
        "scan_as_of_date": pd.to_datetime(tracking_date).normalize(),
        "last_tracked_date": pd.to_datetime(tracking_date).normalize(),
        "signal_as_of_date": pd.to_datetime(
            state["last_processed_date"]
        ).normalize(),
        "first_detected_date": first_detected,
        "active_pivot_price": snapshot["selected_pivot"],
        "active_pivot_type": snapshot["pivot_source"],
        "active_pivot_date": snapshot["selected_pivot_date"],
        "active_pivot_distance_pct": snapshot["distance_from_pivot_pct"],
        "strategy_version": params.get("STRATEGY_VERSION"),
    }


def _current_state_is_archived(state, params):
    return lifecycle_snapshot(state, params)["tracking_state"] == "ARCHIVED"


def _discover_structures(as_of_date, data_path, params, debug=False):
    scanner = BaseLifecycleScanner(
        {**params, "AS_OF_DATE": pd.to_datetime(as_of_date)},
        data_path=data_path,
        debug=debug,
    )
    scanner.run_scan()
    return scanner.all_window_results.copy()


def _commit_date(
    production_dir,
    processing_date,
    states,
    registry,
    tracking_rows,
    lifecycle_events,
    structure_events,
    discoveries,
    params,
    prior_manifest,
    structure_week_end,
):
    dates_dir = os.path.join(production_dir, "dates")
    os.makedirs(dates_dir, exist_ok=True)
    date_label = pd.to_datetime(processing_date).strftime("%Y-%m-%d")
    final_dir = os.path.join(dates_dir, date_label)
    if os.path.exists(final_dir):
        return prior_manifest
    transaction_dir = os.path.join(
        dates_dir, f".{date_label}.tmp-{uuid.uuid4().hex}"
    )
    os.makedirs(transaction_dir)
    try:
        state_dir = os.path.join(transaction_dir, "state")
        LifecycleCheckpointRepository(state_dir, params).save(
            states, lifecycle_events
        )
        structure_dir = os.path.join(transaction_dir, "structures")
        StructureRegistryRepository(structure_dir, params).save(
            registry,
            events=pd.DataFrame(structure_events),
            as_of_date=processing_date,
        )
        _atomic_parquet(
            pd.DataFrame(tracking_rows),
            os.path.join(transaction_dir, "tracking_rows.parquet"),
        )
        if discoveries is not None and not discoveries.empty:
            _atomic_parquet(
                discoveries,
                os.path.join(transaction_dir, "structure_discoveries.parquet"),
            )
        partition_manifest = {
            "processing_date": date_label,
            "checkpoint_count": len(states),
            "tracking_row_count": len(tracking_rows),
            "lifecycle_event_count": len(lifecycle_events),
            "structure_count": len(registry),
            "structure_event_count": len(structure_events),
            "structure_week_end": pd.to_datetime(
                structure_week_end
            ).date().isoformat(),
            "strategy_config_hash": config_hash(params),
        }
        _atomic_json(
            partition_manifest,
            os.path.join(transaction_dir, "manifest.json"),
        )
        os.rename(transaction_dir, final_dir)
    except Exception:
        if os.path.exists(transaction_dir):
            shutil.rmtree(transaction_dir, ignore_errors=True)
        raise

    root_manifest = {
        **prior_manifest,
        "last_committed_date": date_label,
        "last_structure_week_end": pd.to_datetime(
            structure_week_end
        ).date().isoformat(),
        "latest_checkpoint_dir": _relative(
            production_dir, os.path.join(final_dir, "state")
        ),
        "latest_structure_dir": _relative(
            production_dir, os.path.join(final_dir, "structures")
        ),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(root_manifest, os.path.join(production_dir, "manifest.json"))
    materialize_production_views(production_dir, root_manifest)
    return root_manifest


def materialize_production_views(production_dir, manifest=None):
    """Rebuild disposable dashboard history/events from committed partitions."""
    manifest = manifest or _read_manifest(
        os.path.join(production_dir, "manifest.json")
    )
    if manifest is None:
        return {}
    frames = [
        pd.read_parquet(_absolute(production_dir, manifest["seed_history_path"]))
    ]
    event_frames = []
    dates_dir = Path(production_dir) / "dates"
    last_date = pd.to_datetime(manifest["last_committed_date"])
    if dates_dir.exists():
        for date_dir in sorted(path for path in dates_dir.iterdir() if path.is_dir() and not path.name.startswith(".")):
            try:
                partition_date = pd.to_datetime(date_dir.name)
            except ValueError:
                continue
            if partition_date > last_date:
                continue
            row_path = date_dir / "tracking_rows.parquet"
            if row_path.exists():
                frames.append(pd.read_parquet(row_path))
            event_path = date_dir / "state" / "lifecycle_events.parquet"
            if event_path.exists():
                events = pd.read_parquet(event_path)
                if not events.empty:
                    event_frames.append(events)
    history = pd.concat(frames, ignore_index=True, sort=False)
    history["tracking_date"] = pd.to_datetime(history["tracking_date"])
    history = history.sort_values(
        ["tracking_date", "base_id"], kind="stable"
    ).drop_duplicates(["base_id", "tracking_date"], keep="last")
    views_dir = os.path.join(production_dir, "views")
    history_path = os.path.join(views_dir, "tracking_history.parquet")
    _atomic_parquet(history.reset_index(drop=True), history_path)
    events = (
        pd.concat(event_frames, ignore_index=True, sort=False)
        if event_frames
        else pd.DataFrame()
    )
    _atomic_parquet(events, os.path.join(views_dir, "lifecycle_events.parquet"))
    return {
        "history_path": history_path,
        "history_rows": len(history),
        "event_rows": len(events),
    }


def run_daily_pipeline(
    production_dir,
    baseline_dir,
    *,
    data_path,
    params,
    as_of_date=None,
    debug=False,
    progress_callback=None,
):
    manifest = bootstrap_production(production_dir, baseline_dir, params)
    if manifest["strategy_config_hash"] != config_hash(params):
        raise ValueError("Production manifest config does not match this run.")
    latest_data_date = latest_available_market_date(data_path)
    target_date = (
        pd.to_datetime(as_of_date).normalize()
        if as_of_date is not None
        else latest_data_date
    )
    if target_date > latest_data_date:
        raise ValueError(
            f"Requested {target_date.date()} but market data ends "
            f"{latest_data_date.date()}."
        )
    last_committed = pd.to_datetime(manifest["last_committed_date"])
    sessions = market_session_dates(
        data_path, last_committed + pd.Timedelta(days=1), target_date
    )
    if sessions.empty:
        materialize_production_views(production_dir, manifest)
        return {
            "status": "CURRENT",
            "processed_dates": 0,
            "last_committed_date": manifest["last_committed_date"],
            "latest_market_date": latest_data_date.date().isoformat(),
        }

    states, registry = _load_latest_state(production_dir, manifest, params)
    engine = DataEngine(data_path)
    summaries = []
    for completed, processing_date in enumerate(sessions, start=1):
        previous_week_end = pd.to_datetime(
            manifest["last_structure_week_end"]
        )
        current_week_end = latest_completed_week_end(processing_date)
        discoveries = pd.DataFrame()
        structure_events = pd.DataFrame()
        if current_week_end > previous_week_end:
            discoveries = _discover_structures(
                processing_date, data_path, params, debug=debug
            )
            registry, structure_events = upsert_discovered_structures(
                registry, discoveries, processing_date, params
            )

        registry_by_id = {
            str(row["base_id"]): row
            for row in registry.to_dict("records")
        }
        lifecycle_events = []
        tracking_rows = []

        for base_id, state in list(states.items()):
            if _current_state_is_archived(state, params):
                continue
            structure = registry_by_id[base_id]
            daily = _load_symbol_daily(
                engine, structure["Symbol"], processing_date
            )
            state, events = _advance_existing_state(
                state, daily, processing_date, params
            )
            states[base_id] = state
            lifecycle_events.extend(events)
            tracking_rows.append(
                _tracking_row(structure, state, processing_date, params)
            )

        for index, structure_row in registry.iterrows():
            base_id = str(structure_row["base_id"])
            if base_id in states:
                continue
            structure = structure_row.to_dict()
            daily = _load_symbol_daily(
                engine, structure["Symbol"], processing_date
            )
            if daily.empty:
                continue
            latest_close = float(daily["Close"].iloc[-1])
            left_high = float(structure["left_high"])
            base_low = float(structure["base_low"])
            recovery = (
                (latest_close - base_low) / (left_high - base_low)
                if left_high > base_low
                else float("nan")
            )
            if pd.isna(recovery) or recovery < float(
                params.get("TRACKING_ELIGIBLE_RECOVERY_MIN", 0.40)
            ):
                continue
            state, events = _bootstrap_structure_state(
                structure, daily, processing_date, params
            )
            if state is None:
                continue
            registry.at[index, "first_detected_date"] = processing_date
            structure["first_detected_date"] = processing_date
            states[base_id] = state
            lifecycle_events.extend(events)
            tracking_rows.append(
                _tracking_row(structure, state, processing_date, params)
            )

        manifest = _commit_date(
            production_dir,
            processing_date,
            states,
            registry,
            tracking_rows,
            lifecycle_events,
            structure_events.to_dict("records"),
            discoveries,
            params,
            manifest,
            current_week_end,
        )
        summary = {
            "processing_date": processing_date.date().isoformat(),
            "structure_refresh": bool(current_week_end > previous_week_end),
            "structures": len(registry),
            "checkpoints": len(states),
            "tracking_rows": len(tracking_rows),
            "new_structures": len(structure_events),
            "lifecycle_events": len(lifecycle_events),
        }
        summaries.append(summary)
        if progress_callback is not None:
            progress_callback(completed, len(sessions), summary)
    return {
        "status": "PROCESSED",
        "processed_dates": len(summaries),
        "last_committed_date": manifest["last_committed_date"],
        "latest_market_date": latest_data_date.date().isoformat(),
        "dates": summaries,
    }


def validate_production_state(production_dir, params):
    manifest = _read_manifest(os.path.join(production_dir, "manifest.json"))
    if manifest is None:
        return {"passed": False, "errors": ["missing production manifest"]}
    errors = []
    try:
        states, registry = _load_latest_state(production_dir, manifest, params)
    except Exception as exc:
        return {"passed": False, "errors": [str(exc)]}
    history_path = os.path.join(
        production_dir, "views", "tracking_history.parquet"
    )
    if not os.path.exists(history_path):
        errors.append("missing materialized tracking history")
        history = pd.DataFrame()
    else:
        history = pd.read_parquet(history_path)
        duplicates = int(
            history.duplicated(["base_id", "tracking_date"], keep=False).sum()
        )
        if duplicates:
            errors.append(f"{duplicates} duplicate base/date rows")
        latest_history = pd.to_datetime(history["tracking_date"]).max()
        if latest_history.normalize() != pd.to_datetime(
            manifest["last_committed_date"]
        ):
            errors.append("history date does not match committed date")
    registry_ids = set(registry["base_id"].astype(str))
    missing_structures = set(states).difference(registry_ids)
    if missing_structures:
        errors.append(
            f"{len(missing_structures)} checkpoints have no structure"
        )
    invalid_pivots = 0
    for state in states.values():
        snapshot = lifecycle_snapshot(state, params)
        if (
            pd.isna(snapshot.get("selected_pivot"))
            or float(snapshot["selected_pivot"]) <= 0
            or snapshot.get("pivot_source") not in {"LEFT_HIGH", "DAILY_HANDLE"}
        ):
            invalid_pivots += 1
    if invalid_pivots:
        errors.append(f"{invalid_pivots} invalid active pivots")
    return {
        "passed": not errors,
        "errors": errors,
        "last_committed_date": manifest["last_committed_date"],
        "checkpoint_count": len(states),
        "structure_count": len(registry),
        "history_rows": len(history),
    }
