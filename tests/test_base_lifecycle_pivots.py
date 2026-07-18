import os
import sys
import types
import unittest

import pandas as pd


# The lifecycle calculations use local parquet data only; DataEngine imports
# yfinance for its optional download path, which is not needed in these tests.
sys.modules.setdefault("yfinance", types.SimpleNamespace())
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMLIT_DIR = os.path.join(PROJECT_ROOT, "Streamlit")
if STREAMLIT_DIR not in sys.path:
    sys.path.insert(0, STREAMLIT_DIR)

from base_lifecycle_scanner import DEFAULT_PARAMS, calculate_pivot_lifecycle, update_tracking_row


def weekly_frame(highs, lows, closes, atr=1.0):
    index = pd.date_range("2025-01-05", periods=len(closes), freq="W")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": [1_000] * len(closes),
            "volume_ma_10": [1_000] * len(closes),
            "atr": [atr] * len(closes),
        },
        index=index,
    )


class PivotLifecycleTests(unittest.TestCase):
    def test_confirmation_crosses_buffer_not_raw_pivot(self):
        frame = weekly_frame(
            highs=[100, 80, 98, 101],
            lows=[90, 70, 88, 98],
            closes=[95, 72, 95, 100.3],
        )
        result = calculate_pivot_lifecycle(
            frame, 100, frame.index[0], 1, DEFAULT_PARAMS, tracking_eligible=True
        )

        self.assertEqual(result["major_pivot"], 100)
        self.assertEqual(result["major_confirmation_level"], 100.5)
        self.assertTrue(pd.isna(result["breakout_date"]))
        self.assertEqual(result["lifecycle_status"], "BREAKOUT_ATTEMPT")

    def test_major_pivot_freezes_before_breakout_and_ignores_later_highs(self):
        frame = weekly_frame(
            highs=[100, 80, 98, 102, 130, 140],
            lows=[90, 70, 88, 97, 100, 110],
            closes=[95, 72, 95, 101, 120, 125],
        )
        result = calculate_pivot_lifecycle(
            frame, 100, frame.index[0], 1, DEFAULT_PARAMS, tracking_eligible=True
        )

        self.assertEqual(result["major_pivot"], 100)
        self.assertEqual(result["range_high_pivot"], 98)
        self.assertEqual(result["breakout_date"], frame.index[3])
        self.assertLessEqual(result["range_high_pivot"], 105)

    def test_distinct_handle_can_confirm_before_major_pivot(self):
        frame = weekly_frame(
            highs=[100, 80, 90, 94, 92, 97],
            lows=[90, 70, 85, 86, 87, 92],
            closes=[95, 72, 88, 90, 90, 96],
        )
        result = calculate_pivot_lifecycle(
            frame, 100, frame.index[0], 1, DEFAULT_PARAMS, tracking_eligible=True
        )

        self.assertTrue(pd.isna(result["breakout_date"]))
        self.assertEqual(result["handle_pivot"], 94)
        self.assertEqual(result["handle_breakout_date"], frame.index[5])
        self.assertEqual(result["lifecycle_status"], "HANDLE_BREAKOUT_CONFIRMED")

    def test_one_small_undercut_is_not_a_failed_breakout(self):
        frame = weekly_frame(
            highs=[100, 80, 98, 102, 101],
            lows=[90, 70, 88, 97, 98],
            closes=[95, 72, 95, 101, 99.5],
        )
        result = calculate_pivot_lifecycle(
            frame, 100, frame.index[0], 1, DEFAULT_PARAMS, tracking_eligible=True
        )

        self.assertFalse(result["hard_failure"])
        self.assertFalse(result["persistent_failure"])
        self.assertEqual(result["lifecycle_status"], "PIVOT_RETEST_WEAK")

    def test_two_closes_below_pivot_fail_the_breakout(self):
        frame = weekly_frame(
            highs=[100, 80, 98, 102, 101, 100],
            lows=[90, 70, 88, 97, 98, 98],
            closes=[95, 72, 95, 101, 99.5, 99.4],
        )
        result = calculate_pivot_lifecycle(
            frame, 100, frame.index[0], 1, DEFAULT_PARAMS, tracking_eligible=True
        )

        self.assertFalse(result["hard_failure"])
        self.assertTrue(result["persistent_failure"])
        self.assertEqual(result["lifecycle_status"], "FAILED")

    def test_one_close_below_failure_buffer_is_a_hard_failure(self):
        frame = weekly_frame(
            highs=[100, 80, 98, 102, 100],
            lows=[90, 70, 88, 97, 96],
            closes=[95, 72, 95, 101, 98.8],
        )
        result = calculate_pivot_lifecycle(
            frame, 100, frame.index[0], 1, DEFAULT_PARAMS, tracking_eligible=True
        )

        self.assertTrue(result["hard_failure"])
        self.assertEqual(result["lifecycle_status"], "FAILED")

    def test_tracking_reuses_same_major_pivot_lifecycle(self):
        frame = weekly_frame(
            highs=[100, 80, 98, 102, 110, 112],
            lows=[90, 70, 88, 97, 101, 105],
            closes=[95, 72, 95, 101, 108, 110],
        ).drop(columns=["volume_ma_10", "atr"])

        class FakeDataEngine:
            def get_symbol(self, symbol):
                return frame

        row = {
            "Symbol": "TEST",
            "left_high": 100,
            "left_high_index": frame.index[0],
            "base_low": 70,
            "base_low_index": frame.index[1],
            "pivot_price": 100,
            "pivot_index": frame.index[0],
        }
        result = update_tracking_row(row, frame.index[-1], FakeDataEngine())

        self.assertEqual(result["major_pivot"], 100)
        self.assertEqual(result["active_pivot_price"], 100)
        self.assertEqual(result["lifecycle_status"], "BREAKOUT_CONFIRMED")
        self.assertEqual(result["tracking_state"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
