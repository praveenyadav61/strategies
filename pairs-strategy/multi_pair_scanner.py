import pandas as pd
import itertools
from pair_engine import backtest_pair

# -----------------------------
# 1. Load Data
# -----------------------------

data = pd.read_csv("bank_pair_data.csv", index_col="Date", parse_dates=True)

# -----------------------------
# 2. Define Universe
# -----------------------------

bank_universe = [
    "HDFC",
    "ICICI",
    "AXISBANK",
    "SBIN",
    "KOTAK",
    "INDUSIND",
    "BANKBEES"
]

# -----------------------------
# 3. Generate All Pair Combinations
# -----------------------------

pairs = list(itertools.combinations(bank_universe, 2))

results = []

print(f"Testing {len(pairs)} pairs...\n")

# -----------------------------
# 4. Run Scanner
# -----------------------------

for stock1, stock2 in pairs:
    try:
        result = backtest_pair(stock1, stock2, data)
        results.append(result)
        print(f"Completed: {stock1} vs {stock2}")
    except Exception as e:
        print(f"Skipped {stock1} vs {stock2} due to error")

# -----------------------------
# 5. Create Results Table
# -----------------------------

results_df = pd.DataFrame(results)

# Filter only statistically valid pairs
valid_pairs = results_df[results_df["Spread_p_value"] < 0.05]

# Rank by Sharpe
ranked_pairs = valid_pairs.sort_values(by="Sharpe", ascending=False)

print("\n===== TOP COINTEGRATED PAIRS =====")
print(ranked_pairs)

# Optional: Save results
results_df.to_csv("all_pair_results.csv", index=False)
ranked_pairs.to_csv("top_pairs.csv", index=False)

print("\nScan Complete.")
