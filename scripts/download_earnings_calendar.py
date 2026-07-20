"""Download a rolling NSE event-calendar snapshot for the Streamlit dashboard."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import sys

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from data_layer.earnings_calendar import fetch_earnings_calendar


DEFAULT_OUTPUT = ROOT_DIR / "data" / "static" / "earnings_calendar.parquet"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days-back", type=int, default=15)
    parser.add_argument("--days-forward", type=int, default=45)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def build_snapshot(days_back: int, days_forward: int, today: date | None = None) -> pd.DataFrame:
    if days_back < 0 or days_forward < 0:
        raise ValueError("Rolling-window day counts cannot be negative.")

    anchor = today or date.today()
    window_start = anchor - timedelta(days=days_back)
    window_end = anchor + timedelta(days=days_forward)
    snapshot = fetch_earnings_calendar(window_start, window_end)
    snapshot["fetched_at"] = datetime.now(timezone.utc)
    snapshot["window_start"] = pd.Timestamp(window_start)
    snapshot["window_end"] = pd.Timestamp(window_end)
    return snapshot


def write_snapshot_atomic(snapshot: pd.DataFrame, output: Path) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        snapshot.to_parquet(temporary, index=False)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    args = parse_args()
    snapshot = build_snapshot(args.days_back, args.days_forward)
    write_snapshot_atomic(snapshot, args.output)
    start = snapshot["window_start"].iloc[0].date() if not snapshot.empty else "unknown"
    end = snapshot["window_end"].iloc[0].date() if not snapshot.empty else "unknown"
    print(f"Wrote {len(snapshot):,} rows to {args.output.resolve()}")
    print(f"Calendar window: {start} through {end}")


if __name__ == "__main__":
    main()
