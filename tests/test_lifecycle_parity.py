import os
import sys
import unittest

import pandas as pd


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMLIT_DIR = os.path.join(PROJECT_ROOT, "Streamlit")
if STREAMLIT_DIR not in sys.path:
    sys.path.insert(0, STREAMLIT_DIR)

from lifecycle_parity import (
    compare_tracking_history,
    freeze_tracking_baseline,
    validate_tracking_baseline,
)


def history_frame():
    return pd.DataFrame(
        [
            {
                "base_id": "AAA|104W|20250101|20250201",
                "tracking_date": pd.Timestamp("2026-07-20"),
                "Symbol": "AAA",
                "base_window_weeks": 104,
                "selected_pivot": 100.0,
                "pivot_source": "LEFT_HIGH",
                "journey_stage": "BREAKOUT_CONSIDERATION",
                "breakout_date": pd.NaT,
            },
            {
                "base_id": "AAA|104W|20250101|20250201",
                "tracking_date": pd.Timestamp("2026-07-21"),
                "Symbol": "AAA",
                "base_window_weeks": 104,
                "selected_pivot": 96.0,
                "pivot_source": "DAILY_HANDLE",
                "journey_stage": "SUCCESSFUL_BREAKOUT",
                "breakout_date": pd.Timestamp("2026-07-21"),
            },
        ]
    )


class LifecycleParityTests(unittest.TestCase):
    def test_equal_histories_pass(self):
        history = history_frame()
        report = compare_tracking_history(history, history.copy())
        self.assertTrue(report["passed"])
        self.assertEqual(report["total_mismatches"], 0)

    def test_changed_pivot_is_reported(self):
        expected = history_frame()
        actual = expected.copy()
        actual.loc[1, "selected_pivot"] = 97.0
        report = compare_tracking_history(expected, actual)
        self.assertFalse(report["passed"])
        self.assertEqual(report["field_mismatches"]["selected_pivot"], 1)

    def test_missing_date_is_reported(self):
        expected = history_frame()
        report = compare_tracking_history(expected, expected.iloc[:1].copy())
        self.assertFalse(report["passed"])
        self.assertEqual(report["missing_rows"], 1)

    def test_frozen_baseline_round_trip(self):
        fixture_dir = os.path.join(
            PROJECT_ROOT, "data", "test", "lifecycle_parity_fixture"
        )
        source_path = os.path.join(fixture_dir, "source_history.parquet")
        baseline_dir = os.path.join(fixture_dir, "baseline")
        generated_paths = [
            source_path,
            os.path.join(baseline_dir, "tracking_history.parquet"),
            os.path.join(baseline_dir, "manifest.json"),
        ]
        try:
            history_frame().to_parquet(source_path, index=False)
            frozen = freeze_tracking_baseline(
                source_path,
                baseline_dir,
                start_date="2026-07-20",
                end_date="2026-07-21",
                strategy_config={"version": "frozen"},
            )
            report = validate_tracking_baseline(baseline_dir, source_path)

            self.assertTrue(os.path.exists(frozen["manifest_path"]))
            self.assertTrue(report["passed"])
        finally:
            for path in generated_paths:
                if os.path.exists(path):
                    os.remove(path)
            if os.path.isdir(baseline_dir):
                os.rmdir(baseline_dir)


if __name__ == "__main__":
    unittest.main()
