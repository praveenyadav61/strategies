import pandas as pd
import numpy as np


def sharpe_ratio(equity_curve):

    returns = pd.Series(equity_curve).pct_change().dropna()

    return np.sqrt(252) * returns.mean() / returns.std()


def max_drawdown(equity_curve):

    equity = pd.Series(equity_curve)

    rolling_max = equity.cummax()

    drawdown = equity / rolling_max - 1

    return drawdown.min()