from pathlib import Path

import numpy as np
import pandas as pd


def generate_shap_analysis(dataset: pd.DataFrame, models: dict[int, object], output_dir: Path, max_rows: int = 500) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        import shap
        import matplotlib.pyplot as plt
    except ImportError:
        (output_dir / "shap_status.txt").write_text(
            "SHAP analysis skipped because the shap package is not installed.\n",
            encoding="utf-8",
        )
        return

    rows = []
    for horizon, bundle in models.items():
        model = bundle["model"]
        feature_cols = bundle["feature_cols"]
        sample = dataset[feature_cols].tail(max_rows)
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(sample)

        if isinstance(shap_values, list):
            abs_values = np.mean([np.abs(values).mean(axis=0) for values in shap_values], axis=0)
            plot_values = shap_values
        else:
            values = np.asarray(shap_values)
            abs_values = np.abs(values).mean(axis=0)
            if abs_values.ndim > 1:
                abs_values = abs_values.mean(axis=1)
            plot_values = shap_values

        for feature, value in zip(feature_cols, abs_values):
            rows.append({"horizon": horizon, "feature": feature, "mean_abs_shap": float(value)})

        try:
            shap.summary_plot(plot_values, sample, show=False, max_display=25)
            plt.tight_layout()
            plt.savefig(output_dir / f"shap_summary_{horizon}d.png")
            plt.close()
        except Exception as exc:
            (output_dir / f"shap_summary_{horizon}d_error.txt").write_text(str(exc), encoding="utf-8")

    pd.DataFrame(rows).sort_values(["horizon", "mean_abs_shap"], ascending=[True, False]).to_csv(
        output_dir / "shap_values.csv", index=False
    )
