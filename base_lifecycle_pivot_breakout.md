# Base Lifecycle Pivot and Breakout Rules

This document is the authoritative description of pivot selection and the
post-breakout lifecycle used by `Streamlit/base_lifecycle_scanner.py`.

## 1. One actionable pivot

The scanner calculates only the values needed to select one actionable pivot:

1. the base's left high; and
2. a valid handle high, when a handle exists.

Selection is deterministic:

```text
valid distinct handle -> selected_pivot = handle_high
otherwise             -> selected_pivot = left_high
```

The scanner does not calculate a range-high pivot, range-close pivot,
resistance-cluster pivot, or ranked swing pivot.

`major_pivot` and `active_pivot_price` may still appear as compatibility aliases
in saved rows and charts. They contain the same value as `selected_pivot`; they
are not separate calculations.

## 2. Left-high pivot

`left_high_pivot` is the high at the beginning of the accepted base. It is the
fallback pivot and remains important even when a lower handle is selected,
because a successful breakout must eventually clear the old left-high supply.

## 3. Handle detection

The handle is evaluated from recent weekly bars before the signal candle. The
signal candle is excluded so it cannot create its own pivot.

Default rules:

```text
lookback                     = 10 weeks
minimum pullback             = 3%
maximum pullback             = one third of base depth
minimum handle duration      = 2 weeks
valid handle-high band       = 85% to 105% of left high
merge tolerance              = 2% of left high
```

The dynamic depth rule is:

```text
handle_max_pullback_pct = base_depth / 3
handle_pullback_pct = (handle_high - handle_low) / handle_high
```

Example: a 30% deep base permits at most a 10% handle pullback. A 15% deep
base permits at most 5%.

A handle is valid only when its pullback is between the minimum and dynamic
maximum, lasts at least two weeks, and its high is inside the allowed band
around the left high.

If a valid handle high is within 2% of the left high, the levels are treated as
the same resistance area:

```text
pivot_source   = LEFT_HIGH_HANDLE_MERGED
selected_pivot = left_high
```

If it is farther than 2% from the left high, the handle is distinct:

```text
pivot_source   = HANDLE
selected_pivot = handle_high
```

Without a valid handle:

```text
pivot_source   = LEFT_HIGH
selected_pivot = left_high
```

Before breakout, a selected handle is invalidated if the latest close falls
below its handle low. Selection then returns to the left high.

## 4. Breakout confirmation

A close must cross the buffered selected pivot:

```text
breakout_buffer = max(
    0.5% * selected_pivot,
    0.20 * setup_weekly_ATR
)

confirmation_level = selected_pivot + breakout_buffer

previous_close <= confirmation_level
current_close  >  confirmation_level
```

This correctly detects a close that moves from slightly above the raw pivot to
above the buffered level. Comparing `previous_close` only with the raw pivot
would miss that transition.

The first qualifying crossing confirms the breakout. On that date the selected
pivot, pivot source, left high, handle values, ATR, and confirmation buffer are
frozen. Later highs cannot move the pivot upward.

## 5. Fixed post-breakout range

The selected pivot creates a fixed 20%-wide management range:

```text
breakout_range_low  = selected_pivot * 0.90
breakout_range_high = selected_pivot * 1.10
```

Zones describe where the current close is now:

```text
BELOW_RANGE       close < range low
RETEST_RANGE      range low <= close < selected pivot
BUY_RANGE         selected pivot <= close <= range high
ABOVE_BUY_RANGE   close > range high
```

`PRE_BREAKOUT` is used before a breakout is confirmed. The band is a lifecycle
and trade-management classification, not an automatic buy recommendation.

## 6. Successful breakout

For a left-high pivot, success normally means clearing 10% above that pivot.
For a lower handle pivot, merely reaching 10% above the handle may still leave
price below the old left high. Therefore success requires the higher of:

```text
success_level = max(
    breakout_range_high,
    left_high + left_high_confirmation_buffer
)
```

The first post-breakout close above `success_level` sets:

```text
breakout_success      = True
breakout_success_date = first qualifying date
lifecycle_phase       = BREAKOUT_SUCCESS
```

Success is latched. If price later returns to the range, the historical phase
remains `BREAKOUT_SUCCESS`; `current_zone` reports its present location. A
successful stock back inside `RETEST_RANGE` or `BUY_RANGE` is flagged as
`post_success_reentry` for a possible future entry strategy.

## 7. Breakout failure

The normal lower boundary is 10% below the frozen pivot. An additional ATR/pct
buffer distinguishes a decisive failure from a marginal weekly breach:

```text
failure_buffer = max(
    1.0% * selected_pivot,
    0.25 * frozen_setup_weekly_ATR
)

hard_failure_level = breakout_range_low - failure_buffer
```

A confirmed breakout fails when either condition occurs:

```text
1. one weekly close < hard_failure_level
2. two consecutive weekly closes < breakout_range_low
```

One close below the range low but above the hard failure level is only a range
breach warning. It is not immediately archived. Failure is evaluated from
closes, not intraday/week lows, to reduce noise.

When failure occurs:

```text
lifecycle_phase  = FAILED
lifecycle_status = FAILED
```

Tracked rows are then eligible for archival.

## 8. Stalled breakout

If a breakout has not reached the success level within 10 weeks, it is marked:

```text
lifecycle_status = BREAKOUT_STALLED
breakout_stalled = True
```

Stalled is not the same as failed. It remains active unless the failure rules
are later triggered.

## 9. Phase versus current zone

Two fields intentionally answer different questions:

```text
lifecycle_phase = what has historically happened?
current_zone    = where is price now?
```

Phases:

```text
FORMING
BREAKOUT_CONFIRMED
BREAKOUT_SUCCESS
FAILED
```

This separation prevents a successful stock that pulls back from being
mistaken for a stock that never succeeded.

## 10. Status priority

The scanner chooses the most useful current label in this order:

```text
FAILED
BREAKOUT_STALLED
POST_SUCCESS_REENTRY_RANGE
BREAKOUT_SUCCESS
BREAKOUT_RANGE_BREACH
BREAKOUT_RETEST_RANGE
BREAKOUT_BUY_RANGE
HANDLE_READY
NEAR_PIVOT
TRACKING / RESETTING / BASE_FORMING
```

`RESETTING` is used before breakout when a previously selected handle becomes
invalid. It does not mean a confirmed breakout failed.

## 11. Important output columns

Keep these visible in the compact scanner table:

```text
Symbol
lifecycle_phase
current_zone
lifecycle_status
pivot_source
selected_pivot
distance_from_pivot_pct
Depth
recovery_pct
left_high_pivot
handle_high_pivot
handle_pullback_pct
handle_max_pullback_pct
breakout_range_low
breakout_range_high
breakout_date
breakout_success_date
```

Industry, metadata, and extended diagnostics belong in optional/detail views.

## 12. Worked examples

### Left-high pivot

```text
left high                    = 100
no valid handle
selected pivot               = 100
breakout range               = 90 to 110
success level                = at least 110
```

### Lower handle pivot

```text
left high                    = 120
valid handle high            = 100
selected pivot               = 100
breakout range               = 90 to 110
buffered left high           = approximately 120 plus its buffer
success level                = buffered left high, not 110
```

The handle can provide the earlier breakout trigger, but the lifecycle does not
declare full success until price clears the original left-high resistance.

### Failed return

```text
selected pivot               = 100
range low                    = 90
hard failure level           = 89.5 (illustrative)

one close at 89.8            = breach warning
next close back above 90     = remains active
two consecutive closes < 90 = failed
one close below 89.5         = failed immediately
```
