# Base Lifecycle Scanner — Iteration 3 (All Windows)

This is the working specification for `Streamlit/base_lifecycle_scanner.py` and
the Base Phase / Tracking Phase dashboard. Pivot construction, breakout
confirmation, success, retest, and failure details live in
`base_lifecycle_pivot_breakout.md`.

## 1. Purpose

The scanner has one primary job: keep a simple, persistent view of each stock's
journey from recovery through breakout.

The primary stages are:

```text
NOT_TRACKED
RECOVERY_BUILDING
BREAKOUT_CONSIDERATION
SUCCESSFUL_BREAKOUT
FAILED
```

Detailed pivot lifecycle fields remain in the saved data for diagnosis and
future strategies, but they are not the primary grouping or sorting system.
There is no strategy score or rank.

## 2. Data timing

Daily parquet data is the source.

- Base structure, left high, base low, and depth use completed Friday-labelled
  weekly candles. Monday through Thursday reuse the preceding Friday structure;
  Friday refreshes it with the newly completed week.
- The incomplete current week is excluded from structural calculations.
- Completed daily candles detect and confirm the handle, confirm breakout, and
  update post-breakout lifecycle. The latest daily close also drives recovery,
  pivot distance, and the reversible journey stage.

This keeps the base stable while allowing the dashboard to react during the
week as price changes.

## 3. All-window base discovery

Every stock is checked independently in this order:

```text
104 weeks -> 52 weeks -> 26 weeks
```

The scanner evaluates every window for which enough weekly history exists.
Each window can produce a valid lifecycle candidate, but an equivalent smaller
window is consolidated into the largest matching result:

```text
104W and 52W find the same base -> keep 104W once; record 104,52 as equivalent
52W finds a different base      -> save the distinct 52W candidate
26W finds a different base      -> save the distinct 26W candidate
```

Equivalence requires the same symbol, nearby left-high and bottom dates, and
similar anchor prices. This removes duplicate representations such as the same
51-week base found through both 104W and 52W searches while preserving genuinely
different nested bases. Recovery percentage does not decide whether a window is
structurally valid. A valid unique structure below 40% remains `NOT_TRACKED`
until its own recovery reaches the tracking threshold.

Lifecycle Journey, Base Phase, Tracking Phase, and Review Funnel provide a base
window filter. All available windows are selected by default.

## 4. Structural base rules

For each candidate window:

1. Search for the left high while excluding the latest 12 weekly candles.
2. Find the lowest weekly low after that left high.
3. Require the left high and base low to be at least six weeks apart.
4. Calculate depth:

```text
depth = (left_high - base_low) / left_high
```

5. Require depth between 15% and 60%.
6. Require a prior uptrend before the left high:

```text
minimum prior uptrend = max(20%, base depth)
```

The prior-uptrend lookback scales with the window and is capped by the current
configuration. Compression and tight-group fields are informational, not hard
filters.

Actual base width must be at least 12 weeks. It is measured from the left high
to the first applicable structural right edge:

```text
distinct handle exists -> handle pivot date
otherwise breakout     -> breakout date
otherwise               -> latest completed weekly candle
```

A fallback left-high pivot is not a right edge and is ignored for this
measurement. `base_end_date`, `base_end_reason`, and `base_duration_weeks` are
stored so the decision can be inspected in the UI.

No single weekly move may exceed 50% of the total base depth in price:

```text
weekly true range = max(
    weekly high - weekly low,
    abs(weekly high - previous weekly close),
    abs(weekly low - previous weekly close)
)

largest weekly true range / (left high - base low) <= 50%
```

This rejects bases dominated by one abnormal week. When a breakout has already
been confirmed, its breakout candle is excluded from this filter so a powerful
breakout does not invalidate the preceding base. The measured move, its date,
and its depth ratio are saved for review. The 50% limit is a fixed strategy
constant in `DEFAULT_PARAMS`; it does not need to be supplied to the replay
command.

The existing daily trend gate also remains:

```text
latest daily close > EMA200
daily EMA50 > daily EMA200
```

## 5. Daily recovery

Current recovery uses the latest daily close against the frozen structural
range:

```text
recovery_pct = (latest_daily_close - base_low) / (left_high - base_low)
```

Recovery may exceed 100%. The key thresholds are:

```text
40% = visible lifecycle entry
85% = breakout consideration
```

Recovery stages are reversible. A stock without a confirmed breakout can move
from 87% to 78% and return from `BREAKOUT_CONSIDERATION` to
`RECOVERY_BUILDING`. A fresh scan will place it correctly; no manual movement is
required.

## 6. Primary journey-stage decision

The stage priority is:

```python
if failed:
    journey_stage = "FAILED"
elif breakout_success:
    journey_stage = "SUCCESSFUL_BREAKOUT"
elif breakout_confirmed:
    journey_stage = "BREAKOUT_CONSIDERATION"
elif recovery_pct >= 0.85:
    journey_stage = "BREAKOUT_CONSIDERATION"
elif recovery_pct >= 0.40:
    journey_stage = "RECOVERY_BUILDING"
else:
    journey_stage = "NOT_TRACKED"
```

Confirmed breakout, success, and failure are historical/latching outcomes.
Consequently, ordinary recovery movement cannot erase them. Failure has highest
priority, followed by successful breakout.

`NOT_TRACKED` structural rows are not shown in the candidate table and are not
added to active tracking. They can be rediscovered automatically on a later
scan when daily recovery reaches 40%.

## 7. Pivot and breakout summary

Only two actionable pivot sources are needed:

```text
five-session daily handle ready -> selected_pivot = candidate daily High
otherwise                      -> selected_pivot = left high
```

The handle-high eligibility zone is relative to base depth, not to the absolute
left-high price:

```text
base_depth_price = left_high - base_low
minimum handle   = base_low + (0.85 * base_depth_price)
maximum handle   = base_low + (1.10 * base_depth_price)
```

The candidate handle can pull back no more than one third of base depth. Any
higher daily high before confirmation restarts its five-session count. After a
handle is confirmed, a higher high starts a pending replacement, but the
existing confirmed handle remains the active breakout pivot until that
replacement becomes valid. Candidate processing never disables breakout
detection. A daily close crossing the active pivot plus the daily ATR/price
buffer confirms breakout.
Post-breakout management uses a fixed range
from 10% below to 10% above the selected pivot. Success must also clear the old
left-high supply when the handle pivot is lower.

See `base_lifecycle_pivot_breakout.md` for exact formulas and failure buffers.

## 8. Persistence and tracking

At 40% recovery, each valid window candidate can enter active tracking. Its stable
`base_id` uses:

```text
Symbol + base_window_weeks + left_high_date + base_low_date
```

Several windows for the same symbol may be active simultaneously. The same
window/base identity cannot be inserted twice. Pivot is intentionally not part
of `base_id`, because handle selection can evolve while the base remains the
same.

Each tracking update:

1. reloads prices through the as-of date;
2. calculates current recovery and pivot distance from the latest daily close;
3. evaluates handle, breakout, and post-breakout history on completed daily candles;
4. recalculates the primary journey stage;
5. appends a dated history row; and
6. archives a base after a confirmed breakout fails.

Tracking continues even if the structure would no longer be rediscovered by a
fresh scan. This is how confirmed breakout history remains available.

Tracking files:

```text
data/base_lifecycle_tracking/active_tracked_bases.parquet
data/base_lifecycle_tracking/tracking_history.parquet
data/base_lifecycle_tracking/archived_tracked_bases.parquet
```

## 9. Dashboard presentation

`Lifecycle Journey` is the simple primary page. It combines active tracking with
the latest discovery snapshot, keeps one current row per window-aware base, and presents
exactly three primary tables in this order:

```text
Breakout Consideration
Recovery Building
Successful Breakout
```

`FAILED` and `NOT_TRACKED` are not shown on this page. Base Phase and Tracking
Phase remain available as diagnostic pages during validation.

All lifecycle pages expose a multi-select base-window filter with 104W, 52W,
and 26W selected by default. The same symbol can appear more than once when it
has valid bases in several windows.

The three journey tables lead with the compact decision set:

```text
Symbol
today_status
journey_stage
recovery_pct
base_window_weeks
pivot_source
selected_pivot
distance_from_pivot_pct
breakout_range_low
breakout_range_high
```

`today_status` is derived in the dashboard from tracking history and the
selected scan/replay date; it does not require another price scan:

```text
NEW BASE       first_detected_date equals the selected date
NEW TO STAGE   journey_stage differs from the preceding tracking date
CONTINUED      journey_stage is unchanged
```

The activity filter can show any combination of these values. On the History
tab, the status is evaluated against each row's own `tracking_date`; on current
views it is evaluated against the selected or latest tracking date. New and
new-to-stage rows sort before continued rows.

Other technical, industry, and tagging fields are selectable optional columns.
The main review order is journey stage, then recovery descending, then absolute
distance from pivot. The chart shows fine horizontal pivot and breakout-range
lines; detailed stock fields are collapsed below it.

## 10. Replay and saved output

Run a historical/current replay with one command:

```text
python scripts/run_base_lifecycle_replay.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

Omitting `--end-date` replays through the current date. Default `daily` mode
processes business days only. Every processed day refreshes recovery, pivot
distance, and journey state from the daily close; Friday additionally makes the
new completed weekly structure available. `--frequency weekly_friday` remains
available when only weekly snapshots are wanted. Default thresholds are 40%
discovery/tracking and 85% consideration. The script saves dated candidate,
diagnostic-stage, and tracking files under `data/`.

The command prints one progress-bar line after every completed replay date,
showing completed/total dates, percentage, daily versus weekly refresh mode,
candidate count, active tracked bases, and newly tracked bases.

Saved compatibility fields such as `lifecycle_status`, `lifecycle_phase`,
`major_pivot`, and `active_pivot_price` remain useful for detailed inspection.
They must not be treated as additional primary journey groups.

## 11. Intentionally deferred

The architecture retains enough raw fields to add these later without changing
the primary stage contract:

- trader review notes and validation decisions;
- recovery/pivot-distance filters;
- a separate post-success buy strategy;
- scoring or ranking, if evidence later supports it;
- finer secondary stages only when a real review need appears.
