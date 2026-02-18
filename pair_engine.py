import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller

def backtest_pair(stock1, stock2, data, window=60, capital=1_000_000):

    df = data[[stock1, stock2]].dropna()

    y = df[stock1]
    x = df[stock2]

    # -------------------
    # Regression
    # -------------------
    X = sm.add_constant(x)
    model = sm.OLS(y, X).fit()
    beta = model.params[stock2]

    spread = y - beta * x

    # -------------------
    # Cointegration Test
    # -------------------
    p_spread = adfuller(spread)[1]

    # -------------------
    # Z-score
    # -------------------
    rolling_mean = spread.rolling(window).mean()
    rolling_std = spread.rolling(window).std()

    z_score = (spread - rolling_mean) / rolling_std
    z_score = z_score.dropna()

    spread = spread.loc[z_score.index]

    # -------------------
    # Position Logic
    # -------------------
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

    spread_returns = spread.diff()
    strategy_returns = positions.shift(1) * spread_returns
    strategy_returns = strategy_returns.fillna(0)

    equity_curve = capital + strategy_returns.cumsum()

    returns_pct = strategy_returns / capital

    annual_return = returns_pct.mean() * 252
    annual_vol = returns_pct.std() * np.sqrt(252)

    sharpe = annual_return / annual_vol if annual_vol != 0 else 0
    max_drawdown = (equity_curve / equity_curve.cummax() - 1).min()

    total_return = equity_curve.iloc[-1] - capital

    return {
        "Pair": f"{stock1} vs {stock2}",
        "Beta": round(beta,4),
        "Spread_p_value": round(p_spread,6),
        "Sharpe": round(sharpe,4),
        "Max_Drawdown": round(max_drawdown,4),
        "Total_Return": round(total_return,2)
    }
