"""Shadow incremental replay using frozen structure membership and raw candles."""

import json
import os

import pandas as pd

from data_layer.data_engine import DataEngine
from lifecycle_checkpoints import LifecycleCheckpointRepository
from lifecycle_incremental import (
    advance_lifecycle_state,
    initialize_lifecycle_state,
    lifecycle_snapshot,
    resolve_left_setup_atr,
)
from lifecycle_parity import compare_tracking_history
from base_lifecycle_scanner import (
    load_daily_for_tracking,
    prepare_daily_handle_window,
)


def _atomic_parquet(frame, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp"
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def run_shadow_incremental(
    baseline_dir,
    output_dir,
    *,
    data_path,
    params,
    progress_callback=None,
):
    """Recalculate lifecycle fields incrementally for frozen base/date keys."""
    manifest_path = os.path.join(baseline_dir, "manifest.json")
    expected_path = os.path.join(baseline_dir, "tracking_history.parquet")
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    source_path = manifest["source_path"]
    expected = pd.read_parquet(expected_path)
    source = pd.read_parquet(source_path)
    source["tracking_date"] = pd.to_datetime(source["tracking_date"]).dt.normalize()
    expected["tracking_date"] = pd.to_datetime(
        expected["tracking_date"]
    ).dt.normalize()

    engine = DataEngine(data_path)
    states = {}
    all_events = []
    output_rows = []
    grouped = list(source.groupby("base_id", sort=True))
    total = len(grouped)

    for completed, (base_id, base_rows) in enumerate(grouped, start=1):
        base_rows = base_rows.sort_values("tracking_date").copy()
        structure_row = base_rows.iloc[0]
        final_date = base_rows["tracking_date"].max()
        daily_full = load_daily_for_tracking(
            structure_row["Symbol"], final_date, engine
        )
        prepared, resolved_low_date = prepare_daily_handle_window(
            daily_full,
            structure_row["base_low_index"],
            atr_window=params.get("ATR_WINDOW", 14),
        )
        if prepared.empty:
            raise ValueError(f"No bootstrap candles for {base_id}")
        structure = {
            **structure_row.to_dict(),
            "resolved_base_low_date": resolved_low_date,
        }
        first_date = prepared.index[0]
        first_candle = {**prepared.iloc[0].to_dict(), "date": first_date}
        state = initialize_lifecycle_state(
            structure,
            first_candle,
            params,
            left_setup_atr=resolve_left_setup_atr(
                prepared,
                structure_row["left_high_index"],
            ),
        )
        candle_position = 1

        for _, expected_row in base_rows.iterrows():
            tracking_date = pd.to_datetime(expected_row["tracking_date"]).normalize()
            while (
                candle_position < len(prepared)
                and prepared.index[candle_position] <= tracking_date
            ):
                candle_date = prepared.index[candle_position]
                candle = {
                    **prepared.iloc[candle_position].to_dict(),
                    "date": candle_date,
                }
                state, events = advance_lifecycle_state(state, candle, params)
                all_events.extend(events)
                candle_position += 1

            snapshot = lifecycle_snapshot(
                state,
                params,
                tracking_eligible=bool(
                    expected_row.get("tracking_eligible", True)
                ),
            )
            output_row = expected_row.to_dict()
            output_row.update(snapshot)
            output_row.update(
                {
                    "base_id": str(base_id),
                    "tracking_date": tracking_date,
                    "active_pivot_price": snapshot["selected_pivot"],
                    "active_pivot_type": snapshot["pivot_source"],
                    "active_pivot_date": snapshot["selected_pivot_date"],
                    "active_pivot_distance_pct": snapshot[
                        "distance_from_pivot_pct"
                    ],
                }
            )
            output_rows.append(output_row)
        states[str(base_id)] = state
        if progress_callback is not None:
            progress_callback(completed, total, str(base_id))

    output = pd.DataFrame(output_rows).sort_values(
        ["tracking_date", "base_id"]
    ).reset_index(drop=True)
    os.makedirs(output_dir, exist_ok=True)
    history_path = os.path.join(output_dir, "tracking_history.parquet")
    _atomic_parquet(output, history_path)
    repository = LifecycleCheckpointRepository(
        os.path.join(output_dir, "state"), params
    )
    persistence = repository.save(states, all_events)
    report = compare_tracking_history(
        expected,
        output,
        value_columns=manifest["value_columns"],
    )
    report.update(
        {
            "shadow_history_path": history_path,
            **persistence,
        }
    )
    report_path = os.path.join(output_dir, "parity_report.json")
    with open(f"{report_path}.tmp", "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
    os.replace(f"{report_path}.tmp", report_path)
    report["report_path"] = report_path
    return report

