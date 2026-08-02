import os
import sys
import unittest

import pandas as pd


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMLIT_DIR = os.path.join(PROJECT_ROOT, "Streamlit")
if STREAMLIT_DIR not in sys.path:
    sys.path.insert(0, STREAMLIT_DIR)

from base_lifecycle_scanner import DEFAULT_PARAMS
from lifecycle_checkpoints import LifecycleCheckpointRepository
from lifecycle_incremental import (
    advance_lifecycle_state,
    initialize_lifecycle_state,
    lifecycle_snapshot,
    resolve_left_setup_atr,
)


def candle(date, high, low, close, atr=2.0):
    return {
        "date": pd.Timestamp(date),
        "Open": close,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": 1_000,
        "daily_atr_14": atr,
    }


class LifecycleIncrementalTests(unittest.TestCase):
    def test_left_setup_atr_uses_last_candle_through_left_high_date(self):
        dates = pd.to_datetime(
            ["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08"]
        )
        prepared = pd.DataFrame(
            {"daily_atr_14": [2.0, 3.0, 4.0, 5.0, 10.0]},
            index=dates,
        )

        selected = resolve_left_setup_atr(prepared, pd.Timestamp("2026-05-08"))

        self.assertEqual(selected, 10.0)

    def test_breakout_success_and_failure_are_latched_incrementally(self):
        structure = {
            "base_id": "AAA|104W|20250101|20260102",
            "Symbol": "AAA",
            "left_high": 100.0,
            "left_high_index": pd.Timestamp("2025-01-01"),
            "base_low": 70.0,
            "base_low_index": pd.Timestamp("2026-01-02"),
            "resolved_base_low_date": pd.Timestamp("2026-01-02"),
            "Depth": 0.30,
        }
        state = initialize_lifecycle_state(
            structure,
            candle("2026-01-02", 72, 70, 71),
            DEFAULT_PARAMS,
        )
        sequence = [
            candle("2026-01-05", 96, 93, 95),
            candle("2026-01-06", 95, 92, 94),
            candle("2026-01-07", 95, 92, 94),
            candle("2026-01-08", 95, 92, 94),
            candle("2026-01-09", 95, 92, 94),
            candle("2026-01-12", 95, 92, 94),
            candle("2026-01-13", 102, 99, 101),
            candle("2026-01-14", 113, 105, 112),
            candle("2026-01-15", 89, 85, 86),
            candle("2026-01-16", 88, 84, 85),
        ]
        for current in sequence:
            state, _events = advance_lifecycle_state(
                state, current, DEFAULT_PARAMS
            )
        snapshot = lifecycle_snapshot(state, DEFAULT_PARAMS)

        self.assertEqual(snapshot["pivot_source"], "DAILY_HANDLE")
        self.assertEqual(snapshot["breakout_date"], pd.Timestamp("2026-01-13"))
        self.assertTrue(snapshot["breakout_success"])
        self.assertTrue(snapshot["persistent_failure"])
        self.assertEqual(snapshot["journey_stage"], "FAILED")
        self.assertEqual(snapshot["tracking_state"], "ARCHIVED")

    def test_checkpoint_round_trip_can_continue_processing(self):
        fixture_dir = os.path.join(
            PROJECT_ROOT, "data", "test", "lifecycle_checkpoint_fixture"
        )
        generated = [
            os.path.join(fixture_dir, "latest_checkpoints.parquet"),
            os.path.join(fixture_dir, "lifecycle_events.parquet"),
        ]
        structure = {
            "base_id": "AAA|104W|20250101|20260102",
            "Symbol": "AAA",
            "left_high": 100.0,
            "left_high_index": pd.Timestamp("2025-01-01"),
            "base_low": 70.0,
            "base_low_index": pd.Timestamp("2026-01-02"),
            "resolved_base_low_date": pd.Timestamp("2026-01-02"),
            "Depth": 0.30,
        }
        state = initialize_lifecycle_state(
            structure,
            candle("2026-01-02", 72, 70, 71),
            DEFAULT_PARAMS,
        )
        repository = LifecycleCheckpointRepository(fixture_dir, DEFAULT_PARAMS)
        try:
            repository.save({state["base_id"]: state}, [])
            restored = repository.load()[state["base_id"]]
            continued, _events = advance_lifecycle_state(
                restored,
                candle("2026-01-05", 96, 93, 95),
                DEFAULT_PARAMS,
            )
            direct, _events = advance_lifecycle_state(
                state,
                candle("2026-01-05", 96, 93, 95),
                DEFAULT_PARAMS,
            )

            self.assertEqual(
                lifecycle_snapshot(continued, DEFAULT_PARAMS)["selected_pivot"],
                lifecycle_snapshot(direct, DEFAULT_PARAMS)["selected_pivot"],
            )
            self.assertEqual(
                continued["last_processed_date"], direct["last_processed_date"]
            )
        finally:
            for path in generated:
                if os.path.exists(path):
                    os.remove(path)


if __name__ == "__main__":
    unittest.main()
