import os
import pandas as pd
import yfinance as yf
from tqdm import tqdm

def fetch_and_save_static_data():
    """
    Fetches static company information for all tickers in the data/daily directory
    and saves it to a single Parquet file in data/static/.
    """
    data_path = "data/daily/"
    output_path = "data/static/"
    output_file = os.path.join(output_path, "static_data.parquet")

    if not os.path.exists(data_path):
        print(f"Error: Data directory not found at '{data_path}'")
        return

    if not os.path.exists(output_path):
        os.makedirs(output_path)
        print(f"Created directory: {output_path}")

    # 1. Get all ticker symbols from the data directory
    all_files = [f for f in os.listdir(data_path) if f.endswith('.parquet')]
    symbols = [f.replace('.parquet', '') for f in all_files]

    if not symbols:
        print(f"No ticker files found in '{data_path}'")
        return

    # To update all tickers every time, we will simply fetch for all symbols found.
    # This will overwrite the existing file with fresh data for all tickers.
    symbols_to_fetch = symbols
    all_fetched_data = []

    print(f"Fetching/updating static data for {len(symbols_to_fetch)} tickers...")

    # 2. Iterate through all symbols and fetch data
    for symbol in tqdm(symbols_to_fetch, desc="Fetching Ticker Info"):
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            # Check if we got valid data before proceeding (e.g., for delisted stocks)
            if info and info.get('marketCap') is not None:
                # Ensure the symbol is in the dictionary, as it's our primary key
                info['symbol'] = symbol
                all_fetched_data.append(info)
            else:
                all_fetched_data.append({'symbol': symbol, 'error': 'Invalid or no data from API'})
        except Exception as e:
            # If a ticker fails, we still add a record to know it was attempted
            all_fetched_data.append({'symbol': symbol, 'error': f'Failed to fetch: {e}'})

    if not all_fetched_data:
        print("No data was fetched during the run.")
        return

    # 3. Create a new DataFrame from all the fetched data
    df = pd.DataFrame(all_fetched_data)

    # 4. Process date columns (convert from epoch if they exist)
    date_cols_seconds = [
        'exDividendDate', 'lastFiscalYearEnd', 'nextFiscalYearEnd',
        'mostRecentQuarter', 'lastSplitDate', 'earningsTimestamp',
        'lastDividendDate'
    ]
    date_cols_ms = ['firstTradeDateMilliseconds']

    for col in date_cols_seconds:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], unit='s', errors='coerce').dt.date

    for col in date_cols_ms:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], unit='ms', errors='coerce').dt.date

    # Select and reorder columns based on your example and common use cases
    desired_columns = [
        'symbol', 'shortName', 'longName', 'industry', 'sector', 'marketCap',
        'country', 'website', 'longBusinessSummary', 'fullTimeEmployees',
        'fiftyTwoWeekHigh', 'fiftyTwoWeekLow', 'fiftyDayAverage', 'twoHundredDayAverage',
        'trailingPE', 'forwardPE', 'trailingEps', 'forwardEps',
        'bookValue', 'priceToBook', 'dividendRate', 'dividendYield', 'payoutRatio',
        'beta', 'sharesOutstanding', 'floatShares', 'heldPercentInsiders',
        'heldPercentInstitutions', 'lastSplitFactor', 'lastSplitDate',
        'earningsQuarterlyGrowth', 'revenueGrowth', 'financialCurrency',
        'exDividendDate', 'lastFiscalYearEnd', 'firstTradeDateMilliseconds'
    ]

    final_columns = [col for col in desired_columns if col in df.columns]
    df_final = df[final_columns].copy()

    # 4.5 Clean numeric columns to handle non-finite values ('Infinity', etc.)
    # that cause errors when saving to Parquet.
    numeric_cols = [
        'marketCap', 'fullTimeEmployees', 'fiftyTwoWeekHigh', 'fiftyTwoWeekLow',
        'fiftyDayAverage', 'twoHundredDayAverage', 'trailingPE', 'forwardPE',
        'trailingEps', 'forwardEps', 'bookValue', 'priceToBook', 'dividendRate',
        'dividendYield', 'payoutRatio', 'beta', 'sharesOutstanding', 'floatShares',
        'heldPercentInsiders', 'heldPercentInstitutions', 'earningsQuarterlyGrowth',
        'revenueGrowth'
    ]

    for col in numeric_cols:
        if col in df_final.columns:
            # Coerce errors will turn non-numeric strings (like 'Infinity') into NaN
            df_final[col] = pd.to_numeric(df_final[col], errors='coerce')

    # 5. Save to Parquet
    df_final.to_parquet(output_file, index=False)
    print(f"\nSuccessfully saved static data for {len(df_final)} tickers to {output_file}")

if __name__ == "__main__":
    fetch_and_save_static_data()