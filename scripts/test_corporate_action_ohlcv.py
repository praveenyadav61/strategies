"""Live audit of split/bonus-adjusted NSE OHLCV from yfinance and Upstox.

Default case:
    KRISHANA had a 5-for-1 split effective 2026-07-03.

Run:
    python scripts/test_corporate_action_ohlcv.py

Test another NSE action:
    python scripts/test_corporate_action_ohlcv.py ^
      --symbol SYMBOL.NS ^
      --upstox-key "NSE_EQ|NEW_ISIN" ^
      --event-date YYYY-MM-DD ^
      --ratio 5
"""

import argparse
from datetime import timedelta
from urllib.parse import quote

import pandas as pd
import requests
import yfinance as yf


OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def flatten_yfinance_columns(frame):
    frame = frame.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    frame.index.name = "Date"
    return frame


def fetch_yfinance(symbol, start, end, auto_adjust):
    frame = yf.download(
        symbol,
        start=start,
        end=end + timedelta(days=1),  # yfinance end is exclusive
        interval="1d",
        auto_adjust=auto_adjust,
        actions=True,
        repair=True,
        progress=False,
    )
    if frame.empty:
        raise AssertionError(f"yfinance returned no data for {symbol}")
    return flatten_yfinance_columns(frame)


def fetch_upstox(instrument_key, start, end):
    encoded_key = quote(instrument_key, safe="")
    url = (
        "https://api.upstox.com/v3/historical-candle/"
        f"{encoded_key}/days/1/{end:%Y-%m-%d}/{start:%Y-%m-%d}"
    )
    response = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
    response.raise_for_status()
    candles = response.json()["data"]["candles"]
    if not candles:
        raise AssertionError(f"Upstox returned no data for {instrument_key}")

    frame = pd.DataFrame(
        candles,
        columns=["Date", "Open", "High", "Low", "Close", "Volume", "Open Interest"],
    )
    frame["Date"] = pd.to_datetime(frame["Date"]).dt.tz_localize(None).dt.normalize()
    return frame.set_index("Date").sort_index()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="KRISHANA.NS")
    parser.add_argument("--upstox-key", default="NSE_EQ|INE506W01020")
    parser.add_argument("--event-date", type=pd.Timestamp, default=pd.Timestamp("2026-07-03"))
    parser.add_argument("--ratio", type=float, default=5.0)
    parser.add_argument("--window-days", type=int, default=7)
    args = parser.parse_args()

    start = args.event_date - timedelta(days=args.window_days)
    end = args.event_date + timedelta(days=args.window_days)

    adjusted = fetch_yfinance(args.symbol, start, end, auto_adjust=True)
    unadjusted = fetch_yfinance(args.symbol, start, end, auto_adjust=False)
    upstox = fetch_upstox(args.upstox_key, start, end)

    common = adjusted[OHLCV].join(
        upstox[OHLCV],
        how="inner",
        lsuffix="_Yahoo",
        rsuffix="_Upstox",
    )
    if common.empty:
        raise AssertionError("Providers returned no common trading dates")

    price_diff = max(
        (common[f"{column}_Yahoo"] - common[f"{column}_Upstox"]).abs().max()
        for column in ["Open", "High", "Low", "Close"]
    )
    volume_diff = (
        (common["Volume_Yahoo"] - common["Volume_Upstox"]).abs()
        / common["Volume_Upstox"].replace(0, pd.NA)
    ).max()

    split_value = 0.0
    if "Stock Splits" in adjusted.columns and args.event_date in adjusted.index:
        split_value = float(adjusted.at[args.event_date, "Stock Splits"])

    before = adjusted.loc[adjusted.index < args.event_date]
    on_or_after = adjusted.loc[adjusted.index >= args.event_date]
    if before.empty or on_or_after.empty:
        raise AssertionError("Need trading data on both sides of the event")
    event_gap = abs(float(on_or_after.iloc[0]["Open"] / before.iloc[-1]["Close"]) - 1)

    volume_unchanged_by_auto_adjust = adjusted["Volume"].equals(unadjusted["Volume"])
    checks = {
        "yfinance reported expected action ratio": abs(split_value - args.ratio) < 1e-6,
        "Yahoo and Upstox OHLC agree": price_diff <= 0.20,
        "Yahoo and Upstox volume agree": volume_diff <= 0.002,
        "no artificial split-sized price gap": event_gap <= 0.35,
        "auto_adjust did not double-adjust volume": volume_unchanged_by_auto_adjust,
    }

    print(common.to_string())
    print(f"\nMaximum OHLC difference : {price_diff:.4f}")
    print(f"Maximum volume difference: {volume_diff:.4%}")
    print(f"Adjusted event-day gap   : {event_gap:.2%}")
    print(f"Reported action ratio    : {split_value:g}")
    for label, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'} - {label}")

    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
