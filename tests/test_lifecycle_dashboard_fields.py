import os
import sys
import unittest

import pandas as pd


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMLIT_DIR = os.path.join(PROJECT_ROOT, "Streamlit")
if STREAMLIT_DIR not in sys.path:
    sys.path.insert(0, STREAMLIT_DIR)

from lifecycle_dashboard_fields import derive_lifecycle_today_status


class LifecycleDashboardFieldTests(unittest.TestCase):
    def setUp(self):
        self.history = pd.DataFrame(
            [
                {
                    "base_id": "ABC|104W|20240101|20240301",
                    "Symbol": "ABC",
                    "base_window_weeks": 104,
                    "tracking_date": "2026-07-20",
                    "first_detected_date": "2026-07-20",
                    "journey_stage": "RECOVERY_BUILDING",
                },
                {
                    "base_id": "ABC|104W|20240101|20240301",
                    "Symbol": "ABC",
                    "base_window_weeks": 104,
                    "tracking_date": "2026-07-21",
                    "first_detected_date": "2026-07-20",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                },
                {
                    "base_id": "XYZ|52W|20250101|20250301",
                    "Symbol": "XYZ",
                    "base_window_weeks": 52,
                    "tracking_date": "2026-07-21",
                    "first_detected_date": "2026-07-21",
                    "journey_stage": "RECOVERY_BUILDING",
                },
            ]
        )

    def test_latest_rows_distinguish_new_base_and_new_stage(self):
        latest = self.history[self.history["tracking_date"] == "2026-07-21"].copy()
        result = derive_lifecycle_today_status(
            latest, self.history, reference_date="2026-07-21"
        ).set_index("Symbol")

        self.assertEqual(result.loc["ABC", "today_status"], "NEW TO STAGE")
        self.assertEqual(
            result.loc["ABC", "previous_journey_stage"], "RECOVERY_BUILDING"
        )
        self.assertEqual(result.loc["XYZ", "today_status"], "NEW BASE")

    def test_history_rows_are_classified_on_their_own_date(self):
        result = derive_lifecycle_today_status(
            self.history,
            self.history,
            row_date_column="tracking_date",
        )
        abc = result[result["Symbol"] == "ABC"].sort_values("tracking_date")

        self.assertEqual(abc.iloc[0]["today_status"], "NEW BASE")
        self.assertEqual(abc.iloc[1]["today_status"], "NEW TO STAGE")


if __name__ == "__main__":
    unittest.main()
