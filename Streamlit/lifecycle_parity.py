"""Baseline artifacts and parity checks for lifecycle architecture changes."""

import hashlib
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd


PARITY_KEY_COLUMNS = ["base_id", "tracking_date"]
PARITY_VALUE_COLUMNS = [
    "Symbol",
    "base_window_weeks",
    "left_high_index",
    "base_low_index",
    "recovery_pct",
    "selected_pivot",
    "selected_pivot_date",
    "pivot_source",
    "daily_handle_state",
    "daily_handle_candidate_pivot",
    "daily_handle_candidate_date",
    "daily_handle_confirmation_date",
    "daily_handle_invalidated",
    "daily_handle_invalidation_date",
    "breakout_date",
    "breakout_success",
    "breakout_success_date",
    "lifecycle_phase",
    "lifecycle_status",
    "journey_stage",
    "tracking_state",
    "archive_reason",
]
DATE_COLUMNS = {
    "tracking_date",
    "left_high_index",
    "base_low_index",
    "selected_pivot_date",
    "daily_handle_candidate_date",
    "daily_handle_confirmation_date",
    "daily_handle_invalidation_date",
    "breakout_date",
    "breakout_success_date",
}
NUMERIC_COLUMNS = {
    "base_window_weeks",
    "recovery_pct",
    "selected_pivot",
    "daily_handle_candidate_pivot",
}


def _config_hash(config):
    payload = json.dumps(config or {}, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _filter_history(history, start_date=None, end_date=None):
    result = history.copy()
    if "tracking_date" not in result.columns:
        raise ValueError("tracking history is missing required column: tracking_date")
    result["tracking_date"] = pd.to_datetime(
        result["tracking_date"], errors="coerce"
    ).dt.normalize()
    if start_date is not None:
        result = result[result["tracking_date"] >= pd.to_datetime(start_date).normalize()]
    if end_date is not None:
        result = result[result["tracking_date"] <= pd.to_datetime(end_date).normalize()]
    return result.reset_index(drop=True)


def _atomic_parquet(frame, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = f"{path}.tmp"
    frame.to_parquet(temporary_path, index=False)
    os.replace(temporary_path, path)


def _atomic_json(payload, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = f"{path}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
    os.replace(temporary_path, path)


def freeze_tracking_baseline(
    history_path,
    baseline_dir,
    *,
    start_date=None,
    end_date=None,
    strategy_config=None,
):
    """Freeze a date-bounded copy of current tracking output plus its contract."""
    if not os.path.exists(history_path):
        raise FileNotFoundError(history_path)
    history = _filter_history(
        pd.read_parquet(history_path),
        start_date=start_date,
        end_date=end_date,
    )
    if history.empty:
        raise ValueError("No tracking rows exist in the requested baseline range.")
    missing_keys = [column for column in PARITY_KEY_COLUMNS if column not in history]
    if missing_keys:
        raise ValueError(f"tracking history is missing parity keys: {missing_keys}")

    available_values = [
        column for column in PARITY_VALUE_COLUMNS if column in history.columns
    ]
    baseline_columns = PARITY_KEY_COLUMNS + [
        column
        for column in available_values
        if column not in PARITY_KEY_COLUMNS
    ]
    baseline = history[baseline_columns].copy()
    baseline = baseline.sort_values(PARITY_KEY_COLUMNS).reset_index(drop=True)
    duplicated = baseline.duplicated(PARITY_KEY_COLUMNS, keep=False)
    if duplicated.any():
        raise ValueError(
            "Cannot freeze baseline: duplicate base_id + tracking_date rows exist."
        )

    baseline_path = os.path.join(baseline_dir, "tracking_history.parquet")
    manifest_path = os.path.join(baseline_dir, "manifest.json")
    _atomic_parquet(baseline, baseline_path)
    manifest = {
        "artifact_type": "base_lifecycle_parity_baseline",
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_path": os.path.abspath(history_path),
        "start_date": baseline["tracking_date"].min().date().isoformat(),
        "end_date": baseline["tracking_date"].max().date().isoformat(),
        "row_count": int(len(baseline)),
        "unique_base_count": int(baseline["base_id"].nunique()),
        "key_columns": PARITY_KEY_COLUMNS,
        "value_columns": [
            column for column in baseline.columns if column not in PARITY_KEY_COLUMNS
        ],
        "strategy_config": strategy_config or {},
        "strategy_config_hash": _config_hash(strategy_config),
    }
    _atomic_json(manifest, manifest_path)
    return {
        "baseline_path": baseline_path,
        "manifest_path": manifest_path,
        **manifest,
    }


def _normalized_series(series, column):
    if column in DATE_COLUMNS:
        return pd.to_datetime(series, errors="coerce").dt.normalize()
    if column in NUMERIC_COLUMNS:
        return pd.to_numeric(series, errors="coerce")
    return series.astype("string").fillna("<NA>")


def compare_tracking_history(
    expected,
    actual,
    *,
    value_columns=None,
    float_tolerance=1e-9,
    max_examples=20,
):
    """Compare every base/date row and return a machine-readable parity report."""
    missing_expected_keys = [
        column for column in PARITY_KEY_COLUMNS if column not in expected.columns
    ]
    missing_actual_keys = [
        column for column in PARITY_KEY_COLUMNS if column not in actual.columns
    ]
    if missing_expected_keys or missing_actual_keys:
        raise ValueError(
            "Parity keys missing: "
            f"expected={missing_expected_keys}, actual={missing_actual_keys}"
        )

    expected = expected.copy()
    actual = actual.copy()
    for frame in [expected, actual]:
        frame["base_id"] = frame["base_id"].astype(str)
        frame["tracking_date"] = pd.to_datetime(
            frame["tracking_date"], errors="coerce"
        ).dt.normalize()

    expected_duplicates = int(
        expected.duplicated(PARITY_KEY_COLUMNS, keep=False).sum()
    )
    actual_duplicates = int(
        actual.duplicated(PARITY_KEY_COLUMNS, keep=False).sum()
    )
    expected_keys = pd.MultiIndex.from_frame(expected[PARITY_KEY_COLUMNS])
    actual_keys = pd.MultiIndex.from_frame(actual[PARITY_KEY_COLUMNS])
    missing_in_actual = expected_keys.difference(actual_keys)
    unexpected_in_actual = actual_keys.difference(expected_keys)

    requested_columns = value_columns or [
        column
        for column in expected.columns
        if column not in PARITY_KEY_COLUMNS
    ]
    missing_columns = [
        column for column in requested_columns if column not in actual.columns
    ]
    comparable_columns = [
        column
        for column in requested_columns
        if column in expected.columns and column in actual.columns
    ]
    expected_indexed = expected.set_index(PARITY_KEY_COLUMNS)
    actual_indexed = actual.set_index(PARITY_KEY_COLUMNS)
    shared_keys = expected_indexed.index.intersection(actual_indexed.index)
    field_mismatches = {}
    examples = []

    if not expected_duplicates and not actual_duplicates:
        for column in comparable_columns:
            expected_values = _normalized_series(
                expected_indexed.loc[shared_keys, column], column
            )
            actual_values = _normalized_series(
                actual_indexed.loc[shared_keys, column], column
            )
            if column in NUMERIC_COLUMNS:
                equal = np.isclose(
                    expected_values.to_numpy(dtype=float),
                    actual_values.to_numpy(dtype=float),
                    rtol=float_tolerance,
                    atol=float_tolerance,
                    equal_nan=True,
                )
                mismatch_mask = pd.Series(~equal, index=shared_keys)
            elif column in DATE_COLUMNS:
                equal = expected_values.eq(actual_values) | (
                    expected_values.isna() & actual_values.isna()
                )
                mismatch_mask = ~equal
            else:
                mismatch_mask = expected_values.ne(actual_values)
            mismatch_count = int(mismatch_mask.sum())
            if mismatch_count:
                field_mismatches[column] = mismatch_count
                for key in mismatch_mask[mismatch_mask].index:
                    if len(examples) >= max_examples:
                        break
                    key_tuple = key if isinstance(key, tuple) else (key,)
                    examples.append(
                        {
                            "base_id": str(key_tuple[0]),
                            "tracking_date": str(key_tuple[1]),
                            "field": column,
                            "expected": str(expected_indexed.loc[key, column]),
                            "actual": str(actual_indexed.loc[key, column]),
                        }
                    )

    total_mismatches = (
        len(missing_in_actual)
        + len(unexpected_in_actual)
        + len(missing_columns)
        + expected_duplicates
        + actual_duplicates
        + sum(field_mismatches.values())
    )
    return {
        "passed": total_mismatches == 0,
        "expected_rows": int(len(expected)),
        "actual_rows": int(len(actual)),
        "shared_rows": int(len(shared_keys)),
        "missing_rows": int(len(missing_in_actual)),
        "unexpected_rows": int(len(unexpected_in_actual)),
        "expected_duplicate_rows": expected_duplicates,
        "actual_duplicate_rows": actual_duplicates,
        "missing_columns": missing_columns,
        "field_mismatches": field_mismatches,
        "total_mismatches": int(total_mismatches),
        "examples": examples,
    }


def validate_tracking_baseline(
    baseline_dir,
    current_history_path,
    *,
    float_tolerance=1e-9,
):
    """Validate current stored history against a frozen baseline date range."""
    manifest_path = os.path.join(baseline_dir, "manifest.json")
    baseline_path = os.path.join(baseline_dir, "tracking_history.parquet")
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    expected = pd.read_parquet(baseline_path)
    actual = _filter_history(
        pd.read_parquet(current_history_path),
        start_date=manifest["start_date"],
        end_date=manifest["end_date"],
    )
    report = compare_tracking_history(
        expected,
        actual,
        value_columns=manifest["value_columns"],
        float_tolerance=float_tolerance,
    )
    report["baseline_dir"] = os.path.abspath(baseline_dir)
    report["current_history_path"] = os.path.abspath(current_history_path)
    report["strategy_config_hash"] = manifest.get("strategy_config_hash")
    return report
