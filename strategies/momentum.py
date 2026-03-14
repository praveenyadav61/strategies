import pandas as pd

def generate_signals(data):

    returns = data["Close"].pct_change(20)

    signals = pd.Series("HOLD", index=data.index)

    signals[returns > 0.05] = "BUY"
    signals[returns < -0.05] = "SELL"

    return signals