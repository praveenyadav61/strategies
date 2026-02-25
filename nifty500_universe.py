import requests
import pandas as pd
from io import StringIO


class Nifty500Universe:

    NSE_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

    def get_symbols(self):
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(self.NSE_URL, headers=headers)
        response.raise_for_status()

        df = pd.read_csv(StringIO(response.text))

        symbols = df["Symbol"].tolist()
        yahoo_symbols = [symbol + ".NS" for symbol in symbols]

        return yahoo_symbols
