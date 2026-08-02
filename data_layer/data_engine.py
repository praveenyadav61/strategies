import os
from datetime import timedelta
import pandas as pd
import yfinance as yf


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


class MarketDataEngine:
    """Unified market data engine for daily storage and direct fetch.

    Daily data is served from local Parquet files by default, but can also be fetched
    directly from yfinance when requested or when local data is unavailable.
    Intraday data is fetched directly from yfinance on demand.
    """

    DAILY_INTERVALS = {"1d", "daily", "day"}
    INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "120m"}

    def __init__(self, daily_data_dir="data/daily", intraday_store_dir=None, cache_in_memory=True):
        self.daily_engine = DataEngine(daily_data_dir)
        self.intraday_store_dir = intraday_store_dir
        self.cache = {} if cache_in_memory else None

    def _normalize_interval(self, interval):
        if interval is None:
            return "1d"
        return str(interval).strip().lower()

    def _is_daily_interval(self, interval):
        return self._normalize_interval(interval) in self.DAILY_INTERVALS

    def _clean_intraday_df(self, df):
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close", "Volume"]
        df = df[[col for col in required if col in df.columns]]
        df = df.dropna(subset=["Close"])
        df = df[~df.index.duplicated(keep="last")]
        df.sort_index(inplace=True)
        df.index = pd.to_datetime(df.index)
        df.index.name = "Time"
        return df

    def _infer_end_date(self, end):
        if end is not None:
            return pd.to_datetime(end)
        return pd.Timestamp.now().normalize() + timedelta(days=1)

    def _clean_daily_df(self, df):
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close", "Volume"]
        df = df[[col for col in required if col in df.columns]]
        df = df.dropna(subset=["Close"])
        df = df[~df.index.duplicated(keep="last")]
        df.sort_index(inplace=True)
        df.index = pd.to_datetime(df.index)
        df.index.name = "Date"
        return df

    def _fetch_intraday(self, symbol, start=None, end=None, interval="1m", provider_kwargs=None):
        interval = self._normalize_interval(interval)
        if interval not in self.INTRADAY_INTERVALS:
            raise ValueError(f"Unsupported intraday interval: {interval}")

        kwargs = provider_kwargs.copy() if provider_kwargs is not None else {}
        kwargs["interval"] = interval
        kwargs["progress"] = False

        if start is not None:
            # Pass datetime objects to yfinance to avoid string parsing issues
            kwargs["start"] = pd.to_datetime(start)
            kwargs["end"] = self._infer_end_date(end)
        else:
            kwargs["period"] = kwargs.get("period", "7d")

        # Primary fetch using yf.download
        df = yf.download(symbol, **kwargs)

        # Fallback: try Ticker.history() which sometimes returns intraday slices
        if df is None or df.empty:
            try:
                ticker = yf.Ticker(symbol)
                hist_kwargs = {k: v for k, v in kwargs.items() if k in ("period", "interval", "start", "end")}
                df = ticker.history(**hist_kwargs)
            except Exception:
                df = None

        if df is None or df.empty:
            raise FileNotFoundError(
                f"No intraday data for {symbol} with interval {interval}. "
                f"Tried yf.download args: {kwargs}. Possible reasons: symbol not supported for intraday, market closed, or provider limits."
            )

        return self._clean_intraday_df(df)

    def _fetch_daily(self, symbol, start=None, end=None, interval="1d", provider_kwargs=None):
        interval = self._normalize_interval(interval)
        if interval not in self.DAILY_INTERVALS:
            raise ValueError(f"Unsupported daily interval: {interval}")

        kwargs = provider_kwargs.copy() if provider_kwargs is not None else {}
        kwargs["interval"] = "1d"
        kwargs["progress"] = False

        if start is not None:
            kwargs["start"] = pd.to_datetime(start)
            kwargs["end"] = self._infer_end_date(end)
        else:
            kwargs["period"] = kwargs.get("period", "1y")

        df = yf.download(symbol, **kwargs)
        if df is None or df.empty:
            try:
                ticker = yf.Ticker(symbol)
                hist_kwargs = {k: v for k, v in kwargs.items() if k in ("period", "interval", "start", "end")}
                df = ticker.history(**hist_kwargs)
            except Exception:
                df = None

        if df is None or df.empty:
            raise FileNotFoundError(
                f"No daily data for {symbol}. Tried yf.download args: {kwargs}."
            )

        return self._clean_daily_df(df)

    def get_daily(self, symbol, start=None, end=None, last_n=None):
        return self.daily_engine.get_symbol(symbol, start=start, end=end, last_n=last_n)

    def get_daily_direct(self, symbol, start=None, end=None, persist=False, provider_kwargs=None):
        df = self._fetch_daily(symbol, start=start, end=end, provider_kwargs=provider_kwargs)
        if persist:
            self._persist_daily(symbol, df)
        return df

    def get_intraday(self, symbol, start=None, end=None, interval="1m", provider_kwargs=None):
        cache_key = (symbol, start, end, interval)
        if self.cache is not None and cache_key in self.cache:
            return self.cache[cache_key].copy()

        df = self._fetch_intraday(symbol, start=start, end=end, interval=interval, provider_kwargs=provider_kwargs)
        if self.cache is not None:
            self.cache[cache_key] = df.copy()
        return df

    def get_intraday_direct(self, symbol, start=None, end=None, interval="1m", persist=False, provider_kwargs=None):
        df = self.get_intraday(symbol, start=start, end=end, interval=interval, provider_kwargs=provider_kwargs)
        if persist and self.intraday_store_dir is not None:
            self._persist_intraday(symbol, df)
        return df

    def get_data(self, symbol, start=None, end=None, interval="1d", last_n=None, persist=False, provider_kwargs=None):
        interval = self._normalize_interval(interval)
        if self._is_daily_interval(interval):
            try:
                return self.get_daily(symbol, start=start, end=end, last_n=last_n)
            except FileNotFoundError:
                df = self._fetch_daily(symbol, start=start, end=end, provider_kwargs=provider_kwargs)
                if persist:
                    self._persist_daily(symbol, df)
                return df

        df = self.get_intraday(symbol, start=start, end=end, interval=interval, provider_kwargs=provider_kwargs)
        if persist and self.intraday_store_dir is not None:
            self._persist_intraday(symbol, df)
        return df

    def _persist_daily(self, symbol, df):
        file_path = self.daily_engine.get_file_path(symbol)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        df.to_parquet(file_path)
        return file_path

    def list_daily_symbols(self):
        return self.daily_engine.list_symbols()

    def clear_cache(self):
        if self.cache is not None:
            self.cache = {}

    def list_intraday_symbols(self, date=None):
        if self.intraday_store_dir is None:
            return []

        symbols = set()
        base_path = os.path.join(self.intraday_store_dir)
        if date:
            date_dir = os.path.join(base_path, pd.to_datetime(date).strftime("%Y-%m-%d"))
            if os.path.exists(date_dir):
                for file_name in os.listdir(date_dir):
                    if file_name.endswith(".parquet"):
                        symbols.add(file_name.replace(".parquet", ""))
        else:
            for root, _, files in os.walk(base_path):
                for file_name in files:
                    if file_name.endswith(".parquet"):
                        symbols.add(file_name.replace(".parquet", ""))
        return sorted(symbols)
