# Base Lifecycle Platform — New Project Blueprint

## 1. Document role

This is the long-term implementation contract for rebuilding the Base Lifecycle
system in a new repository. Copy it to
`docs/BASE_LIFECYCLE_PROJECT_BLUEPRINT.md` before development starts.

The final system must support:

- all-window base discovery and durable candidate history;
- deterministic, replaceable base selection;
- recovery, breakout, success, failure, completion, and repeated-base cycles;
- price and non-price feature enrichment;
- independent strategies at recovery, breakout, and post-breakout levels;
- future evidence-based scoring;
- point-in-time historical replay without look-ahead bias;
- partial reruns that reuse compatible upstream artifacts;
- shadow experiments alongside a stable baseline;
- compact trader views backed by complete diagnostics.

Build this system through small validated stages. Do not attempt one large
rewrite.

---

## 2. Permanent instructions for Codex

Create an `AGENTS.md` in the new repository containing:

```text
Before planning or changing Base Lifecycle code, read:
1. docs/BASE_LIFECYCLE_PROJECT_BLUEPRINT.md
2. docs/IMPLEMENTATION_STATUS.md
3. docs/DECISIONS.md

The blueprint defines the target architecture. IMPLEMENTATION_STATUS.md defines
what actually exists today. Do not assume a later stage is implemented merely
because it appears in the blueprint.
```

Codex must follow these rules:

1. Identify the affected architectural layer before editing.
2. Identify every downstream artifact invalidated by the change.
3. Reuse upstream artifacts only when their schema, inputs, code, and config
   fingerprints remain compatible.
4. Never silently change a persisted field's meaning.
5. Version detector, selector, lifecycle, feature, and strategy rules
   independently.
6. Implement one stage or one bounded cross-stage change at a time.
7. Add validation in the same change as behaviour.
8. Keep business rules out of UI code.
9. Never use information published after a historical `as_of_date`.
10. Never introduce scoring only to hide an unresolved selection decision.
11. Compare experiments with a named frozen baseline.
12. Update `docs/IMPLEMENTATION_STATUS.md` after every completed stage.
13. Record important choices in `docs/DECISIONS.md`.
14. At handoff, report changed layers, invalidated artifacts, commands run,
    validation results, and the next safe stage.

Every change plan should include:

```text
Changed layer:
Changed contract/rule:
Upstream artifacts reused:
Downstream artifacts invalidated:
Required schema migration:
Smallest correct rerun command:
Required validations:
```

---

## 3. Core design principles

### 3.1 Separate facts, interpretations, and decisions

```text
Facts          = normalized market and external data
Interpretation = structures, pivots, lifecycle events, features
Decision       = primary selection, strategy signals, scores, trader actions
```

A downstream decision must never rewrite upstream facts.

### 3.2 Persist reusable layer outputs

```text
Raw sources
  ↓
Normalized daily data
  ↓
Completed weekly bars
  ↓
All window candidates
  ↓
Consolidated unique structures
  ↓
Primary/shadow selection decisions
  ↓
Lifecycle events and current state
  ↓
Feature snapshots
  ↓
Strategy signals
  ↓
Scores and rankings
  ↓
Dashboard views
```

Each arrow is an explicit versioned contract. This enables selective reruns.

### 3.3 Detection and selection are separate

The detector answers:

```text
Which valid structures exist and why?
```

The selector answers:

```text
Which valid structure should this policy make primary?
```

The detector must not contain scoring or UI priorities.

### 3.4 Time correctness is mandatory

Every artifact has an `as_of_date`. External information also has an
`available_date`. Historical processing may consume a record only when:

```text
available_date <= as_of_date
```

### 3.5 Multiple structures per stock are normal

```text
Symbol
├── Structure A → Lifecycle A → completed
├── Structure B → Lifecycle B → failed
└── Structure C → Lifecycle C → active
```

A successful old base must not permanently block a later base.

### 3.6 Replays are deterministic and idempotent

Identical data fingerprints, code versions, configs, and dates must produce
identical canonical output. Repeating a partition must not duplicate events.

---

## 4. Target repository layout

```text
project/
├── AGENTS.md
├── pyproject.toml
├── README.md
├── config/
│   ├── data.yaml
│   ├── structure.yaml
│   ├── selection.yaml
│   ├── lifecycle.yaml
│   ├── features.yaml
│   ├── strategies.yaml
│   └── environments/{development,research,production}.yaml
├── docs/
│   ├── BASE_LIFECYCLE_PROJECT_BLUEPRINT.md
│   ├── IMPLEMENTATION_STATUS.md
│   ├── DECISIONS.md
│   ├── DATA_DICTIONARY.md
│   ├── RUNBOOK.md
│   └── VALIDATION_REPORTS.md
├── src/base_lifecycle/
│   ├── cli.py
│   ├── config.py
│   ├── contracts/{identifiers,schemas,versions}.py
│   ├── data/{ingest,normalize,quality,calendar}.py
│   ├── bars/{daily,weekly}.py
│   ├── structure/{detector,windows,validator,deduplication}.py
│   ├── selection/{base,largest_window,shadow}.py
│   ├── pivot/{handle,levels,breakout}.py
│   ├── lifecycle/{events,reducer,transitions,completion}.py
│   ├── features/{base,registry,price,fundamentals,events,market_context}.py
│   ├── strategies/{base,recovery,breakout,post_breakout}.py
│   ├── scoring/{base,experiments}.py
│   ├── persistence/{artifact_store,manifests,repositories}.py
│   ├── pipeline/{graph,runner,invalidation,comparison}.py
│   └── views/{journey,diagnostics}.py
├── apps/streamlit_app.py
├── scripts/{bootstrap,run_historical,run_daily,validate_stage,compare_runs}.ps1
├── tests/{unit,contracts,integration,golden,temporal,performance}/
└── artifacts/
    ├── manifests/
    ├── normalized_daily/
    ├── weekly_bars/
    ├── base_candidates/
    ├── base_structures/
    ├── selection_decisions/
    ├── lifecycle_events/
    ├── lifecycle_state/
    ├── feature_snapshots/
    ├── strategy_signals/
    ├── rankings/
    └── dashboard_views/
```

Storage technology may change. Logical contracts and layer boundaries should
remain stable.

---

## 5. Layer catalog

| Layer | Responsibility | Consumes | Produces |
|---|---|---|---|
| L0 | Raw source capture | Files/APIs | Immutable raw snapshots |
| L1 | Normalization/quality | L0 | Canonical daily and external records |
| L2 | Bar aggregation | L1 | Daily signals and completed weekly bars |
| L3 | Structure discovery | L2 | All candidates and rejection diagnostics |
| L4 | Structure consolidation | L3 | Deduplicated valid structures |
| L5 | Selection | L4 | Primary and shadow decisions |
| L6 | Lifecycle | L2, L4, L5 | Events and current state |
| L7 | Feature enrichment | L1, L2, L4, L6 | Point-in-time features |
| L8 | Strategies | L4, L6, L7 | Named strategy signals |
| L9 | Scoring/ranking | L4, L6, L7, L8 | Experimental/promoted ranks |
| L10 | Views/UI | L4–L9 | Read-optimized views and charts |

Dependencies flow downward only. The UI must never call detector internals to
recalculate a base.

---

## 6. Canonical identifiers

```text
symbol_id = normalized exchange-aware symbol

structure_id = hash(
    symbol_id,
    left_high_date,
    base_low_date,
    detector_major_version
)

candidate_id = hash(
    structure_id,
    scan_window_weeks,
    as_of_date,
    detector_full_version
)

lifecycle_id = structure_id + lifecycle_sequence

selection_id = hash(symbol_id, as_of_date, selection_policy_version)

signal_id = hash(lifecycle_id, signal_date, strategy_name, strategy_version)
```

Search window is not part of `structure_id`; several windows may discover the
same geometry.

---

## 7. Artifact manifests and cache validity

Every persisted artifact partition must have a manifest:

```text
artifact_name
schema_version
layer
run_id
created_at
as_of_start
as_of_end
symbol_count
row_count
input_artifact_versions
input_fingerprints
code_version
config_hash
rule_version
partition_keys
validation_status
validation_report_path
```

An artifact is reusable only when all relevant fingerprints match. File
existence is not sufficient proof of validity.

Recommended partitioning:

```text
as_of_date / symbol_bucket
```

Long runs should resume from the last completed validated partition.

---

## 8. Configuration contracts

Avoid one giant parameter dictionary. Separate configs by consumer.

Example `config/structure.yaml`:

```yaml
version: structure_v1
windows_weeks: [104, 52, 26]
left_high_exclusion_weeks:
  104: 12
  52: 12
  26: 12
minimum_base_duration_weeks: 12
minimum_peak_to_low_weeks: 6
minimum_depth: 0.15
maximum_depth: 0.60
maximum_single_week_move_to_depth: 0.50
prior_uptrend:
  minimum_pct: 0.20
  depth_multiplier: 1.0
  lookback_ratio: 0.50
  minimum_lookback_weeks: 12
  maximum_lookback_weeks: 52
  minimum_advance_weeks: 4
```

Example `config/selection.yaml`:

```yaml
version: selection_largest_window_v1
policy: largest_window
deduplicate_identical_structures: true
shadow_track_alternatives: true
tie_breakers:
  - actual_base_duration_desc
  - left_high_date_asc
```

Example `config/lifecycle.yaml`:

```yaml
version: lifecycle_v1
recovery_tracking_threshold: 0.40
recovery_consideration_threshold: 0.85
handle:
  lookback_weeks: 10
  minimum_pullback_pct: 0.03
  maximum_pullback_base_depth_fraction: 0.333333
  minimum_duration_weeks: 2
  minimum_left_high_ratio: 0.85
  maximum_left_high_ratio: 1.05
  merge_tolerance_pct: 0.02
breakout:
  price_buffer_pct: 0.005
  atr_buffer_multiplier: 0.20
  management_range_pct: 0.10
failure:
  price_buffer_pct: 0.01
  atr_buffer_multiplier: 0.25
  consecutive_range_breaches: 2
```

Changing a config invalidates only its consuming layer and downstream layers.

---

## 9. Core data contracts

### 9.1 Normalized daily bars

```text
symbol_id, session_date, open, high, low, close, volume,
source, source_updated_at, ingested_at, data_quality_flags
```

Primary key: `symbol_id + session_date`.

### 9.2 Completed weekly bars

```text
symbol_id, week_end_date, open, high, low, close, volume,
is_complete, source_daily_start, source_daily_end, weekly_builder_version
```

Only `is_complete = true` may enter structural or breakout logic.

### 9.3 Base candidates

```text
candidate_id, structure_id, symbol_id, as_of_date, scan_window_weeks,
left_high, left_high_date, base_low, base_low_date, base_depth,
peak_to_low_weeks, base_end_date, base_end_reason, base_duration_weeks,
prior_uptrend_pct, minimum_prior_uptrend_pct,
largest_single_week_move, largest_single_week_move_date,
single_week_move_to_depth_ratio, is_structurally_valid, rejection_reason,
detector_version, config_hash
```

Rejected candidates are first-class diagnostic data.

### 9.4 Consolidated structures

```text
structure_id, symbol_id, left_high_date, base_low_date,
valid_in_windows, largest_context_window, first_detected_date,
last_detected_date, latest_measurement_date, structure_status, detector_version
```

### 9.5 Selection decisions

```text
selection_id, symbol_id, as_of_date, selected_structure_id,
candidate_structure_ids, selection_policy, selection_policy_version,
selection_reason, is_shadow_decision
```

### 9.6 Lifecycle events

```text
event_id, lifecycle_id, structure_id, symbol_id, event_date, event_type,
previous_stage, new_stage, latest_close, recovery_pct, selected_pivot,
event_payload, lifecycle_rule_version
```

Events are append-only and uniquely keyed.

### 9.7 Current lifecycle state

```text
lifecycle_id, structure_id, symbol_id, journey_stage, current_zone,
selected_pivot, pivot_source, breakout_date, breakout_success_date,
failure_date, completion_date, last_signal_date, last_structure_date,
lifecycle_rule_version
```

Current state must be reproducible by reducing ordered lifecycle events.

### 9.8 Feature snapshots

```text
feature_snapshot_id, symbol_id, structure_id, lifecycle_id, as_of_date,
feature_name, feature_value, source_period_end, available_date, source,
feature_provider_version, quality_flags
```

### 9.9 Strategy signals

```text
signal_id, lifecycle_id, signal_date, strategy_name, strategy_version,
signal_type, signal_strength, explanation, input_feature_versions
```

---

## 10. Historical execution and selective reruns

Expose one canonical Python CLI. PowerShell files are convenience wrappers and
must contain no business logic.

### 10.1 Layer commands

```powershell
python -m base_lifecycle.cli data ingest --start 2020-01-01 --end 2026-07-17
python -m base_lifecycle.cli data validate --start 2020-01-01 --end 2026-07-17
python -m base_lifecycle.cli bars build-weekly --start 2020-01-01 --end 2026-07-17
python -m base_lifecycle.cli structure discover --start 2026-01-01 --end 2026-07-17
python -m base_lifecycle.cli structure consolidate --start 2026-01-01 --end 2026-07-17
python -m base_lifecycle.cli selection run --start 2026-01-01 --end 2026-07-17 --policy largest_window
python -m base_lifecycle.cli lifecycle replay --start 2026-01-01 --end 2026-07-17
python -m base_lifecycle.cli features run --start 2026-01-01 --end 2026-07-17 --providers price,fundamentals,events
python -m base_lifecycle.cli strategies run --start 2026-01-01 --end 2026-07-17 --strategies recovery,breakout,post_breakout
python -m base_lifecycle.cli views build --as-of 2026-07-17
```

### 10.2 Full build

```powershell
python -m base_lifecycle.cli pipeline run `
  --start 2020-01-01 --end 2026-07-17 `
  --from raw --through views
```

### 10.3 Rerun after selection-only changes

```powershell
python -m base_lifecycle.cli pipeline run `
  --start 2026-01-01 --end 2026-07-17 `
  --from selection --through views
```

### 10.4 Rerun one feature and its consumers

```powershell
python -m base_lifecycle.cli pipeline run `
  --start 2026-01-01 --end 2026-07-17 `
  --from features --feature-providers earnings --through views
```

### 10.5 Preview impact without executing

```powershell
python -m base_lifecycle.cli pipeline impact `
  --changed config/selection.yaml
```

Expected output:

```text
Reusable: normalized_daily, weekly_bars, base_candidates, base_structures
Invalidated: selection_decisions, lifecycle_state, strategy_signals,
             rankings, dashboard_views
```

### 10.6 Cache controls

```text
--reuse-valid-cache    reuse only fingerprint-compatible artifacts
--force-layer LAYER    rebuild one layer
--force-downstream     rebuild the layer and consumers
--run-id ID            name an experiment run
--baseline-run ID      compare with a frozen baseline
--dry-run              show execution/invalidation without writing
```

The runner must fail clearly when compatible upstream artifacts are missing.

---

## 11. Change-to-rerun matrix

| Changed item | Reusable | Must rerun |
|---|---|---|
| UI styling/sorting | L0–L9 | L10 |
| Strategy threshold | L0–L7 | L8–L10 |
| Scoring weights | L0–L8 | L9–L10 |
| One feature provider | L0–L6 and other providers | affected L7 provider and dependent L8–L10 |
| Selection policy | L0–L4 | L5–L10 |
| Breakout/failure rules | L0–L5 | L6–L10 |
| Handle/pivot rules | L0–L5 | L6–L10 |
| Structural rules | L0–L2 | L3–L10 |
| Weekly aggregation | L0–L1 | L2–L10 |
| Raw-data correction | unaffected raw partitions | affected L1 partitions and downstream |
| External-data correction | L0–L6 | affected provider and consumers |

For every selective rerun, validate that affected final partitions equal a
clean full run.

---

## 12. Two-clock replay and data freshness

```text
Daily clock:
  close, recovery, pivot distance, daily/event features

Completed-week clock:
  structure, handle, pivot, breakout, success, failure
```

Monday–Thursday reuse the latest completed weekly artifact. Friday publishes a
new weekly partition only when its required daily data is available.

Every symbol/date must record:

```text
requested_as_of_date
actual_signal_date
actual_structure_date
data_age_business_days
is_stale
```

Replay modes:

```text
strict      = fail partition on missing/stale required data
quarantine  = continue but isolate invalid symbols
diagnostic  = continue and preserve complete failure information
```

Never silently process a July date using a June close as if it were current.

---

## 13. Lifecycle contract

Initial lifecycle stages:

```text
NOT_TRACKED
RECOVERY_BUILDING
BREAKOUT_CONSIDERATION
SUCCESSFUL_BREAKOUT
FAILED
COMPLETED
```

Priority:

```python
if completed:
    stage = "COMPLETED"
elif failed:
    stage = "FAILED"
elif breakout_success:
    stage = "SUCCESSFUL_BREAKOUT"
elif breakout_confirmed:
    stage = "BREAKOUT_CONSIDERATION"
elif recovery_pct >= consideration_threshold:
    stage = "BREAKOUT_CONSIDERATION"
elif recovery_pct >= tracking_threshold:
    stage = "RECOVERY_BUILDING"
else:
    stage = "NOT_TRACKED"
```

Recovery transitions are reversible before confirmation. Breakout, success,
failure, and completion are historical events and cannot be erased by ordinary
daily recovery movement.

---

## 14. Feature and strategy extension contracts

All feature providers implement:

```python
class FeatureProvider:
    name: str
    version: str

    def required_inputs(self) -> list[str]: ...

    def calculate(
        self,
        symbol_id,
        as_of_date,
        structure,
        lifecycle,
        repositories,
    ) -> list[FeatureValue]: ...
```

Providers must not mutate structures/lifecycles, access future information, or
silently interpret missing data as a positive signal. Missing, stale,
unavailable, and not-applicable are separate states.

Strategies implement:

```python
class Strategy:
    name: str
    version: str

    def evaluate(self, context: StrategyContext) -> list[Signal]: ...
```

Keep these future decision scores separate:

```text
Base-selection quality
Breakout-entry readiness
Post-success/re-entry opportunity
```

Do not create one universal score.

---

## 15. Validation framework

Each layer supports:

```powershell
python -m base_lifecycle.cli validate --layer LAYER --run-id RUN_ID
```

Required validation classes:

1. Unit: pure formulas and transition functions.
2. Contract: schema, types, keys, enums, nullability, units, versions.
3. Temporal: no future availability; no incomplete weekly consumption.
4. Golden: reviewed named examples with committed expected outputs.
5. Determinism: identical input/config produces identical canonical hashes.
6. Partial/full equivalence: selective rerun equals clean full output.
7. Reconciliation: foreign keys, event reduction, selection validity.
8. Performance: runtime, memory, cache hits, invalidated partitions.

Golden fixtures must include:

```text
Valid long base
Too-short base
V-shaped recovery
Excessive single-week move
Same structure found in multiple windows
Different valid structures for one symbol
Handle pivot
Fallback left-high pivot
Immediate post-bottom breakout
Successful breakout
Marginal breach
Hard failure
Two-close failure
Successful stock forming a later base
Stale historical input
```

Reconciliation invariants:

```text
Every selected structure exists and is valid.
Every lifecycle event references an existing structure.
Current state equals reduction of ordered events.
Every signal records exact input versions.
Only one primary selection exists per symbol/date/policy.
No event ID is duplicated.
```

---

## 16. Staged implementation and validation gates

### Stage 0 — Governance and skeleton

Goal: establish repository layout, typed configs, CLI skeleton, manifests,
documentation, and tests without strategy logic.

Deliverables:

```text
AGENTS.md and required docs
Typed config loader
CLI help and dry-run skeleton
Manifest serialization
Test command and CI
```

Validate:

```text
All configs parse.
Unknown config keys fail.
CLI help works for every planned command.
Manifests round-trip.
Tests run from a clean checkout.
```

Exit gate: no detector work until config and artifact versioning work.

### Stage 1 — Point-in-time data foundation

Goal: normalized daily data, exchange/session handling, completed weekly bars,
and stale-data protection.

Validate:

```text
Unique symbol/date keys.
Low <= Open/Close <= High.
Non-negative volume.
Sorted, non-duplicate sessions.
Known weekly fixtures aggregate exactly.
Incomplete current week is excluded.
Stale dates are detected/quarantined.
Repeated builds have identical canonical hashes.
```

Exit gate: a historical range builds reproducibly with freshness reporting.

### Stage 2 — All-window candidate discovery

Goal: evaluate 104/52/26 independently and persist accepted/rejected candidates
without selection, scoring, pivot, or lifecycle concerns.

Validate:

```text
Every possible configured window is evaluated.
Left-high exclusion is applied exactly.
Peak-to-low >= 6 weeks.
Actual base duration >= 12 weeks.
Depth is within 15%–60%.
Prior uptrend >= max(20%, depth).
Single-week move/depth <= 50%.
Recovery never controls structural validity.
Every rejection has a stable reason and measurements.
Golden structures match reviewed expectations.
```

Exit gate: all structural formulas and edge cases are independently trusted.

### Stage 3 — Structure consolidation

Goal: collapse identical geometry found by multiple windows.

Validate:

```text
Same left-high/base-low maps to one structure.
Different structures remain separate.
IDs are stable across equivalent reruns.
Every valid candidate maps to exactly one structure.
Candidate and mapping counts reconcile.
```

### Stage 4 — Primary and shadow selection

Goal: add a replaceable selector. Start with `largest_window`; keep alternatives
as shadow candidates. Do not add numerical scoring.

Validate:

```text
Zero candidates → no selection.
One candidate → direct selection.
Several candidates → exactly one deterministic primary.
Selected structure is valid.
Changing selection config reuses L0–L4 artifacts.
Selection reason is human-readable.
```

### Stage 5 — Pivot and event-based lifecycle

Goal: recovery, handle, pivot, breakout, success, and failure as append-only
events plus a deterministic reducer.

Validate:

```text
Daily recovery uses latest valid daily close.
Weekly events use completed weeks only.
Handle pullback maximum equals one third of depth.
Immediate first-post-bottom breakout is detected.
Buffered crossing works at boundaries.
Pivot and management levels freeze after breakout.
Success and both failure paths work.
Recovery is reversible only before confirmation.
Historical outcomes latch.
Event reduction reconstructs current state.
Replay creates no duplicate events.
```

### Stage 6 — Completion and repeated bases

Goal: finish old successful lifecycles and allow later structures for the same
stock without losing history.

Validate:

```text
Completion differs from failure.
Completed history remains queryable.
A later structure creates a new lifecycle sequence.
The same structure cannot duplicate an active lifecycle.
A golden stock completes two independent base cycles.
```

### Stage 7 — Orchestration and selective reruns

Goal: dependency graph, manifests, invalidation, resume, comparison, and
partial/full equivalence.

Validate:

```text
Selection change invalidates L5 onward only.
Structure change invalidates L3 onward.
UI change invalidates L10 only.
Missing/incompatible upstream artifacts fail clearly.
Interrupted runs resume correctly.
Dry-run lists correct reuse/invalidation.
At least three partial reruns equal clean full runs.
```

### Stage 8 — Feature providers

Goal: add versioned price and non-price enrichment without modifying structure
or lifecycle logic.

Suggested order:

```text
1. Existing price context
2. Market/sector regime
3. Earnings and sales
4. Announcements/events
5. Institutional/bulk/block activity
6. Other fundamentals and qualitative tags
```

Validate:

```text
No look-ahead.
Every value has source and available date.
Missing is not silently converted to zero/false.
Changing one provider reuses unrelated providers.
Provider output is deterministic.
Hand-checked examples reconcile.
```

### Stage 9 — Strategy signals

Goal: independent recovery, breakout, and post-breakout strategies consuming
the same stable context.

Validate:

```text
Strategies cannot mutate upstream data.
Signals record exact input versions.
Mandatory missing features suppress or explicitly qualify signals.
Each strategy has positive, negative, and boundary fixtures.
Changing one strategy invalidates only its signals and consumers.
```

### Stage 10 — Shadow experiments and scoring

Goal: introduce scores only after candidate outcomes exist.

Maintain separate scores:

```text
base_selection_score
breakout_readiness_score
post_breakout_opportunity_score
```

Validate:

```text
No future outcome leakage.
Baseline and experiment use the same candidate universe.
Raw measurements remain unchanged.
Coverage, stability, turnover, false positives, drawdown, and missing-data bias
are reported—not only average return.
Score explanations show contributing features.
Trader review is recorded before promotion.
```

### Stage 11 — Dashboard and review workflow

Primary journey tables:

```text
Breakout Consideration
Recovery Building
Successful Breakout
```

Diagnostics:

```text
Alternative/shadow bases
Rejected candidates
Lifecycle events
Completed/failed lifecycles
Feature provenance
Signal explanations
Baseline/experiment comparisons
```

Validate:

```text
Displayed rows reconcile to artifact IDs.
Alternatives cannot be mistaken for primary selections.
Charts use persisted frozen levels.
Filters never change calculations.
Stale and empty states are explicit.
Trader can trace every row to structure, lifecycle, features, and strategy.
```

### Stage 12 — Production hardening

Goal: safe unattended daily/Friday processing.

Validate:

```text
Fresh install reproduces a baseline.
Daily execution is idempotent.
One-symbol failure cannot corrupt valid partitions.
Exit status reflects validation outcome.
Backups restore successfully.
Schema migrations work on copies.
Performance meets target universe/range budget.
```

---

## 17. Feedback and experiment workflow

Every strategy change follows:

```text
1. Record a hypothesis.
2. Name/freeze the baseline run.
3. Create a new rule or config version.
4. Run pipeline impact in dry-run mode.
5. Execute the smallest correct rerun.
6. Run layer validations.
7. Compare baseline and experiment.
8. Review aggregate changes and named examples.
9. Record trader feedback.
10. Accept, revise, reject, or retain as shadow.
11. Update decisions and implementation status.
```

Experiment records contain:

```text
experiment_id, hypothesis, owner, created_at,
baseline_run_id, experiment_run_id, changed_layers, config_diff,
candidate_universe, validation_status, aggregate_results,
reviewed_examples, trader_feedback, decision, decision_reason
```

Never overwrite the baseline during an experiment.

---

## 18. Implementation status template

`docs/IMPLEMENTATION_STATUS.md`:

```text
Current stage:
Stage status: NOT_STARTED | IN_PROGRESS | VALIDATING | COMPLETE
Last validated run:
Current production policy versions:
Known limitations:
Open decisions:
Next bounded task:

L0 Raw sources:
L1 Normalized data:
L2 Bar aggregation:
L3 Structure discovery:
L4 Consolidation:
L5 Selection:
L6 Lifecycle:
L7 Features:
L8 Strategies:
L9 Scoring:
L10 Views:

Latest validation results:
Artifact migrations pending:
```

Codex must use this file instead of guessing maturity from file names.

---

## 19. Decision log template

`docs/DECISIONS.md` entry:

```text
Decision ID:
Date:
Problem:
Options considered:
Decision:
Reason:
Affected layers:
Artifact invalidation:
Migration required:
Validation evidence:
Revisit condition:
```

Always record changes to structure identity, base duration meaning, selection
policy, lifecycle completion, required features, scoring promotion, or
price-frequency semantics.

---

## 20. Schema evolution rules

1. Every artifact has a schema version.
2. Prefer additive nullable fields when semantics are unchanged.
3. Use a new field when meaning changes.
4. Provide migrations for retained historical artifacts.
5. Test migrations on copies.
6. Never mix incompatible rule versions in an unlabelled table.
7. Preserve baseline runs required for comparisons.
8. During early development a clean replay is acceptable, but cleanup and
   compatibility loss must be explicit.

---

## 21. Initial non-goals

Do not implement during foundation stages:

- machine-learning selection;
- one universal score;
- automatic order execution;
- optimization against the full historical sample;
- many external features simultaneously;
- UI-owned calculations;
- silent stale-data fallback;
- overlapping active bases before completion semantics exist.

---

## 22. Final definition of done

```text
All three windows are evaluated and preserved.
Identical structures are deduplicated.
Selection is replaceable and independently rerunnable.
Lifecycle is event-based and reproducible.
Successful stocks can later form new bases.
Non-price features are point-in-time safe and versioned.
Strategies emit independent explainable signals.
Scores are optional consumers, not structural dependencies.
Partial reruns equal clean full reruns.
Every dashboard row is traceable to artifacts and rule versions.
Historical experiments compare against frozen baselines.
Codex can determine the affected layer and smallest safe rerun from manifests
and repository documentation.
```

Reach this state through staged validation, trader feedback, and promoted
versions—not through one unreviewed rewrite.

---

## 23. Bootstrap procedure for a new Codex repository

1. Create an empty repository.
2. Copy this file to `docs/BASE_LIFECYCLE_PROJECT_BLUEPRINT.md`.
3. Give Codex only the Stage 0 request below.
4. Review and commit Stage 0 before requesting Stage 1.
5. Keep the existing scanner repository read-only as a behavioural reference;
   do not copy its monolithic structure into the new architecture.
6. Bring across a small anonymized/golden OHLCV fixture set before copying the
   full historical dataset.
7. Establish one named baseline run as soon as Stage 2 produces stable output.
8. Never advance a stage while its exit gate remains incomplete.

Recommended first prompt:

```text
Read docs/BASE_LIFECYCLE_PROJECT_BLUEPRINT.md completely.

Implement Stage 0 only. Do not implement market-data ingestion, base detection,
pivots, lifecycle rules, features, scoring, or UI yet.

Before editing:
1. Create a plan mapped to the Stage 0 deliverables and validations.
2. Identify any repository/environment constraints.
3. Create AGENTS.md, IMPLEMENTATION_STATUS.md, DECISIONS.md, the typed config
   skeleton, artifact-manifest model, CLI skeleton, and test command.

After implementation:
1. Run every Stage 0 validation.
2. Update IMPLEMENTATION_STATUS.md.
3. Report created contracts, commands, validation evidence, known limitations,
   and the exact next Stage 1 task.
4. Stop after Stage 0 for review.
```

Recommended prompt for every later stage:

```text
Read AGENTS.md, docs/BASE_LIFECYCLE_PROJECT_BLUEPRINT.md,
docs/IMPLEMENTATION_STATUS.md, and docs/DECISIONS.md completely.

Implement only Stage <N>. Preserve all completed upstream contracts. Before
editing, produce the required impact statement and verify that the prior stage's
exit gate is complete. Add the stage validations, run them, update implementation
status and decisions, and stop for review before advancing.
```

Recommended experimental-change prompt after the platform exists:

```text
Treat this as an experiment, not an immediate production-rule replacement.
Identify the affected layer, freeze/name the baseline, version the proposed
change, run pipeline impact, execute the smallest valid downstream rerun, run
partial-versus-full validation on a sample, compare named examples and aggregate
results, record the decision, and leave the experiment in shadow mode unless I
explicitly approve promotion.
```
