from base_scanner import BaseFormationScanner

scanner = BaseFormationScanner()
bases = scanner.scan_universe()

print("\nStocks Currently Forming Base:\n")

if not bases:
    print("No strong bases found today.")
else:
    for stock in bases:
        print(stock)

print(f"\nTotal: {len(bases)}")
