import os
import pandas as pd
import yfinance as yf

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "daily")

os.makedirs(DATA_DIR, exist_ok=True)

def get_symbols():
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

    df = pd.read_csv(url)

    # 🔥 Clean column names
    df.columns = df.columns.str.strip().str.upper()

    # Debug (optional)
    # print(df.columns)

    # Filter EQ series
    if "SERIES" in df.columns:
        df = df[df["SERIES"] == "EQ"]
    else:
        print("WARNING: SERIES column not found, using all symbols")

    symbols = df["SYMBOL"].astype(str).tolist()
    symbols = [s + ".NS" for s in symbols]

    return symbols


def clean(df):
    # Flatten columns if needed
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]]

    df = df.dropna(subset=["Close"])
    df = df[~df.index.duplicated(keep="last")]
    df.sort_index(inplace=True)
    df.index.name = "Date"

    return df


def update_symbol(symbol):

    file_path = os.path.join(DATA_DIR, f"{symbol}.parquet")

    try:
        # -------------------------
        # First time download
        # -------------------------
        if not os.path.exists(file_path):
            print(f"Downloading full: {symbol}")

            df = yf.download(symbol, start="2014-01-01", progress=False)

            if df.empty:
                print(f"No data: {symbol}")
                return

        # -------------------------
        # Incremental update
        # -------------------------
        else:
            existing = pd.read_parquet(file_path)
            df_new = yf.download(symbol, period="2mo", progress=False)
            if isinstance(df_new.columns, pd.MultiIndex):
                df_new.columns = df_new.columns.get_level_values(0)
            if df_new.empty:
                print(f"No new data: {symbol}")
                return

            df = pd.concat([existing, df_new])

        # -------------------------
        # Clean
        # -------------------------
        df = clean(df)
        # -------------------------
        # Save
        # -------------------------
        df.to_parquet(file_path)

        # print(f"Saved {symbol} → {df.index[-1].date()}")

    except Exception as e:
        print(f"Error {symbol}: {e}")


if __name__ == "__main__":
    # symbols = [
    #     "RELIANCE.NS",
    #     "TCS.NS",
    #     "INFY.NS",
    #     "SBIN.NS",
    #     "IOC.NS"
    # ]
    symbols=get_symbols()
    for s in symbols:
        update_symbol(s)
    print("daily data load completed.")
    