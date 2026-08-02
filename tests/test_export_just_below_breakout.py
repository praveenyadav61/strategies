import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from export_just_below_breakout import (
    export_recent_signal_files,
    select_just_below_breakout,
)


class JustBelowBreakoutExportTests(unittest.TestCase):
    def test_recent_export_writes_latest_session_files_with_stable_names(self):
        history = pd.DataFrame(
            [
                {
                    "Symbol": "AAA",
                    "tracking_date": date,
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 98.0,
                    "largest_single_week_move": 5.0,
                    "breakout_date": pd.NaT,
                }
                for date in ["2026-07-22", "2026-07-23", "2026-07-24"]
            ]
        )
        output_dir = os.path.join(PROJECT_ROOT, "outputs")
        with patch.object(pd.DataFrame, "to_csv") as to_csv:
            summary = export_recent_signal_files(
                history,
                output_dir,
                sessions=2,
            )

            self.assertEqual(summary["dates"], ["2026-07-23", "2026-07-24"])
            self.assertEqual(
                [
                    os.path.basename(item["output_path"])
                    for item in summary["files"]
                ],
                ["signal_2026-07-23.csv", "signal_2026-07-24.csv"],
            )
            self.assertEqual(to_csv.call_count, 2)

    def test_default_mode_uses_largest_single_week_move(self):
        history = pd.DataFrame(
            [
                {
                    "Symbol": "WITHIN",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 94.0,
                    "largest_single_week_move": 7.0,
                    "breakout_date": pd.NaT,
                },
                {
                    "Symbol": "OUTSIDE",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 92.0,
                    "largest_single_week_move": 7.0,
                    "breakout_date": pd.NaT,
                },
            ]
        )

        result = select_just_below_breakout(history)

        self.assertEqual(result["symbol"].tolist(), ["WITHIN"])

    def test_max_weekly_move_can_be_derived_from_stored_ratio(self):
        history = pd.DataFrame(
            [
                {
                    "Symbol": "DERIVED",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 94.0,
                    "left_high": 100.0,
                    "base_low": 70.0,
                    "largest_single_week_move_to_depth_ratio": 0.25,
                    "breakout_date": pd.NaT,
                }
            ]
        )

        result = select_just_below_breakout(history)

        self.assertEqual(result["symbol"].tolist(), ["DERIVED"])

    def test_default_mode_uses_five_percent_minimum_floor(self):
        history = pd.DataFrame(
            [
                {
                    "Symbol": "FLOOR",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 95.5,
                    "largest_single_week_move": 4.0,
                    "breakout_date": pd.NaT,
                }
            ]
        )

        result = select_just_below_breakout(history)

        self.assertEqual(result["symbol"].tolist(), ["FLOOR"])

    def test_above_pivot_buffer_uses_confirmation_level_as_signal_limit(self):
        history = pd.DataFrame(
            [
                {
                    "Symbol": "BUFFER",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 101.0,
                    "confirmation_level": 102.0,
                    "largest_single_week_move": 6.0,
                    "breakout_date": pd.NaT,
                },
                {
                    "Symbol": "ABOVE_LEVEL",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 103.0,
                    "confirmation_level": 102.0,
                    "largest_single_week_move": 6.0,
                    "breakout_date": pd.NaT,
                },
            ]
        )

        result = select_just_below_breakout(history)

        self.assertEqual(
            result.to_dict("records"),
            [{"symbol": "BUFFER", "price_high_limit": 102.0}],
        )

    def test_filters_latest_consideration_rows_below_pivot(self):
        history = pd.DataFrame(
            [
                {
                    "Symbol": "OLD",
                    "tracking_date": "2026-07-23",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 99.0,
                    "breakout_date": pd.NaT,
                },
                {
                    "Symbol": "KEEP.NS",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 97.0,
                    "breakout_date": pd.NaT,
                },
                {
                    "Symbol": "TOO_FAR",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 94.9,
                    "breakout_date": pd.NaT,
                },
                {
                    "Symbol": "BROKEN_OUT",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 99.0,
                    "breakout_date": "2026-07-24",
                },
                {
                    "Symbol": "WRONG_STAGE",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "RECOVERY_BUILDING",
                    "selected_pivot": 100.0,
                    "latest_close": 99.0,
                    "breakout_date": pd.NaT,
                },
            ]
        )

        result = select_just_below_breakout(
            history,
            reference_date="2026-07-24",
            distance_mode="percentage",
        )

        self.assertEqual(result.to_dict("records"), [
            {"symbol": "KEEP", "price_high_limit": 100.0}
        ])

    def test_keeps_closest_structure_per_symbol(self):
        history = pd.DataFrame(
            [
                {
                    "Symbol": "AAA",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 105.0,
                    "distance_from_pivot_pct": -0.04,
                    "breakout_date": pd.NaT,
                },
                {
                    "Symbol": "AAA",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 101.0,
                    "distance_from_pivot_pct": -0.01,
                    "breakout_date": pd.NaT,
                },
            ]
        )

        result = select_just_below_breakout(
            history, distance_mode="percentage"
        )

        self.assertEqual(result.to_dict("records"), [
            {"symbol": "AAA", "price_high_limit": 101.0}
        ])

    def test_output_columns_are_stable_when_no_rows_match(self):
        history = pd.DataFrame(
            [
                {
                    "Symbol": "AAA",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "RECOVERY_BUILDING",
                    "selected_pivot": 100.0,
                }
            ]
        )

        result = select_just_below_breakout(history)

        self.assertTrue(result.empty)
        self.assertEqual(
            list(result.columns), ["symbol", "price_high_limit"]
        )

    def test_atr_mode_uses_configured_atr_multiple(self):
        history = pd.DataFrame(
            [
                {
                    "Symbol": "WITHIN",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 98.0,
                    "setup_atr": 5.0,
                    "breakout_date": pd.NaT,
                },
                {
                    "Symbol": "OUTSIDE",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 97.0,
                    "setup_atr": 5.0,
                    "breakout_date": pd.NaT,
                },
            ]
        )

        result = select_just_below_breakout(
            history,
            distance_mode="atr",
            atr_multiple=0.5,
        )

        self.assertEqual(result["symbol"].tolist(), ["WITHIN"])

    def test_hybrid_mode_uses_smaller_limit(self):
        history = pd.DataFrame(
            [
                {
                    "Symbol": "ATR_LIMITED",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 97.0,
                    "setup_atr": 4.0,
                    "breakout_date": pd.NaT,
                },
                {
                    "Symbol": "PCT_LIMITED",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 94.0,
                    "setup_atr": 20.0,
                    "breakout_date": pd.NaT,
                },
                {
                    "Symbol": "KEEP",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 98.5,
                    "setup_atr": 4.0,
                    "breakout_date": pd.NaT,
                },
            ]
        )

        result = select_just_below_breakout(
            history,
            distance_mode="hybrid",
            max_distance_pct=5.0,
            atr_multiple=0.5,
        )

        self.assertEqual(result["symbol"].tolist(), ["KEEP"])

    def test_hybrid_falls_back_to_percentage_when_atr_is_missing(self):
        history = pd.DataFrame(
            [
                {
                    "Symbol": "AAA",
                    "tracking_date": "2026-07-24",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "selected_pivot": 100.0,
                    "latest_close": 97.0,
                    "breakout_date": pd.NaT,
                }
            ]
        )

        result = select_just_below_breakout(
            history,
            distance_mode="hybrid",
            max_distance_pct=5.0,
            atr_multiple=0.5,
        )

        self.assertEqual(result["symbol"].tolist(), ["AAA"])


if __name__ == "__main__":
    unittest.main()
