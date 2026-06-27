# Market Regime Refactor Notes

This refactor follows `Market Regime Model Refactor.docx` with two deliberate omissions:

1. Phase 8 breadth features are skipped for now.
2. Phase 11 walk-forward validation is skipped for now.

Key changes:

* Label generation now uses per-symbol score calibration by default.
* `regime_score` and `raw_regime_score` are excluded from model features to avoid leakage.
* Structure scoring now uses monthly, weekly, daily, and trendline components.
* Volatility is treated as risk magnitude, not bearish direction.
* Persistence features influence labels and are saved for audit.
* Diagnostics, feature audit, evaluation, transition duration reports, and plots are generated on every run.

Run from the repository root:

```bash
python model/market_regime/run_pipeline.py
```
