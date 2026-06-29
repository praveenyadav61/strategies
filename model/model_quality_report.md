# Market Regime Model Quality Report

## Metadata

| Field | Value |
|---|---:|
| Index symbol | NIFTY_50 |
| Model version | smooth |
| Ground truth version | gt_v0.0.0 |
| Rows scored | 347 |

## Summary

| Metric | Value |
|---|---:|
| Error severity score | 19.45 / 100 |
| Accuracy | 48.41% |
| Weighted error score | 0.1945 |
| Penalty points total | 67.5000 |
| Correct rows | 168 |
| Dangerous errors | 2 |
| Opportunity-cost errors | 8 |
| Acceptable-caution mismatches | 100 |
| Mild-aggression mismatches | 69 |

## Verdict

- Status: REVIEW
- Reason: 2 dangerous error(s) require inspection.

## Per-Regime Metrics

| Ground truth regime | Rows | Accuracy | Weighted error | Dangerous | Opportunity cost |
|---|---:|---:|---:|---:|---:|
| RISK_ON | 118 | 64.41% | 0.1229 | 0 | 8 |
| NEUTRAL | 104 | 24.04% | 0.3558 | 0 | 0 |
| RISK_OFF | 125 | 53.60% | 0.1280 | 2 | 0 |

## Confusion Matrix

| Ground truth \ Model | RISK_ON | NEUTRAL | RISK_OFF | Total |
|---|---:|---:|---:|---:|
| RISK_ON | 76 | 34 | 8 | 118 |
| NEUTRAL | 69 | 25 | 10 | 104 |
| RISK_OFF | 2 | 56 | 67 | 125 |

## Notes

- Lower weighted error score is better.
- Dangerous errors are the most important failure class.
- CSV files remain the audit source for row-level and tabular review.
