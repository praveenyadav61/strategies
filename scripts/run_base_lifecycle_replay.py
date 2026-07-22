import argparse
import os
import sys
from datetime import date


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMLIT_DIR = os.path.join(PROJECT_ROOT, "Streamlit")
for path in [PROJECT_ROOT, STREAMLIT_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

from base_lifecycle_scanner import DEFAULT_PARAMS, DATA_PATH, run_tracking_replay


def parse_windows(value):
    windows = [int(item.strip()) for item in str(value).split(",") if item.strip()]
    if not windows:
        raise argparse.ArgumentTypeError("At least one base window is required.")
    return windows


def build_params(args):
    params = DEFAULT_PARAMS.copy()
    params.update(
        {
            "MIN_WEEKS": args.min_weeks,
            "MIN_BASE_DURATION_WEEKS": args.min_base_duration,
            "MAX_WEEKS": max(args.base_windows),
            "BASE_WINDOWS": args.base_windows,
            "MIN_WEEKLY_BARS_REQUIRED": args.min_weeks + 2,
            "MIN_DEPTH": args.min_depth / 100.0,
            "MAX_DEPTH": args.max_depth / 100.0,
            "RECOVERY_MIN": args.recovery_min / 100.0,
            "TRACKING_ELIGIBLE_RECOVERY_MIN": args.tracking_recovery_min / 100.0,
            "BREAKOUT_CONSIDERATION_RECOVERY_MIN": args.consideration_recovery_min / 100.0,
            "MIN_PRIOR_UPTREND_PCT": args.prior_uptrend_min / 100.0,
            "PRIOR_UPTREND_DEPTH_MULTIPLIER": args.prior_uptrend_depth_multiplier,
            "PRIOR_UPTREND_LOOKBACK_RATIO": args.prior_uptrend_lookback_ratio,
            "PRIOR_UPTREND_MIN_LOOKBACK_WEEKS": args.prior_uptrend_min_lookback,
            "PRIOR_UPTREND_MAX_LOOKBACK_WEEKS": args.prior_uptrend_max_lookback,
            "PRIOR_UPTREND_MIN_ADVANCE_WEEKS": args.prior_uptrend_min_advance,
            "MIN_PEAK_TO_LOW_WEEKS": args.min_peak_to_low_weeks,
            "ATR_WINDOW": args.atr_window,
            "COMPRESSION_LOOKBACK": args.compression_lookback,
            "BREAKOUT_PRICE_BUFFER_PCT": args.breakout_price_buffer / 100.0,
            "BREAKOUT_ATR_BUFFER_MULTIPLIER": args.breakout_atr_buffer,
            "FAILURE_PRICE_BUFFER_PCT": args.failure_price_buffer / 100.0,
            "FAILURE_ATR_BUFFER_MULTIPLIER": args.failure_atr_buffer,
            "BREAKOUT_RANGE_PCT": args.breakout_range / 100.0,
            "BREAKOUT_STALL_WEEKS": args.breakout_stall_weeks,
        }
    )
    return params


def print_replay_progress(completed, total, summary):
    percent = int(round((completed / total) * 100)) if total else 100
    bar_width = 24
    filled = int(round(bar_width * completed / total)) if total else bar_width
    progress_bar = "#" * filled + "-" * (bar_width - filled)
    structure_mode = "weekly + daily" if summary["weekly_structure_refresh"] else "daily"
    print(
        f"[{progress_bar}] {percent:3d}% "
        f"({completed}/{total}) {summary['scan_as_of_date']} completed | "
        f"{structure_mode} | candidates={summary['candidates']} | "
        f"active={summary['tracked_active']} | new={summary['new_tracked_bases']}",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run Base Lifecycle replay from a start date to an end date without Streamlit."
    )
    parser.add_argument("--start-date", required=True, help="Replay start date, e.g. 2026-07-01")
    parser.add_argument("--end-date", default=date.today().isoformat(), help="Replay end date. Defaults to today.")
    parser.add_argument(
        "--frequency",
        choices=["daily", "weekly_friday"],
        default="daily",
        help=(
            "Default daily mode processes business days: daily state every day and "
            "a refreshed completed-week structure on Fridays."
        ),
    )
    parser.add_argument("--base-windows", type=parse_windows, default=parse_windows("104,52,26"))
    parser.add_argument("--min-weeks", type=int, default=8)
    parser.add_argument(
        "--min-base-duration",
        type=int,
        default=12,
        help="Minimum weeks from left high to handle pivot, breakout, or current structure",
    )
    parser.add_argument("--min-depth", type=float, default=15.0, help="Percent")
    parser.add_argument("--max-depth", type=float, default=60.0, help="Percent")
    parser.add_argument("--recovery-min", type=float, default=40.0, help="Lifecycle discovery recovery percent")
    parser.add_argument("--tracking-recovery-min", type=float, default=40.0, help="Lifecycle persistence recovery percent")
    parser.add_argument("--consideration-recovery-min", type=float, default=85.0, help="Breakout consideration recovery percent")
    parser.add_argument("--prior-uptrend-min", type=float, default=20.0, help="Percent")
    parser.add_argument("--prior-uptrend-depth-multiplier", type=float, default=1.0)
    parser.add_argument("--prior-uptrend-lookback-ratio", type=float, default=0.50)
    parser.add_argument("--prior-uptrend-min-lookback", type=int, default=12)
    parser.add_argument("--prior-uptrend-max-lookback", type=int, default=52)
    parser.add_argument("--prior-uptrend-min-advance", type=int, default=4)
    parser.add_argument("--min-peak-to-low-weeks", type=int, default=6)
    parser.add_argument("--atr-window", type=int, default=14)
    parser.add_argument("--compression-lookback", type=int, default=10)
    parser.add_argument("--breakout-price-buffer", type=float, default=0.5, help="Percent")
    parser.add_argument("--breakout-atr-buffer", type=float, default=0.20, help="ATR multiplier")
    parser.add_argument("--failure-price-buffer", type=float, default=1.0, help="Percent")
    parser.add_argument("--failure-atr-buffer", type=float, default=0.25, help="ATR multiplier")
    parser.add_argument("--breakout-range", type=float, default=10.0, help="Percent above/below pivot")
    parser.add_argument("--breakout-stall-weeks", type=int, default=10)
    parser.add_argument("--data-path", default=DATA_PATH)
    parser.add_argument("--no-tracking", action="store_true", help="Save scanner snapshots without updating tracking files.")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    params = build_params(args)
    print(
        f"Starting Base Lifecycle replay: {args.start_date} to {args.end_date}",
        flush=True,
    )
    summary_df = run_tracking_replay(
        params,
        args.start_date,
        args.end_date,
        frequency=args.frequency,
        data_path=args.data_path,
        debug=args.debug,
        update_tracking=not args.no_tracking,
        progress_callback=print_replay_progress,
    )

    print(
        summary_df[
            [
                "scan_as_of_date",
                "weekly_structure_refresh",
                "candidates",
                "all_window_rows",
                "tracked_active",
                "tracked_archived",
                "new_tracked_bases",
            ]
        ].to_string(index=False)
    )
    print(f"\nCompleted {len(summary_df)} replay dates.")


if __name__ == "__main__":
    main()
