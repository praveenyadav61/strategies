import pandas as pd
import numpy as np

def read_data(ticker,start_date=None,end_date=None):
    df=pd.read_parquet(f"data/market_data/{ticker}.parquet")
    if start_date or end_date is None:
        start_date=df['Date'].min()
        end_date=df['Date'].max()
    df=df.loc[start_date:end_date]
    return df