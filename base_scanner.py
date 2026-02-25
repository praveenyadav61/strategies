import os
import pandas as pd


class BaseFormationScanner:

    def __init__(self, data_dir="data/market_data"):
        self.data_dir = data_dir

    def check_base(self, df):

        if len(df) < 120:
            return False

        df = df.copy()

        # Latest row only
        latest = df.iloc[-1]

        # 1️⃣ Near 60-day high
        high_60 = df["High"].rolling(60).max().iloc[-1]
        near_high = latest["Close"] >= 0.9 * high_60

        # 2️⃣ 20-day range compression
        high_20 = df["High"].rolling(20).max().iloc[-1]
        low_20 = df["Low"].rolling(20).min().iloc[-1]
        range_20 = (high_20 - low_20) / latest["Close"]
        tight_range = range_20 < 0.15

        # 3️⃣ Volatility contraction
        vol_20 = df["Close"].pct_change().rolling(20).std().iloc[-1]
        vol_60 = df["Close"].pct_change().rolling(60).std().iloc[-1]
        vol_contracting = vol_20 < 0.6 * vol_60

        # 4️⃣ Volume drying
        vol_avg_10 = df["Volume"].rolling(10).mean().iloc[-1]
        vol_avg_50 = df["Volume"].rolling(50).mean().iloc[-1]
        volume_dry = vol_avg_10 < vol_avg_50

        return near_high and tight_range and vol_contracting and volume_dry

    def check_flat_base(self, df):
        

    def scan_universe(self):

        base_stocks = []

        for file in os.listdir(self.data_dir):
            if file.endswith(".parquet"):

                symbol = file.replace(".parquet", "")
                file_path = os.path.join(self.data_dir, file)

                df = pd.read_parquet(file_path)

                try:
                    if self.check_base(df):
                        base_stocks.append(symbol)
                except:
                    continue

        return base_stocks
