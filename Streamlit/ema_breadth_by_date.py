import argparse
import os
import sys

import pandas as pd


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_layer.data_engine import DataEngine


DEFAULT_DATA_DIR = "data/daily"
REQUIRED_COLUMNS = {"Close"}


def parse_scan_date(date_value):
    """Parse user input dates such as 01-01-2026 or 2026-01-01."""
    parsed = pd.to_datetime(date_value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid date: {date_value}. Use DD-MM-YYYY, for example 01-01-2026.")
    return parsed.normalize()


def prepare_symbol_data(df):
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.loc[:, ~df.columns.duplicated()]
    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(f"Missing columns: {', '.join(sorted(missing_columns))}")

    return df


def get_ema_snapshot_on_date(df, scan_date, min_history=200, max_stale_days=7):
    history = df.loc[df.index <= scan_date].copy()
    if len(history) < min_history:
        return None

    close = history["Close"].dropna()
    if len(close) < min_history:
        return None

    ema_50 = close.ewm(span=50, adjust=False).mean()
    ema_200 = close.ewm(span=200, adjust=False).mean()

    actual_date = close.index[-1]
    if max_stale_days is not None and (scan_date - actual_date).days > max_stale_days:
        return None

    close_price = close.iloc[-1]
    previous_close = close.iloc[-2]
    ema_50_value = ema_50.iloc[-1]
    ema_200_value = ema_200.iloc[-1]
    all_time_high_close = close.max()

    advanced = close_price > previous_close
    declined = close_price < previous_close
    unchanged = close_price == previous_close
    at_ath = close_price >= all_time_high_close

    return {
        "actual_date": actual_date,
        "close": close_price,
        "previous_close": previous_close,
        "ema_50": ema_50_value,
        "ema_200": ema_200_value,
        "all_time_high_close": all_time_high_close,
        "above_50ema": close_price > ema_50_value,
        "above_200ema": close_price > ema_200_value,
        "above_both": close_price > ema_50_value and close_price > ema_200_value,
        "ema50_above_ema200": ema_50_value > ema_200_value,
        "advanced": advanced,
        "declined": declined,
        "unchanged": unchanged,
        "at_ath": at_ath,
        "ath_closed_green": at_ath and advanced,
    }


def scan_ema_breadth(dates, data_dir=DEFAULT_DATA_DIR, min_history=200, max_stale_days=7):
    scan_dates = [parse_scan_date(date_value) for date_value in dates]
    data_engine = DataEngine(data_dir=data_dir)
    symbols = data_engine.list_symbols()

    summary_rows = []
    detail_rows = []

    for scan_date in scan_dates:
        processed = 0
        skipped = 0
        above_50 = 0
        above_200 = 0
        above_both = 0
        ema50_above_ema200 = 0
        advances = 0
        declines = 0
        unchanged = 0
        at_ath = 0
        ath_closed_green = 0
        actual_dates = []

        for symbol in symbols:
            try:
                df = prepare_symbol_data(data_engine.get_symbol(symbol))
                snapshot = get_ema_snapshot_on_date(
                    df,
                    scan_date,
                    min_history=min_history,
                    max_stale_days=max_stale_days,
                )
            except Exception:
                skipped += 1
                continue

            if snapshot is None:
                skipped += 1
                continue

            processed += 1
            above_50 += int(snapshot["above_50ema"])
            above_200 += int(snapshot["above_200ema"])
            above_both += int(snapshot["above_both"])
            ema50_above_ema200 += int(snapshot["ema50_above_ema200"])
            advances += int(snapshot["advanced"])
            declines += int(snapshot["declined"])
            unchanged += int(snapshot["unchanged"])
            at_ath += int(snapshot["at_ath"])
            ath_closed_green += int(snapshot["ath_closed_green"])
            actual_dates.append(snapshot["actual_date"].date())

            detail_rows.append(
                {
                    "requested_date": scan_date.date(),
                    "actual_date": snapshot["actual_date"].date(),
                    "symbol": symbol,
                    "close": snapshot["close"],
                    "previous_close": snapshot["previous_close"],
                    "ema_50": snapshot["ema_50"],
                    "ema_200": snapshot["ema_200"],
                    "all_time_high_close": snapshot["all_time_high_close"],
                    "above_50ema": snapshot["above_50ema"],
                    "above_200ema": snapshot["above_200ema"],
                    "above_both": snapshot["above_both"],
                    "ema50_above_ema200": snapshot["ema50_above_ema200"],
                    "advanced": snapshot["advanced"],
                    "declined": snapshot["declined"],
                    "unchanged": snapshot["unchanged"],
                    "at_ath": snapshot["at_ath"],
                    "ath_closed_green": snapshot["ath_closed_green"],
                }
            )

        summary_rows.append(
            {
                "requested_date": scan_date.date(),
                "actual_date_min": min(actual_dates) if actual_dates else None,
                "actual_date_max": max(actual_dates) if actual_dates else None,
                "total_symbols": len(symbols),
                "processed_symbols": processed,
                "skipped_symbols": skipped,
                "above_50ema": above_50,
                "above_200ema": above_200,
                "above_both_50_200ema": above_both,
                "ema50_above_ema200": ema50_above_ema200,
                "advances": advances,
                "declines": declines,
                "unchanged": unchanged,
                "advance_decline_ratio": round(advances / declines, 2) if declines else None,
                "at_ath": at_ath,
                "ath_closed_green": ath_closed_green,
                "above_50ema_pct": round((above_50 / processed) * 100, 2) if processed else 0,
                "above_200ema_pct": round((above_200 / processed) * 100, 2) if processed else 0,
                "above_both_pct": round((above_both / processed) * 100, 2) if processed else 0,
                "at_ath_pct": round((at_ath / processed) * 100, 2) if processed else 0,
                "ath_closed_green_pct": round((ath_closed_green / at_ath) * 100, 2) if at_ath else 0,
            }
        )

    return pd.DataFrame(summary_rows), pd.DataFrame(detail_rows)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Count stocks trading above 50 EMA and 200 EMA for one or more dates."
    )
    parser.add_argument(
        "dates",
        nargs="+",
        help="Dates to scan. Example: 01-01-2026 15-01-2026",
    )
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Path to daily parquet data directory.")
    parser.add_argument(
        "--min-history",
        type=int,
        default=200,
        help="Minimum candles required before a symbol is counted.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional CSV path for detailed symbol-level output.",
    )
    parser.add_argument(
        "--max-stale-days",
        type=int,
        default=7,
        help="Skip symbols whose latest candle is older than this many days before the requested date.",
    )
    return parser


def main():
    args = build_arg_parser().parse_args()
    summary_df, detail_df = scan_ema_breadth(
        args.dates,
        data_dir=args.data_dir,
        min_history=args.min_history,
        max_stale_days=args.max_stale_days,
    )

    print("\n===== EMA BREADTH SUMMARY =====")
    print(summary_df.to_string(index=False))

    if args.output:
        detail_df.to_csv(args.output, index=False)
        print(f"\nDetailed output saved to: {args.output}")


if __name__ == "__main__":
    main()
