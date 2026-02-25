from ema_trend_scanner import EMATrendScanner

scanner = EMATrendScanner()
stocks = scanner.scan_universe()

print("\nStocks Respecting 10 EMA Trend:\n")

if not stocks:
    print("None found today.")
else:
    for s in stocks:
        print(s)

print(f"\nTotal: {len(stocks)}")
