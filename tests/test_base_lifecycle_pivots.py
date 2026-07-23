import os
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd


sys.modules.setdefault("yfinance", types.SimpleNamespace())
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMLIT_DIR = os.path.join(PROJECT_ROOT, "Streamlit")
if STREAMLIT_DIR not in sys.path:
    sys.path.insert(0, STREAMLIT_DIR)

from base_lifecycle_scanner import (
    BaseLifecycleScanner,
    DEFAULT_PARAMS,
    build_base_id,
    build_replay_dates,
    calculate_single_week_move_metrics,
    calculate_pivot_lifecycle,
    calculate_pivot_zone,
    calculate_daily_handle_state,
    consolidate_tracking_structures,
    determine_journey_stage,
    latest_completed_week_end,
    ordered_base_windows,
    prepare_new_tracking_rows,
    resolve_base_end,
    resample_completed_weekly,
    update_tracking_row,
)
from base_structure_identity import bases_are_equivalent, consolidate_equivalent_bases


def weekly_frame(highs, lows, closes, atr=1.0):
    index = pd.date_range("2025-01-03", periods=len(closes), freq="W-FRI")
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


def lifecycle(frame, depth=0.30, tracking=True):
    return calculate_pivot_lifecycle(
        frame,
        left_high=100,
        left_high_date=frame.index[0],
        bottom_idx_i=1,
        base_depth=depth,
        params=DEFAULT_PARAMS,
        tracking_eligible=tracking,
    )


def daily_handle_frame():
    index = pd.date_range("2026-01-02", periods=18, freq="B")
    highs = [101, 96, 90, 85, 80, 72, 76, 80, 84, 88, 92, 96, 95, 95, 95, 95, 95, 98.5]
    lows = [98, 92, 86, 81, 76, 70, 72, 76, 80, 84, 88, 94, 93, 92, 93, 93.5, 94, 96]
    closes = [100, 94, 88, 83, 78, 71, 75, 79, 83, 87, 91, 95, 94, 93, 94, 94, 94.5, 97.5]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": 1_000,
        },
        index=index,
    )


class JourneyStageTests(unittest.TestCase):
    def test_recovery_thresholds(self):
        self.assertEqual(determine_journey_stage(0.39), "NOT_TRACKED")
        self.assertEqual(determine_journey_stage(0.40), "RECOVERY_BUILDING")
        self.assertEqual(determine_journey_stage(0.849), "RECOVERY_BUILDING")
        self.assertEqual(determine_journey_stage(0.85), "BREAKOUT_CONSIDERATION")

    def test_confirmed_breakout_does_not_fall_back_with_recovery(self):
        self.assertEqual(
            determine_journey_stage(0.78, breakout_confirmed=True),
            "BREAKOUT_CONSIDERATION",
        )

    def test_success_and_failure_are_latched_with_failure_priority(self):
        self.assertEqual(
            determine_journey_stage(0.70, breakout_success=True),
            "SUCCESSFUL_BREAKOUT",
        )
        self.assertEqual(
            determine_journey_stage(1.10, breakout_success=True, failed=True),
            "FAILED",
        )


class BaseDiscoveryTests(unittest.TestCase):
    def test_peak_to_low_default_is_six_weeks(self):
        self.assertEqual(DEFAULT_PARAMS["MIN_PEAK_TO_LOW_WEEKS"], 6)

    def test_base_id_is_unique_per_window(self):
        common = {
            "Symbol": "TEST.NS",
            "left_high_index": "2026-01-02",
            "base_low_index": "2026-03-06",
        }
        id_104 = build_base_id({**common, "base_window_weeks": 104})
        id_52 = build_base_id({**common, "base_window_weeks": 52})

        self.assertNotEqual(id_104, id_52)
        self.assertIn("|104W|", id_104)
        self.assertIn("|52W|", id_52)

    def test_same_symbol_can_enter_tracking_for_multiple_windows(self):
        results = pd.DataFrame(
            [
                {
                    "Symbol": "TEST",
                    "scan_window_weeks": 104,
                    "base_window_weeks": 104,
                    "left_high_index": pd.Timestamp("2026-01-02"),
                    "base_low_index": pd.Timestamp("2026-03-06"),
                    "recovery_pct": 0.60,
                },
                {
                    "Symbol": "TEST",
                    "scan_window_weeks": 52,
                    "base_window_weeks": 52,
                    "left_high_index": pd.Timestamp("2026-02-06"),
                    "base_low_index": pd.Timestamp("2026-04-03"),
                    "recovery_pct": 0.70,
                },
            ]
        )
        new_rows = prepare_new_tracking_rows(
            results,
            "2026-07-17",
            active_df=pd.DataFrame(),
            archived_df=pd.DataFrame(),
        )

        self.assertEqual(len(new_rows), 2)
        self.assertEqual(set(new_rows["base_window_weeks"]), {104, 52})
        self.assertEqual(new_rows["base_id"].nunique(), 2)

    def test_same_structure_is_kept_only_in_largest_window(self):
        common = {
            "Symbol": "TEST",
            "left_high_index": pd.Timestamp("2025-07-04"),
            "base_low_index": pd.Timestamp("2026-03-27"),
            "left_high": 1765.95,
            "base_low": 866.40,
            "journey_stage": "BREAKOUT_CONSIDERATION",
        }
        results = consolidate_equivalent_bases(
            [
                {**common, "base_window_weeks": 104},
                {**common, "base_window_weeks": 52},
            ]
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["base_window_weeks"], 104)
        self.assertEqual(results[0]["equivalent_base_windows"], "104,52")

    def test_nearby_left_highs_with_same_bottom_are_equivalent(self):
        first = {
            "Symbol": "TEST",
            "left_high_index": "2025-07-04",
            "base_low_index": "2026-03-27",
            "left_high": 1765.95,
            "base_low": 866.40,
        }
        second = {
            **first,
            "left_high_index": "2025-07-11",
            "left_high": 1705.19,
        }
        self.assertTrue(bases_are_equivalent(first, second))

    def test_existing_tracking_duplicates_are_consolidated(self):
        common = {
            "Symbol": "DEEPAKFERT",
            "left_high_index": "2025-07-04",
            "base_low_index": "2026-03-27",
            "left_high": 1765.95,
            "base_low": 866.40,
            "journey_stage": "BREAKOUT_CONSIDERATION",
        }
        active = pd.DataFrame(
            [
                {**common, "base_window_weeks": 104, "base_id": "base-104"},
                {**common, "base_window_weeks": 52, "base_id": "base-52"},
            ]
        )

        result = consolidate_tracking_structures(active)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["base_id"], "base-104")
        self.assertEqual(result.iloc[0]["equivalent_base_windows"], "104,52")

    def test_scanner_keeps_every_valid_window(self):
        index = pd.date_range("2021-01-01", periods=900, freq="B")
        close = pd.Series(range(100, 1000), index=index, dtype="float64")
        daily = pd.DataFrame(
            {
                "Open": close,
                "High": close + 1,
                "Low": close - 1,
                "Close": close,
                "Volume": 1_000,
            },
            index=index,
        )

        class FakeDataEngine:
            def get_symbol(self, symbol):
                return daily

        scanner = BaseLifecycleScanner(data_path="unused")
        scanner.data_engine = FakeDataEngine()

        def valid_window(_weekly, _params, symbol, *_args, **kwargs):
            window = int(_args[3])
            return {
                "Symbol": symbol,
                "scan_window_weeks": window,
                "base_window_weeks": window,
                "journey_stage": "RECOVERY_BUILDING",
            }

        with patch(
            "base_lifecycle_scanner.check_lifecycle_conditions",
            side_effect=valid_window,
        ):
            result = scanner.scan_symbol("TEST.NS")

        self.assertIsNotNone(result)
        _largest, all_windows = result
        self.assertEqual(
            [row["base_window_weeks"] for row in all_windows],
            [104, 52, 26],
        )

    def test_single_week_move_uses_true_range_relative_to_base_depth(self):
        frame = weekly_frame(
            highs=[102, 98, 96, 88],
            lows=[98, 75, 78, 82],
            closes=[100, 80, 84, 86],
        )
        metrics = calculate_single_week_move_metrics(frame, base_depth_price=30)

        self.assertEqual(metrics["largest_single_week_move"], 25)
        self.assertEqual(metrics["largest_single_week_move_date"], frame.index[1])
        self.assertAlmostEqual(
            metrics["largest_single_week_move_to_depth_ratio"],
            25 / 30,
        )

    def test_breakout_week_can_be_excluded_from_single_week_filter(self):
        frame = weekly_frame(
            highs=[100, 98, 140],
            lows=[94, 90, 100],
            closes=[96, 94, 135],
        )
        metrics = calculate_single_week_move_metrics(
            frame,
            base_depth_price=20,
            excluded_end_date=frame.index[-1],
        )

        self.assertEqual(metrics["largest_single_week_move"], 8)
        self.assertAlmostEqual(
            metrics["largest_single_week_move_to_depth_ratio"],
            0.40,
        )

    def test_base_width_prefers_distinct_handle_pivot(self):
        end_date, reason = resolve_base_end(
            "2026-01-02",
            {
                "pivot_source": "HANDLE",
                "selected_pivot_date": "2026-04-03",
                "breakout_date": "2026-04-17",
            },
            "2026-05-01",
        )
        self.assertEqual(end_date, pd.Timestamp("2026-04-03"))
        self.assertEqual(reason, "HANDLE_PIVOT")

    def test_base_width_ignores_fallback_left_high_pivot(self):
        end_date, reason = resolve_base_end(
            "2026-01-02",
            {
                "pivot_source": "LEFT_HIGH",
                "selected_pivot_date": "2026-01-02",
                "breakout_date": pd.NaT,
            },
            "2026-04-03",
        )
        self.assertEqual(end_date, pd.Timestamp("2026-04-03"))
        self.assertEqual(reason, "CURRENT_STRUCTURE")

    def test_base_width_uses_breakout_without_distinct_handle(self):
        end_date, reason = resolve_base_end(
            "2026-01-02",
            {
                "pivot_source": "LEFT_HIGH",
                "selected_pivot_date": "2026-01-02",
                "breakout_date": "2026-04-10",
            },
            "2026-05-01",
        )
        self.assertEqual(end_date, pd.Timestamp("2026-04-10"))
        self.assertEqual(reason, "BREAKOUT")

    def test_daily_replay_skips_weekends(self):
        replay_dates = build_replay_dates("2026-07-13", "2026-07-19", "daily")
        self.assertEqual(
            list(replay_dates),
            list(pd.date_range("2026-07-13", "2026-07-17", freq="D")),
        )

    def test_structure_refresh_uses_friday_boundary(self):
        self.assertEqual(
            latest_completed_week_end("2026-07-13"),
            pd.Timestamp("2026-07-10"),
        )
        self.assertEqual(
            latest_completed_week_end("2026-07-17"),
            pd.Timestamp("2026-07-17"),
        )

    def test_windows_are_always_largest_first(self):
        self.assertEqual(
            ordered_base_windows({"BASE_WINDOWS": [26, 104, 52, 104]}),
            [104, 52, 26],
        )

    def test_incomplete_week_is_excluded(self):
        index = pd.date_range("2025-01-06", periods=8, freq="B")
        daily = pd.DataFrame(
            {
                "Open": range(8),
                "High": range(1, 9),
                "Low": range(8),
                "Close": range(1, 9),
                "Volume": [100] * 8,
            },
            index=index,
        )
        weekly = resample_completed_weekly(daily, as_of_date=index[-1])

        self.assertEqual(list(weekly.index), [pd.Timestamp("2025-01-10")])
        self.assertEqual(float(weekly.iloc[0]["Close"]), 5)


class PivotLifecycleTests(unittest.TestCase):
    def test_pivot_zone_is_relative_to_deep_base_depth(self):
        zone = calculate_pivot_zone(
            left_high=100,
            base_depth=0.40,
            params=DEFAULT_PARAMS,
        )

        self.assertEqual(zone["implied_base_low"], 60)
        self.assertEqual(zone["pivot_min_price"], 94)
        self.assertEqual(zone["pivot_max_price"], 104)

    def test_pivot_zone_scales_with_shallow_base_depth(self):
        zone = calculate_pivot_zone(
            left_high=100,
            base_depth=0.20,
            params=DEFAULT_PARAMS,
        )

        self.assertEqual(zone["implied_base_low"], 80)
        self.assertEqual(zone["pivot_min_price"], 97)
        self.assertEqual(zone["pivot_max_price"], 102)

    def test_left_high_remains_active_until_five_daily_sessions(self):
        frame = daily_handle_frame()
        result = calculate_daily_handle_state(
            frame.iloc[:16],
            left_high=100,
            left_high_date=frame.index[0],
            base_low=70,
            base_low_date=frame.index[5],
            base_depth=0.30,
            params=DEFAULT_PARAMS,
        )

        self.assertEqual(result["daily_handle_state"], "HANDLE_CANDIDATE")
        self.assertEqual(result["daily_handle_sessions_after_pivot"], 4)
        self.assertEqual(result["selected_pivot"], 100)
        self.assertEqual(result["pivot_source"], "LEFT_HIGH")

    def test_daily_handle_high_replaces_left_high_after_five_sessions(self):
        frame = daily_handle_frame()
        result = calculate_daily_handle_state(
            frame.iloc[:17],
            left_high=100,
            left_high_date=frame.index[0],
            base_low=70,
            base_low_date=frame.index[5],
            base_depth=0.30,
            params=DEFAULT_PARAMS,
        )

        self.assertEqual(result["daily_handle_state"], "HANDLE_READY")
        self.assertEqual(result["selected_pivot"], 96)
        self.assertEqual(result["selected_pivot_date"], frame.index[11])
        self.assertEqual(result["pivot_source"], "DAILY_HANDLE")
        self.assertTrue(result["daily_handle_valid"])

    def test_daily_close_breakout_freezes_the_ready_handle_high(self):
        frame = daily_handle_frame()
        result = calculate_daily_handle_state(
            frame,
            left_high=100,
            left_high_date=frame.index[0],
            base_low=70,
            base_low_date=frame.index[5],
            base_depth=0.30,
            params=DEFAULT_PARAMS,
        )

        self.assertEqual(result["daily_breakout_date"], frame.index[-1])
        self.assertEqual(result["selected_pivot"], 96)
        self.assertEqual(result["selected_pivot_date"], frame.index[11])

    def test_higher_daily_high_restarts_handle_confirmation(self):
        frame = daily_handle_frame().iloc[:15].copy()
        frame.loc[frame.index[-1], ["High", "Low", "Close"]] = [97, 94, 95]
        result = calculate_daily_handle_state(
            frame,
            left_high=100,
            left_high_date=frame.index[0],
            base_low=70,
            base_low_date=frame.index[5],
            base_depth=0.30,
            params=DEFAULT_PARAMS,
        )

        self.assertEqual(result["daily_handle_candidate_pivot"], 97)
        self.assertEqual(result["daily_handle_candidate_date"], frame.index[-1])
        self.assertEqual(result["daily_handle_sessions_after_pivot"], 0)
        self.assertEqual(result["selected_pivot"], 100)

    def test_replacement_candidate_keeps_confirmed_handle_breakout_eligible(self):
        index = pd.date_range("2026-03-30", periods=9, freq="B")
        closes = [71, 95, 94, 94, 94, 94, 94, 96, 101]
        frame = pd.DataFrame(
            {
                "Open": closes,
                "High": [72, 96, 95, 95, 95, 95, 95, 98, 102],
                "Low": [70, 94, 93, 93, 93, 93, 93, 94, 96],
                "Close": closes,
                "Volume": 1_000,
            },
            index=index,
        )

        result = calculate_daily_handle_state(
            frame,
            left_high=100,
            left_high_date=index[0] - pd.Timedelta(days=30),
            base_low=70,
            base_low_date=index[0],
            base_depth=0.30,
            params=DEFAULT_PARAMS,
        )

        self.assertEqual(result["daily_breakout_date"], index[-1])
        self.assertEqual(result["selected_pivot"], 96)
        self.assertEqual(result["pivot_source"], "DAILY_HANDLE")
        self.assertEqual(result["daily_handle_state"], "BREAKOUT_CONFIRMED")

    def test_replacement_candidate_does_not_replace_active_handle_early(self):
        frame = daily_handle_frame().iloc[:18].copy()
        frame.loc[frame.index[-1], ["High", "Low", "Close"]] = [97, 94, 95]

        result = calculate_daily_handle_state(
            frame,
            left_high=100,
            left_high_date=frame.index[0],
            base_low=70,
            base_low_date=frame.index[5],
            base_depth=0.30,
            params=DEFAULT_PARAMS,
        )

        self.assertEqual(result["daily_handle_state"], "HANDLE_REPLACEMENT_PENDING")
        self.assertEqual(result["selected_pivot"], 96)
        self.assertEqual(result["pivot_source"], "DAILY_HANDLE")
        self.assertTrue(result["daily_handle_breakout_eligible"])

    def test_failed_replacement_candidate_keeps_confirmed_handle(self):
        frame = daily_handle_frame().iloc[:17].copy()
        extra_dates = pd.date_range(frame.index[-1] + pd.offsets.BDay(), periods=2, freq="B")
        extra = pd.DataFrame(
            {
                "Open": [95, 95],
                "High": [97, 104],
                "Low": [94, 94],
                "Close": [95, 95],
                "Volume": [1_000, 1_000],
            },
            index=extra_dates,
        )
        frame = pd.concat([frame, extra])

        result = calculate_daily_handle_state(
            frame,
            left_high=100,
            left_high_date=frame.index[0],
            base_low=70,
            base_low_date=frame.index[5],
            base_depth=0.30,
            params=DEFAULT_PARAMS,
        )

        self.assertEqual(result["daily_handle_state"], "HANDLE_READY")
        self.assertEqual(result["selected_pivot"], 96)
        self.assertEqual(result["pivot_source"], "DAILY_HANDLE")

    def test_active_handle_invalidation_returns_to_left_high(self):
        frame = daily_handle_frame().iloc[:17].copy()
        invalidation_date = frame.index[-1] + pd.offsets.BDay()
        frame.loc[invalidation_date, ["Open", "High", "Low", "Close", "Volume"]] = [
            88,
            90,
            80,
            85,
            1_000,
        ]

        result = calculate_daily_handle_state(
            frame,
            left_high=100,
            left_high_date=frame.index[0],
            base_low=70,
            base_low_date=frame.index[5],
            base_depth=0.30,
            params=DEFAULT_PARAMS,
        )

        self.assertEqual(result["daily_handle_state"], "LEFT_HIGH_ACTIVE")
        self.assertEqual(result["selected_pivot"], 100)
        self.assertEqual(result["pivot_source"], "LEFT_HIGH")
        self.assertTrue(result["daily_handle_invalidated"])

    def test_daily_gap_crosses_the_one_active_left_high_pivot(self):
        index = pd.date_range("2026-06-01", periods=3, freq="B")
        frame = pd.DataFrame(
            {
                "Open": [72, 96, 105],
                "High": [74, 99, 110],
                "Low": [70, 94, 104],
                "Close": [72, 98, 108],
                "Volume": [1_000, 1_000, 1_000],
            },
            index=index,
        )

        result = calculate_daily_handle_state(
            frame,
            left_high=100,
            left_high_date=index[0] - pd.Timedelta(days=30),
            base_low=70,
            base_low_date=index[0],
            base_depth=0.30,
            params=DEFAULT_PARAMS,
        )

        self.assertEqual(result["daily_breakout_date"], index[-1])
        self.assertEqual(result["selected_pivot"], 100)
        self.assertEqual(result["pivot_source"], "LEFT_HIGH")

    def test_every_daily_state_has_exactly_one_active_pivot(self):
        frame = daily_handle_frame()
        for end in range(2, len(frame) + 1):
            result = calculate_daily_handle_state(
                frame.iloc[:end],
                left_high=100,
                left_high_date=frame.index[0],
                base_low=70,
                base_low_date=frame.index[5],
                base_depth=0.30,
                params=DEFAULT_PARAMS,
            )
            self.assertGreater(float(result["selected_pivot"]), 0)
            self.assertIn(result["pivot_source"], {"LEFT_HIGH", "DAILY_HANDLE"})

    def test_excessive_daily_handle_pullback_restores_left_high(self):
        frame = daily_handle_frame().iloc[:14].copy()
        frame.loc[frame.index[-1], ["High", "Low", "Close"]] = [94, 85, 87]
        result = calculate_daily_handle_state(
            frame,
            left_high=100,
            left_high_date=frame.index[0],
            base_low=70,
            base_low_date=frame.index[5],
            base_depth=0.30,
            params=DEFAULT_PARAMS,
        )

        self.assertEqual(result["daily_handle_state"], "LEFT_HIGH_ACTIVE")
        self.assertEqual(result["selected_pivot"], 100)
        self.assertEqual(result["pivot_source"], "LEFT_HIGH")

    def test_breakout_on_first_week_after_bottom_is_detected(self):
        frame = weekly_frame(
            highs=[100, 80, 108, 125],
            lows=[90, 70, 98, 108],
            closes=[95, 72, 105, 120],
        )
        result = lifecycle(frame)

        self.assertEqual(result["pivot_source"], "LEFT_HIGH")
        self.assertEqual(result["breakout_date"], frame.index[2])
        self.assertTrue(result["breakout_success"])
        self.assertEqual(result["breakout_success_date"], frame.index[3])
        self.assertEqual(result["lifecycle_phase"], "BREAKOUT_SUCCESS")

    def test_confirmation_crosses_buffer_not_raw_pivot(self):
        frame = weekly_frame(
            highs=[100, 80, 98, 101],
            lows=[90, 70, 88, 98],
            closes=[95, 72, 95, 100.3],
        )
        result = lifecycle(frame)

        self.assertEqual(result["selected_pivot"], 100)
        self.assertEqual(result["confirmation_level"], 100.5)
        self.assertTrue(pd.isna(result["breakout_date"]))

    def test_distinct_handle_can_break_out_before_left_high(self):
        frame = weekly_frame(
            highs=[100, 80, 96, 94, 95, 99],
            lows=[90, 70, 92, 90, 92, 95],
            closes=[95, 72, 94, 92, 95, 98],
        )
        result = lifecycle(frame)

        self.assertEqual(result["pivot_source"], "HANDLE")
        self.assertEqual(result["selected_pivot"], 96)
        self.assertAlmostEqual(result["handle_pivot_base_recovery"], 26 / 30)
        self.assertEqual(result["breakout_date"], frame.index[5])
        self.assertFalse(result["breakout_success"])

    def test_valid_handle_uses_one_third_of_base_depth(self):
        frame = weekly_frame(
            highs=[100, 80, 96, 94, 95, 97],
            lows=[90, 70, 92, 90, 92, 94],
            closes=[95, 72, 94, 92, 95, 96],
        )
        result = lifecycle(frame, depth=0.30)

        self.assertAlmostEqual(result["handle_max_pullback_pct"], 0.10)
        self.assertEqual(result["selected_pivot"], 96)
        self.assertEqual(result["pivot_source"], "HANDLE")

    def test_success_requires_the_buffered_left_high(self):
        frame = weekly_frame(
            highs=[100, 50, 91, 88, 90, 94, 103],
            lows=[90, 40, 86, 84, 87, 90, 98],
            closes=[95, 42, 89, 87, 90, 93, 101],
        )
        result = lifecycle(frame, depth=0.60)

        self.assertEqual(result["selected_pivot"], 91)
        self.assertEqual(result["success_level"], 100.5)
        self.assertTrue(result["breakout_success"])

    def test_failure_remains_latched_after_recovery(self):
        frame = weekly_frame(
            highs=[100, 80, 98, 102, 91, 99],
            lows=[90, 70, 88, 97, 87, 94],
            closes=[95, 72, 95, 101, 88.8, 98],
        )
        result = lifecycle(frame)

        self.assertTrue(result["hard_failure"])
        self.assertEqual(result["lifecycle_phase"], "FAILED")

    def test_one_marginal_range_breach_is_not_failure(self):
        frame = weekly_frame(
            highs=[100, 80, 98, 102, 91],
            lows=[90, 70, 88, 97, 88],
            closes=[95, 72, 95, 101, 89.5],
        )
        result = lifecycle(frame)

        self.assertFalse(result["hard_failure"])
        self.assertFalse(result["persistent_failure"])
        self.assertEqual(result["lifecycle_status"], "BREAKOUT_RANGE_BREACH")

    def test_two_consecutive_range_breaches_fail(self):
        frame = weekly_frame(
            highs=[100, 80, 98, 102, 91, 90],
            lows=[90, 70, 88, 97, 88, 87],
            closes=[95, 72, 95, 101, 89.5, 89.4],
        )
        result = lifecycle(frame)

        self.assertFalse(result["hard_failure"])
        self.assertTrue(result["persistent_failure"])
        self.assertEqual(result["lifecycle_status"], "FAILED")

    def test_tracking_recovery_uses_latest_daily_close(self):
        frame = weekly_frame(
            highs=[100, 80, 82, 84, 85, 86, 87, 88],
            lows=[90, 70, 72, 74, 76, 78, 80, 81],
            closes=[95, 72, 74, 76, 78, 80, 81, 82],
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
            "Depth": 0.30,
            "scan_window_weeks": 104,
            "pivot_price": 100,
            "pivot_index": frame.index[0],
        }
        result = update_tracking_row(row, frame.index[-1], FakeDataEngine())

        self.assertAlmostEqual(result["recovery_pct"], 0.40)
        self.assertEqual(result["journey_stage"], "RECOVERY_BUILDING")
        self.assertEqual(result["base_window_weeks"], 104)


if __name__ == "__main__":
    unittest.main()
