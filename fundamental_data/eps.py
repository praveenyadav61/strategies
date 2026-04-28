import os
import time
import requests
import pandas as pd
import numpy as np
from io import StringIO

# -------------------------
# CONFIG
# -------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "quarterly")
os.makedirs(DATA_DIR, exist_ok=True)

FULL_FILE = os.path.join(DATA_DIR, "eps_full.csv")
PROCESSED_FILE = os.path.join(DATA_DIR, "eps_processed.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


# -------------------------
# GET SYMBOLS
# -------------------------
def get_symbols():
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        df = pd.read_csv(StringIO(response.text))
        df.columns = df.columns.str.strip().str.upper()

        if "SERIES" in df.columns:
            df = df[df["SERIES"] == "EQ"]

        return [s + ".NS" for s in df["SYMBOL"].astype(str)]

    except Exception as e:
        print(f"[ERROR] Fetching symbols failed: {e}")
        return []

# -------------------------
# GET EPS DATA (WITH RETRY)
# -------------------------
def get_eps_data(full_symbol, retries=2):
    clean_slug = full_symbol.replace(".NS", "")

    urls = [
        f"https://www.screener.in/company/{clean_slug}/consolidated/",
        f"https://www.screener.in/company/{clean_slug}/"
    ]

    for attempt in range(retries):
        for url in urls:
            try:
                response = requests.get(url, headers=HEADERS, timeout=10)

                if response.status_code != 200:
                    continue

                tables = pd.read_html(StringIO(response.text))
                df = tables[0]

                eps_row = df[df.iloc[:, 0].str.contains('EPS in Rs', case=False, na=False)]
                # print("eps row for ",full_symbol,eps_row)
                if eps_row.empty:
                    return None

                eps = eps_row.iloc[0, 1:]

                # FIXED DATE PARSING
                dates = pd.to_datetime(df.columns[1:], format="%b %Y", errors="coerce")
                dates = dates + pd.offsets.MonthEnd(0)

                result = pd.DataFrame({
                    "symbol": clean_slug,
                    "date": dates,
                    "eps": pd.to_numeric(eps.values, errors="coerce")
                })

                result = result.dropna(subset=["date", "eps"])
                return result

            except Exception:
                continue

        time.sleep(1)

    print(f"[WARN] Failed: {full_symbol}")
    return None

# -------------------------
# UPDATE FULL DATA
# -------------------------
def update_full_data(new_df):
    if os.path.exists(FULL_FILE):
        existing = pd.read_csv(FULL_FILE)
        existing["date"] = pd.to_datetime(existing["date"], errors="coerce")

        combined = pd.concat([existing, new_df])

        combined = combined.drop_duplicates(
            subset=["symbol", "date"],
            keep="last"
        )
    else:
        combined = new_df

    combined = combined.sort_values(["symbol", "date"])

    combined.to_csv(FULL_FILE, index=False)
    return combined

# -------------------------
# CREATE PROCESSED DATA
# -------------------------
def create_processed_data(df):
    df = df.sort_values("date").groupby("symbol").tail(12)

    df["log_eps"] = df["eps"].apply(lambda x: np.log(x) if x > 0 else None)

    return df.sort_values(["symbol", "date"])

# -------------------------
# MAIN
# -------------------------
def main():
    symbols = get_symbols()
    if not symbols:
        print("[ERROR] No symbols fetched")
        return

    # For testing (remove later)
    # symbols = symbols[:10]

    all_data = []

    for sym in symbols[0:50]:
        print(f"[INFO] Processing {sym}")

        df = get_eps_data(sym)

        if df is not None:
            all_data.append(df)

        time.sleep(0.8)

    if not all_data:
        print("[ERROR] No EPS data collected")
        return

    new_df = pd.concat(all_data, ignore_index=True)

    full_df = update_full_data(new_df)
    processed_df = create_processed_data(full_df)

    processed_df.to_csv(PROCESSED_FILE, index=False)

    print("[SUCCESS] EPS data updated")


if __name__ == "__main__":
    main()