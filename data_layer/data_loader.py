import os
import pandas as pd
from datetime import datetime


class DataLoader:

    def __init__(self, provider, data_dir="data/daily"):
        self.provider = provider
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    def get_file_path(self, symbol):
        return os.path.join(self.data_dir, f"{symbol}.parquet")

    def update_symbol(self, symbol, start_date="2014-01-01"):

        REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

        file_path = self.get_file_path(symbol)
        today = datetime.today().strftime("%Y-%m-%d")

        # -------------------------
        # First time download
        # -------------------------
        if not os.path.exists(file_path):
            print(f"Downloading full data for {symbol}")
            df = self.provider.fetch_data(symbol, start_date, today)
            if df.empty:
                print(f"No data returned for {symbol}")
                return

        # -------------------------
        # Incremental update
        # -------------------------
        else:

            print(f"Updating {symbol}")
            existing_df = pd.read_parquet(file_path, engine="pyarrow")

            last_date = existing_df.index[-1]
            new_start = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

            df_new = self.provider.fetch_data(symbol, new_start, today)

            if df_new.empty:
                print(f"No new data for {symbol}")
                return

            df = pd.concat([existing_df, df_new])
            df = df[~df.index.duplicated(keep="last")]
        # -------------------------
        # Clean & Validate
        # -------------------------
        # print(f"data for {symbol} has {len(df)} rows after update")
        # print(df.tail())
        # df.index = pd.to_datetime(df.index)

        # Fix yfinance multiindex columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        missing = set(REQUIRED_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"{symbol} missing columns {missing}")

        df = df[REQUIRED_COLUMNS]

        df.index.name = "Date"
        df.sort_index(inplace=True)
        df.to_parquet(file_path, engine="pyarrow")

        print(f"Saved {symbol}")

    def update_universe(self, symbols, start_date="2014-01-01"):
        for symbol in symbols:
            try:
                self.update_symbol(symbol, start_date)
            except Exception as e:
                print(f"Error with {symbol}: {e}")
