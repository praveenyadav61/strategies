import os
import pandas as pd


class DataEngine:

    def __init__(self, data_dir="data/daily"):

        self.data_dir = data_dir
        self.cache = {}

    def get_file_path(self, symbol):
        return os.path.join(self.data_dir, f"{symbol}.parquet")

    # -----------------------------
    # Load single symbol
    # -----------------------------

    def get_symbol(self, symbol, start=None, end=None, last_n=None):

        if symbol not in self.cache:

            file_path = self.get_file_path(symbol)

            if not os.path.exists(file_path):
                raise FileNotFoundError(f"No data for {symbol}")

            df = pd.read_parquet(file_path, engine="pyarrow")

            df.index = pd.to_datetime(df.index)

            df.sort_index(inplace=True)

            self.cache[symbol] = df

        data = self.cache[symbol]

        # date filtering
        if start or end:
            data = data.loc[start:end]

        # last N days
        if last_n is not None:
            data = data.tail(last_n)

        return data.copy()

    # -----------------------------
    # Load multiple symbols
    # -----------------------------

    def get_symbols(self, symbols, start=None, end=None, last_n=None):

        data = {}

        for symbol in symbols:
            try:
                data[symbol] = self.get_symbol(symbol, start, end, last_n)
            except Exception as e:
                print(f"Skipping {symbol}: {e}")

        return data

    # -----------------------------
    # List available symbols
    # -----------------------------

    def list_symbols(self):

        files = os.listdir(self.data_dir)

        symbols = [
            f.replace(".parquet", "")
            for f in files
            if f.endswith(".parquet")
        ]

        return sorted(symbols)

    # -----------------------------
    # Clear cache (optional)
    # -----------------------------

    def clear_cache(self):

        self.cache = {}