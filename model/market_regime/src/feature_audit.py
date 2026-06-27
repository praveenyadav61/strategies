from pathlib import Path

import pandas as pd


def generate_feature_audit(dataset: pd.DataFrame, feature_cols: list[str], output_dir: Path, dominance_threshold: float = 0.99) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for col in feature_cols:
        series = dataset[col]
        value_counts = series.value_counts(normalize=True, dropna=False)
        dominant_pct = float(value_counts.iloc[0]) if not value_counts.empty else 0.0
        variance = float(series.var()) if pd.api.types.is_numeric_dtype(series) else 0.0
        rows.append(
            {
                "feature": col,
                "null_pct": float(series.isna().mean()),
                "unique_values": int(series.nunique(dropna=False)),
                "dominant_pct": dominant_pct,
                "variance": variance,
                "is_dead_feature": bool(series.nunique(dropna=True) <= 1),
                "is_near_constant": bool(dominant_pct >= dominance_threshold),
            }
        )
    report = pd.DataFrame(rows).sort_values(["is_dead_feature", "is_near_constant", "dominant_pct"], ascending=False)
    report.to_csv(output_dir / "feature_audit.csv", index=False)
    report[report["is_dead_feature"]].to_csv(output_dir / "dead_features.csv", index=False)
    report[report["is_near_constant"]].to_csv(output_dir / "near_constant_features.csv", index=False)
