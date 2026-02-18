import yfinance as yf
import pandas as pd

# Define tickers
tickers = [
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "AXISBANK.NS",
    "SBIN.NS",
    "KOTAKBANK.NS",
    "INDUSINDBK.NS",
    "BANKBEES.NS"
]

# Download 10 years of daily data
data = yf.download(
    tickers,
    start="2015-01-01",
    end=None,
    interval="1d",
    auto_adjust=True
)

# Keep only Close prices
close_prices = data["Close"]

# Drop missing values
close_prices = close_prices.dropna()

# Rename columns
close_prices.columns = ["HDFC",
    "ICICI",
    "AXISBANK",
    "SBIN",
    "KOTAK",
    "INDUSIND",
    "BANKBEES"]

# Save to CSV
close_prices.to_csv("bank_pair_data.csv")

print("Data downloaded successfully!")
# print(close_prices.tail())
# print(len(close_prices))
# print(close_prices.index.duplicated().sum())
# print(close_prices.describe())

# print(close_prices.corr())

# Expected: Correlation likely > 0.75
# below 0.6 → warning sign.




