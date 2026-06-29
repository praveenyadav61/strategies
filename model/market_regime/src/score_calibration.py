import pandas as pd


LABELS = ["STRONG_RISK_OFF", "RISK_OFF", "NEUTRAL", "RISK_ON", "STRONG_RISK_ON"]


def _labels_from_percentiles(percentiles: pd.Series, q10: float, q30: float, q70: float, q90: float) -> pd.Series:
    labels = pd.Series("NEUTRAL", index=percentiles.index)
    labels.loc[percentiles <= q10] = "STRONG_RISK_OFF"
    labels.loc[(percentiles > q10) & (percentiles <= q30)] = "RISK_OFF"
    labels.loc[(percentiles > q70) & (percentiles <= q90)] = "RISK_ON"
    labels.loc[percentiles > q90] = "STRONG_RISK_ON"
    return labels


def calibrate_scores(labels_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    method = config["labels"].get("calibration", {}).get("method", "quantile")
    quantiles = config["labels"].get("calibration", {}).get(
        "quantiles",
        {"strong_risk_off": 0.10, "risk_off": 0.30, "neutral": 0.70, "risk_on": 0.90},
    )
    df = labels_df.copy()
    df["raw_regime_score"] = df["regime_score"]

    calibrated = []
    for _, group in df.groupby("symbol", sort=False):
        g = group.copy()
        if method == "yearly_quantile":
            pieces = []
            for _, year_group in g.groupby(g["Date"].dt.year, sort=False):
                pieces.append(_apply_quantile_labels(year_group, quantiles))
            g = pd.concat(pieces).sort_index()
        elif method == "fixed_threshold":
            thresholds = config["labels"]["thresholds"]
            g["regime_label"] = g["regime_score"].apply(lambda score: _fixed_threshold_label(score, thresholds))
        else:
            g = _apply_quantile_labels(g, quantiles)
        calibrated.append(g)

    return pd.concat(calibrated, ignore_index=True)


def _apply_quantile_labels(group: pd.DataFrame, quantiles: dict) -> pd.DataFrame:
    g = group.copy()
    scores = g["regime_score"]
    q10 = scores.quantile(float(quantiles["strong_risk_off"]))
    q30 = scores.quantile(float(quantiles["risk_off"]))
    q70 = scores.quantile(float(quantiles["neutral"]))
    q90 = scores.quantile(float(quantiles["risk_on"]))
    percentiles = scores.rank(method="first", pct=True)
    g["regime_label"] = _labels_from_percentiles(
        percentiles,
        float(quantiles["strong_risk_off"]),
        float(quantiles["risk_off"]),
        float(quantiles["neutral"]),
        float(quantiles["risk_on"]),
    )
    g["calibration_q10"] = q10
    g["calibration_q30"] = q30
    g["calibration_q70"] = q70
    g["calibration_q90"] = q90
    return g


def _fixed_threshold_label(score: float, thresholds: dict) -> str:
    if score < thresholds["strong_risk_off"]:
        return "STRONG_RISK_OFF"
    if score < thresholds["risk_off"]:
        return "RISK_OFF"
    if score <= thresholds["neutral"]:
        return "NEUTRAL"
    if score <= thresholds["risk_on"]:
        return "RISK_ON"
    return "STRONG_RISK_ON"
