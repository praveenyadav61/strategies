import yfinance as yf


class YahooDataProvider:

    def fetch_data(self, symbol, start, end):
        df = yf.download(symbol, start=start, end=end, progress=False)
        df.index.name = "Date"
        return df
