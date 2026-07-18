# Base Lifecycle Scanner Flow

This file is the working spec for the newer base/tracking lifecycle engine and
`Streamlit/base_lifecycle_scanner.py`. Keep suggestions, doubts, and future rule
changes here so the logic can evolve without disturbing the older Base Formation
scanner.

Pivot construction, buffered breakout confirmation, pivot freezing, and failure
rules are specified in `base_lifecycle_pivot_breakout.md`. That focused document
is authoritative whenever this overview and the pivot implementation differ.

## 1. Data Universe

- Reads daily parquet files from `data/daily`.
- Fallback path: `data/test_data`.
- Uses the last `1000` daily candles per stock.

## 2. Fixed Daily Trend Filter

Stock is rejected unless:

```text
latest close > EMA200
EMA50 > EMA200
```

EMA values are calculated on daily close.

## 3. Weekly Conversion

Daily data is resampled to weekly:

```text
Open   = first
High   = max
Low    = min
Close  = last
Volume = sum
```

Minimum weekly bars required:

```text
MIN_WEEKLY_BARS_REQUIRED = MIN_WEEKS + 2
default = 8 + 2 = 10 weeks
```

## 4. Multi-Window Scan

Each stock is scanned separately across:

```text
26, 52, 104 weeks
```

If stock has fewer weekly candles than a window, that window is skipped.

## 5. Left High Detection

For each scan window:

- Exclude the last `MIN_WEEKS` from peak search.
- Default `MIN_WEEKS = 8`.

Example:

```text
In a 52-week window, scanner searches left high in the first 44 weeks.
```

Logic:

```text
peak_search_window = window excluding last MIN_WEEKS
left_high = highest High in peak_search_window
```

## 6. Base Low Detection

After left high:

```text
base_low = lowest Low after left_high
```

## 7. Depth Filter

Depth:

```text
Depth = (left_high - base_low) / left_high
```

Current default hard filter:

```text
MIN_DEPTH = 15%
MAX_DEPTH = 60%
```

Accepted only if:

```text
15% <= depth <= 60%
```

## 8. Recovery Filter

Recovery from bottom:

```text
recovery_pct = (latest_close - base_low) / (left_high - base_low)
```

Base phase default hard filter:

```text
recovery_pct >= 60%
```

Tracking eligibility default:

```text
TRACKING_ELIGIBLE_RECOVERY_MIN = 85%
```

There is no upper cap, so values above `100%` are allowed. These may already be
breakout or extension cases and should be handled by tracking instead of being
rejected by base detection.

## 9. Base Duration

Returned as information, not a hard filter:

```text
base_duration_weeks = weeks from left_high to latest candle
```

## 10. Compression

Calculated, not a hard filter.

Weekly ATR uses:

```text
ATR_WINDOW = 14
```

Compression is true if:

```text
average ATR of last 10 weeks < 30th percentile ATR of full scan window
```

Defaults:

```text
COMPRESSION_LOOKBACK = 10
ATR percentile threshold = 30%
```

## 11. Tight Group

Calculated, not a hard filter.

Uses last `5` weekly closes:

```text
tight_range = (max_close - min_close) / average_close
```

Tight group is true if:

```text
tight_range < 5%
```

Returned as:

```text
Tight Groups = 1 or 0
```

## 12. Prior Uptrend

Prior uptrend is a hard scanner filter in the lifecycle scanner.

Looks at up to `12` weekly candles before left high:

```text
prior_uptrend_pct = (left_high - lowest_low_before_base) / lowest_low_before_base
```

Minimum required prior uptrend:

```text
min_prior_uptrend_pct = max(20%, 1.0 * depth)
```

Example:

```text
If depth = 20%:
min_prior_uptrend_pct = max(20%, 20%) = 20%
```

If prior uptrend is below the required value, that stock-window result is rejected.
Both values are configurable in the Base Lifecycle sidebar:

```text
MIN_PRIOR_UPTREND_PCT
PRIOR_UPTREND_DEPTH_MULTIPLIER
```

Returned for accepted rows as:

```text
prior_uptrend = True
```

## 13. Pivot Detection

The scanner exposes five raw values after the base low:

```text
left_high_pivot
range_high_pivot
range_close_pivot
resistance_cluster_pivot
handle_high_pivot
```

Raw candidates must stay between 85% and 105% of the left high. The actionable
major pivot is `max(left_high_pivot, range_high_pivot)`. A handle is separately
actionable only when it is more than 2% below the major pivot. The older swing
calculation is retained only as `legacy_pivot_price` for comparison.

See `base_lifecycle_pivot_breakout.md` for exact construction and freezing rules.

## 14. Distance Metrics

Returned columns:

```text
distance_from_left_high_pct = (latest_close - left_high) / left_high
distance_from_pivot_pct    = (latest_close - major_pivot) / major_pivot
```

Examples:

```text
-0.03 means 3% below pivot/left high.
 0.08 means 8% above pivot/left high.
```

## 15. Breakout Detection

Breakout is confirmed by a weekly-close crossing of a frozen buffered level:

```text
breakout_buffer = max(0.5% of pivot, 0.20 * setup weekly ATR)
confirmation_level = pivot + breakout_buffer

previous_close <= confirmation_level
current_close > confirmation_level
```

The evaluated candle is excluded from its own pivot calculation. At confirmation,
the major pivot, candidates, setup ATR, buffers, and breakout date freeze.

Returned metrics:

- `breakout_date`
- `days_since_breakout`
- `weeks_since_breakout`
- `breakout_close`
- `breakout_volume_ratio`
- `gain_since_breakout_pct`
- `max_gain_after_breakout_pct`
- `max_drawdown_after_breakout_pct`
- `pullback_from_post_breakout_high_pct`
- `holding_pivot`

Volume ratio:

```text
breakout_volume_ratio = breakout_week_volume / 10-week volume MA
```

## 16. Lifecycle Status

Pre-breakout progression includes:

```text
BASE_FORMING / TRACKING
CLOSE_RESISTANCE_CLEARED
HANDLE_BREAKOUT_ATTEMPT
HANDLE_BREAKOUT_CONFIRMED
BREAKOUT_ATTEMPT
BREAKOUT_CONFIRMED
```

Post-breakout holding/failure states include:

```text
HOLDING_PIVOT
PIVOT_RETEST_WEAK
PULLBACK_TO_PIVOT
EXTENDED
FAILED
```

One close below the frozen failure level or two consecutive closes below the raw
major pivot produces `FAILED`. Exact status priority is documented in
`base_lifecycle_pivot_breakout.md`.

## 17. Score

Max score is capped at `100`.

Score components:

```text
Recovery quality: up to 25 points
Depth quality:    up to 20 points
Pivot distance:   up to 20 points if below/near pivot
Post-breakout:    up to 15 points if above pivot
Prior uptrend:    +10
Compression:      +10
Tight group:      +5
Pivot detected:   +10
```

Depth quality is best around:

```text
30% depth
```

Distance logic:

- If below pivot, best score is near pivot.
- If above pivot, score reduces as it gets extended.
- Above `25%` from pivot gives `0` for post-breakout distance score.

## 18. Best Row Selection

For each stock:

- Scanner may find valid results in multiple windows.
- The main dashboard table is not duplicated by window.
- It sorts window results by:

```text
score descending
pivot_detected descending
scan_window_weeks descending
```

Then keeps the best row in the main table.

This means the main table is a union of symbols, with one best row per stock.
If the same stock qualifies in `16`, `26`, and `52` weeks, only its best-scoring
row appears in the main table.

All valid stock-window rows are still stored and shown in:

```text
All Window Results
```

So `All Window Results` can contain the same stock multiple times, one row per
valid scan window.

## 19. Ranking

Final candidate table:

```text
sort by score descending
rank = 1, 2, 3...
```

## 20. Weekly Snapshot Comparison

Each run saves:

```text
data/base_lifecycle_scans/base_lifecycle_YYYY-MM-DD.parquet
data/base_lifecycle_scans/latest.parquet
data/base_lifecycle_scans/base_lifecycle_windows_YYYY-MM-DD.parquet
data/base_lifecycle_scans/latest_windows.parquet
data/base_lifecycle_scans/base_lifecycle_stages_YYYY-MM-DD.parquet
data/base_lifecycle_scans/latest_stage_results.parquet
```

Comparison with previous snapshot:

```text
New       = not present previously
Improved  = score_delta >= +5
Weakened  = score_delta <= -5
Continued = same status and small score change
Dropped   = present before, absent now
```

If lifecycle status changed, it shows:

```text
OLD_STATUS -> NEW_STATUS
```

Lifecycle symbols are stored stockwise without exchange suffix:

```text
ABB.NS parquet file -> Symbol = ABB
```

Local file lookup still supports `.NS.parquet`, but scanner outputs and tracking
ids avoid `.NS` so the flow can generalize stockwise.

## 21. Review Funnel

The lifecycle scanner also stores stage-level rows so a trader can inspect stocks
before they become final candidates.

Current stage keys:

```text
daily_trend_passed
weekly_data_passed
depth_passed
recovery_passed
prior_uptrend_passed
pivot_evaluated
final_candidates
rejected
```

Stage tables may show the same stock multiple times because each stock-window is
evaluated separately across:

```text
26, 52, 104 weeks
```

The main lifecycle table still shows one best row per stock, but the Review
Funnel can show every stock-window row at each scanner step.

Rejected rows may include:

```text
daily_trend_failed
not_enough_weekly_data
depth_too_shallow
depth_too_deep
recovery_too_low
prior_uptrend_too_low
no_valid_window
condition_error
```

This is intended for manual review while scanner rules are still being improved.

## 22. Historical Tracking Replay

The lifecycle engine supports historical as-of scans:

```text
AS_OF_DATE
```

When this is set, each symbol is sliced to data available on or before that date.
This lets prior-uptrend and other rule changes be tested on historical snapshots.

The Base Lifecycle page also supports replay between a start date and end date.
Replay frequency can be:

```text
Daily
Weekly Friday
```

Daily replay stores one snapshot per calendar date in the selected range.
Weekly Friday replay stores Friday snapshots plus the exact end date if needed.
Each run is saved using the snapshot date:

```text
base_lifecycle_YYYY-MM-DD.parquet
base_lifecycle_windows_YYYY-MM-DD.parquet
base_lifecycle_stages_YYYY-MM-DD.parquet
```

Lifecycle dashboard pages can load any saved snapshot date that has a matching
`base_lifecycle_YYYY-MM-DD.parquet` file. This allows reviewing the dashboard as
of a historical scan date instead of always viewing `latest`.

## 23. Continuous Base Tracking

Scanner snapshots answer:

```text
What fresh bases did this scan date detect?
```

The tracking ledger answers:

```text
Which previously detected bases are still being watched?
```

Tracking files are stored separately from weekly scanner snapshot files:

```text
data/base_lifecycle_tracking/active_tracked_bases.parquet
data/base_lifecycle_tracking/tracking_history.parquet
data/base_lifecycle_tracking/archived_tracked_bases.parquet
```

When a base first appears in the lifecycle scanner and has
`recovery_pct >= TRACKING_ELIGIBLE_RECOVERY_MIN`, it is added to active tracking
with a stable `base_id` built from:

```text
Symbol
left_high_date
base_low_date
```

Pivot is deliberately excluded from `base_id` because pivot logic may evolve
while the same base is being tracked.

On each single scan or replay date:

```text
1. Fresh bases are scanned and saved as normal.
2. New detected bases are added to active tracking.
3. Existing active bases are updated from current price data even if they no longer pass fresh base detection.
4. Breakout, pullback, extension, and failure metrics are recalculated from the stored pivot.
5. FAILED bases move to archived tracking.
6. Every date update is appended to tracking_history.
```

This allows a stock that was detected two weeks ago to keep being tracked after
breakout or extension, even if today's base scanner would no longer rediscover
that old base.

## 24. UI Workflow

Only two lifecycle pages are exposed in the sidebar:

```text
Base Phase
Tracking Phase
```

`Base Phase` scans and replays base candidates over an as-of date or date range.
During initial setup, scan/replay execution is kept out of Streamlit. Run it
from:

```text
python scripts/run_base_lifecycle_replay.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

Omit `--end-date` to replay through the current date. The script stores scanner
snapshots and sends eligible bases into tracking.

`Tracking Phase` reviews active, historical, and archived tracked bases from the
separate tracking files.

Tracking Phase recalculates the same historical state machine through each
tracking date. Once a breakout is found, the actionable levels remain frozen:

```text
left_high_pivot
range_high_pivot
range_close_pivot
resistance_cluster_pivot
handle_high_pivot
major_pivot
major_confirmation_level
major_failure_level
handle_pivot
handle_confirmation_level
handle_failure_level
active_pivot_price
active_pivot_type
active_pivot_reason
```

`active_pivot_price` is now a compatibility/display alias for `major_pivot`.
The old ranked active-pivot selector is not used by lifecycle or failure logic.
Tracked bases archive only after a confirmed major breakout fails; a failed
handle breakout returns to `RESETTING` instead.

Base Phase prior-uptrend now uses a variable lookback based on the selected base
window:

```text
prior_uptrend_lookback_weeks =
    min(PRIOR_UPTREND_MAX_LOOKBACK_WEEKS,
        max(PRIOR_UPTREND_MIN_LOOKBACK_WEEKS,
            scan_window_weeks * PRIOR_UPTREND_LOOKBACK_RATIO))
```

Defaults:

```text
26W base  -> 13W prior lookback
52W base  -> 26W prior lookback
104W base -> 52W prior lookback
```

The prior low must also be at least `PRIOR_UPTREND_MIN_ADVANCE_WEEKS`
before the left high, default 4 weeks. This avoids passing a stock only because
of a one-week spike from a very recent low.

Base Phase rejects structures where the left high and base low are from the same
weekly candle:

```text
peak_to_low_weeks < MIN_PEAK_TO_LOW_WEEKS
```

Default `MIN_PEAK_TO_LOW_WEEKS = 1`.

Tracking/status labels used by the lifecycle engine:

```text
BASE_FORMING
TRACKING
NEAR_PIVOT
CLOSE_RESISTANCE_CLEARED
HANDLE_BREAKOUT_ATTEMPT
HANDLE_BREAKOUT_CONFIRMED
BREAKOUT_ATTEMPT
BREAKOUT_CONFIRMED
HOLDING_PIVOT
PIVOT_RETEST_WEAK
EXTENDED
PULLBACK_TO_PIVOT
FAILED
RESETTING
```

New tracking rows carry manual review fields for later workflow support:

```text
review_status
setup_rating
notes
last_reviewed_date
```

Rows include `setup_reason`, a compact explanation such as:

```text
52W base, 31% depth, 93% recovery, -2.1% from pivot, 44% prior trend
```

Lifecycle UI code lives outside `home.py` in:

```text
Streamlit/base_lifecycle_pages.py
```

`home.py` only routes to the two lifecycle page render functions.

## Open Suggestions / Notes

- UI now keeps lifecycle review focused on `Base Phase` and `Tracking Phase`.
- Add future suggestions below this line.
- Keep proposed changes concrete: condition, current value, suggested value, and reason.
