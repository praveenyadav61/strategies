import numpy as np
import pandas as pd

from src.score_calibration import calibrate_scores


def _normalize(series: pd.Series, lower: float, upper: float) -> pd.Series:
    return ((series - lower) / (upper - lower)).clip(0, 1)


def build_trader_labels(features_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    weights = config["labels"]["weights"]
    structure_weights = config["labels"]["structure_weights"]
    persistence_weight = float(config["labels"].get("persistence_adjustment_weight", 0.10))
    df = features_df.copy()

    trend = (
        0.16 * df["Above_EMA200"]
        + 0.10 * df["Above_EMA50"]
        + 0.10 * df["EMA50_Above_EMA200"]
        + 0.16 * _normalize(df["EMA200_Dist"], -0.12, 0.12)
        + 0.12 * _normalize(df["EMA50_200_Spread"], -0.08, 0.08)
        + 0.08 * _normalize(df["EMA50_Slope_5"], -0.02, 0.02)
        + 0.08 * _normalize(df["EMA50_Slope_20"], -0.04, 0.04)
        + 0.06 * _normalize(df["EMA200_Slope_20"], -0.025, 0.025)
        + 0.08 * _normalize(df["RSI14"], 30, 70)
        + 0.06 * _normalize(df["ADX14"], 10, 35)
    )
    monthly_structure = _structure_score(df, "Monthly")
    weekly_structure = _structure_score(df, "Weekly")
    daily_structure = _structure_score(df, "Daily")
    trendline_structure = (
        0.35 * _normalize(df["Dist_Trendline_Support"], 0, 0.12)
        + 0.25 * (1 - _normalize(df["Dist_Trendline_Resistance"], 0, 0.12))
        + 0.25 * _normalize(df["Trendline_Support_Slope"], -0.06, 0.06)
        + 0.15 * df["Trendline_Resistance_Break"]
    )
    structure = (
        structure_weights["monthly"] * monthly_structure
        + structure_weights["weekly"] * weekly_structure
        + structure_weights["daily"] * daily_structure
        + structure_weights["trendline"] * trendline_structure
    )
    volatility_expansion = (
        0.30 * _normalize(df["NATR14"], 0.8, 3.5)
        + 0.20 * _normalize(df["NATR21"], 0.8, 3.5)
        + 0.20 * _normalize(df["BB_WIDTH"], 0.02, 0.12)
        + 0.20 * _normalize(df["ATR5_ATR50_RATIO"], 0.7, 1.6)
        + 0.10 * _normalize(df["GK_VOL_21"], 0.004, 0.025)
    )
    volatility_compression = 1 - volatility_expansion
    volatility = 100 * (0.50 + 0.35 * (trend - 0.50) + 0.15 * (volatility_expansion - 0.50))

    persistence = (
        0.30 * _normalize(df["days_above_ema200"], 0, 90)
        - 0.30 * _normalize(df["days_below_ema200"], 0, 90)
        + 0.20 * _normalize(df["days_above_ema50"], 0, 45)
        - 0.20 * _normalize(df["days_below_ema50"], 0, 45)
    ) * 100

    df["trend_score"] = trend * 100
    df["monthly_structure_score"] = monthly_structure * 100
    df["weekly_structure_score"] = weekly_structure * 100
    df["daily_structure_score"] = daily_structure * 100
    df["trendline_structure_score"] = trendline_structure * 100
    df["structure_score"] = structure * 100
    df["volatility_expansion_score"] = volatility_expansion * 100
    df["volatility_compression_score"] = volatility_compression * 100
    df["volatility_score"] = volatility
    df["persistence_score"] = persistence
    base_score = (
        weights["trend"] * df["trend_score"]
        + weights["structure"] * df["structure_score"]
        + weights["volatility"] * df["volatility_score"]
    )
    df["regime_score"] = (base_score + persistence_weight * df["persistence_score"]).clip(0, 100)
    df = calibrate_scores(df, config)
    df["days_in_current_regime"] = _days_in_current_regime(df)
    return df[
        [
            "symbol",
            "Date",
            "regime_score",
            "raw_regime_score",
            "regime_label",
            "trend_score",
            "structure_score",
            "monthly_structure_score",
            "weekly_structure_score",
            "daily_structure_score",
            "trendline_structure_score",
            "volatility_score",
            "volatility_expansion_score",
            "volatility_compression_score",
            "persistence_score",
            "days_in_current_regime",
            "calibration_q10",
            "calibration_q30",
            "calibration_q70",
            "calibration_q90",
        ]
    ]


def _structure_score(df: pd.DataFrame, level: str) -> pd.Series:
    support = _normalize(df[f"Dist_{level}_Support"], 0, 0.12)
    resistance = 1 - _normalize(df[f"Dist_{level}_Resistance"], 0, 0.12)
    support_touches = _normalize(df[f"{level}_Support_Touch_Count"], 0, 6)
    resistance_break = df[f"{level}_Resistance_Break"]
    support_break_penalty = df[f"{level}_Support_Break"]
    return (0.35 * support + 0.25 * resistance + 0.15 * support_touches + 0.25 * resistance_break - 0.20 * support_break_penalty).clip(0, 1)


def _days_in_current_regime(df: pd.DataFrame) -> pd.Series:
    values = []
    for _, group in df.sort_values(["symbol", "Date"]).groupby("symbol", sort=False):
        changes = group["regime_label"].ne(group["regime_label"].shift()).cumsum()
        values.append(group.groupby(changes).cumcount() + 1)
    return pd.concat(values).sort_index()


def validate_against_ground_truth(labels_df: pd.DataFrame, ground_truth_path) -> pd.DataFrame:
    gt = pd.read_csv(ground_truth_path, parse_dates=["date"]).rename(columns={"date": "Date", "gt_regime": "gt_regime_3class"})
    nifty = labels_df[labels_df["symbol"].eq("NIFTY_50")].copy()
    nifty["pred_regime_3class"] = nifty["regime_label"].replace(
        {
            "STRONG_RISK_OFF": "RISK_OFF",
            "STRONG_RISK_ON": "RISK_ON",
        }
    )
    merged = gt.merge(nifty[["Date", "pred_regime_3class", "regime_label", "regime_score", "raw_regime_score"]], on="Date", how="left")
    merged["is_match"] = merged["gt_regime_3class"].eq(merged["pred_regime_3class"])
    return merged
