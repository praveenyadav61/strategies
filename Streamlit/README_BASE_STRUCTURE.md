# Base Lifecycle Scanner — Structure Criteria

The scanner converts William O'Neil and Mark Minervini's base concepts, together with practical trading experience, into consistent and measurable rules suitable for research, monitoring and eventual algorithmic execution.

## Current criteria

| Area | Current rule | Effect | Reasoning |
|---|---|---|---|
| Trend | Latest close > EMA 200 and EMA 50 > EMA 200 | Hard requirement | Keeps the scan focused on securities in an established long-term uptrend rather than rebounds inside a larger decline |
| Weekly data | Only completed weekly candles are used; at least 10 weekly bars must be available | Hard requirement | Prevents incomplete midweek candles from moving structural highs, lows and recovery values |
| Search windows | Scan 104, 52 and 26-week lookbacks, largest first | Structure discovery | Captures long bases as well as newer or nested structures without assuming a fixed base duration |
| Left high | Highest weekly high in the search window after excluding the latest 8 weeks | Structural anchor | Identifies the point from which the correction began while avoiding a very recent fluctuation being treated as a mature base start |
| Bottom | Lowest weekly low occurring after the selected left high | Structural anchor | Enforces the chronological sequence `left high → correction → bottom` |
| Base depth | `(left high - bottom) / left high`; must be between 15% and 65% | Hard requirement | Rejects pullbacks that are too small to represent the intended base and structures with excessive technical damage |
| Prior uptrend | Advance before the left high must be at least `max(20%, base depth)` | Hard requirement | Confirms that the base is consolidating a meaningful earlier advance; deeper bases require stronger prior movement |
| Prior advance duration | The qualifying prior advance must span at least 4 weeks | Hard requirement | Avoids treating a brief price spike as an established prior trend |
| Prior-uptrend lookback | Proportional to the base window and limited to 12–52 weeks | Validation range | Provides enough history to evaluate the earlier advance without using an unrelated distant move |
| Recovery | `(latest close - bottom) / (left high - bottom)` | Lifecycle measure | Shows how far price has recovered through the base; it measures maturity rather than structure quality alone |
| Tracking threshold | Recovery of at least 40% | Lifecycle classification | Below 40%, the structure is retained as `NOT_TRACKED`; at 40%+, it enters `RECOVERY_BUILDING` |
| Breakout consideration | Recovery of at least 85% | Lifecycle classification | Price is sufficiently close to the prior high for pivot, handle and breakout analysis; this is not itself a buy signal |
| Similar structures | Merge equivalent detections found through the 104, 52 and 26-week windows | Deduplication | Prevents the same economic base from appearing multiple times merely because different lookbacks detected it |

> **Important:** Excluding the latest 8 weeks when locating the left high does not impose an 8-week minimum base width or an 8-week left-high-to-bottom duration.

## Informational measurements

These values are stored for UI filtering, ranking and research. They do not currently reject a base.

| Column | What it measures | Why it is retained |
|---|---|---|
| `peak_to_low_weeks` | Weeks from the left high to the bottom | Distinguishes a rapid decline from a gradual correction |
| `base_duration_weeks` | Total duration from the left high to the resolved structure end | Allows later testing of whether wider bases produce better results |
| `largest_single_week_move_to_depth_ratio` | Largest weekly true range ÷ total base depth | Identifies structures in which one abnormal week dominates the correction |
| Compression and tightness | Volatility contraction and recent closing-range tightness | Supports quality ranking without changing the definition of a valid base |

## Equivalent-structure rule

Two detections are merged only when the symbol matches and all the following tolerances are satisfied:

| Anchor | Maximum difference |
|---|---:|
| Left-high date | 2 weeks |
| Bottom date | 1 week |
| Left-high price | 5% |
| Bottom price | 3% |

The largest matching window is retained as the canonical result. Matching windows are recorded in `equivalent_base_windows`; prices and measurements are not averaged. A smaller-window result remains separate when its anchors represent a genuinely different or nested base.

## Design principle

> Use hard rules for conditions necessary to define the base. Keep debatable quality characteristics as measurable columns until results justify turning them into filters.

## Current strategy version

`base_lifecycle_2026-07-31`

- Left-high-to-bottom duration is informational, not a rejection condition.
- Total base duration is informational, not a rejection condition.
- Largest weekly true-range-to-depth ratio is informational, not a rejection condition.

## Commands to rerun the strategy

Run these commands one at a time from the project root. Continue to the next step only when the current command completes successfully.

### 1. Reconstruct the baseline through 28 July 2026

```powershell
.\quant\Scripts\python.exe .\scripts\run_lifecycle_pipeline.py reconstruct-baseline `
  --name frozen-2026-07-31-depth65 `
  --start-date 2026-05-01 `
  --end-date 2026-07-28
```

### 2. Build and validate incremental checkpoints

```powershell
.\quant\Scripts\python.exe .\scripts\run_lifecycle_pipeline.py shadow-incremental `
  --name frozen-2026-07-31-depth65
```

Required result:

```text
"passed": true
"total_mismatches": 0
```

### 3. Preserve the current production before switching

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Move-Item `
  -LiteralPath .\data\base_lifecycle_layers\production `
  -Destination ".\data\base_lifecycle_layers\production-before-depth65-$stamp"
```

The backup is recoverable and is not used as the active dashboard source.

### 4. Activate the reconstructed result

```powershell
.\quant\Scripts\python.exe .\scripts\run_lifecycle_pipeline.py daily `
  --baseline-name frozen-2026-07-31-depth65 `
  --as-of-date 2026-07-28 `
  --production-dir data\base_lifecycle_layers\production
```

### 5. Validate active production

```powershell
.\quant\Scripts\python.exe .\scripts\run_lifecycle_pipeline.py validate-state `
  --production-dir data\base_lifecycle_layers\production
```

Required result:

```text
"passed": true
```

### 6. Export the latest next-session candidates

```powershell
.\quant\Scripts\python.exe .\scripts\export_just_below_breakout.py `
  --production-dir data\base_lifecycle_layers\production
```

This produces `data\just_below_breakout.csv` with:

```text
symbol,price_high_limit
```

The same command also writes the latest 10 market sessions to:

```text
data/signals/signal_YYYY-MM-DD.csv
```

Use `--history-sessions` to change the number of dated files and
`--signals-dir` to choose another destination.

The default next-session conditions are:

```text
Below pivot:
0 <= selected_pivot - latest_close
  <= max(largest_single_week_move, selected_pivot * 5%)

Above pivot buffer:
selected_pivot < latest_close <= confirmation_level
```

`largest_single_week_move` is the largest weekly true range observed for the
base. If only its stored ratio is available, the exporter reconstructs the
absolute move from base depth. Below-pivot rows export the selected pivot as
`price_high_limit`; above-pivot buffer rows export the confirmation level.

Historical all-date signal export is a post-replay step and will use the same tracking history; it does not require changes to the scanner or replay calculation.
