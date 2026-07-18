# Base Lifecycle Pivot and Breakout Logic

This is the authoritative reference for pivot construction, breakout detection,
and breakout failure in `Streamlit/base_lifecycle_scanner.py`. Use this document
for future discussions instead of reconstructing the rules from code.

The older Base Formation scanner is not covered here and is not changed by this
logic.

## 1. Design Principles

1. Calculate several raw structural values for inspection.
2. Operate on only two actionable levels: the major pivot and a distinct handle pivot.
3. Never allow a candle to create the pivot that it is simultaneously breaking.
4. Freeze pivots, ATR values, and buffers when a breakout confirms.
5. Never allow breakout or post-breakout highs to move a frozen pivot.
6. Require a buffer above resistance for confirmation and hysteresis below resistance for failure.
7. Use weekly closes, not weekly highs, for breakout and failure decisions.

## 2. Base Reference Points

For each 26-, 52-, or 104-week scan window:

```text
left_high = highest weekly high before the final MIN_WEEKS
base_low  = lowest weekly low from left_high onward
```

Pivot candidates are constructed only from weekly candles after `base_low`.

## 3. Valid Pivot Zone

A price can be a pivot for the same base only when:

```text
0.85 * left_high <= candidate <= 1.05 * left_high
```

Defaults:

```text
PIVOT_MIN_LEFT_HIGH_RATIO = 0.85
PIVOT_MAX_LEFT_HIGH_RATIO = 1.05
```

A price above 105% of the left high is not a new pivot. It is a possible
breakout or post-breakout price. It does not invalidate the frozen pivot.

## 4. No Self-Referencing Candle

When candle `t` is evaluated for breakout, raw pivots are calculated only from:

```text
base_low + 1 through candle t - 1
```

The high or close of candle `t` cannot raise its own breakout threshold.

## 5. Raw Pivot Values

### 5.1 Left-high pivot

```text
left_high_pivot = left_high
```

This is the original resistance and the fallback major pivot.

### 5.2 Range-high pivot

```text
range_high_pivot = highest valid weekly high after base_low and before the evaluated candle
```

It is no longer a rolling eight-week value. Before breakout it expands with the
right side of the base. At confirmed breakout it freezes.

### 5.3 Range-close pivot

```text
range_close_pivot = highest valid weekly close over the same pre-breakout range
```

This indicates price acceptance. Clearing it is an intermediate event, not a
confirmed major breakout.

`close_high_pivot` remains temporarily as a compatibility alias for old saved
snapshots. New logic and UI use `range_close_pivot`.

### 5.4 Resistance-cluster pivot

The latest 12 eligible highs are grouped using a default `+/-3%` band. The
largest group is retained when it has at least two touches:

```text
TRACKING_CLUSTER_LOOKBACK_WEEKS = 12
TRACKING_CLUSTER_TOLERANCE_PCT  = 0.03
TRACKING_MIN_CLUSTER_TOUCHES    = 2
```

The cluster validates that resistance is repeated rather than a single wick.
It is supporting evidence and is not a separate breakout threshold.

### 5.5 Handle-high pivot

The latest ten eligible weeks are searched for a high followed by a controlled
pullback:

```text
3% <= handle pullback <= 18%
```

The latest valid handle is retained. It becomes separately actionable only when:

```text
handle_pivot < major_pivot
and (major_pivot - handle_pivot) / major_pivot > 2%
```

If the two levels are within 2%, the handle is merged conceptually with the
major pivot and does not produce a separate early-breakout signal.

## 6. Actionable Levels

Only two levels drive lifecycle decisions.

### Major pivot

```text
major_pivot = max(left_high_pivot, range_high_pivot)
```

Because range highs are capped at 105% of the left high, the major pivot remains
part of the same base structure.

### Handle pivot

```text
handle_pivot = frozen distinct handle_high_pivot
```

The cluster and range-close values remain diagnostics. The legacy swing pivot is
stored as `legacy_pivot_price` for comparison but does not drive breakout or failure.

## 7. Breakout Buffers

The setup ATR is the weekly ATR available before the candle being evaluated.

```text
breakout_buffer = max(
    pivot * BREAKOUT_PRICE_BUFFER_PCT,
    setup_atr * BREAKOUT_ATR_BUFFER_MULTIPLIER
)
```

Defaults:

```text
BREAKOUT_PRICE_BUFFER_PCT       = 0.005   # 0.5%
BREAKOUT_ATR_BUFFER_MULTIPLIER  = 0.20
```

```text
confirmation_level = pivot + breakout_buffer
```

ATR and the calculated buffer freeze when breakout confirms.

## 8. Major Breakout

### Attempt

```text
major_pivot < current_close <= major_confirmation_level
```

Status:

```text
BREAKOUT_ATTEMPT
```

### Newly confirmed event

```text
previous_close <= major_confirmation_level
and current_close > major_confirmation_level
```

Status:

```text
BREAKOUT_CONFIRMED
```

The comparison is against the confirmation level, not the raw pivot. Therefore,
a previous close between the pivot and confirmation level does not prevent the
next candle from confirming.

At confirmation, these values freeze:

```text
major_pivot
major_pivot_date
range_high_pivot
range_close_pivot
resistance_cluster_pivot
setup_atr
major_breakout_buffer
major_confirmation_level
major_failure_buffer
major_failure_level
breakout_date
```

## 9. Handle Breakout

The handle uses the same buffer formula.

### Attempt

```text
handle_pivot < current_close <= handle_confirmation_level
```

Status:

```text
HANDLE_BREAKOUT_ATTEMPT
```

### Confirmed event

```text
previous_close <= handle_confirmation_level
and current_close > handle_confirmation_level
```

Status:

```text
HANDLE_BREAKOUT_CONFIRMED
```

If one candle crosses both handle and major confirmation levels, the major
breakout has priority.

## 10. Range-Close Event

When the latest close exceeds the prior range-close pivot but has not confirmed
the major or handle breakout:

```text
CLOSE_RESISTANCE_CLEARED
```

This is a watch state. It is not a confirmed base breakout.

## 11. Failure Buffers

Failure uses a wider opposite-side buffer:

```text
failure_buffer = max(
    pivot * FAILURE_PRICE_BUFFER_PCT,
    breakout_atr * FAILURE_ATR_BUFFER_MULTIPLIER
)

failure_level = pivot - failure_buffer
```

Defaults:

```text
FAILURE_PRICE_BUFFER_PCT       = 0.01   # 1%
FAILURE_ATR_BUFFER_MULTIPLIER  = 0.25
```

This creates hysteresis:

```text
confirmation requires pivot + breakout buffer
failure requires pivot - failure buffer or persistence
```

## 12. Major Breakout Failure

Weekly lows do not fail a breakout. Failure is based on weekly closes.

### Holding pivot

```text
current_close >= major_pivot
```

When price has pulled back inside the confirmation band after already confirming:

```text
HOLDING_PIVOT
```

### Mild one-week undercut

```text
major_failure_level <= current_close < major_pivot
```

Status:

```text
PIVOT_RETEST_WEAK
```

This is not immediately failed.

### Hard failure

```text
current_close < major_failure_level
```

One decisive weekly close is sufficient.

### Persistent failure

```text
previous_close < major_pivot
and current_close < major_pivot
```

Two consecutive weekly closes below the raw pivot are sufficient even when
neither exceeds the hard-failure buffer.

### Final failure condition

```text
FAILED = hard_failure or persistent_failure
```

Tracked bases with `FAILED` status are archived with reason
`confirmed_breakout_failed`.

## 13. Handle Failure

Before major breakout, a confirmed handle breakout fails when:

```text
current_close < handle_failure_level
```

or:

```text
two consecutive weekly closes < handle_pivot
```

A handle failure returns the setup to `RESETTING`. It does not fail or archive
the entire base because the major breakout never confirmed.

## 14. Status Priority

Major-breakout states have priority over handle states.

Simplified order:

```text
BASE_FORMING / TRACKING
    -> CLOSE_RESISTANCE_CLEARED
    -> HANDLE_BREAKOUT_ATTEMPT
    -> HANDLE_BREAKOUT_CONFIRMED
    -> BREAKOUT_ATTEMPT
    -> BREAKOUT_CONFIRMED
    -> HOLDING_PIVOT / PIVOT_RETEST_WEAK / PULLBACK_TO_PIVOT
    -> FAILED
```

`EXTENDED` applies when a confirmed breakout is more than 25% above its frozen
major pivot.

## 15. Operational vs Diagnostic Calculations

Operational:

```text
major_pivot
major_confirmation_level
major_failure_level
handle_pivot
handle_confirmation_level
handle_failure_level
```

Diagnostic/supporting:

```text
left_high_pivot
range_high_pivot
range_close_pivot
resistance_cluster_pivot
resistance_cluster_touches
handle_high_pivot
legacy_pivot_price
```

The scanner intentionally does not compare price against every raw pivot after
breakout. Once the major pivot confirms, only its frozen thresholds control its
holding/failure state.

## 16. Example

```text
left_high                  = 100.00
range_high                 = 98.00
major_pivot                = 100.00
setup ATR                  = 2.00
breakout buffer            = max(0.50, 0.40) = 0.50
major confirmation level   = 100.50
failure buffer             = max(1.00, 0.50) = 1.00
major failure level        = 99.00
```

Lifecycle examples:

```text
close 100.30                         -> BREAKOUT_ATTEMPT
previous 100.30, current 101.20      -> BREAKOUT_CONFIRMED
later close 100.20                   -> HOLDING_PIVOT
one later close 99.50                -> PIVOT_RETEST_WEAK
one later close 98.80                -> FAILED (hard failure)
two consecutive closes 99.50, 99.40 -> FAILED (persistent failure)
```

## 17. Parameters to Backtest Later

The structure is implemented, but these defaults remain tuning parameters:

```text
0.5% breakout price buffer
0.20 ATR breakout multiplier
1.0% failure price buffer
0.25 ATR failure multiplier
2.0% handle/major merge tolerance
3.0% resistance-cluster tolerance
3%-18% valid handle pullback
```

Change these only through scanner parameters and validate them with replay data.
Do not change state-transition definitions merely to improve a small sample.
