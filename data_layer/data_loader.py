import os
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed


class DataLoader:

    def __init__(self, provider, data_dir="data/daily1", max_workers=6):
        self.provider = provider
        self.data_dir = data_dir
        self.max_workers = max_workers
        os.makedirs(self.data_dir, exist_ok=True)

    def get_file_path(self, symbol):
        return os.path.join(self.data_dir, f"{symbol}.parquet")

    def clean_df(self, df):
        df = df[["Open", "High", "Low", "Close", "Volume"]]
        df = df.dropna(subset=["Close"])
        df = df[~df.index.duplicated(keep="last")]
        df.sort_index(inplace=True)
        df.index.name = "Date"
        return df

    def update_symbol(self, symbol, start_date="2014-01-01"):

        file_path = self.get_file_path(symbol)
        today = datetime.today().strftime("%Y-%m-%d")

        try:
            # First time
            if not os.path.exists(file_path):
                df = self.provider.fetch_data(symbol, start=start_date, end=today)

                if df.empty:
                    return {"symbol": symbol, "status": "no_data"}

            else:
                existing = pd.read_parquet(file_path)

                last_date = existing.index[-1]
                new_start = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

                # 🔥 Hybrid fetch
                df_new = self.provider.fetch_data(symbol, period="2mo")

                # fallback if needed
                if df_new.empty or df_new.index.max() <= last_date:
                    df_new = self.provider.fetch_data(symbol, start=new_start, end=today)

                if df_new.empty:
                    return {"symbol": symbol, "status": "no_update"}

                df = pd.concat([existing, df_new])

            df = self.clean_df(df)
            df.to_parquet(file_path)

            return {
                "symbol": symbol,
                "status": "updated",
                "latest": str(df.index[-1].date())
            }

        except Exception as e:
            return {"symbol": symbol, "status": "error"}

    def update_universe(self, symbols):
        total = len(symbols)
        completed = 0
        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(self.update_symbol, s) for s in symbols]

            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                print(f"Updated {result['symbol']}: {result['status'], result['latest'] }", end=" | ")
                completed += 1
                percent = (completed / total) * 100

                if completed % 20 == 0 or completed == total:
                    print(f"Progress: {completed}/{total} ({percent:.1f}%)", end="\r")

        print()

        updated = sum(1 for r in results if r["status"] == "updated")
        failed = sum(1 for r in results if r["status"] == "error")

        print(f"Updated: {updated}")
        print(f"Failed: {failed}")

        return results