from pathlib import Path

import pandas as pd
import yfinance as yf


REQUIRED_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]


def download_ohlcv(tickers: dict[str, str | list[str]], start_date: str, end_date: str | None) -> pd.DataFrame:
    frames = []
    for symbol, candidates in tickers.items():
        candidate_list = candidates if isinstance(candidates, list) else [candidates]
        best_df = pd.DataFrame()
        best_ticker = None
        for ticker in candidate_list:
            print(f"Downloading {symbol} ({ticker})...")
            try:
                df = yf.download(
                    ticker,
                    start=start_date,
                    end=end_date,
                    progress=False,
                    auto_adjust=False,
                    threads=False,
                    timeout=20,
                )
            except Exception as exc:
                print(f"Warning: download failed for {symbol} ({ticker}): {exc}")
                df = pd.DataFrame()
            if not df.empty and len(df) > len(best_df):
                best_df = df
                best_ticker = ticker
        if best_df.empty:
            print(f"Warning: no rows returned for {symbol} from candidates {candidate_list}")
            continue
        df = best_df
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        df["symbol"] = symbol
        df["source_ticker"] = best_ticker
        print(f"Selected {symbol} source {best_ticker} with {len(df)} rows.")
        frames.append(df)

    if not frames:
        raise RuntimeError("No market data was downloaded. Check network access or ticker availability.")

    data = pd.concat(frames, ignore_index=True)
    data["Date"] = pd.to_datetime(data["Date"]).dt.tz_localize(None)
    return data[["symbol", "source_ticker", *REQUIRED_COLUMNS]]


def write_raw_data(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.sort_values(["symbol", "Date"]).to_csv(output_path, index=False)


def load_raw_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["Date"])
    missing = set(["symbol", *REQUIRED_COLUMNS]) - set(df.columns)
    if missing:
        raise ValueError(f"Raw data missing required columns: {sorted(missing)}")
    if "source_ticker" not in df.columns:
        df["source_ticker"] = df["symbol"]
    return df.sort_values(["symbol", "Date"]).reset_index(drop=True)
