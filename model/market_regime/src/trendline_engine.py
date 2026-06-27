import numpy as np
import pandas as pd


def _rolling_trendline(values: pd.Series, window: int) -> pd.Series:
    output = []
    x = np.arange(window)
    for i in range(len(values)):
        if i < window:
            output.append(np.nan)
            continue
        y = values.iloc[i - window:i].to_numpy(dtype=float)
        if np.isnan(y).any():
            output.append(np.nan)
            continue
        slope, intercept = np.polyfit(x, y, 1)
        output.append(intercept + slope * window)
    return pd.Series(output, index=values.index)


def add_trendline_features(features_df: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for _, group in features_df.groupby("symbol", sort=False):
        g = group.copy().reset_index(drop=True)
        g["Trendline_Support_Value"] = _rolling_trendline(g["Low"].rolling(21).min(), 63)
        g["Trendline_Resistance_Value"] = _rolling_trendline(g["High"].rolling(21).max(), 63)
        g["Dist_Trendline_Support"] = (g["Close"] - g["Trendline_Support_Value"]) / g["Close"]
        g["Dist_Trendline_Resistance"] = (g["Trendline_Resistance_Value"] - g["Close"]) / g["Close"]
        g["Trendline_Slope_Up"] = g["Trendline_Support_Value"].pct_change(20)
        g["Trendline_Slope_Down"] = g["Trendline_Resistance_Value"].pct_change(20)
        g["Trendline_Support_Slope"] = g["Trendline_Slope_Up"]
        g["Trendline_Resistance_Slope"] = g["Trendline_Slope_Down"]
        parts.append(g)
    return pd.concat(parts, ignore_index=True).dropna().reset_index(drop=True)
