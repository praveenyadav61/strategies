import os
import pandas as pd
import numpy as np


# =========================
# CONFIG
# =========================
DATA_DIR = "data/daily"


class EMAFeatureGenerator:

    def __init__(self, data_dir=DATA_DIR):
        self.data_dir = data_dir

    # ---------------------------
    # Load data
    # ---------------------------
    def load_data(self, path):
        try:
            df = pd.read_parquet(path)
            df = df.sort_index()
            df = df.dropna(subset=["Close"])
            return df
        except:
            return None

    # ---------------------------
    # EMA calculation
    # ---------------------------
    def add_ema(self, df):
        df["ema10"] = df["Close"].ewm(span=10).mean()
        df["ema21"] = df["Close"].ewm(span=21).mean()
        df["ema50"] = df["Close"].ewm(span=50).mean()
        return df

    # ---------------------------
    # Efficiency
    # ---------------------------
    def compute_efficiency(self, df, window=20):
        prices = df["Close"].tail(window)
        net = abs(prices.iloc[-1] - prices.iloc[0])
        path = np.sum(np.abs(prices.diff().dropna()))
        return net / path if path != 0 else 0

    # ---------------------------
    # Z-score
    # ---------------------------
    def compute_zscore(self, df, ema_col):
        dist = (df["Close"] - df[ema_col]) / df[ema_col]

        mu = dist.rolling(20).mean()
        sigma = dist.rolling(20).std()

        z = (dist - mu) / sigma
        return z.iloc[-1]

    # ---------------------------
    # Distance from EMA
    # ---------------------------
    def compute_distance_pct(self, df, ema_col):
        latest = df.iloc[-1]
        return (latest["Close"] - latest[ema_col]) / latest[ema_col]

    # ---------------------------
    # Support behavior
    # ---------------------------
    def compute_support(self, df, ema_col, window=10):
        recent = df.tail(window)
        ema = recent[ema_col]

        touches = (recent["Low"] >= ema * 0.98).sum()
        breaches = (recent["Close"] < ema).sum()

        return touches, breaches

    # ---------------------------
    # EMA slope
    # ---------------------------
    def compute_slope(self, series, n=5):
        if len(series) < n:
            return 0
        return (series.iloc[-1] - series.iloc[-n]) / series.iloc[-n]

    # ---------------------------
    # MAIN
    # ---------------------------
    def generate(self):

        files = [f for f in os.listdir(self.data_dir) if f.endswith(".parquet")]
        results = []

        print(f"Processing {len(files)} stocks...")

        for file in files:

            symbol = file.replace(".parquet", "")
            df = self.load_data(os.path.join(self.data_dir, file))

            if df is None or len(df) < 100:
                continue

            df = self.add_ema(df)
            latest = df.iloc[-1]

            # ---------------------------
            # Compute all features
            # ---------------------------
            efficiency = self.compute_efficiency(df)

            z10 = self.compute_zscore(df, "ema10")
            z21 = self.compute_zscore(df, "ema21")
            z50 = self.compute_zscore(df, "ema50")

            d10 = self.compute_distance_pct(df, "ema10")
            d21 = self.compute_distance_pct(df, "ema21")
            d50 = self.compute_distance_pct(df, "ema50")

            t10, b10 = self.compute_support(df, "ema10")
            t21, b21 = self.compute_support(df, "ema21")
            t50, b50 = self.compute_support(df, "ema50")

            slope10 = self.compute_slope(df["ema10"])
            slope21 = self.compute_slope(df["ema21"])
            slope50 = self.compute_slope(df["ema50"])

            # EMA alignment
            alignment = (
                latest["ema10"] > latest["ema21"] > latest["ema50"]
            )

            # ---------------------------
            # Store everything
            # ---------------------------
            results.append({
                "symbol": symbol,
                "close": latest["Close"],

                # ---- EMA values
                "ema10": latest["ema10"],
                "ema21": latest["ema21"],
                "ema50": latest["ema50"],

                # ---- alignment
                "ema_alignment": alignment,

                # ---- efficiency
                "efficiency": efficiency,

                # ---- z-scores
                "z_ema10": z10,
                "z_ema21": z21,
                "z_ema50": z50,

                # ---- distance
                "dist_ema10": d10,
                "dist_ema21": d21,
                "dist_ema50": d50,

                # ---- support
                "touch_ema10": t10,
                "touch_ema21": t21,
                "touch_ema50": t50,

                "breach_ema10": b10,
                "breach_ema21": b21,
                "breach_ema50": b50,

                # ---- slope
                "slope_ema10": slope10,
                "slope_ema21": slope21,
                "slope_ema50": slope50,
            })

        return pd.DataFrame(results)


# ---------------------------
# RUN
# ---------------------------
if __name__ == "__main__":

    generator = EMAFeatureGenerator()

    df = generator.generate()

    if df.empty:
        print("No data generated")
    else:
        print("\nSample Output:")
        print(df.head(10))

        df.to_csv("ema_feature_data.csv", index=False)
        print("\nSaved to ema_feature_data.csv")