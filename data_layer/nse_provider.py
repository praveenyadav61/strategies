import pandas as pd
from nsepython import equity_history


class NSEDataProvider:

    def fetch_data(self, symbol, start, end):
        try:
            start = pd.to_datetime(start).strftime("%d-%m-%Y")
            end = pd.to_datetime(end).strftime("%d-%m-%Y")

            df = equity_history(symbol.replace(".NS", ""), "EQ", start, end)

            if df.empty:
                return df

            df = df.rename(columns={
                "CH_OPENING_PRICE": "Open",
                "CH_TRADE_HIGH_PRICE": "High",
                "CH_TRADE_LOW_PRICE": "Low",
                "CH_CLOSING_PRICE": "Close",
                "CH_TOT_TRADED_QTY": "Volume"
            })

            df["Date"] = pd.to_datetime(df["CH_TIMESTAMP"])
            df.set_index("Date", inplace=True)

            return df[["Open", "High", "Low", "Close", "Volume"]]

        except Exception as e:
            print(f"NSE failed {symbol}: {e}")
            return pd.DataFrame()