# Base Lifecycle Pivot and Breakout Rules

This document is the authoritative description of pivot selection and the
post-breakout lifecycle used by `Streamlit/base_lifecycle_scanner.py`.

The dashboard's primary `journey_stage` is intentionally simpler than the
detailed statuses below. `BREAKOUT_CONSIDERATION` covers both 85%+ recovery and
a confirmed-but-not-yet-successful breakout; `SUCCESSFUL_BREAKOUT` and `FAILED`
are latched historical outcomes. See `base_lifecycle_flow.md` for that primary
stage contract.

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

## 3. Daily handle detection

The accepted base, left high, base low, and depth come from completed weekly
candles. Handle construction then replays completed daily candles after the
actual daily low inside the weekly base-low candle. An incomplete current-day
candle is never used.

Default rules:

```text
maximum pullback             = one third of base depth
confirmation duration        = 5 completed sessions after the pivot candle
base_depth_price             = left high - base low
valid handle-high minimum    = base low + 85% of base_depth_price
valid handle-high maximum    = base low + 110% of base_depth_price
```

The dynamic depth rule is:

```text
handle_max_pullback_pct = base_depth / 3
handle_pullback_pct = (handle_high - handle_low) / handle_high
```

Example: a 30% deep base permits at most a 10% handle pullback. A 15% deep
base permits at most 5%.

A daily high inside the 85% to 110% recovery zone becomes the one temporary
handle candidate. Any higher completed daily high replaces the candidate and
restarts the five-session count. Lower highs do not create more pivot values.
There is no minimum pullback: a tight sideways range is allowed. If the lowest
subsequent daily low creates a pullback greater than one third of base depth,
the candidate is invalidated.

The left high remains the active breakout pivot while the candidate is forming.
After five completed sessions without a higher high and without excessive
pullback, the candidate candle's daily high replaces it:

```text
pivot_source   = DAILY_HANDLE
selected_pivot = candidate daily High
```

Without a valid handle:

```text
pivot_source   = LEFT_HIGH
selected_pivot = left_high
```

If a higher high appears after `HANDLE_READY` without a closing breakout, the
state becomes `HANDLE_REFORMING` and the five-session confirmation restarts.
The previous ready handle remains stored, but breakout confirmation is disabled
until the higher candidate is ready. Excessive pullback returns selection to
the left high.

## 4. Breakout confirmation

A close must cross the buffered selected pivot:

```text
breakout_buffer = max(
    0.5% * selected_pivot,
    0.20 * pivot_candle_daily_ATR_14
)

confirmation_level = selected_pivot + breakout_buffer

previous_daily_close <= confirmation_level
current_daily_close  >  confirmation_level
```

This correctly detects a close that moves from slightly above the raw pivot to
above the buffered level. Comparing `previous_close` only with the raw pivot
would miss that transition.

Once a handle is ready, breakout is checked before processing a higher high.
Therefore a daily close above the existing confirmation level freezes the
existing pivot; the breakout candle cannot move its own pivot upward.

The left-high pivot is breakout-eligible immediately after the base low and
remains authoritative until a daily handle becomes ready.

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
buffer distinguishes a decisive failure from a marginal daily breach:

```text
failure_buffer = max(
    1.0% * selected_pivot,
    0.25 * breakout_day_daily_ATR_14
)

hard_failure_level = breakout_range_low - failure_buffer
```

A confirmed breakout fails when either condition occurs:

```text
1. one daily close < hard_failure_level
2. two consecutive daily closes < breakout_range_low
```

One close below the range low but above the hard failure level is only a range
breach warning. It is not immediately archived. Failure is evaluated from
daily closes, not intraday lows, to reduce noise.

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
