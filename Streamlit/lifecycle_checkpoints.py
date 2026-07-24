"""Versioned checkpoint/event persistence for shadow incremental lifecycle."""

import hashlib
import json
import os

import numpy as np
import pandas as pd


def config_hash(config):
    payload = json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_default(value):
    if isinstance(value, (pd.Timestamp,)):
        return {"__timestamp__": value.isoformat() if pd.notna(value) else None}
    if value is pd.NaT:
        return {"__timestamp__": None}
    if isinstance(value, np.generic):
        return value.item()
    if pd.isna(value):
        return None
    raise TypeError(f"Unsupported checkpoint value: {type(value)!r}")


def _json_hook(value):
    if "__timestamp__" in value:
        raw = value["__timestamp__"]
        return pd.to_datetime(raw) if raw is not None else pd.NaT
    return value


def serialize_state(state):
    return json.dumps(state, default=_json_default, sort_keys=True)


def deserialize_state(payload):
    return json.loads(payload, object_hook=_json_hook)


def _atomic_parquet(frame, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp"
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


class LifecycleCheckpointRepository:
    def __init__(self, root_dir, strategy_config):
        self.root_dir = root_dir
        self.checkpoint_path = os.path.join(root_dir, "latest_checkpoints.parquet")
        self.event_path = os.path.join(root_dir, "lifecycle_events.parquet")
        self.config_hash = config_hash(strategy_config)

    def save(self, states, events):
        checkpoint_rows = []
        for base_id, state in states.items():
            checkpoint_rows.append(
                {
                    "base_id": str(base_id),
                    "Symbol": state.get("Symbol"),
                    "last_processed_date": pd.to_datetime(
                        state.get("last_processed_date")
                    ),
                    "checkpoint_schema_version": int(
                        state["checkpoint_schema_version"]
                    ),
                    "logic_version": state["logic_version"],
                    "config_hash": self.config_hash,
                    "state_json": serialize_state(state),
                }
            )
        _atomic_parquet(pd.DataFrame(checkpoint_rows), self.checkpoint_path)
        event_frame = pd.DataFrame(events)
        if not event_frame.empty:
            identity = [
                column
                for column in ["base_id", "event_date", "event_type", "pivot_price", "price"]
                if column in event_frame.columns
            ]
            event_frame = event_frame.drop_duplicates(identity, keep="last")
        _atomic_parquet(event_frame, self.event_path)
        return {
            "checkpoint_path": self.checkpoint_path,
            "event_path": self.event_path,
            "checkpoint_count": len(checkpoint_rows),
            "event_count": len(event_frame),
        }

    def load(self):
        if not os.path.exists(self.checkpoint_path):
            return {}
        frame = pd.read_parquet(self.checkpoint_path)
        incompatible = frame[
            (frame["config_hash"] != self.config_hash)
            | (frame["checkpoint_schema_version"] != 1)
        ]
        if not incompatible.empty:
            raise ValueError("Checkpoint version/config does not match this run.")
        return {
            str(row["base_id"]): deserialize_state(row["state_json"])
            for _, row in frame.iterrows()
        }

