# Base Lifecycle Command Runbook

This is the operating-command contract for the layered Base Lifecycle system.

## Command status

### Available now

- `reconstruct-baseline`
- `freeze-baseline`
- `validate`
- `shadow-incremental`
- `daily`
- `validate-state`
- Existing production replay: `scripts/run_base_lifecycle_replay.py`

### Planned before production checkpoint cutover

- `weekly-refresh`
- `rebuild`
- `audit-reconstruction`

Do not use a planned command until it has been implemented and its help output
is available through:

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py --help
```

---

## 1. Current validated baseline

The frozen reference version is:

```text
frozen-v5-2026-07-23
```

Its result covers:

```text
2026-05-01 through 2026-07-23
32,724 base/date rows
887 unique bases
0 parity mismatches
```

Do not modify this baseline directory:

```text
data/base_lifecycle_layers/baselines/frozen-v5-2026-07-23/
```

---

## 2. Commands available now

### Run the existing production replay

Single date:

```powershell
.\quant\Scripts\python.exe scripts\run_base_lifecycle_replay.py `
  --start-date 2026-07-24 `
  --end-date 2026-07-24
```

Date range:

```powershell
.\quant\Scripts\python.exe scripts\run_base_lifecycle_replay.py `
  --start-date 2026-07-24 `
  --end-date 2026-07-31
```

This remains available as the independent full reconstruction and repair path.

### Rebuild a clean isolated baseline

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py `
  reconstruct-baseline `
  --name frozen-v5-2026-07-23 `
  --start-date 2026-05-01 `
  --end-date 2026-07-23
```

Use a new name if a reconstruction with that name already exists.

### Freeze an existing clean tracking history

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py `
  freeze-baseline `
  --name frozen-v5-2026-07-23 `
  --start-date 2026-05-01 `
  --end-date 2026-07-23
```

### Validate a baseline

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py `
  validate `
  --name frozen-v5-2026-07-23 `
  --tracking-dir data\base_lifecycle_layers\baselines\frozen-v5-2026-07-23\reconstruction\tracking
```

Expected result:

```text
passed: true
total_mismatches: 0
```

### Run the incremental shadow comparison

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py `
  shadow-incremental `
  --name frozen-v5-2026-07-23
```

This:

1. Bootstraps each frozen base once.
2. Advances its lifecycle one daily candle at a time.
3. Writes versioned checkpoints and lifecycle events.
4. Compares all derived results with the baseline.
5. Does not modify production tracking data.

Expected result:

```text
expected_rows: 32,724
actual_rows: 32,724
total_mismatches: 0
checkpoint_count: 887
event_count: 2,651
```

### Start the Streamlit dashboard

```powershell
.\quant\Scripts\python.exe -m streamlit run Streamlit\home.py
```

On Lifecycle Journey, choose:

```text
Incremental Shadow · frozen-v5-2026-07-23 (validated)
```

Use `Production tracking` to return to the existing production files.

---

## 3. Normal daily command — available

Run this once after daily price data has been updated:

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py daily
```

It:

```text
Find the latest available market-data date
→ read the last successful checkpoint
→ identify missing business dates
→ process only missing daily candles
→ bootstrap newly discovered bases
→ save checkpoints, events, and dashboard views
```

It is idempotent. Running it again when current returns:

```text
No missing market dates. Nothing to process.
```

This is the only command required by a normal cloud schedule.

### Process through a specific date

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py daily `
  --as-of-date 2026-07-24
```

### Process a specific date range — planned

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py daily `
  --start-date 2026-07-24 `
  --end-date 2026-07-31
```

Already completed dates will be skipped unless an explicit force/rebuild
operation is requested.

---

## 4. Weekly processing — automatic

No separate weekly command will normally be scheduled.

When `daily` detects a newly completed weekly boundary, it automatically:

```text
Refresh weekly base structures
→ evaluate 104/52/26-week windows
→ register newly discovered bases
→ bootstrap their daily lifecycle
→ advance existing checkpoints
```

The same daily command will be scheduled Monday through Friday:

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py daily
```

### Manual weekly repair or testing — planned

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py weekly-refresh `
  --as-of-date 2026-07-24
```

The command will resolve the latest completed Friday and will not use an
incomplete weekly candle.

---

## 5. Historical rebuild by affected layer — planned

### Dashboard, sorting, filters, tags, or journey thresholds

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py rebuild `
  --from-layer views
```

This will not read OHLC files or recalculate pivots.

### Metrics only

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py rebuild `
  --from-layer metrics `
  --start-date 2026-05-01 `
  --end-date 2026-07-23
```

This will consume saved lifecycle history.

### Pivot, handle, breakout, success, or failure rules

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py rebuild `
  --from-layer lifecycle `
  --start-date 2026-05-01 `
  --end-date 2026-07-23
```

This will:

```text
Reuse saved base structures
→ invalidate lifecycle checkpoints from the start date
→ replay daily candles
→ rebuild lifecycle events and views
```

It will not rediscover every historical base.

### Base-structure rules

Use this after changing:

- Left-high selection
- Bottom selection
- Base depth
- Minimum decline duration
- Minimum base duration
- Prior-uptrend rules
- 104/52/26-week structure selection
- Equivalent-base rules

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py rebuild `
  --from-layer structures `
  --start-date 2026-05-01 `
  --end-date 2026-07-23
```

This is the expensive full rebuild because every downstream layer becomes
invalid.

### Corrected data for selected symbols

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py rebuild `
  --from-layer structures `
  --symbols AEROFLEX,RADICO `
  --start-date 2026-06-01 `
  --end-date 2026-07-23
```

This will rebuild only affected symbols and downstream dates.

---

## 6. Validation commands

### Validate current persisted state

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py validate-state
```

It will check:

- Duplicate `base_id + tracking_date` keys
- Checkpoint schema/config compatibility
- Checkpoint dates versus available market data
- Missing derived views
- Events later than their checkpoint
- Archived bases still marked active
- Missing or multiple confirmed active pivots
- Partial-date writes

### Independent reconstruction audit

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py audit-reconstruction `
  --start-date 2026-07-01 `
  --end-date 2026-07-31
```

This will independently reconstruct a selected range and compare it with
incremental results.

---

## 7. Decision table

| Change | Smallest required command |
|---|---|
| Normal market day | `daily` |
| Completed Friday | `daily` automatically refreshes structures |
| Dashboard columns or sorting | `rebuild --from-layer views` |
| 40%/85% journey thresholds | `rebuild --from-layer views` |
| Metrics formulas | `rebuild --from-layer metrics` |
| Pivot or handle rules | `rebuild --from-layer lifecycle` |
| Breakout/success/failure rules | `rebuild --from-layer lifecycle` |
| Base depth or duration | `rebuild --from-layer structures` |
| Left-high or bottom logic | `rebuild --from-layer structures` |
| Raw data corrected | Rebuild affected symbols from the earliest affected layer/date |

---

## 8. Cloud schedule after cutover

Schedule one command after daily OHLC data has been updated:

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py daily
```

The cloud environment must persist these artifacts between executions:

```text
Base structure registry
Latest lifecycle checkpoints
Lifecycle events
Daily tracking history/views
Layer manifests
Raw OHLC data
```

Do not rely on an ephemeral runner's local disk as the authoritative state.
Use object storage, a database, or a persistent volume.

---

## 9. Production-cutover checklist

Before replacing the existing replay command:

1. Implement `daily`.
2. Implement Friday structure refresh.
3. Implement the versioned structure registry.
4. Test one-day incremental equivalence.
5. Test multi-day catch-up equivalence.
6. Test same-date idempotence.
7. Test restart from persisted checkpoints.
8. Test interrupted-date atomicity.
9. Test new-base bootstrap on Friday.
10. Run an independent reconstruction audit.
11. Confirm zero unexplained mismatches.
12. Change the dashboard production source only after these checks pass.
