import yfinance as yf
import pandas as pd
import os
import time

CSV_PATH = "data/eps_all_stocks.csv"


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

def get_nse_symbols():
    # You should replace this with your own list source if you have one
    # Example minimal list
    # return ["RELIANCE.NS", "TCS.NS", "INFY.NS"]
    return get_symbols()


def fetch_eps(symbol):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.quarterly_earnings

        if df is None or df.empty:
            return None

        df = df.reset_index()
        df.columns = ["date", "eps"]
        df["symbol"] = symbol

        df = df[["symbol", "date", "eps"]]
        df = df.sort_values("date")

        # keep last 12 quarters
        df = df.tail(12)

        return df

    except Exception as e:
        print(f"Error for {symbol}: {e}")
        return None


def load_existing():
    if os.path.exists(CSV_PATH):
        return pd.read_csv(CSV_PATH, parse_dates=["date"])
    return pd.DataFrame(columns=["symbol", "date", "eps"])


def update_eps():
    symbols = get_nse_symbols()
    existing_df = load_existing()

    all_new_data = []

    for symbol in symbols:
        print(f"Processing {symbol}")

        df = fetch_eps(symbol)
        if df is None:
            continue

        all_new_data.append(df)
        time.sleep(0.2)  # avoid rate limit

    if not all_new_data:
        print("No new data fetched")
        return

    new_df = pd.concat(all_new_data, ignore_index=True)

    # Merge with existing
    final_df = pd.concat([existing_df, new_df], ignore_index=True)

    # Remove duplicates
    final_df = final_df.drop_duplicates(subset=["symbol", "date"])

    # Keep only last 12 quarters per stock
    final_df = (
        final_df.sort_values("date")
        .groupby("symbol")
        .tail(12)
        .reset_index(drop=True)
    )

    # Save
    os.makedirs("data", exist_ok=True)
    final_df.to_csv(CSV_PATH, index=False)

    print(f"Updated EPS data saved to {CSV_PATH}")


if __name__ == "__main__":
    update_eps()