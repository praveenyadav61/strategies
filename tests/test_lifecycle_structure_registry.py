import os
import sys
import unittest

import pandas as pd


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMLIT_DIR = os.path.join(PROJECT_ROOT, "Streamlit")
if STREAMLIT_DIR not in sys.path:
    sys.path.insert(0, STREAMLIT_DIR)

from base_lifecycle_scanner import DEFAULT_PARAMS
from lifecycle_structure_registry import (
    structures_from_tracking_history,
    upsert_discovered_structures,
)


def structure(base_id, left_date, low_date, left=100.0, low=70.0):
    return {
        "base_id": base_id,
        "Symbol": "AAA",
        "base_window_weeks": 104,
        "scan_window_weeks": 104,
        "left_high": left,
        "left_high_index": pd.Timestamp(left_date),
        "base_low": low,
        "base_low_index": pd.Timestamp(low_date),
        "Depth": (left - low) / left,
    }


class LifecycleStructureRegistryTests(unittest.TestCase):
    def test_history_becomes_one_structure_per_base(self):
        rows = []
        for tracking_date in ["2026-07-22", "2026-07-23"]:
            rows.append(
                {
                    **structure(
                        "AAA|104W|20250103|20260403",
                        "2025-01-03",
                        "2026-04-03",
                    ),
                    "tracking_date": tracking_date,
                    "first_detected_date": "2026-07-10",
                }
            )
        registry = structures_from_tracking_history(
            pd.DataFrame(rows), DEFAULT_PARAMS
        )

        self.assertEqual(len(registry), 1)
        self.assertEqual(registry.iloc[0]["structure_state"], "REGISTERED")
        self.assertEqual(
            registry.iloc[0]["last_structure_seen_date"],
            pd.Timestamp("2026-07-23"),
        )

    def test_exact_and_equivalent_discoveries_do_not_duplicate_registry(self):
        original = pd.DataFrame(
            [
                {
                    **structure(
                        "AAA|104W|20250103|20260403",
                        "2025-01-03",
                        "2026-04-03",
                    ),
                    "tracking_date": "2026-07-23",
                }
            ]
        )
        registry = structures_from_tracking_history(original, DEFAULT_PARAMS)
        discoveries = pd.DataFrame(
            [
                structure(
                    "AAA|104W|20250103|20260403",
                    "2025-01-03",
                    "2026-04-03",
                ),
                structure(
                    "AAA|52W|20250110|20260403",
                    "2025-01-10",
                    "2026-04-03",
                    left=99.0,
                ),
            ]
        )

        updated, events = upsert_discovered_structures(
            registry, discoveries, "2026-07-24", DEFAULT_PARAMS
        )

        self.assertEqual(len(updated), 1)
        self.assertTrue(events.empty)

    def test_distinct_discovery_is_registered(self):
        original = pd.DataFrame(
            [
                {
                    **structure(
                        "AAA|104W|20250103|20260403",
                        "2025-01-03",
                        "2026-04-03",
                    ),
                    "tracking_date": "2026-07-23",
                }
            ]
        )
        registry = structures_from_tracking_history(original, DEFAULT_PARAMS)
        discoveries = pd.DataFrame(
            [
                structure(
                    "AAA|52W|20250801|20260501",
                    "2025-08-01",
                    "2026-05-01",
                    left=120,
                    low=90,
                )
            ]
        )

        updated, events = upsert_discovered_structures(
            registry, discoveries, "2026-07-24", DEFAULT_PARAMS
        )

        self.assertEqual(len(updated), 2)
        self.assertEqual(len(events), 1)
        self.assertEqual(events.iloc[0]["event_type"], "STRUCTURE_DISCOVERED")


if __name__ == "__main__":
    unittest.main()
