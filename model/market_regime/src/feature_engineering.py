import numpy as np
import pandas as pd


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def _true_range(df: pd.DataFrame) -> pd.Series:
    return pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift(1)).abs(),
            (df["Low"] - df["Close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _adx(df: pd.DataFrame, period: int) -> pd.Series:
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    atr = _true_range(df).ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.fillna(0).ewm(alpha=1 / period, adjust=False).mean()


def _gk_vol(df: pd.DataFrame, period: int) -> pd.Series:
    log_hl = np.log(df["High"] / df["Low"])
    log_co = np.log(df["Close"] / df["Open"])
    gk = 0.5 * log_hl**2 - (2 * np.log(2) - 1) * log_co**2
    return np.sqrt(gk.rolling(period).mean())


def _cmf(df: pd.DataFrame, period: int) -> pd.Series:
    denom = (df["High"] - df["Low"]).replace(0, np.nan)
    money_flow_multiplier = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / denom
    money_flow_volume = money_flow_multiplier.fillna(0) * df["Volume"]
    return money_flow_volume.rolling(period).sum() / df["Volume"].rolling(period).sum().replace(0, np.nan)


def build_base_features(raw_df: pd.DataFrame) -> pd.DataFrame:
    output = []
    for symbol, group in raw_df.sort_values(["symbol", "Date"]).groupby("symbol", sort=False):
        df = group.copy().reset_index(drop=True)
        source_ticker = df["source_ticker"].iloc[0] if "source_ticker" in df.columns else symbol
        close = df["Close"]

        for period in [10, 21, 50, 200]:
            df[f"EMA{period}"] = close.ewm(span=period, adjust=False).mean()
            df[f"EMA{period}_Dist"] = (close - df[f"EMA{period}"]) / df[f"EMA{period}"]

        df["Above_EMA200"] = (close > df["EMA200"]).astype(int)
        df["Above_EMA50"] = (close > df["EMA50"]).astype(int)
        df["EMA50_Above_EMA200"] = (df["EMA50"] > df["EMA200"]).astype(int)
        df["days_above_ema200"] = _consecutive_days(df["Above_EMA200"].eq(1))
        df["days_below_ema200"] = _consecutive_days(df["Above_EMA200"].eq(0))
        df["days_above_ema50"] = _consecutive_days(df["Above_EMA50"].eq(1))
        df["days_below_ema50"] = _consecutive_days(df["Above_EMA50"].eq(0))

        df["EMA10_21_Spread"] = (df["EMA10"] - df["EMA21"]) / df["EMA21"]
        df["EMA21_50_Spread"] = (df["EMA21"] - df["EMA50"]) / df["EMA50"]
        df["EMA50_200_Spread"] = (df["EMA50"] - df["EMA200"]) / df["EMA200"]
        df["EMA50_Slope_5"] = df["EMA50"].pct_change(5)/5
        df["EMA50_Slope_20"] = df["EMA50"].pct_change(20)/20
        df["EMA200_Slope_20"] = df["EMA200"].pct_change(20)/20

        for period in [7, 14, 28]:
            df[f"RSI{period}"] = _rsi(close, period)
        for period in [14, 28]:
            df[f"ADX{period}"] = _adx(df, period)
        for period in [1, 5, 10]:
            df[f"ROC{period}"] = close.pct_change(period)

        tr = _true_range(df)
        for period in [5, 14, 21]:
            df[f"ATR{period}"] = tr.ewm(alpha=1 / period, adjust=False).mean()
            df[f"NATR{period}"] = df[f"ATR{period}"] / close * 100
        df["ATR50"] = tr.ewm(alpha=1 / 50, adjust=False).mean()
        df["ATR5_ATR50_RATIO"] = df["ATR5"] / df["ATR50"].replace(0, np.nan)
        df["GK_VOL_21"] = _gk_vol(df, 21)
        middle = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        df["BB_WIDTH"] = ((middle + 2 * bb_std) - (middle - 2 * bb_std)) / middle

        for period in [5, 20]:
            vol_mean = df["Volume"].rolling(period).mean()
            vol_std = df["Volume"].rolling(period).std()
            df[f"VOL_Z_{period}"] = ((df["Volume"] - vol_mean) / vol_std.replace(0, np.nan)).fillna(0)
        df["CMF20"] = _cmf(df, 20)

        df["symbol"] = symbol
        df["source_ticker"] = source_ticker
        output.append(df)

    features = pd.concat(output, ignore_index=True)
    return features.dropna().sort_values(["symbol", "Date"]).reset_index(drop=True)


def _consecutive_days(mask: pd.Series) -> pd.Series:
    groups = mask.ne(mask.shift()).cumsum()
    counts = mask.groupby(groups).cumcount() + 1
    return counts.where(mask, 0)
