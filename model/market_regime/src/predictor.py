import pandas as pd


def predict_probabilities(dataset: pd.DataFrame, models: dict[int, object], class_order: list[str]) -> pd.DataFrame:
    outputs = []
    keys = ["symbol", "Date"]
    for horizon, bundle in models.items():
        model = bundle["model"]
        encoder = bundle["label_encoder"]
        feature_cols = bundle["feature_cols"]
        probs = model.predict_proba(dataset[feature_cols])
        frame = dataset[keys].copy()
        frame["horizon"] = horizon
        for label in class_order:
            col = f"P_{label}"
            frame[col] = 0.0
            if label in encoder.classes_:
                frame[col] = probs[:, list(encoder.classes_).index(label)]
        outputs.append(frame)
    return pd.concat(outputs, ignore_index=True)
