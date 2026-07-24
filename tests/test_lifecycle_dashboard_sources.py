import os
import sys
import unittest

import pandas as pd


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMLIT_DIR = os.path.join(PROJECT_ROOT, "Streamlit")
if STREAMLIT_DIR not in sys.path:
    sys.path.insert(0, STREAMLIT_DIR)

from base_lifecycle_pages import (
    build_failure_review_rows,
    preferred_lifecycle_tracking_source,
    tracking_state_from_history,
)


class LifecycleDashboardSourceTests(unittest.TestCase):
    def test_checkpoint_production_is_selected_without_a_ui_control(self):
        legacy = {"kind": "production"}
        checkpoint = {"kind": "shadow", "history_path": "checkpoint.parquet"}
        sources = {
            "Production tracking": legacy,
            "Incremental Shadow": {"kind": "shadow"},
            "Checkpoint Production": checkpoint,
        }

        self.assertIs(
            preferred_lifecycle_tracking_source(sources),
            checkpoint,
        )

    def test_legacy_tracking_is_fallback_when_checkpoint_is_unavailable(self):
        legacy = {"kind": "production"}

        self.assertIs(
            preferred_lifecycle_tracking_source(
                {"Production tracking": legacy}
            ),
            legacy,
        )

    def test_shadow_history_derives_latest_active_and_archived_rows(self):
        history = pd.DataFrame(
            [
                {
                    "base_id": "AAA",
                    "tracking_date": "2026-07-21",
                    "tracking_state": "ACTIVE",
                },
                {
                    "base_id": "AAA",
                    "tracking_date": "2026-07-22",
                    "tracking_state": "ARCHIVED",
                },
                {
                    "base_id": "BBB",
                    "tracking_date": "2026-07-21",
                    "tracking_state": "ACTIVE",
                },
                {
                    "base_id": "BBB",
                    "tracking_date": "2026-07-23",
                    "tracking_state": "ACTIVE",
                },
            ]
        )

        state = tracking_state_from_history(history)

        self.assertEqual(set(state["active"]["base_id"]), {"BBB"})
        self.assertEqual(set(state["archived"]["base_id"]), {"AAA"})
        self.assertEqual(len(state["history"]), 4)
        self.assertEqual(
            state["archived"].iloc[0]["archived_date"],
            pd.Timestamp("2026-07-22"),
        )

    def test_failure_review_separates_success_failure_and_pullback(self):
        history = pd.DataFrame(
            [
                {
                    "base_id": "PULLBACK",
                    "journey_stage": "BREAKOUT_CONSIDERATION",
                    "tracking_date": "2026-07-21",
                },
                {
                    "base_id": "PULLBACK",
                    "journey_stage": "RECOVERY_BUILDING",
                    "tracking_date": "2026-07-22",
                },
            ]
        )
        state = {
            "history": history,
            "active": history.tail(1).copy(),
            "archived": pd.DataFrame(
                [
                    {
                        "base_id": "BEFORE_SUCCESS",
                        "journey_stage": "FAILED",
                        "breakout_date": "2026-07-10",
                        "breakout_success": False,
                        "breakout_success_date": pd.NaT,
                    },
                    {
                        "base_id": "AFTER_SUCCESS",
                        "journey_stage": "FAILED",
                        "breakout_date": "2026-07-10",
                        "breakout_success": True,
                        "breakout_success_date": "2026-07-12",
                    },
                ]
            ),
        }

        review = build_failure_review_rows(state)

        self.assertEqual(
            set(review["failure_category"]),
            {
                "FAILED_AFTER_BREAKOUT",
                "FAILED_AFTER_SUCCESS",
                "CONSIDERATION_PULLBACK",
            },
        )


if __name__ == "__main__":
    unittest.main()
