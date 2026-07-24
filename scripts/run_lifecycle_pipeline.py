"""Staged entrypoint for lifecycle migration and parity validation.

The existing replay command remains the production calculation path.  This
entrypoint initially owns the safety boundary: freeze a canonical result and
validate subsequent refactors against it.
"""

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMLIT_DIR = os.path.join(PROJECT_ROOT, "Streamlit")
for path in [PROJECT_ROOT, STREAMLIT_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

from base_lifecycle_scanner import (
    DATA_PATH,
    DEFAULT_PARAMS,
    TRACKING_DIR,
    run_tracking_replay,
    tracking_paths,
)
from lifecycle_parity import freeze_tracking_baseline, validate_tracking_baseline
from lifecycle_shadow import run_shadow_incremental
from lifecycle_daily_orchestrator import (
    run_daily_pipeline,
    validate_production_state,
)


DEFAULT_BASELINE_ROOT = os.path.join(
    PROJECT_ROOT, "data", "base_lifecycle_layers", "baselines"
)
DEFAULT_PRODUCTION_DIR = os.path.join(
    PROJECT_ROOT, "data", "base_lifecycle_layers", "production"
)
DEFAULT_BASELINE_NAME = "frozen-v5-2026-07-23"


def _baseline_dir(root, name):
    if not str(name).strip():
        raise ValueError("baseline name cannot be empty")
    return os.path.join(root, str(name).strip())


def freeze_command(args):
    history_path = tracking_paths(args.tracking_dir)["history"]
    result = freeze_tracking_baseline(
        history_path,
        _baseline_dir(args.output_root, args.name),
        start_date=args.start_date,
        end_date=args.end_date,
        strategy_config=DEFAULT_PARAMS,
    )
    print(json.dumps(result, indent=2, default=str))


def _print_progress(completed, total, summary):
    print(
        f"[{completed}/{total}] {summary['scan_as_of_date']} "
        f"candidates={summary['candidates']} "
        f"active={summary['tracked_active']} "
        f"new={summary['new_tracked_bases']}",
        flush=True,
    )


def reconstruct_baseline_command(args):
    baseline_dir = _baseline_dir(args.output_root, args.name)
    reconstruction_dir = os.path.join(baseline_dir, "reconstruction")
    scan_dir = os.path.join(reconstruction_dir, "scans")
    tracking_dir = os.path.join(reconstruction_dir, "tracking")
    history_path = tracking_paths(tracking_dir)["history"]
    if os.path.exists(history_path):
        raise SystemExit(
            "This baseline name already has reconstructed tracking history. "
            "Use a new --name so the canonical run starts from empty state."
        )
    run_tracking_replay(
        DEFAULT_PARAMS,
        args.start_date,
        args.end_date,
        frequency="daily",
        data_path=args.data_path,
        scan_dir=scan_dir,
        tracking_dir=tracking_dir,
        debug=args.debug,
        update_tracking=True,
        progress_callback=_print_progress,
    )
    result = freeze_tracking_baseline(
        history_path,
        baseline_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        strategy_config=DEFAULT_PARAMS,
    )
    result["reconstruction_dir"] = reconstruction_dir
    print(json.dumps(result, indent=2, default=str))


def validate_command(args):
    history_path = tracking_paths(args.tracking_dir)["history"]
    report = validate_tracking_baseline(
        _baseline_dir(args.baseline_root, args.name),
        history_path,
        float_tolerance=args.float_tolerance,
    )
    print(json.dumps(report, indent=2, default=str))
    if not report["passed"]:
        raise SystemExit(1)


def shadow_incremental_command(args):
    baseline_dir = _baseline_dir(args.baseline_root, args.name)
    output_dir = args.output_dir or os.path.join(
        baseline_dir, "shadow_incremental"
    )

    def progress(completed, total, base_id):
        if completed == 1 or completed == total or completed % 50 == 0:
            print(
                f"[{completed}/{total}] checkpointed {base_id}",
                flush=True,
            )

    report = run_shadow_incremental(
        baseline_dir,
        output_dir,
        data_path=args.data_path,
        params=DEFAULT_PARAMS,
        progress_callback=progress,
    )
    print(json.dumps(report, indent=2, default=str))
    if not report["passed"]:
        raise SystemExit(1)


def _daily_progress(completed, total, summary):
    mode = (
        "weekly + daily"
        if summary["structure_refresh"]
        else "daily"
    )
    print(
        f"[{completed}/{total}] {summary['processing_date']} completed | "
        f"{mode} | structures={summary['structures']} | "
        f"checkpoints={summary['checkpoints']} | "
        f"rows={summary['tracking_rows']} | "
        f"new_structures={summary['new_structures']}",
        flush=True,
    )


def daily_command(args):
    report = run_daily_pipeline(
        args.production_dir,
        _baseline_dir(args.baseline_root, args.baseline_name),
        data_path=args.data_path,
        params=DEFAULT_PARAMS,
        as_of_date=args.as_of_date,
        debug=args.debug,
        progress_callback=_daily_progress,
    )
    print(json.dumps(report, indent=2, default=str))


def validate_state_command(args):
    report = validate_production_state(
        args.production_dir, DEFAULT_PARAMS
    )
    print(json.dumps(report, indent=2, default=str))
    if not report["passed"]:
        raise SystemExit(1)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Base Lifecycle layered migration and parity tools."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze_parser = subparsers.add_parser(
        "freeze-baseline",
        help="Freeze current tracking output as the canonical parity baseline.",
    )
    freeze_parser.add_argument("--name", required=True)
    freeze_parser.add_argument("--start-date", required=True)
    freeze_parser.add_argument("--end-date", required=True)
    freeze_parser.add_argument("--tracking-dir", default=TRACKING_DIR)
    freeze_parser.add_argument("--output-root", default=DEFAULT_BASELINE_ROOT)
    freeze_parser.set_defaults(handler=freeze_command)

    reconstruct_parser = subparsers.add_parser(
        "reconstruct-baseline",
        help=(
            "Run a clean replay in an isolated directory and freeze its output "
            "as the canonical baseline."
        ),
    )
    reconstruct_parser.add_argument("--name", required=True)
    reconstruct_parser.add_argument("--start-date", required=True)
    reconstruct_parser.add_argument("--end-date", required=True)
    reconstruct_parser.add_argument("--data-path", default=DATA_PATH)
    reconstruct_parser.add_argument("--output-root", default=DEFAULT_BASELINE_ROOT)
    reconstruct_parser.add_argument("--debug", action="store_true")
    reconstruct_parser.set_defaults(handler=reconstruct_baseline_command)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Compare current tracking history with a frozen baseline.",
    )
    validate_parser.add_argument("--name", required=True)
    validate_parser.add_argument("--tracking-dir", default=TRACKING_DIR)
    validate_parser.add_argument("--baseline-root", default=DEFAULT_BASELINE_ROOT)
    validate_parser.add_argument("--float-tolerance", type=float, default=1e-9)
    validate_parser.set_defaults(handler=validate_command)

    shadow_parser = subparsers.add_parser(
        "shadow-incremental",
        help=(
            "Build versioned checkpoints by advancing one candle at a time and "
            "compare the results with a frozen baseline."
        ),
    )
    shadow_parser.add_argument("--name", required=True)
    shadow_parser.add_argument("--data-path", default=DATA_PATH)
    shadow_parser.add_argument("--baseline-root", default=DEFAULT_BASELINE_ROOT)
    shadow_parser.add_argument("--output-dir")
    shadow_parser.set_defaults(handler=shadow_incremental_command)

    daily_parser = subparsers.add_parser(
        "daily",
        help=(
            "Bootstrap from the validated baseline when necessary, then "
            "process only missing market sessions. Completed weeks refresh "
            "the structure registry automatically."
        ),
    )
    daily_parser.add_argument("--as-of-date")
    daily_parser.add_argument("--data-path", default=DATA_PATH)
    daily_parser.add_argument(
        "--production-dir", default=DEFAULT_PRODUCTION_DIR
    )
    daily_parser.add_argument(
        "--baseline-root", default=DEFAULT_BASELINE_ROOT
    )
    daily_parser.add_argument(
        "--baseline-name", default=DEFAULT_BASELINE_NAME
    )
    daily_parser.add_argument("--debug", action="store_true")
    daily_parser.set_defaults(handler=daily_command)

    state_parser = subparsers.add_parser(
        "validate-state",
        help="Validate production manifests, checkpoints, structures, and views.",
    )
    state_parser.add_argument(
        "--production-dir", default=DEFAULT_PRODUCTION_DIR
    )
    state_parser.set_defaults(handler=validate_state_command)
    return parser


def main():
    args = build_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
