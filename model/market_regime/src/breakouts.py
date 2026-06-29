import pandas as pd


def add_breakout_features(features_df: pd.DataFrame) -> pd.DataFrame:
    df = features_df.copy()
    for level in ["Daily", "Weekly", "Monthly"]:
        df[f"{level}_Support_Break"] = (df["Close"] < df[f"Nearest_{level}_Support"]).astype(int)
        df[f"{level}_Resistance_Break"] = (df["Close"] > df[f"Nearest_{level}_Resistance"]).astype(int)
    df["Trendline_Support_Break"] = (df["Close"] < df["Trendline_Support_Value"]).astype(int)
    df["Trendline_Resistance_Break"] = (df["Close"] > df["Trendline_Resistance_Value"]).astype(int)
    return df
