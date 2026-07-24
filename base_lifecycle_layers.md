# Base Lifecycle Layered Migration

This document is the implementation contract for optimizing the existing
lifecycle without changing the frozen strategy.

## Non-negotiable parity rule

The optimized system is accepted only when all of these produce the same row
for every `base_id + tracking_date`:

1. Canonical clean historical replay.
2. Reconstruction by repeatedly applying the shared daily transition.
3. Incremental execution using yesterday's persisted state plus today's candle.

Dates, states, pivot sources, event dates, and archive outcomes must match
exactly. Numeric prices and percentages use only a very small floating-point
tolerance.

## Implemented foundation

### Shared daily state transition

`Streamlit/lifecycle_state_machine.py` owns the path-dependent handle state.

```python
new_state, events = advance_daily_handle_state(
    previous_state,
    completed_daily_candle,
    params,
)
```

`calculate_daily_handle_state()` now reconstructs history by initializing the
state once and folding this transition over the daily candles. The transition
is therefore already used by the existing lifecycle calculations; there is no
second pivot interpretation.

The state contains:

- confirmed active pivot and source;
- pending handle candidate;
- candidate session count and lowest pullback;
- confirmed handle pullback state;
- breakout latch;
- last processed candle and close;
- diagnostic handle fields.

The returned events are observational. They will become the append-only event
layer later, but they do not affect calculations.

### Canonical baseline and validation

`Streamlit/lifecycle_parity.py` can freeze and compare the important lifecycle
fields for every base/date row.

Create a clean isolated baseline:

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py `
  reconstruct-baseline `
  --name frozen-v5-2026-07-23 `
  --start-date 2026-05-01 `
  --end-date 2026-07-23
```

The replay is written below:

```text
data/base_lifecycle_layers/baselines/<name>/reconstruction/
```

It does not modify the normal scanner or dashboard tracking directories. A
baseline name cannot be reconstructed twice; use a new name rather than mixing
two runs.

If a clean tracking history already exists, freeze it without replay:

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py `
  freeze-baseline `
  --name frozen-v5-2026-07-23 `
  --start-date 2026-05-01 `
  --end-date 2026-07-23
```

Validate the normal stored history:

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py `
  validate `
  --name frozen-v5-2026-07-23
```

Validation exits with code `1` on any missing row, unexpected row, missing
column, duplicate key, or field mismatch. This makes it suitable for CI.

### Replay output isolation

The existing replay also accepts:

```text
--scan-dir
--tracking-dir
```

This permits shadow runs and experiments without cleaning production data.

### Same-date idempotence

Tracking-history replacement now compares normalized `base_id + tracking_date`
keys. Running a date again replaces that date instead of appending a duplicate
caused by different string representations of the same timestamp.

## Target layers

### Layer 1 — Base Structure Registry

Heavy weekly structure discovery. It stores fixed base facts only:

- base identity and window;
- left high and bottom;
- depth, duration, and structural validation fields;
- first and last validity dates;
- structure logic/config versions.

This layer is refreshed after a completed Friday candle and whenever base
formation rules change.

### Layer 2 — Daily Lifecycle State and Events

Uses the structure registry plus completed daily candles. It stores one current
state per base and append-only transition events. Normal execution advances
only missing candles. New bases are bootstrapped once from their base low.

Changes to pivot, handle, breakout, success, or failure rules rebuild from this
layer while reusing Layer 1.

### Layer 3 — Journey Views and Metrics

Pure derived mappings:

- Recovery Building;
- Breakout Consideration;
- Successful Breakout;
- dashboard filtering, sorting, optional tags, and later metrics.

Threshold or UI changes rebuild only this layer.

## Incremental checkpoint shadow layer

The first incremental shadow layer is implemented.

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py `
  shadow-incremental `
  --name frozen-v5-2026-07-23
```

It uses the frozen reconstruction for base membership and immutable structure
facts, then independently recalculates all pivot, handle, breakout, success,
failure, status, and journey fields by advancing completed daily candles.

Outputs:

```text
<baseline>/shadow_incremental/tracking_history.parquet
<baseline>/shadow_incremental/state/latest_checkpoints.parquet
<baseline>/shadow_incremental/state/lifecycle_events.parquet
<baseline>/shadow_incremental/parity_report.json
```

The checkpoint contains the complete serializable path-dependent state and is
guarded by checkpoint-schema, logic-version, and strategy-config hashes.
Checkpoint writes and shadow-history writes use temporary files followed by
atomic replacement.

For `frozen-v5-2026-07-23`, the shadow result is:

```text
baseline rows        32,724
shadow rows          32,724
missing/unexpected   0
duplicate keys       0
field mismatches     0
final checkpoints    887
lifecycle events     2,651
```

The shadow harness deliberately reuses frozen discovery dates. It proves the
daily lifecycle can be incremental without changing results; it does not yet
replace weekly base discovery or the production tracking store.

## Production daily orchestrator

The date-oriented production orchestrator and versioned structure registry are
implemented:

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py daily
```

It bootstraps once from the validated baseline, reads actual market sessions,
advances only missing candles, refreshes structures at a newly completed weekly
boundary, bootstraps newly eligible structures, and commits one recoverable
partition per processing date. Re-running a completed date is a no-op.

Validate current persisted state:

```powershell
.\quant\Scripts\python.exe scripts\run_lifecycle_pipeline.py validate-state
```

The initial production seed through 2026-07-23 matches all 32,724 frozen
base/date rows with zero differences.

The next boundary is selective historical rebuild orchestration and a cloud
persistence adapter. The local production runner is already usable with
persistent local storage.
