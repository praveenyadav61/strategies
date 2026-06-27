from pathlib import Path
import pickle

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import LabelEncoder

try:
    from lightgbm import LGBMClassifier
except ImportError:  # pragma: no cover
    LGBMClassifier = None
    from sklearn.ensemble import RandomForestClassifier


def _classifier(random_state: int, num_class: int):
    if LGBMClassifier is not None:
        return LGBMClassifier(
            objective="multiclass",
            num_class=num_class,
            n_estimators=180,
            learning_rate=0.035,
            num_leaves=31,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=random_state,
            verbosity=-1,
        )
    return RandomForestClassifier(
        n_estimators=120,
        max_depth=9,
        min_samples_leaf=4,
        class_weight="balanced_subsample",
        random_state=random_state,
        n_jobs=-1,
    )


def train_models(
    dataset: pd.DataFrame,
    feature_cols: list[str],
    horizons: list[int],
    class_order: list[str],
    model_dir: Path,
    n_splits: int,
    random_state: int,
) -> tuple[dict[int, object], pd.DataFrame, pd.DataFrame]:
    models = {}
    reports = []
    importances = []
    model_dir.mkdir(parents=True, exist_ok=True)

    for horizon in horizons:
        target_col = f"regime_t_plus_{horizon}"
        work = dataset.dropna(subset=feature_cols + [target_col]).sort_values(["Date", "symbol"]).reset_index(drop=True)
        encoder = LabelEncoder()
        encoder.fit(class_order)
        y = encoder.transform(work[target_col])
        x = work[feature_cols]

        fold_scores = []
        split_count = min(n_splits, max(2, len(work) // 200))
        for fold, (train_idx, test_idx) in enumerate(TimeSeriesSplit(n_splits=split_count).split(x), start=1):
            if len(np.unique(y[train_idx])) < 2:
                fold_scores.append(
                    {
                        "horizon": horizon,
                        "fold": fold,
                        "rows_train": len(train_idx),
                        "rows_test": len(test_idx),
                        "accuracy": np.nan,
                        "balanced_accuracy": np.nan,
                        "macro_f1": np.nan,
                        "status": "skipped_single_class_train",
                    }
                )
                continue
            model = _classifier(random_state, len(class_order))
            model.fit(x.iloc[train_idx], y[train_idx])
            preds = model.predict(x.iloc[test_idx])
            fold_scores.append(
                {
                    "horizon": horizon,
                    "fold": fold,
                    "rows_train": len(train_idx),
                    "rows_test": len(test_idx),
                    "accuracy": accuracy_score(y[test_idx], preds),
                    "balanced_accuracy": balanced_accuracy_score(y[test_idx], preds),
                    "macro_f1": f1_score(y[test_idx], preds, average="macro", zero_division=0),
                    "status": "ok",
                }
            )

        final_model = _classifier(random_state, len(class_order))
        final_model.fit(x, y)
        bundle = {"model": final_model, "label_encoder": encoder, "feature_cols": feature_cols, "horizon": horizon}
        with (model_dir / f"model_{horizon}d.pkl").open("wb") as handle:
            pickle.dump(bundle, handle)
        models[horizon] = bundle
        reports.extend(fold_scores)

        if hasattr(final_model, "feature_importances_"):
            values = final_model.feature_importances_
        else:
            values = np.zeros(len(feature_cols))
        importances.extend(
            {"horizon": horizon, "feature": col, "importance": float(value)}
            for col, value in zip(feature_cols, values)
        )

    return models, pd.DataFrame(reports), pd.DataFrame(importances)
