"""Export next-session signals sitting below their active breakout pivot.

The source is the latest committed Base Lifecycle production run.  The output
contains exactly two columns for downstream consumption:

    symbol, price_high_limit

``price_high_limit`` is the next actionable level: the selected pivot for a
stock below the pivot, or the confirmation level for a stock already trading
inside the breakout buffer.  The default below-pivot rule uses the larger of
the structure's maximum weekly move and a five-percent pivot-distance floor.
"""

import argparse
import json
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRODUCTION_DIR = (
    PROJECT_ROOT / "data" / "base_lifecycle_layers" / "production"
)
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "just_below_breakout.csv"
DEFAULT_SIGNALS_DIR = PROJECT_ROOT / "data" / "signals"
DEFAULT_HISTORY_SESSIONS = 10
DISTANCE_MODES = ("max_weekly_move", "percentage", "atr", "hybrid")
DEFAULT_DISTANCE_MODE = "max_weekly_move"
DEFAULT_MAX_DISTANCE_PCT = 5.0
DEFAULT_ATR_MULTIPLE = 0.50


def _series(frame, column, default=pd.NA):
    if column in frame.columns:
        return frame[column]
    return pd.Series(default, index=frame.index)


def latest_committed_date(production_dir):
    """Read the authoritative date from the production manifest when present."""
    manifest_path = Path(production_dir) / "manifest.json"
    if not manifest_path.exists():
        return pd.NaT
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    return pd.to_datetime(manifest.get("last_committed_date"), errors="coerce")


def select_just_below_breakout(
    history,
    reference_date=None,
    distance_mode=DEFAULT_DISTANCE_MODE,
    max_distance_pct=DEFAULT_MAX_DISTANCE_PCT,
    atr_multiple=DEFAULT_ATR_MULTIPLE,
):
    """Return one closest-to-pivot structure per symbol.

    A row qualifies when it belongs to the selected run, is in
    BREAKOUT_CONSIDERATION, has not broken out, and either:

    - is below the pivot by no more than the configured distance; or
    - is above the pivot but no higher than the confirmation level.

    Modes:
    - ``max_weekly_move``: larger of the largest weekly true range observed in
      the base and ``max_distance_pct`` of the pivot
    - ``percentage``: pivot * max_distance_pct
    - ``atr``: setup_atr * atr_multiple
    - ``hybrid``: the smaller of the percentage and ATR limits

    Hybrid mode falls back to the percentage limit when ATR is unavailable.
    """
    output_columns = ["symbol", "price_high_limit"]
    if history is None or history.empty:
        return pd.DataFrame(columns=output_columns)
    distance_mode = str(distance_mode).strip().lower()
    if distance_mode not in DISTANCE_MODES:
        raise ValueError(
            f"distance_mode must be one of: {', '.join(DISTANCE_MODES)}"
        )
    if max_distance_pct < 0:
        raise ValueError("max_distance_pct must be non-negative")
    if atr_multiple < 0:
        raise ValueError("atr_multiple must be non-negative")

    required = {"Symbol", "tracking_date", "selected_pivot"}
    missing = required.difference(history.columns)
    if missing:
        raise ValueError(
            "tracking history is missing required columns: "
            + ", ".join(sorted(missing))
        )

    rows = history.copy()
    rows["_tracking_date"] = pd.to_datetime(
        rows["tracking_date"], errors="coerce"
    ).dt.normalize()
    resolved_date = pd.to_datetime(reference_date, errors="coerce")
    if pd.isna(resolved_date):
        resolved_date = rows["_tracking_date"].max()
    if pd.isna(resolved_date):
        return pd.DataFrame(columns=output_columns)
    resolved_date = resolved_date.normalize()
    rows = rows[rows["_tracking_date"].eq(resolved_date)].copy()

    pivot = pd.to_numeric(rows["selected_pivot"], errors="coerce")
    stored_distance = pd.to_numeric(
        _series(rows, "distance_from_pivot_pct"), errors="coerce"
    )
    latest_close = pd.to_numeric(
        _series(rows, "latest_close"), errors="coerce"
    )
    calculated_distance = (latest_close - pivot) / pivot
    rows["_distance"] = stored_distance.where(
        stored_distance.notna(), calculated_distance
    )
    rows["_pivot"] = pivot
    rows["_gap_to_pivot"] = -rows["_distance"] * rows["_pivot"]

    percentage_limit = (
        rows["_pivot"] * float(max_distance_pct) / 100.0
    )
    setup_atr = pd.to_numeric(
        _series(rows, "setup_atr"), errors="coerce"
    )
    atr_limit = setup_atr * float(atr_multiple)
    largest_weekly_move = pd.to_numeric(
        _series(rows, "largest_single_week_move"), errors="coerce"
    )
    weekly_move_ratio = pd.to_numeric(
        _series(rows, "largest_single_week_move_to_depth_ratio"),
        errors="coerce",
    )
    left_high = pd.to_numeric(_series(rows, "left_high"), errors="coerce")
    base_low = pd.to_numeric(_series(rows, "base_low"), errors="coerce")
    derived_weekly_move = (left_high - base_low) * weekly_move_ratio
    rows["_max_weekly_move"] = largest_weekly_move.where(
        largest_weekly_move.notna(), derived_weekly_move
    )
    if distance_mode == "max_weekly_move":
        rows["_allowed_distance"] = pd.concat(
            [rows["_max_weekly_move"], percentage_limit], axis=1
        ).max(axis=1, skipna=True)
    elif distance_mode == "percentage":
        rows["_allowed_distance"] = percentage_limit
    elif distance_mode == "atr":
        rows["_allowed_distance"] = atr_limit
    else:
        rows["_allowed_distance"] = pd.concat(
            [percentage_limit, atr_limit], axis=1
        ).min(axis=1, skipna=True)

    journey_stage = _series(rows, "journey_stage", "").fillna("").astype(str)
    breakout_date = pd.to_datetime(
        _series(rows, "breakout_date"), errors="coerce"
    )
    tracking_state = (
        _series(rows, "tracking_state", "ACTIVE")
        .fillna("ACTIVE")
        .astype(str)
    )
    base_eligible = (
        journey_stage.eq("BREAKOUT_CONSIDERATION")
        & breakout_date.isna()
        & tracking_state.ne("ARCHIVED")
        & rows["_pivot"].gt(0)
    )
    below_pivot = (
        rows["_gap_to_pivot"].ge(0)
        & rows["_allowed_distance"].notna()
        & rows["_gap_to_pivot"].le(rows["_allowed_distance"])
    )
    confirmation_level = pd.to_numeric(
        _series(rows, "confirmation_level"), errors="coerce"
    )
    above_pivot_buffer = (
        latest_close.gt(rows["_pivot"])
        & confirmation_level.notna()
        & latest_close.le(confirmation_level)
    )
    eligible = base_eligible & (below_pivot | above_pivot_buffer)
    rows["_signal_limit"] = rows["_pivot"].where(
        ~above_pivot_buffer, confirmation_level
    )
    rows = rows[eligible].copy()
    if rows.empty:
        return pd.DataFrame(columns=output_columns)

    rows["_symbol"] = (
        rows["Symbol"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.replace(r"\.NS$", "", regex=True)
    )
    rows = rows[rows["_symbol"].ne("")]

    # Higher distance is closer to zero because all eligible values are <= 0.
    rows = (
        rows.sort_values(
            ["_symbol", "_distance", "_pivot"],
            ascending=[True, False, True],
            kind="stable",
        )
        .drop_duplicates("_symbol", keep="first")
        .sort_values(["_distance", "_symbol"], ascending=[False, True])
    )

    result = rows[["_symbol", "_signal_limit"]].rename(
        columns={
            "_symbol": "symbol",
            "_signal_limit": "price_high_limit",
        }
    )
    result["price_high_limit"] = result["price_high_limit"].round(4)
    return result.reset_index(drop=True)


def export_latest_just_below_breakout(
    production_dir=DEFAULT_PRODUCTION_DIR,
    output_path=DEFAULT_OUTPUT_PATH,
    distance_mode=DEFAULT_DISTANCE_MODE,
    max_distance_pct=DEFAULT_MAX_DISTANCE_PCT,
    atr_multiple=DEFAULT_ATR_MULTIPLE,
):
    production_dir = Path(production_dir)
    history_path = production_dir / "views" / "tracking_history.parquet"
    if not history_path.exists():
        raise FileNotFoundError(
            f"Production tracking history not found: {history_path}"
        )

    history = pd.read_parquet(history_path)
    reference_date = latest_committed_date(production_dir)
    result = select_just_below_breakout(
        history,
        reference_date=reference_date,
        distance_mode=distance_mode,
        max_distance_pct=max_distance_pct,
        atr_multiple=atr_multiple,
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False)
    return {
        "reference_date": (
            reference_date.date().isoformat()
            if pd.notna(reference_date)
            else pd.to_datetime(history["tracking_date"]).max().date().isoformat()
        ),
        "rows": len(result),
        "distance_mode": distance_mode,
        "max_distance_pct": float(max_distance_pct),
        "atr_multiple": float(atr_multiple),
        "output_path": str(output_path.resolve()),
    }


def export_recent_signal_files(
    history,
    signals_dir=DEFAULT_SIGNALS_DIR,
    *,
    end_date=None,
    sessions=DEFAULT_HISTORY_SESSIONS,
    distance_mode=DEFAULT_DISTANCE_MODE,
    max_distance_pct=DEFAULT_MAX_DISTANCE_PCT,
    atr_multiple=DEFAULT_ATR_MULTIPLE,
):
    """Write point-in-time signal files for the latest market sessions."""
    if sessions <= 0:
        raise ValueError("sessions must be positive")
    if history is None or history.empty:
        return {"dates": [], "files": [], "total_rows": 0}
    tracking_dates = pd.to_datetime(
        _series(history, "tracking_date"), errors="coerce"
    ).dt.normalize()
    resolved_end = pd.to_datetime(end_date, errors="coerce")
    if pd.isna(resolved_end):
        resolved_end = tracking_dates.max()
    if pd.isna(resolved_end):
        return {"dates": [], "files": [], "total_rows": 0}
    resolved_end = resolved_end.normalize()
    selected_dates = sorted(
        tracking_dates[tracking_dates.le(resolved_end)].dropna().unique()
    )[-int(sessions):]
    signals_dir = Path(signals_dir)
    signals_dir.mkdir(parents=True, exist_ok=True)
    files = []
    total_rows = 0
    for signal_date in selected_dates:
        signal_date = pd.Timestamp(signal_date).normalize()
        result = select_just_below_breakout(
            history,
            reference_date=signal_date,
            distance_mode=distance_mode,
            max_distance_pct=max_distance_pct,
            atr_multiple=atr_multiple,
        )
        output_path = signals_dir / f"signal_{signal_date.date().isoformat()}.csv"
        result.to_csv(output_path, index=False)
        files.append(
            {
                "signal_date": signal_date.date().isoformat(),
                "rows": len(result),
                "output_path": str(output_path.resolve()),
            }
        )
        total_rows += len(result)
    return {
        "dates": [item["signal_date"] for item in files],
        "files": files,
        "total_rows": total_rows,
    }


def export_recent_production_signals(
    production_dir=DEFAULT_PRODUCTION_DIR,
    signals_dir=DEFAULT_SIGNALS_DIR,
    *,
    sessions=DEFAULT_HISTORY_SESSIONS,
    distance_mode=DEFAULT_DISTANCE_MODE,
    max_distance_pct=DEFAULT_MAX_DISTANCE_PCT,
    atr_multiple=DEFAULT_ATR_MULTIPLE,
):
    """Read production once and export recent point-in-time signal files."""
    production_dir = Path(production_dir)
    history_path = production_dir / "views" / "tracking_history.parquet"
    if not history_path.exists():
        raise FileNotFoundError(
            f"Production tracking history not found: {history_path}"
        )
    history = pd.read_parquet(history_path)
    return export_recent_signal_files(
        history,
        signals_dir,
        end_date=latest_committed_date(production_dir),
        sessions=sessions,
        distance_mode=distance_mode,
        max_distance_pct=max_distance_pct,
        atr_multiple=atr_multiple,
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Export latest-run next-session signals that are within the "
            "selected stock-specific distance of their active breakout pivot."
        )
    )
    parser.add_argument(
        "--production-dir",
        default=str(DEFAULT_PRODUCTION_DIR),
        help="Layered lifecycle production directory.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Destination CSV path.",
    )
    parser.add_argument(
        "--signals-dir",
        default=str(DEFAULT_SIGNALS_DIR),
        help=(
            "Directory for dated signal_YYYY-MM-DD.csv files. Defaults to "
            "data/signals."
        ),
    )
    parser.add_argument(
        "--history-sessions",
        type=int,
        default=DEFAULT_HISTORY_SESSIONS,
        help="Number of latest market sessions to export. Defaults to 10.",
    )
    parser.add_argument(
        "--distance-mode",
        choices=DISTANCE_MODES,
        default=DEFAULT_DISTANCE_MODE,
        help=(
            "Distance rule. max_weekly_move uses the larger of the "
            "structure's largest weekly true range and max-distance-pct; it "
            "is the default. Legacy percentage, atr, and hybrid modes remain "
            "available."
        ),
    )
    parser.add_argument(
        "--max-distance-pct",
        type=float,
        default=DEFAULT_MAX_DISTANCE_PCT,
        help=(
            "Percentage limit below the pivot. Used as the minimum floor by "
            "max_weekly_move and by percentage/hybrid modes. Defaults to 5."
        ),
    )
    parser.add_argument(
        "--atr-multiple",
        type=float,
        default=DEFAULT_ATR_MULTIPLE,
        help=(
            "Setup ATR multiple below the pivot. Used by atr and hybrid "
            "modes. Defaults to 0.50."
        ),
    )
    return parser


def main():
    args = build_parser().parse_args()
    summary = export_latest_just_below_breakout(
        production_dir=args.production_dir,
        output_path=args.output,
        distance_mode=args.distance_mode,
        max_distance_pct=args.max_distance_pct,
        atr_multiple=args.atr_multiple,
    )
    history_summary = export_recent_production_signals(
        production_dir=args.production_dir,
        signals_dir=args.signals_dir,
        sessions=args.history_sessions,
        distance_mode=args.distance_mode,
        max_distance_pct=args.max_distance_pct,
        atr_multiple=args.atr_multiple,
    )
    print(
        f"Exported {summary['rows']} symbols from "
        f"{summary['reference_date']} using {summary['distance_mode']} mode "
        f"to {summary['output_path']}"
    )
    print(
        f"Exported {len(history_summary['files'])} dated signal files "
        f"({history_summary['total_rows']} total rows) to "
        f"{Path(args.signals_dir).resolve()}"
    )


if __name__ == "__main__":
    main()
