import pandas as pd
import numpy as np
import itertools
from statsmodels.tsa.stattools import adfuller
import statsmodels.api as sm
from pair_engine import backtest_pair

# =========================================
# 1. Load Data
# =========================================

data = pd.read_csv("nifty50_5yr_data.csv", index_col="Date", parse_dates=True)

print("Data Loaded:", data.shape)

# =========================================
# 2. Correlation Filter
# =========================================

correlation_matrix = data.corr()

pairs = []
correlation_threshold = 0.7

for stock1, stock2 in itertools.combinations(data.columns, 2):
    corr = correlation_matrix.loc[stock1, stock2]
    if corr > correlation_threshold:
        pairs.append((stock1, stock2, corr))

print(f"\nPairs after correlation filter (> {correlation_threshold}): {len(pairs)}")

# =========================================
# 3. Cointegration Test
# =========================================

cointegrated_pairs = []

for stock1, stock2, corr in pairs:

    df = data[[stock1, stock2]].dropna()

    y = df[stock1]
    x = df[stock2]

    X = sm.add_constant(x)
    model = sm.OLS(y, X).fit()
    beta = model.params[stock2]

    spread = y - beta * x
    p_value = adfuller(spread)[1]

    if p_value < 0.05:
        cointegrated_pairs.append((stock1, stock2, corr, p_value))

print(f"Pairs after cointegration filter (p < 0.05): {len(cointegrated_pairs)}")

# =========================================
# 4. Select Top 100 by strongest stationarity
# =========================================

cointegrated_pairs = sorted(cointegrated_pairs, key=lambda x: x[3])
top_pairs = cointegrated_pairs[:100]

print(f"\nRunning backtest on top {len(top_pairs)} pairs...")

# =========================================
# 5. Backtest Using pair_engine.py
# =========================================

results = []

for stock1, stock2, corr, p_value in top_pairs:
    try:
        result = backtest_pair(stock1, stock2, data)
        result["Correlation"] = round(corr,4)
        result["Spread_p_value"] = round(p_value,6)
        results.append(result)
        print(f"Completed: {stock1} vs {stock2}")
    except:
        print(f"Skipped: {stock1} vs {stock2}")

results_df = pd.DataFrame(results)

# =========================================
# 6. Rank by Sharpe
# =========================================

ranked = results_df.sort_values(by="Sharpe", ascending=False)

print("\n===== TOP PAIRS BY SHARPE =====")
print(ranked.head(10))

ranked.to_csv("optimized_pair_results.csv", index=False)

print("\nScan Completed.")
