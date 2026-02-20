import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller

def backtest_pair(stock1, stock2, data,
                  window_z=60,
                  window_beta=252,
                  capital=1_000_000,
                  leverage=1,
                  transaction_cost_rate=0.001):

    df = data[[stock1, stock2]].dropna()

    # Need enough data
    if len(df) < window_beta + window_z:
        return None

    y = df[stock1]
    x = df[stock2]

    betas = []
    spread_list = []

    # ------------------------------
    # Rolling 252-day beta
    # ------------------------------

    for i in range(window_beta, len(df)):

        y_window = y.iloc[i-window_beta:i]
        x_window = x.iloc[i-window_beta:i]

        X = sm.add_constant(x_window)
        model = sm.OLS(y_window, X).fit()
        beta_t = model.params[stock2]

        betas.append(beta_t)

        spread_today = y.iloc[i] - beta_t * x.iloc[i]
        spread_list.append(spread_today)

    spread = pd.Series(spread_list, index=df.index[window_beta:])
    betas = pd.Series(betas, index=df.index[window_beta:])

    # ------------------------------
    # Cointegration check on spread
    # ------------------------------

    try:
        p_spread = adfuller(spread)[1]
    except:
        return None

    # ------------------------------
    # Z-score
    # ------------------------------

    rolling_mean = spread.rolling(window_z).mean()
    rolling_std = spread.rolling(window_z).std()

    z_score = (spread - rolling_mean) / rolling_std
    z_score = z_score.dropna()

    spread = spread.loc[z_score.index]

    # ------------------------------
    # Position logic
    # ------------------------------

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

    # ------------------------------
    # Strategy returns
    # ------------------------------

    spread_returns = spread.diff()
    strategy_returns = positions.shift(1) * spread_returns
    strategy_returns = strategy_returns.fillna(0)

    # Apply leverage
    strategy_returns = strategy_returns * leverage

    # ------------------------------
    # Transaction cost (spread-based)
    # ------------------------------

    position_change = positions.diff().abs().fillna(0)

    # Apply cost as fraction of spread move scale
    transaction_cost = position_change * transaction_cost_rate

    strategy_returns = strategy_returns - transaction_cost

    # ------------------------------
    # Equity curve
    # ------------------------------

    equity_curve = capital + strategy_returns.cumsum()

    returns_pct = strategy_returns / capital

    annual_return = returns_pct.mean() * 252
    annual_vol = returns_pct.std() * np.sqrt(252)

    sharpe = annual_return / annual_vol if annual_vol != 0 else 0

    max_drawdown = (equity_curve / equity_curve.cummax() - 1).min()

    total_return = equity_curve.iloc[-1] - capital

    return {
        "Pair": f"{stock1} vs {stock2}",
        "Avg_Beta": round(betas.mean(),4),
        "Spread_p_value": round(p_spread,6),
        "Sharpe": round(sharpe,4),
        "Max_Drawdown": round(max_drawdown,4),
        "Total_Return": round(total_return,2)
    }
