import yfinance as yf
import pandas as pd


class YahooDataProvider:

    def fetch_data(self, symbol, start=None, end=None, period=None):

        try:
            if period:
                df = yf.download(symbol, period=period, progress=False)
            else:
                df = yf.download(symbol, start=start, end=end, progress=False)

            if df is None or df.empty:
                return pd.DataFrame()

            # 🔥 FIX: flatten MultiIndex ALWAYS
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # Keep only required columns
            # df = df[["Open", "High", "Low", "Close", "Volume"]]
            required_cols = ["Open", "High", "Low", "Close", "Volume"]

            df = df.loc[:, df.columns.intersection(required_cols)]
            df = df[required_cols]  # enforce order

            # Remove NaNs (important)
            df = df.dropna(subset=["Close"])

            df.index.name = "Date"

            return df

        except Exception:
            return pd.DataFrame()