import os
import pandas as pd
import numpy as np


class EMATrendScanner:

    def __init__(self, data_dir="data/daily"):
        self.data_dir = data_dir

    def check_ema_trend(self, df):

        if len(df) < 100:
            return False

        df = df.copy()

        # Calculate EMAs
        df["EMA10"] = df["Close"].ewm(span=10, adjust=False).mean()
        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

        recent = df.iloc[-20:]
        latest = df.iloc[-1]

        # 1️⃣ EMA Alignment
        alignment = (
            latest["Close"] > latest["EMA10"] >
            latest["EMA20"] > latest["EMA50"]
        )

        if not alignment:
            return False
        print(f"EMA Alignment OK for {latest.name} - Close: {latest['Close']:.2f}, EMA10: {latest['EMA10']:.2f}, EMA20: {latest['EMA20']:.2f}, EMA50: {latest['EMA50']:.2f}")
        # 2️⃣ Positive slopes
        slope_10 = recent["EMA10"].iloc[-1] - recent["EMA10"].iloc[0]
        slope_20 = recent["EMA20"].iloc[-1] - recent["EMA20"].iloc[0]
        slope_50 = recent["EMA50"].iloc[-1] - recent["EMA50"].iloc[0]

        if slope_10 <= 0 or slope_20 <= 0 or slope_50 <= 0:
            return False

        # 3️⃣ Staying above EMA10
        above_ratio = (recent["Close"] > recent["EMA10"]).mean()
        if above_ratio < 0.75:
            return False

        # 4️⃣ Touch detection (within 1% of EMA10 or EMA20)
        touch_10 = np.abs(recent["Low"] - recent["EMA10"]) / recent["EMA10"] < 0.01
        touch_20 = np.abs(recent["Low"] - recent["EMA20"]) / recent["EMA20"] < 0.01
        touch_count = touch_10.sum() + touch_20.sum()

        if touch_count < 2:
            return False

        return True

    def scan_universe(self):

        trending_stocks = []

        for file in os.listdir(self.data_dir):
            if file.endswith(".parquet"):

                symbol = file.replace(".parquet", "")
                file_path = os.path.join(self.data_dir, file)

                df = pd.read_parquet(file_path)

                try:
                    if self.check_ema_trend(df):
                        trending_stocks.append(symbol)
                except:
                    continue

        return trending_stocks
