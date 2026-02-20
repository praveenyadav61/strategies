import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
import matplotlib
import matplotlib.pyplot as plt
matplotlib.use('Agg')

# -------------------------
# 1. Load Data
# -------------------------

data = pd.read_csv("bank_pair_data.csv", index_col="Date", parse_dates=True)

hdfc = data["HDFC"]
icici = data["ICICI"]

print("Data loaded successfully\n")

# -------------------------
# 2. ADF Test Function
# -------------------------

def adf_test(series, name):
    result = adfuller(series)
    print(f"ADF Test for {name}")
    print(f"ADF Statistic: {result[0]}")
    print(f"p-value: {result[1]}")
    print("----------------------------\n")

# -------------------------
# 3. Check if price series are non-stationary
# -------------------------

adf_test(hdfc, "HDFC Price")
adf_test(icici, "ICICI Price")

# -------------------------
# 4. Run Regression
# HDFC = beta * ICICI + error
# -------------------------

X = sm.add_constant(icici)
model = sm.OLS(hdfc, X).fit()

beta = model.params["ICICI"]

print(f"Hedge Ratio (beta): {beta}\n")

# -------------------------
# 5. Extract Residuals (Spread)
# -------------------------

spread = hdfc - beta * icici

# -------------------------
# 6. ADF Test on Residuals
# -------------------------

adf_test(spread, "Spread (Residuals)")

print("Cointegration test completed.")



spread.plot(figsize=(12,6))
plt.axhline(spread.mean(), color='red', linestyle='--')
plt.title("Spread (HDFC - beta * ICICI)")
plt.savefig("spread_plot.png")
plt.close()


print("next phase z score calculation #############################################################")
window = 60  # 60 trading days (~3 months)

rolling_mean = spread.rolling(window).mean()
rolling_std = spread.rolling(window).std()

z_score = (spread - rolling_mean) / rolling_std

z_score = z_score.dropna()
print(z_score.tail(10))
z_score.plot(figsize=(12,6))
plt.axhline(2, linestyle='--')
plt.axhline(-2, linestyle='--')
plt.axhline(0)
plt.title("Z-Score of Spread")
plt.savefig("zscore_plot.png")
plt.close()

print("signals generation #############################################################")
signals = pd.DataFrame(index=z_score.index)

signals["long_entry"] = z_score < -2
signals["short_entry"] = z_score > 2
signals["exit"] = abs(z_score) < 0.5


positions = pd.Series(0, index=z_score.index)

for i in range(1, len(z_score)):
    
    if z_score.iloc[i] < -2:
        positions.iloc[i] = 1   # Long spread
    
    elif z_score.iloc[i] > 2:
        positions.iloc[i] = -1  # Short spread
    
    elif abs(z_score.iloc[i]) < 0.5:
        positions.iloc[i] = 0   # Exit
    
    else:
        positions.iloc[i] = positions.iloc[i-1]  # Hold previous position
spread_returns = spread.diff()
strategy_returns = positions.shift(1) * spread_returns
capital = 1_000_000

equity_curve = capital + strategy_returns.cumsum()

equity_curve.plot(figsize=(12,6))
plt.title("Equity Curve - Pairs Strategy")
plt.savefig("equity_curve.png")
plt.close()



import numpy as np

total_return = equity_curve.iloc[-1] - capital
returns_pct = strategy_returns / capital

sharpe = np.sqrt(252) * returns_pct.mean() / returns_pct.std()

max_drawdown = (equity_curve / equity_curve.cummax() - 1).min()

print("Total Return:", total_return)
print("Sharpe Ratio:", sharpe)
print("Max Drawdown:", max_drawdown)



