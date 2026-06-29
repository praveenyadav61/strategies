import yfinance as yf
import pandas as pd
import numpy as np
import os

def download_market_data(tickers: dict, start_date: str, end_date: str) -> dict:
    """
    Downloads daily historical OHLCV data for a dictionary of tickers.
    """
    data_dict = {}
    for name, ticker in tickers.items():
        print(f"Downloading {name} ({ticker})...")
        try:
            df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if df.empty:
                print(f"Warning: No data found for {ticker}")
                continue
                
            # Handle multi-index columns commonly returned by new yfinance versions
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            data_dict[ticker] = df
        except Exception as e:
            print(f"Failed to download {ticker}: {e}")
            
    return data_dict

def calc_rsi(series: pd.Series, period: int) -> pd.Series:
    """Calculate Relative Strength Index (RSI) using Wilder's smoothing."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average Directional Index (ADX)."""
    up = df['High'] - df['High'].shift(1)
    down = df['Low'].shift(1) - df['Low']
    
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    
    tr = pd.concat([
        df['High'] - df['Low'], 
        np.abs(df['High'] - df['Close'].shift(1)), 
        np.abs(df['Low'] - df['Close'].shift(1))
    ], axis=1).max(axis=1)
    
    atr = pd.Series(tr).ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean() / atr)
    minus_di = 100 * (pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean() / atr)
    
    # Handle division by zero: if there's no directional movement, DX is 0.
    dx_denominator = plus_di + minus_di
    dx = (100 * np.abs(plus_di - minus_di) / dx_denominator).fillna(0)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx

def calc_natr(df: pd.DataFrame, period: int) -> pd.Series:
    """Calculate Normalized Average True Range (NATR)."""
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift(1))
    low_close = np.abs(df['Low'] - df['Close'].shift(1))
    
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    return (atr / df['Close']) * 100

def calc_gk_vol(df: pd.DataFrame, period: int = 21) -> pd.Series:
    """Calculate Garman-Klass Volatility."""
    log_hl = np.log(df['High'] / df['Low'])
    log_co = np.log(df['Close'] / df['Open'])
    gk = 0.5 * log_hl**2 - (2 * np.log(2) - 1) * log_co**2
    return np.sqrt(gk.rolling(period).mean())

def build_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Engineers features optimized for a 3-state market regime model.
    Handles non-stationarity via normalization/delta calculation.
    """
    df = df.copy()
    close = df['Close']
    
    # 1. Trend & Disparity (Normalized by baseline)
    emas = {
        10: close.ewm(span=10, adjust=False).mean(),
        21: close.ewm(span=21, adjust=False).mean(),
        50: close.ewm(span=50, adjust=False).mean(),
        200: close.ewm(span=200, adjust=False).mean()
    }
    
    # Distance from price to EMAs
    for period, ema in emas.items():
        df[f'dist_ema_{period}'] = (close - ema) / ema
        
    # EMA Spreads
    df['spread_ema_10_21'] = (emas[10] - emas[21]) / emas[21]
    df['spread_ema_21_50'] = (emas[21] - emas[50]) / emas[50]
    df['spread_ema_50_200'] = (emas[50] - emas[200]) / emas[200]
    
    # 2. Momentum
    for period in [7, 14, 28]:
        df[f'rsi_{period}'] = calc_rsi(close, period)
    df['adx_14'] = calc_adx(df, period=14)
    
    # 3. Volatility
    for period in [5, 14, 21]:
        df[f'natr_{period}'] = calc_natr(df, period)
    df['gk_vol_21'] = calc_gk_vol(df, period=21)
    
    # 4. Volume
    if 'Volume' in df.columns:
        vol = df['Volume']
        for period in [5, 20]:
            mean = vol.rolling(period).mean()
            std = vol.rolling(period).std()
            # Handle division by zero: if std is 0, z-score is 0.
            df[f'vol_zscore_{period}'] = ((vol - mean) / std).fillna(0)
            
    # 5. Sequence Tracking (Rate of Change/Delta Shifts)
    metrics_to_shift = [
        'dist_ema_10', 'dist_ema_21', 'dist_ema_50', 'dist_ema_200',
        'rsi_14', 'adx_14', 'natr_14', 'gk_vol_21'
    ]
    
    for metric in metrics_to_shift:
        df[f'{metric}_roc_1d'] = df[metric].diff(1)
        df[f'{metric}_roc_5d'] = df[metric].diff(5)
        
    # 6. Clean Data: Drop NaNs introduced by lookbacks (e.g., 200 EMA + diffs)
    df_clean = df.dropna()
    
    return df_clean

if __name__ == "__main__":
    # Dictionary of requested tickers
    # Note: Direct index tickers for Midcap 100 (^CNXMIDCAP) and Smallcap 250 (^CNXSC)
    # are currently unreliable via the yfinance API, causing download failures.
    # We are using highly correlated ETFs as proxies to ensure data availability.
    TICKERS = {
        "Nifty 50": "^NSEI",
        "Nifty Midcap 100": "MID100I.NS", # ICICI Prudential Nifty Midcap 100 ETF
        "Nifty Smallcap 250": "SMALL250.NS" # Nippon India ETF Nifty Smallcap 250
    }

    START_DATE = "2021-01-01"
    END_DATE = pd.Timestamp.today().strftime('%Y-%m-%d')

    # Test execution
    print("Starting market data ingestion pipeline...")
    market_data = download_market_data(TICKERS, START_DATE, END_DATE)

    if "^NSEI" in market_data:
        print("Building regime features for Nifty 50 (^NSEI)...")
        nsei_df = market_data["^NSEI"]
        features_df = build_regime_features(nsei_df)

        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, "nsei_regime_features.csv")
        features_df.to_csv(output_path)
        
        print(f"Pipeline complete! Engineered dataset structure: {features_df.shape}")
        print(f"Data successfully saved to: {output_path}")