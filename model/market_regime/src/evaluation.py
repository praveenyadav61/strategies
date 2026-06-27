from pathlib import Path

import numpy as np

import pandas as pd
from sklearn.metrics import (
    balanced_accuracy_score,
    classification_report,
    cohen_kappa_score,
    confusion_matrix,
    matthews_corrcoef,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import LabelEncoder

from src.train_lightgbm import _classifier


def evaluate_models(
    dataset: pd.DataFrame,
    feature_cols: list[str],
    horizons: list[int],
    output_dir: Path,
    n_splits: int,
    class_order: list[str],
    random_state: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = []

    for horizon in horizons:
        target_col = f"regime_t_plus_{horizon}"
        encoder = LabelEncoder()
        encoder.fit(class_order)
        work = dataset.dropna(subset=feature_cols + [target_col]).sort_values(["Date", "symbol"]).reset_index(drop=True)
        x = work[feature_cols]
        y = encoder.transform(work[target_col])
        split_count = min(n_splits, max(2, len(work) // 200))
        y_true_parts = []
        y_pred_parts = []
        skipped_folds = 0
        for train_idx, test_idx in TimeSeriesSplit(n_splits=split_count).split(x):
            if len(np.unique(y[train_idx])) < 2:
                skipped_folds += 1
                continue
            model = _classifier(random_state, len(class_order))
            model.fit(x.iloc[train_idx], y[train_idx])
            y_true_parts.append(y[test_idx])
            y_pred_parts.append(model.predict(x.iloc[test_idx]))

        if not y_true_parts:
            continue
        y_true = encoder.inverse_transform(np.concatenate(y_true_parts))
        y_pred = encoder.inverse_transform(np.concatenate(y_pred_parts))
        labels = list(encoder.classes_)
        cm = pd.DataFrame(confusion_matrix(y_true, y_pred, labels=labels), index=labels, columns=labels)
        cm.to_csv(output_dir / f"confusion_matrix_{horizon}d.csv")

        report = pd.DataFrame(classification_report(y_true, y_pred, labels=labels, output_dict=True, zero_division=0)).transpose()
        report.to_csv(output_dir / f"classification_report_{horizon}d.csv")

        summary_rows.append(
            {
                "horizon": horizon,
                "balanced_accuracy": balanced_accuracy_score(y_true, y_pred),
                "mcc": matthews_corrcoef(y_true, y_pred),
                "cohen_kappa": cohen_kappa_score(y_true, y_pred),
                "rows_tested": len(y_true),
                "skipped_folds": skipped_folds,
            }
        )

    pd.DataFrame(summary_rows).to_csv(output_dir / "evaluation_summary.csv", index=False)
