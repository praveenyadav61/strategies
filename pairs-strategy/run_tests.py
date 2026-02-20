import pandas as pd
from pair_engine import backtest_pair

data = pd.read_csv("bank_pair_data.csv", index_col="Date", parse_dates=True)

pairs_to_test = [
    ("AXISBANK", "ICICI"),
    ("SBIN", "ICICI"),
    ("BANKBEES", "ICICI"),
    ("BANKBEES", "SBIN")
]

results = []

for stock1, stock2 in pairs_to_test:
    result = backtest_pair(stock1, stock2, data)
    results.append(result)

results_df = pd.DataFrame(results)
print("\n===== PAIR TEST RESULTS =====")
print(results_df)
