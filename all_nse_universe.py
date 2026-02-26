import requests
import pandas as pd
from io import StringIO


class AllNSEUniverse:

    NSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

    def get_symbols(self):

        headers = {"User-Agent": "Mozilla/5.0"}

        response = requests.get(self.NSE_URL, headers=headers)
        response.raise_for_status()

        df = pd.read_csv(StringIO(response.text))

        # Clean column names (important!)
        df.columns = df.columns.str.strip().str.upper()

        # Print columns once to verify
        print("Available columns:", df.columns.tolist())

        # Check correct column names
        if "SERIES" in df.columns:
            df = df[df["SERIES"] == "EQ"]
        else:
            print("Warning: SERIES column not found. Using all rows.")

        if "SYMBOL" in df.columns:
            symbols = df["SYMBOL"].tolist()
        else:
            raise Exception("SYMBOL column not found in NSE file.")

        yahoo_symbols = [symbol + ".NS" for symbol in symbols]

        return yahoo_symbols