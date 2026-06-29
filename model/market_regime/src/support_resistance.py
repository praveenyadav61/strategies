import numpy as np
import pandas as pd


def _nearest_levels(group: pd.DataFrame, lookback: int, prefix: str, tolerance_pct: float) -> pd.DataFrame:
    close = group["Close"].to_numpy()
    high = group["High"].rolling(5, center=True).max()
    low = group["Low"].rolling(5, center=True).min()
    swing_high = group["High"].where(group["High"].eq(high))
    swing_low = group["Low"].where(group["Low"].eq(low))

    support_values = []
    resistance_values = []
    support_touches = []
    resistance_touches = []

    for i, price in enumerate(close):
        start = max(0, i - lookback)
        lows = swing_low.iloc[start:i].dropna()
        highs = swing_high.iloc[start:i].dropna()
        supports = lows[lows <= price]
        resistances = highs[highs >= price]

        support = supports.iloc[(supports - price).abs().argmin()] if not supports.empty else np.nan
        resistance = resistances.iloc[(resistances - price).abs().argmin()] if not resistances.empty else np.nan

        support_values.append(support)
        resistance_values.append(resistance)
        support_touches.append(int(((lows - support).abs() / price <= tolerance_pct).sum()) if pd.notna(support) else 0)
        resistance_touches.append(int(((highs - resistance).abs() / price <= tolerance_pct).sum()) if pd.notna(resistance) else 0)

    group[f"Nearest_{prefix}_Support"] = support_values
    group[f"Nearest_{prefix}_Resistance"] = resistance_values
    group[f"{prefix}_Support_Touch_Count"] = support_touches
    group[f"{prefix}_Resistance_Touch_Count"] = resistance_touches
    group[f"Dist_{prefix}_Support"] = (group["Close"] - group[f"Nearest_{prefix}_Support"]) / group["Close"]
    group[f"Dist_{prefix}_Resistance"] = (group[f"Nearest_{prefix}_Resistance"] - group["Close"]) / group["Close"]
    return group


def add_support_resistance_features(features_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    parts = []
    daily = int(config["features"]["daily_support_resistance_lookback"])
    weekly = int(config["features"]["weekly_support_resistance_lookback"]) * 5
    monthly = int(config["features"]["monthly_support_resistance_lookback"]) * 21
    tolerance = float(config["features"]["support_resistance_tolerance_pct"])

    for _, group in features_df.groupby("symbol", sort=False):
        g = group.copy().reset_index(drop=True)
        g = _nearest_levels(g, daily, "Daily", tolerance)
        g = _nearest_levels(g, weekly, "Weekly", tolerance)
        g = _nearest_levels(g, monthly, "Monthly", tolerance)
        parts.append(g)
    return pd.concat(parts, ignore_index=True).dropna().reset_index(drop=True)
