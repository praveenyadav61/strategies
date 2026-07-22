import sys
import unittest
from pathlib import Path

import pandas as pd


STREAMLIT_DIR = Path(__file__).resolve().parents[1] / "Streamlit"
if str(STREAMLIT_DIR) not in sys.path:
    sys.path.insert(0, str(STREAMLIT_DIR))

from tradingview_lifecycle_chart import (  # noqa: E402
    build_lifecycle_chart_html,
    build_lifecycle_markers,
    build_lifecycle_price_lines,
    calculate_rsi,
    prepare_lifecycle_chart_data,
)


class TradingViewLifecycleChartTests(unittest.TestCase):
    def setUp(self):
        dates = pd.bdate_range("2026-01-02", periods=30)
        self.daily = pd.DataFrame(
            {
                "Open": [90 + index * 0.2 for index in range(30)],
                "High": [92 + index * 0.2 for index in range(30)],
                "Low": [88 + index * 0.2 for index in range(30)],
                "Close": [91 + index * 0.2 for index in range(30)],
                "Volume": [100_000 + index for index in range(30)],
            },
            index=dates,
        )
        self.result = {
            "left_high_index": dates[2],
            "left_high": 100.0,
            "base_low_index": dates[8],
            "base_low": 70.0,
            "selected_pivot": 98.0,
            "pivot_source": "DAILY_HANDLE",
            "daily_handle_candidate_pivot": 99.0,
            "daily_handle_candidate_date": dates[18],
            "daily_handle_low": 93.0,
            "daily_handle_low_date": dates[20],
            "daily_handle_confirmation_date": dates[23],
            "breakout_range_low": 88.2,
            "breakout_range_high": 107.8,
            "breakout_date": dates[25],
            "breakout_success_date": dates[28],
        }

    def test_daily_and_weekly_frames_are_valid_ohlc(self):
        daily = prepare_lifecycle_chart_data(self.daily, "Daily")
        weekly = prepare_lifecycle_chart_data(self.daily, "Weekly")
        self.assertEqual(len(daily), 30)
        self.assertGreater(len(weekly), 1)
        self.assertEqual(weekly.iloc[0]["Open"], self.daily.iloc[0]["Open"])
        self.assertIn("Close", weekly.columns)

    def test_lines_distinguish_active_candidate_and_range(self):
        lines = build_lifecycle_price_lines(self.result)
        titles = {line["title"] for line in lines}
        self.assertIn("Active pivot - Daily Handle", titles)
        self.assertIn("Left high", titles)
        self.assertIn("Handle candidate", titles)
        self.assertIn("Breakout range +10%", titles)
        self.assertIn("Breakout range -10%", titles)

    def test_markers_snap_to_available_candles(self):
        # A weekend event must be placed on a real nearby chart candle.
        result = dict(self.result, breakout_date="2026-01-11")
        markers = build_lifecycle_markers(result, self.daily.index)
        available = {date.strftime("%Y-%m-%d") for date in self.daily.index}
        self.assertTrue(markers)
        self.assertTrue(all(marker["time"] in available for marker in markers))
        self.assertEqual(markers, sorted(markers, key=lambda marker: marker["time"]))

    def test_rsi_uses_displayed_closes_and_stays_bounded(self):
        rsi = calculate_rsi(self.daily["Close"], period=14).dropna()
        self.assertTrue(len(rsi) > 0)
        self.assertTrue(rsi.between(0, 100).all())
        self.assertEqual(float(rsi.iloc[-1]), 100.0)

    def test_html_contains_responsive_chart_features_and_clean_json(self):
        document = build_lifecycle_chart_html(
            self.daily, self.result, "TEST&CO", timeframe="Daily"
        )
        self.assertIn("lightweight-charts@5.0.9", document)
        self.assertIn("ResizeObserver", document)
        self.assertIn("requestFullscreen", document)
        self.assertIn("createSeriesMarkers", document)
        self.assertIn("HistogramSeries", document)
        self.assertIn("LineSeries", document)
        self.assertIn("RSI 14", document)
        self.assertIn("Overbought 70", document)
        self.assertIn('"volumes":', document)
        self.assertIn('"rsi":', document)
        self.assertIn("Charts by TradingView", document)
        self.assertIn("TEST&amp;CO", document)
        self.assertNotIn("NaN", document)


if __name__ == "__main__":
    unittest.main()
