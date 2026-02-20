import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller

# ============================
# 1. LOAD DATA
# ============================

data = pd.read_csv("bank_pair_data.csv", index_col="Date", parse_dates=True)

hdfc = data["HDFC"]
icici = data["ICICI"]

print("Data Loaded")
print("Period:", data.index.min().date(), "to", data.index.max().date())
print("Total observations:", len(data))
print("\n")

# ============================
# 2. COINTEGRATION TEST
# ============================

def adf_test(series, name):
    result = adfuller(series)
    print(f"ADF Test: {name}")
    print(f"ADF Statistic: {result[0]:.4f}")
    print(f"p-value: {result[1]:.6f}")
    print("-" * 40)
    return result[1]

print("Running Cointegration Test...\n")

p_hdfc = adf_test(hdfc, "HDFC Price")
p_icici = adf_test(icici, "ICICI Price")

X = sm.add_constant(icici)
model = sm.OLS(hdfc, X).fit()

beta = model.params["ICICI"]

print(f"Hedge Ratio (beta): {beta:.4f}")
print("-" * 40)

spread = hdfc - beta * icici

p_spread = adf_test(spread, "Spread (Residuals)")

if p_spread < 0.05:
    print("✅ Spread is stationary → Pair is cointegrated\n")
else:
    print("⚠ Spread not stationary → Strategy risky\n")

# ============================
# 3. Z-SCORE CONSTRUCTION
# ============================

window = 60

rolling_mean = spread.rolling(window).mean()
rolling_std = spread.rolling(window).std()

z_score = (spread - rolling_mean) / rolling_std
z_score = z_score.dropna()

print("Latest Z-Score:", round(z_score.iloc[-1], 4))
print("-" * 40)

# ============================
# 4. POSITION ENGINE
# ============================

positions = pd.Series(0, index=z_score.index)

for i in range(1, len(z_score)):
    
    if z_score.iloc[i] < -2:
        positions.iloc[i] = 1
    
    elif z_score.iloc[i] > 2:
        positions.iloc[i] = -1
    
    elif abs(z_score.iloc[i]) < 0.5:
        positions.iloc[i] = 0
    
    else:
        positions.iloc[i] = positions.iloc[i-1]

# ============================
# 5. STRATEGY RETURNS
# ============================

spread = spread.loc[z_score.index]

spread_returns = spread.diff()

strategy_returns = positions.shift(1) * spread_returns
strategy_returns = strategy_returns.fillna(0)

# ============================
# 6. EQUITY CURVE
# ============================

capital = 1_000_000

equity_curve = capital + strategy_returns.cumsum()

# ============================
# 7. PERFORMANCE METRICS
# ============================

returns_pct = strategy_returns / capital

total_return = equity_curve.iloc[-1] - capital
annual_return = returns_pct.mean() * 252
annual_vol = returns_pct.std() * np.sqrt(252)

sharpe = annual_return / annual_vol if annual_vol != 0 else 0

max_drawdown = (equity_curve / equity_curve.cummax() - 1).min()

total_trades = (positions.diff() != 0).sum()

win_days = (strategy_returns > 0).sum()
loss_days = (strategy_returns < 0).sum()

print("\n===== PERFORMANCE SUMMARY =====")
print(f"Total Return: ₹{total_return:,.2f}")
print(f"Annual Return: {annual_return:.4f}")
print(f"Annual Volatility: {annual_vol:.4f}")
print(f"Sharpe Ratio: {sharpe:.4f}")
print(f"Max Drawdown: {max_drawdown:.4f}")
print(f"Total Position Changes: {total_trades}")
print(f"Winning Days: {win_days}")
print(f"Losing Days: {loss_days}")
print("=" * 40)

print("\nBacktest Completed.")
