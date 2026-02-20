import os
import pandas as pd
from datetime import datetime


class DataLoader:

    def __init__(self, provider, data_dir="data/market_data"):
        self.provider = provider
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    def get_file_path(self, symbol):
        return os.path.join(self.data_dir, f"{symbol}.parquet")

    def update_symbol(self, symbol, start_date="2014-01-01"):

        file_path = self.get_file_path(symbol)
        today = datetime.today().strftime("%Y-%m-%d")

        # First download
        if not os.path.exists(file_path):
            print(f"Downloading full data for {symbol}")
            df = self.provider.fetch_data(symbol, start_date, today)

        else:
            print(f"Updating {symbol}")
            existing_df = pd.read_parquet(file_path)

            last_date = existing_df.index[-1]
            new_start = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

            df_new = self.provider.fetch_data(symbol, new_start, today)

            if df_new.empty:
                print(f"No new data for {symbol}")
                return

            df = pd.concat([existing_df, df_new])
            df = df[~df.index.duplicated(keep="last")]

        df.index.name = "Date"
        df.sort_index(inplace=True)
        df.to_parquet(file_path, engine="pyarrow")

        print(f"Saved {symbol}")

    def load_symbol(self, symbol):
        file_path = self.get_file_path(symbol)

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"No data found for {symbol}")

        return pd.read_parquet(file_path)

    def update_universe(self, symbols, start_date="2014-01-01"):
        for symbol in symbols:
            try:
                self.update_symbol(symbol, start_date)
            except Exception as e:
                print(f"Error with {symbol}: {e}")
