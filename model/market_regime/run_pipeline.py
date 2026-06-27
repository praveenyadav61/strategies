from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src.breakouts import add_breakout_features
from src.config import ensure_dirs, load_config
from src.data_loader import download_ohlcv, load_raw_data, write_raw_data
from src.evaluation import evaluate_models
from src.feature_analysis import generate_shap_analysis
from src.feature_audit import generate_feature_audit
from src.feature_engineering import build_base_features
from src.label_engine import build_trader_labels, validate_against_ground_truth
from src.model_dataset import build_model_dataset, feature_columns
from src.predictor import predict_probabilities
from src.regime_diagnostics import generate_regime_diagnostics
from src.support_resistance import add_support_resistance_features
from src.train_lightgbm import train_models
from src.transition_matrix import apply_transition_smoothing, learn_transition_matrix, write_transition_reports
from src.trendline_engine import add_trendline_features


def main() -> None:
    config = load_config(BASE_DIR / "config" / "config.yaml")
    paths = ensure_dirs(BASE_DIR)

    raw_path = paths["raw"] / "nifty_indices_raw.csv"
    expected_symbols = set(config["data"]["tickers"])
    min_rows = int(config["data"].get("min_raw_rows_per_symbol", 252))
    if raw_path.exists():
        raw = load_raw_data(raw_path)
        missing_symbols = expected_symbols - set(raw["symbol"].unique())
        row_counts = raw.groupby("symbol").size()
        thin_symbols = {symbol for symbol in expected_symbols if row_counts.get(symbol, 0) < min_rows}
        if missing_symbols or thin_symbols:
            print(f"Raw data needs refresh. Missing={sorted(missing_symbols)}, thin={sorted(thin_symbols)}")
            raw = download_ohlcv(
                tickers=config["data"]["tickers"],
                start_date=config["data"]["start_date"],
                end_date=config["data"].get("end_date"),
            )
            write_raw_data(raw, raw_path)
        else:
            print(f"Loaded raw data: {raw_path}")
    else:
        raw = download_ohlcv(
            tickers=config["data"]["tickers"],
            start_date=config["data"]["start_date"],
            end_date=config["data"].get("end_date"),
        )
        write_raw_data(raw, raw_path)
        print(f"Wrote raw data: {raw_path}")

    features_base = build_base_features(raw)
    features_base.to_csv(paths["features"] / "features_base.csv", index=False)

    features_sr = add_support_resistance_features(features_base, config)
    features_sr.to_csv(paths["features"] / "features_support_resistance.csv", index=False)

    features_trendline = add_trendline_features(features_sr)
    features_trendline.to_csv(paths["features"] / "features_trendline.csv", index=False)

    features_breakouts = add_breakout_features(features_trendline)
    features_breakouts.to_csv(paths["features"] / "features_breakouts.csv", index=False)

    labels = build_trader_labels(features_breakouts, config)
    labels.to_csv(paths["labels"] / "regime_labels.csv", index=False)
    generate_regime_diagnostics(features_breakouts, labels, paths["diagnostics"])

    ground_truth = BASE_DIR.parent / "ground_truth.csv"
    if ground_truth.exists():
        validation = validate_against_ground_truth(labels, ground_truth)
        validation.to_csv(paths["labels"] / "ground_truth_validation.csv", index=False)
        print(f"Validation rows against ground_truth.csv: {len(validation)}")

    horizons = [int(value) for value in config["model"]["horizons"]]
    dataset = build_model_dataset(features_breakouts, labels, horizons)
    dataset.to_csv(paths["features"] / "model_dataset.csv", index=False)

    class_order = config["labels"]["class_order"]
    columns = feature_columns(dataset, horizons)
    generate_feature_audit(dataset, columns, paths["diagnostics"])
    models, cv_report, importances = train_models(
        dataset=dataset,
        feature_cols=columns,
        horizons=horizons,
        class_order=class_order,
        model_dir=paths["models"],
        n_splits=int(config["model"]["n_splits"]),
        random_state=int(config["model"]["random_state"]),
    )
    cv_report.to_csv(paths["models"] / "cv_report.csv", index=False)
    importances.sort_values(["horizon", "importance"], ascending=[True, False]).to_csv(
        paths["models"] / "feature_importance.csv", index=False
    )
    generate_shap_analysis(dataset, models, paths["models"])
    evaluate_models(
        dataset=dataset,
        feature_cols=columns,
        horizons=horizons,
        output_dir=paths["evaluation"],
        n_splits=int(config["model"]["n_splits"]),
        class_order=class_order,
        random_state=int(config["model"]["random_state"]),
    )

    probabilities = predict_probabilities(dataset, models, class_order)
    probabilities.to_csv(paths["predictions"] / "raw_probabilities.csv", index=False)

    transition = learn_transition_matrix(labels, class_order, float(config["transition"]["direct_jump_penalty"]))
    transition.to_csv(paths["models"] / "transition_matrix.csv", index=False)
    write_transition_reports(labels, transition, paths["models"], class_order)

    forecast = apply_transition_smoothing(probabilities, transition, class_order)
    forecast.to_csv(paths["predictions"] / "final_regime_forecast.csv", index=False)

    print("Pipeline complete.")
    print(f"Feature rows: {len(features_breakouts)}")
    print(f"Model rows: {len(dataset)}")
    print(f"Final forecast: {paths['predictions'] / 'final_regime_forecast.csv'}")


if __name__ == "__main__":
    main()
