import pandas as pd


NON_FEATURE_COLUMNS = {
    "Date",
    "symbol",
    "source_ticker",
    "regime_label",
    "regime_score",
    "raw_regime_score",
    "calibration_q10",
    "calibration_q30",
    "calibration_q70",
    "calibration_q90",
    "target_label",
}


def build_model_dataset(features_df: pd.DataFrame, labels_df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    df = features_df.merge(labels_df, on=["symbol", "Date"], how="inner")
    df = df.sort_values(["symbol", "Date"]).reset_index(drop=True)
    for horizon in horizons:
        df[f"regime_t_plus_{horizon}"] = df.groupby("symbol")["regime_label"].shift(-horizon)
    return df.dropna().reset_index(drop=True)


def feature_columns(dataset: pd.DataFrame, horizons: list[int]) -> list[str]:
    target_cols = {f"regime_t_plus_{horizon}" for horizon in horizons}
    blocked = NON_FEATURE_COLUMNS | target_cols
    return [col for col in dataset.columns if col not in blocked and pd.api.types.is_numeric_dtype(dataset[col])]
