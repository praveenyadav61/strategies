import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def learn_transition_matrix(labels_df: pd.DataFrame, class_order: list[str], direct_jump_penalty: float) -> pd.DataFrame:
    counts = pd.DataFrame(1.0, index=class_order, columns=class_order)
    for _, group in labels_df.sort_values(["symbol", "Date"]).groupby("symbol", sort=False):
        labels = group["regime_label"].tolist()
        for prev_label, next_label in zip(labels[:-1], labels[1:]):
            counts.loc[prev_label, next_label] += 1

    for source in class_order:
        i = class_order.index(source)
        for dest in class_order:
            j = class_order.index(dest)
            if abs(i - j) > 1:
                counts.loc[source, dest] *= direct_jump_penalty

    matrix = counts.div(counts.sum(axis=1), axis=0)
    matrix.insert(0, "from_regime", matrix.index)
    return matrix.reset_index(drop=True)


def apply_transition_smoothing(raw_probabilities: pd.DataFrame, transition_matrix: pd.DataFrame, class_order: list[str]) -> pd.DataFrame:
    transitions = transition_matrix.set_index("from_regime")[class_order]
    outputs = []
    prob_cols = [f"P_{label}" for label in class_order]

    for (symbol, horizon), group in raw_probabilities.sort_values(["symbol", "horizon", "Date"]).groupby(["symbol", "horizon"], sort=False):
        prev_label = "NEUTRAL"
        rows = []
        for _, row in group.iterrows():
            probs = row[prob_cols].to_numpy(dtype=float)
            adjusted = probs * transitions.loc[prev_label].to_numpy(dtype=float)
            adjusted = adjusted / adjusted.sum() if adjusted.sum() else probs
            idx = int(np.argmax(adjusted))
            final_label = class_order[idx]
            rows.append(
                {
                    "symbol": symbol,
                    "Date": row["Date"],
                    "horizon": horizon,
                    "final_regime": final_label,
                    "final_regime_probability": float(adjusted[idx]),
                }
            )
            prev_label = final_label
        outputs.append(pd.DataFrame(rows))
    return pd.concat(outputs, ignore_index=True)


def write_transition_reports(labels_df: pd.DataFrame, transition_matrix: pd.DataFrame, output_dir, class_order: list[str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    matrix = transition_matrix.set_index("from_regime")[class_order]

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(matrix.to_numpy(), cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(class_order)), labels=class_order, rotation=45, ha="right")
    ax.set_yticks(range(len(class_order)), labels=class_order)
    ax.set_title("Regime Transition Matrix")
    fig.colorbar(im, ax=ax)
    plt.tight_layout()
    plt.savefig(output_dir / "transition_heatmap.png")
    plt.close()

    durations = []
    for symbol, group in labels_df.sort_values(["symbol", "Date"]).groupby("symbol", sort=False):
        regime_run = group["regime_label"].ne(group["regime_label"].shift()).cumsum()
        for _, run in group.groupby(regime_run):
            durations.append(
                {
                    "symbol": symbol,
                    "regime_label": run["regime_label"].iloc[0],
                    "start_date": run["Date"].iloc[0],
                    "end_date": run["Date"].iloc[-1],
                    "duration_days": len(run),
                }
            )
    duration_df = pd.DataFrame(durations)
    duration_df.to_csv(output_dir / "regime_duration_detail.csv", index=False)
    duration_report = (
        duration_df.groupby(["symbol", "regime_label"])["duration_days"]
        .agg(["count", "mean", "median", "max"])
        .reset_index()
        .rename(columns={"count": "runs", "mean": "avg_duration_days", "max": "max_duration_days"})
    )
    duration_report.to_csv(output_dir / "regime_duration_report.csv", index=False)

    persistence_rows = []
    for regime in class_order:
        persistence_rows.append(
            {
                "regime_label": regime,
                "state_persistence_probability": float(matrix.loc[regime, regime]),
                "probability_of_regime_change": float(1 - matrix.loc[regime, regime]),
            }
        )
    pd.DataFrame(persistence_rows).to_csv(output_dir / "state_persistence_report.csv", index=False)
