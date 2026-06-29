from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def generate_regime_diagnostics(features_df: pd.DataFrame, labels_df: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    distribution = (
        labels_df.groupby(["symbol", "regime_label"])
        .size()
        .rename("rows")
        .reset_index()
        .sort_values(["symbol", "regime_label"])
    )
    distribution["pct"] = distribution["rows"] / distribution.groupby("symbol")["rows"].transform("sum")
    distribution.to_csv(output_dir / "regime_distribution.csv", index=False)

    score_cols = [
        "regime_score",
        "raw_regime_score",
        "trend_score",
        "structure_score",
        "volatility_score",
        "persistence_score",
    ]
    labels_df.groupby("symbol")[score_cols].describe().to_csv(output_dir / "regime_score_distribution.csv")

    null_report = features_df.isna().sum().rename("null_count").reset_index()
    null_report.columns = ["feature", "null_count"]
    null_report.to_csv(output_dir / "feature_null_report.csv", index=False)
    variance = features_df.select_dtypes("number").var().rename("variance").reset_index()
    variance.columns = ["feature", "variance"]
    variance.to_csv(output_dir / "feature_variance_report.csv", index=False)

    breakout_cols = [col for col in features_df.columns if col.endswith("_Break")]
    breakout_rows = []
    for col in breakout_cols:
        counts = features_df[col].value_counts(normalize=True, dropna=False)
        breakout_rows.append(
            {
                "feature": col,
                "pct_zero": float(counts.get(0, 0)),
                "pct_one": float(counts.get(1, 0)),
                "dominant_pct": float(counts.max()) if not counts.empty else 0,
            }
        )
    pd.DataFrame(breakout_rows).to_csv(output_dir / "breakout_feature_distribution.csv", index=False)

    _plot_regime_distribution(distribution, output_dir / "regime_distribution.png")
    _plot_score_histogram(labels_df, output_dir / "regime_score_histogram.png")
    _plot_score_by_year(labels_df, output_dir / "regime_score_by_year.png")


def _plot_regime_distribution(distribution: pd.DataFrame, path: Path) -> None:
    pivot = distribution.pivot(index="symbol", columns="regime_label", values="pct").fillna(0)
    ax = pivot.plot(kind="bar", figsize=(12, 6))
    ax.set_ylabel("Share")
    ax.set_title("Regime Distribution")
    plt.tight_layout()
    plt.savefig(path)
    plt.close()


def _plot_score_histogram(labels_df: pd.DataFrame, path: Path) -> None:
    ax = labels_df["regime_score"].hist(bins=40, figsize=(10, 5))
    ax.set_title("Calibrated Regime Score Histogram")
    ax.set_xlabel("Regime Score")
    ax.set_ylabel("Rows")
    plt.tight_layout()
    plt.savefig(path)
    plt.close()


def _plot_score_by_year(labels_df: pd.DataFrame, path: Path) -> None:
    df = labels_df.copy()
    df["year"] = df["Date"].dt.year
    pivot = df.groupby(["year", "symbol"])["regime_score"].median().unstack("symbol")
    ax = pivot.plot(figsize=(12, 6), marker="o")
    ax.set_title("Median Regime Score By Year")
    ax.set_ylabel("Median Score")
    plt.tight_layout()
    plt.savefig(path)
    plt.close()
