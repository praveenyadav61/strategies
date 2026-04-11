import os
import pandas as pd
import numpy as np


# =========================
# 🔧 PARAMETERS
# =========================
PARAMS = {
    "ema21_buffer": 1,

    "z10_max": 1.2,
    "z21_max": 1.4,

    "touch10": 2,
    "touch21": 2,

    "breach_max": 1,
    "support_buffer": 0.98,
}


class EMAScanner:

    def __init__(self, data_dir="data/daily"):
        self.data_dir = data_dir

    # ---------------------------
    # Load
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
    # EMA
    # ---------------------------
    def add_ema(self, df):
        df["ema10"] = df["Close"].ewm(span=10).mean()
        df["ema21"] = df["Close"].ewm(span=21).mean()
        return df

    # ---------------------------
    # Slope
    # ---------------------------
    def compute_slope(self, series, n=5):
        if len(series) < n:
            return 0
        return (series.iloc[-1] - series.iloc[-n]) / series.iloc[-n]

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

        if dist.iloc[-1] <= 0:
            return None

        mu = dist.rolling(20).mean()
        sigma = dist.rolling(20).std()

        z = (dist - mu) / sigma
        return z.iloc[-1]

    # ---------------------------
    # Support
    # ---------------------------
    def compute_support(self, df, ema_col):
        recent = df.tail(10)
        ema = recent[ema_col]

        # touches = (recent["Low"] >= ema * PARAMS["support_buffer"]).sum()
        buffer = 0.02
        touches = (abs(recent["Low"] - ema) / ema < (1 - PARAMS["support_buffer"])).sum()
        breaches = (recent["Close"] < ema).sum()

        return touches, breaches

    # ---------------------------
    # MOMENTUM REGIME FILTER
    # ---------------------------
    def momentum_regime_filter(self, df):
        latest = df.iloc[-1]

        slope21 = self.compute_slope(df["ema21"])

        condition = (
            slope21 > 0 and
            latest["Close"] > latest["ema21"] * PARAMS["ema21_buffer"] and
            latest["ema10"] > latest["ema21"]
        )

        return condition, slope21

    # ---------------------------
    # EMA10 follower
    # ---------------------------
    def is_ema10_follower(self, df):
        z = self.compute_zscore(df, "ema10")
        if z is None or z > PARAMS["z10_max"]:
            return False, z, 0, 0

        touches, breaches = self.compute_support(df, "ema10")

        if touches >= PARAMS["touch10"] and breaches <= PARAMS["breach_max"]:
            return True, z, touches, breaches

        return False, z, touches, breaches

    # ---------------------------
    # EMA21 follower
    # ---------------------------
    def is_ema21_follower(self, df):
        z = self.compute_zscore(df, "ema21")
        if z is None or z > PARAMS["z21_max"]:
            return False, z, 0, 0

        touches, breaches = self.compute_support(df, "ema21")

        if touches >= PARAMS["touch21"] and breaches <= PARAMS["breach_max"]:
            return True, z, touches, breaches

        return False, z, touches, breaches

    # ---------------------------
    # MAIN SCAN
    # ---------------------------
    def scan(self):

        files = [f for f in os.listdir(self.data_dir) if f.endswith(".parquet")]

        step1_fail = []
        results = []

        print(f"Total stocks: {len(files)}")

        for file in files:

            symbol = file.replace(".parquet", "")
            df = self.load_data(os.path.join(self.data_dir, file))

            if df is None or len(df) < 100:
                continue

            #custom dates
            df = df.loc["2023-01-01":"2023-06-15"]
            if df.empty:
                continue

            df = self.add_ema(df)
            latest = df.iloc[-1]

            # =========================
            # STEP 1: MOMENTUM REGIME
            # =========================
            pass_filter, slope21 = self.momentum_regime_filter(df)

            if not pass_filter:
                step1_fail.append(symbol)
                continue

            # =========================
            # STEP 2: FOLLOWERS
            # =========================
            ema10_flag, z10, t10, b10 = self.is_ema10_follower(df)
            ema21_flag, z21, t21, b21 = self.is_ema21_follower(df)

            followers = []
            if ema10_flag:
                followers.append("ema10")
            if ema21_flag:
                followers.append("ema21")

            if not followers:
                continue

            # =========================
            # EXTRA FEATURES
            # =========================
            efficiency = self.compute_efficiency(df)

            slope10 = self.compute_slope(df["ema10"])

            dist10 = (latest["Close"] - latest["ema10"]) / latest["ema10"]
            dist21 = (latest["Close"] - latest["ema21"]) / latest["ema21"]

            alignment = latest["ema10"] > latest["ema21"]

            # =========================
            # OUTPUT
            # =========================
            results.append({
                "symbol": symbol,
                "close": latest["Close"],

                "followers": ",".join(followers),

                # EMA
                "ema10": latest["ema10"],
                "ema21": latest["ema21"],

                # slope
                "slope_ema10": slope10,
                "slope_ema21": slope21,

                # efficiency
                "efficiency": efficiency,

                # zscore
                "z_ema10": z10,
                "z_ema21": z21,

                # distance
                "dist_ema10": dist10,
                "dist_ema21": dist21,

                # support
                "touch_ema10": t10,
                "touch_ema21": t21,

                "breach_ema10": b10,
                "breach_ema21": b21,

                # alignment
                "ema_alignment": alignment,
            })

        # =========================
        # DEBUG
        # =========================
        print("\n--- DEBUG ---")
        print(f"Momentum Filter Failed: {len(step1_fail)}")
        print("Sample Fail:", step1_fail[:10])

        return pd.DataFrame(results)


# ---------------------------
# RUN
# ---------------------------
if __name__ == "__main__":

    scanner = EMAScanner("data/daily")

    df = scanner.scan()

    if df.empty:
        print("No stocks found")
    else:
        print("\nTop Results:")
        print(df.head(15))

        df.to_csv("ema_trend_follower_olddata.csv", index=False)
        print("\nSaved to ema_momentum_results.csv")