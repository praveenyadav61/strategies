import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

# --------------------------------------------------
# 1. Define NIFTY 50 Tickers (Yahoo NSE format)
# --------------------------------------------------

nifty50_tickers = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS",
    "HINDUNILVR.NS","ITC.NS","SBIN.NS","BHARTIARTL.NS","KOTAKBANK.NS",
    "LT.NS","AXISBANK.NS","ASIANPAINT.NS","MARUTI.NS","SUNPHARMA.NS",
    "TITAN.NS","ULTRACEMCO.NS","NESTLEIND.NS","BAJFINANCE.NS","BAJAJFINSV.NS",
    "HCLTECH.NS","WIPRO.NS","ONGC.NS","POWERGRID.NS","NTPC.NS",
    "JSWSTEEL.NS","TATAMOTORS.NS","M&M.NS","ADANIPORTS.NS","COALINDIA.NS",
    "GRASIM.NS","TECHM.NS","DRREDDY.NS","INDUSINDBK.NS","HDFCLIFE.NS",
    "SBILIFE.NS","EICHERMOT.NS","DIVISLAB.NS","BRITANNIA.NS","CIPLA.NS",
    "APOLLOHOSP.NS","HEROMOTOCO.NS","UPL.NS","BAJAJ-AUTO.NS","BPCL.NS",
    "TATASTEEL.NS","LTIM.NS","SHRIRAMFIN.NS","ADANIENT.NS","PIDILITIND.NS"
]

# --------------------------------------------------
# 2. Define Date Range (Last 5 Years)
# --------------------------------------------------

end_date = datetime.today()
start_date = end_date - timedelta(days=5*365)

# --------------------------------------------------
# 3. Download Data
# --------------------------------------------------

print("Downloading NIFTY 50 data...")

data = yf.download(
    nifty50_tickers,
    start=start_date.strftime('%Y-%m-%d'),
    end=end_date.strftime('%Y-%m-%d'),
    interval="1d",
    auto_adjust=True,
    progress=True
)["Close"]

# --------------------------------------------------
# 4. Clean Data
# --------------------------------------------------

# Drop stocks with too many missing values
data = data.dropna(axis=1, thresh=int(0.95 * len(data)))

# Forward fill small gaps
data = data.fillna(method="ffill")

# Drop remaining NaNs
data = data.dropna()

print("\nDownload complete.")
print("Final dataset shape:", data.shape)
print("Start:", data.index.min().date())
print("End:", data.index.max().date())

# --------------------------------------------------
# 5. Save to CSV
# --------------------------------------------------

data.to_csv("nifty50_5yr_data.csv")

print("\nSaved as nifty50_5yr_data.csv")
