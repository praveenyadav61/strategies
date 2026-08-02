"""Persistent, price-structure-only registry for the layered lifecycle."""

import json
import os
from datetime import datetime, timezone

import pandas as pd

from base_lifecycle_scanner import build_base_id
from base_structure_identity import bases_are_equivalent
from lifecycle_checkpoints import config_hash


STRUCTURE_SCHEMA_VERSION = 2
STRUCTURE_COLUMNS = [
    "base_id",
    "Symbol",
    "scan_window_weeks",
    "base_window_weeks",
    "left_high",
    "left_high_index",
    "base_low",
    "base_low_index",
    "Depth",
    "peak_to_low_weeks",
    "base_duration_weeks",
    "base_age_weeks",
    "base_end_date",
    "base_end_reason",
    "prior_uptrend",
    "prior_uptrend_pct",
    "prior_uptrend_lookback_weeks",
    "prior_uptrend_low_date",
    "prior_uptrend_low_price",
    "prior_uptrend_advance_weeks",
    "largest_single_week_move",
    "largest_single_week_move_date",
    "largest_single_week_move_to_depth_ratio",
    "tracking_eligible_recovery_min",
    "equivalent_base_windows",
    "equivalent_window_count",
    "first_detected_date",
    "first_structure_seen_date",
    "last_structure_seen_date",
    "structure_state",
    "structure_schema_version",
    "structure_config_hash",
]
DATE_COLUMNS = [
    "left_high_index",
    "base_low_index",
    "base_end_date",
    "prior_uptrend_low_date",
    "largest_single_week_move_date",
    "first_detected_date",
    "first_structure_seen_date",
    "last_structure_seen_date",
]


def _atomic_parquet(frame, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp"
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def _atomic_json(payload, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
    os.replace(temporary, path)


def normalize_registry(frame):
    if frame is None or frame.empty:
        return pd.DataFrame(columns=STRUCTURE_COLUMNS)
    result = frame.copy()
    for column in DATE_COLUMNS:
        if column in result.columns:
            result[column] = pd.to_datetime(result[column], errors="coerce")
    for column in STRUCTURE_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result[STRUCTURE_COLUMNS].copy()


def structures_from_tracking_history(history, params):
    """Extract one immutable structure row per base from a clean history."""
    if history is None or history.empty:
        return normalize_registry(pd.DataFrame())
    source = history.copy()
    source["tracking_date"] = pd.to_datetime(
        source["tracking_date"], errors="coerce"
    )
    source = source.sort_values(["tracking_date", "base_id"], kind="stable")
    first = source.drop_duplicates("base_id", keep="first").copy()
    first["first_structure_seen_date"] = first.get(
        "first_detected_date", first["tracking_date"]
    )
    latest_dates = source.groupby("base_id")["tracking_date"].max()
    first["last_structure_seen_date"] = first["base_id"].map(latest_dates)
    first["structure_state"] = "REGISTERED"
    first["structure_schema_version"] = STRUCTURE_SCHEMA_VERSION
    first["structure_config_hash"] = config_hash(params)
    return normalize_registry(first)


def upsert_discovered_structures(registry, discoveries, as_of_date, params):
    """Add genuinely new structures and update exact existing identities."""
    registry = normalize_registry(registry)
    if discoveries is None or discoveries.empty:
        return registry, pd.DataFrame()
    scan_date = pd.to_datetime(as_of_date).normalize()
    rows = registry.to_dict("records")
    by_id = {str(row["base_id"]): row for row in rows}
    events = []

    for raw in discoveries.to_dict("records"):
        row = raw.copy()
        row["base_id"] = str(row.get("base_id") or build_base_id(row))
        row["Symbol"] = str(row.get("Symbol", "")).strip()
        base_id = row["base_id"]
        if base_id in by_id:
            by_id[base_id]["last_structure_seen_date"] = scan_date
            continue

        equivalent = next(
            (
                existing
                for existing in rows
                if str(existing.get("Symbol", "")).strip() == row["Symbol"]
                and bases_are_equivalent(existing, row, params=params)
            ),
            None,
        )
        if equivalent is not None:
            equivalent["last_structure_seen_date"] = scan_date
            continue

        row.update(
            {
                "first_detected_date": pd.NaT,
                "first_structure_seen_date": scan_date,
                "last_structure_seen_date": scan_date,
                "structure_state": "REGISTERED",
                "structure_schema_version": STRUCTURE_SCHEMA_VERSION,
                "structure_config_hash": config_hash(params),
            }
        )
        normalized = normalize_registry(pd.DataFrame([row])).iloc[0].to_dict()
        rows.append(normalized)
        by_id[base_id] = normalized
        events.append(
            {
                "base_id": base_id,
                "Symbol": row["Symbol"],
                "event_type": "STRUCTURE_DISCOVERED",
                "event_date": scan_date,
                "base_window_weeks": row.get(
                    "base_window_weeks", row.get("scan_window_weeks")
                ),
            }
        )
    return normalize_registry(pd.DataFrame(rows)), pd.DataFrame(events)


class StructureRegistryRepository:
    def __init__(self, root_dir, params):
        self.root_dir = root_dir
        self.registry_path = os.path.join(root_dir, "base_structures.parquet")
        self.event_path = os.path.join(root_dir, "structure_events.parquet")
        self.manifest_path = os.path.join(root_dir, "manifest.json")
        self.params_hash = config_hash(params)

    def save(self, registry, events=None, as_of_date=None):
        registry = normalize_registry(registry)
        _atomic_parquet(registry, self.registry_path)
        event_frame = events if events is not None else pd.DataFrame()
        _atomic_parquet(event_frame, self.event_path)
        manifest = {
            "artifact_type": "base_lifecycle_structure_registry",
            "schema_version": STRUCTURE_SCHEMA_VERSION,
            "structure_config_hash": self.params_hash,
            "as_of_date": (
                pd.to_datetime(as_of_date).date().isoformat()
                if as_of_date is not None
                else None
            ),
            "structure_count": int(len(registry)),
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_json(manifest, self.manifest_path)
        return manifest

    def load(self):
        if not os.path.exists(self.registry_path):
            return normalize_registry(pd.DataFrame())
        result = normalize_registry(pd.read_parquet(self.registry_path))
        hashes = set(result["structure_config_hash"].dropna().astype(str))
        if hashes and hashes != {self.params_hash}:
            raise ValueError("Structure registry config does not match this run.")
        return result

