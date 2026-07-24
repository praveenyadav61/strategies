import os
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
from io import StringIO

# ==============================
# CONFIG
# ==============================
DATA_DIR = "data"
WINDOW = 500
Z_THRESHOLD = 2
MIN_AVG_VOLUME = 500_000

TELEGRAM_BOT_TOKEN = "8364001439:AAEMzJixxvFXvojZ6u8JLwSsb1A1B9sN5Lc" 
TELEGRAM_CHAT_ID = "813867421" 


# ==============================
# TELEGRAM
# ==============================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    })


# ==============================
# DELIVERY FETCH
# ==============================
def fetch_delivery_for_date(target_date):
    headers = {"User-Agent": "Mozilla/5.0"}

    for i in range(5):
        d = target_date - timedelta(days=i)
        ds = d.strftime("%d%m%Y")

        url = f"https://archives.nseindia.com/archives/equities/mto/MTO_{ds}.DAT"

        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                continue

            lines = res.text.splitlines()

            start_idx = None
            for idx, line in enumerate(lines):
                if line.startswith("Record Type"):
                    start_idx = idx + 1
                    break

            if start_idx is None:
                continue

            data = []
            for line in lines[start_idx:]:
                parts = line.split(",")
                if len(parts) < 7:
                    continue

                symbol = parts[2].strip()
                try:
                    delivery_pct = float(parts[-1])
                except:
                    continue

                data.append((symbol, delivery_pct))

            print(f"Using delivery: {ds}")
            return dict(data), d

        except Exception:
            continue

    print("No delivery data found")
    return {}, None


# ==============================
# METRICS
# ==============================
def compute_metrics(df):
    df = df.copy()

    df["vol_mean"] = df["Volume"].rolling(WINDOW).mean()
    df["vol_std"] = df["Volume"].rolling(WINDOW).std()
    df["vol_std"] = df["vol_std"].replace(0, np.nan)

    df["volume_zscore"] = (df["Volume"] - df["vol_mean"]) / df["vol_std"]
    df["volume_ratio"] = df["Volume"] / df["vol_mean"]

    df["range_pct"] = (df["High"] - df["Low"]) / df["Close"] * 100
    df["price_change_pct"] = df["Close"].pct_change() * 100

    df["close_strength"] = (df["Close"] - df["Low"]) / (df["High"] - df["Low"])
    df["close_strength"] = df["close_strength"].replace([np.inf, -np.inf], np.nan)

    df["volume_percentile"] = df["Volume"].rolling(WINDOW).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1]
    ) * 100

    return df


# ==============================
# DETECT
# ==============================
def detect(df, symbol, delivery_map, delivery_date):
    latest = df.iloc[-1]

    if pd.isna(latest["volume_zscore"]) or latest["vol_mean"] < MIN_AVG_VOLUME:
        return None

    if latest["volume_zscore"] < Z_THRESHOLD:
        return None

    base_symbol = symbol.replace(".NS", "")

    delivery = None
    if delivery_date is not None and base_symbol in delivery_map:
        delivery = delivery_map[base_symbol]

    return {
        "Symbol": symbol,
        "Volume Z-Score": round(latest["volume_zscore"], 2),
        "Volume Ratio": round(latest["volume_ratio"], 2),
        "Volume Percentile": round(latest["volume_percentile"], 1),
        "Close Strength (CLV)": round(latest["close_strength"], 2),
        "Range %": round(latest["range_pct"], 2),
        "Price Change %": round(latest["price_change_pct"], 2),
        "Close Price": round(latest["Close"], 2),
        "Delivery %": round(delivery, 1) if delivery is not None else None
    }


# ==============================
# SCAN
# ==============================
def run():
    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".parquet")]

    if not files:
        return []

    sample = pd.read_parquet(os.path.join(DATA_DIR, files[0]))
    last_date = sample.index[-1].to_pydatetime()

    delivery_map, delivery_date = fetch_delivery_for_date(last_date)

    results = []

    for f in files:
        symbol = f.replace(".parquet", "")

        try:
            df = pd.read_parquet(os.path.join(DATA_DIR, f))

            if len(df) < WINDOW:
                continue

            df = compute_metrics(df)

            signal = detect(df, symbol, delivery_map, delivery_date)

            if signal:
                results.append(signal)

        except Exception as e:
            print(symbol, e)

    return results


# ==============================
# FORMAT
# ==============================
def format_msg(results):
    if not results:
        return "No volume bursts today."

    results = sorted(results, key=lambda x: x["Volume Z-Score"], reverse=True)

    msg = "📊 *Volume Burst Alert*\n\n"

    for r in results[:20]:
        msg += (
            f"*{r['Symbol']}*\n"
            f"Z:{r['Volume Z-Score']} | VR:{r['Volume Ratio']} | %ile:{r['Volume Percentile']}\n"
            f"CLV:{r['Close Strength (CLV)']} | Range:{r['Range %']}%\n"
            f"Chg:{r['Price Change %']}% | Close:{r['Close Price']}\n"
        )

        if r["Delivery %"] is not None:
            msg += f"Delivery:{r['Delivery %']}%\n"

        msg += "\n"

    return msg

def print_table(results):
    if not results:
        print("No volume bursts today.")
        return

    df = pd.DataFrame(results)

    df = df.sort_values(by="Volume Z-Score", ascending=False)

    print("\n=== Volume Burst Table ===\n")
    print(df.to_string(index=False))
# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    results = run()

    print_table(results)

    msg = format_msg(results)

    print(msg)

    # send_telegram(msg)