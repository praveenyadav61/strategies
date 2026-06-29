from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


DEFAULT_CONFIG = {
    "data": {
        "start_date": "2021-01-01",
        "end_date": "2026-06-19",
        "min_raw_rows_per_symbol": 252,
        "tickers": {
            "NIFTY_50": ["^NSEI"],
            "NIFTY_MIDCAP_100": ["^CNXMIDCAP", "MIDCAPETF.NS", "MOM100.NS"],
            "NIFTY_SMALLCAP_250": ["^CNXSC", "SMALLCAP.NS", "SMALL250.NS"],
        },
    },
    "features": {
        "daily_support_resistance_lookback": 126,
        "weekly_support_resistance_lookback": 52,
        "monthly_support_resistance_lookback": 60,
        "support_resistance_tolerance_pct": 0.015,
    },
    "labels": {
        "weights": {"trend": 0.50, "structure": 0.35, "volatility": 0.15},
        "persistence_adjustment_weight": 0.10,
        "structure_weights": {"monthly": 0.35, "weekly": 0.25, "daily": 0.15, "trendline": 0.25},
        "calibration": {
            "method": "quantile",
            "quantiles": {"strong_risk_off": 0.10, "risk_off": 0.30, "neutral": 0.70, "risk_on": 0.90},
        },
        "thresholds": {"strong_risk_off": 25, "risk_off": 40, "neutral": 60, "risk_on": 75},
        "class_order": ["STRONG_RISK_OFF", "RISK_OFF", "NEUTRAL", "RISK_ON", "STRONG_RISK_ON"],
    },
    "model": {"horizons": [5, 10], "n_splits": 5, "min_train_rows": 252, "random_state": 42, "enable_walk_forward": False},
    "transition": {"direct_jump_penalty": 0.10},
}


def load_config(config_path: Path) -> dict:
    if yaml is None:
        print("PyYAML is not installed; using built-in default config.")
        return DEFAULT_CONFIG
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def ensure_dirs(base_dir: Path) -> dict[str, Path]:
    paths = {
        "raw": base_dir / "data" / "raw",
        "features": base_dir / "data" / "features",
        "labels": base_dir / "data" / "labels",
        "models": base_dir / "data" / "models",
        "predictions": base_dir / "data" / "predictions",
        "diagnostics": base_dir / "data" / "diagnostics",
        "evaluation": base_dir / "data" / "evaluation",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths
