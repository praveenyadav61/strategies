import sys
import os
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from modular_base_scanner import CupScanner, DEFAULT_PARAMS


DATA_DIR = ROOT_DIR / "data" / "daily"
OUTPUT_FILE = ROOT_DIR / "data" / "daily_breakouts.csv"
NOTIFICATION_FILE = ROOT_DIR / "data" / "daily_breakout_notifications.txt"


def load_daily_price(symbol):
    symbol = symbol.strip()
    path = DATA_DIR / f"{symbol}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Daily file not found: {path}")
    df = pd.read_parquet(path)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    return df.sort_index()


def detect_breakouts(base_df):
    breakouts = []

    for _, row in base_df.iterrows():
        symbol = row["Symbol"]
        pivot_price = float(row["pivot_price"])
        pivot_index = row.get("pivot_index")

        try:
            daily_df = load_daily_price(symbol)
        except FileNotFoundError:
            continue

        if len(daily_df) < 2:
            continue

        today = daily_df.index[-1]
        close_today = float(daily_df["Close"].iloc[-1])
        close_prev = float(daily_df["Close"].iloc[-2])
        day_move = close_today - close_prev
        day_move_pct = (day_move / close_prev) * 100 if close_prev else float("nan")

        if close_prev <= pivot_price < close_today:
            breakouts.append(
                {
                    "date": today.date(),
                    "symbol": symbol,
                    "pivot_price": pivot_price,
                    "pivot_index": str(pivot_index),
                    "pivot_index_pos": int(row.get("pivot_index_pos", -1)),
                    "close_prev": close_prev,
                    "close_today": close_today,
                    "day_move": day_move,
                    "day_move_pct": day_move_pct,
                    "depth": float(row.get("Depth", float("nan"))),
                    "recovery": float(row.get("Recovery", float("nan"))),
                    "ath": float(row.get("ATH", float("nan"))),
                    "scan_date": pd.Timestamp.now(),
                }
            )

    return pd.DataFrame(breakouts)


def load_existing_breakouts(path):
    if path.exists():
        return pd.read_csv(path, parse_dates=["date", "scan_date"])
    return pd.DataFrame()


def save_breakouts(df, path):
    if df.empty:
        return
    # force datetime conversion
    df["date"] = pd.to_datetime(df["date"])
    df["scan_date"] = pd.to_datetime(df["scan_date"])
    # remove duplicates
    df = df.drop_duplicates(
        subset=["symbol", "pivot_price"],
        keep="last"
    )
    # latest first
    df = df.sort_values(
        by=["date", "symbol"],
        ascending=[False, True]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)

def notify_new_breakouts(breakout_df):
    import requests
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not found.")
        return
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    # no breakouts
    if breakout_df.empty:
        message = (
            f"Daily Pivot Breakouts\n"
            f"{now}\n\n"
            f"No new breakouts detected today."
        )
    else:
        lines = [
            f"Daily Pivot Breakouts",
            f"{now}",
            ""
        ]

        for _, row in breakout_df.iterrows():

            breakout_pct = (
                (row["close_today"] - row["pivot_price"])
                / row["pivot_price"]
            ) * 100
            day_move = row.get("day_move", row["close_today"] - row["close_prev"])
            day_move_pct = row.get(
                "day_move_pct",
                (day_move / row["close_prev"]) * 100 if row["close_prev"] else float("nan"),
            )

            lines.append(
                f"• {row['symbol']}\n"
                f"Pivot: {row['pivot_price']:.2f}\n"
                f"Previous Close: {row['close_prev']:.2f}\n"
                f"Close: {row['close_today']:.2f} "
                f"({breakout_pct:.2f}% above pivot)\n"
                f"Day Move: {day_move:+.2f} ({day_move_pct:+.2f}%)\n"
            )

        message = "\n".join(lines)

    print(message)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:
        response = requests.post(url, data=payload, timeout=10)

        if response.status_code == 200:
            print("Telegram notification sent.")
        else:
            print("Telegram notification failed:", response.text)

    except Exception as e:
        print("Telegram error:", e)

def run_daily_breakout_scan(debug=False):
    scanner = CupScanner(DEFAULT_PARAMS, debug=debug)
    base_df = scanner.run_scan()

    # uncomment below
    if base_df.empty:
        print("No cup bases found.")
        return

    breakout_df = detect_breakouts(base_df)
    if breakout_df.empty:
        notify_new_breakouts(breakout_df)
        print("No daily pivot breakouts detected today.")
        return
        
    
    #comment 
    # breakout_df = pd.DataFrame([
    #     {
    #         "date": pd.Timestamp.today(),
    #         "symbol": "RELIANCE",
    #         "pivot_price": 2450.0,
    #         "pivot_index": "2026-04-12",
    #         "pivot_index_pos": 45,
    #         "close_prev": 2440.0,
    #         "close_today": 2485.0,
    #         "depth": 0.22,
    #         "recovery": 0.91,
    #         "ath": 2600.0,
    #         "scan_date": pd.Timestamp.now(),
    #     }
    # ])


    existing_df = load_existing_breakouts(OUTPUT_FILE)
    combined = pd.concat([existing_df, breakout_df], ignore_index=True)
    save_breakouts(combined, OUTPUT_FILE)
    notify_new_breakouts(breakout_df)
    print(f"Detected {len(breakout_df)} breakout(s) today.")
    print(f"Saved breakout file: {OUTPUT_FILE}")


if __name__ == "__main__":
    run_daily_breakout_scan()
