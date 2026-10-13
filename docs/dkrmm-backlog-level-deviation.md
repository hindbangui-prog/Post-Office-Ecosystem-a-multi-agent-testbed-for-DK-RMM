# DK-RMM: `backlog_level_deviation`

Added 2026-10-13. One indicator, registered beside the twenty of 2026-10-12, so that a backlog
that stays high is still a signal after `backlog_growth` has returned to zero. The formula is in
`docs/dkrmm-mathematics.md`, section 22. Nothing else in DK-RMM was changed: no state, no
threshold, no persistence rule, no other indicator's calculation, and no learning rule. Every
number below was measured; where it comes from is named.

## 1. Why a new indicator (the inspection)

Under M-S-DROP the intake dock fills to its cap of 26 and then refuses arrivals, so the backlog
stops changing. Read on the five model-enabled live runs (`results/m_s_drop_crewai/live/MS-DROP`):

- **`backlog_growth`** (change in parcels inside per tick) is 0.0 from the time the dock is full.
  It was in evidence in 0, 3, 1, 0 and 0 post-fault readings.
- **`tail_deviation`** does read a level: its zone-backlog metric, the 95th percentile of the
  by-zone counts against the median of its past values, reached 3.47 (seed 11) and 4.0 (seed 13)
  with the dock full. But the indicator is the largest of three ratios (task wait, message delay,
  zone backlog) and is z-scored against a history dominated by the task-wait ratio. With the dock
  full its z was 0.73 in seed 11, so it was never evidence there, and 5.14 in seed 13. It sits in
  the behavioural congestion kind, uses no capacity and keeps no per-zone evidence. It measures
  extremes against their baseline p95, not sustained level by zone, so it does not duplicate the
  new indicator.
- **`resource_saturation`** reads the dock category as 1.0 once full, but it is the largest of
  five categories, and the robot category already reads 0.8 to 1.0 in normal running. Its z with
  the dock full was 0.80 (seed 11).

## 2. The registry entry and the formula

```
(
    "backlog_level_deviation",
    "derived",
    "up",
    "current unfinished-parcel backlog by zone relative to its normal "
    "baseline and available capacity; sustained elevation remains a "
    "signal even when backlog growth returns to zero",
),
```

The formula is the "headroom used" option you chose:

$$e_z = \frac{L_z - B_z}{C_z - B_z}, \qquad x = \max_z e_z$$

| Symbol | What it is | Source |
|---|---|---|
| $L_z$ | parcels in zone $z$ now | the snapshot's `by_zone` (`parcel.current_zone`), each parcel once; parcels that left are not in `env.parcels` |
| $B_z$ | the zone's normal level: median of its past levels | a FIFO of up to `BASELINE` (24) readings, learned under the existing rule (H'); at least 4 (`TAIL_MIN_BASELINE`) |
| $C_z$ | the zone's capacity | INTAKE: `generator.max_on_dock` (26); TEMPORARY_STORAGE: `env.storage.capacity` (20) |

- **Reading it.** 0 at the normal level, 1 at capacity, negative below normal. It is defined when
  the normal level is 0.
- **Aggregation.** The fullest zone with a capacity, like `resource_saturation`'s bottleneck.
  SORTING, DISPATCH and the total have no declared capacity in the model. Their level, normal
  level and level/normal are recorded as zone evidence and do not enter the value.
- **Not evaluable** when no zone has a value. A zone has none when its level was not read, its
  baseline has fewer than 4 readings, its capacity was not read or is 0, or its capacity is not
  above its normal level. Each case is written in the zone's `note`, and no value is made up for it.
- **Scoring.** The existing machinery: z against the indicator's own past, direction up, threshold
  `DEVIATION_Z` = 2.0, in the existing operational `backlog` kind beside `backlog_growth`.
- **No new kind and no new threshold.** On its own it is one kind, so it can make a reading
  DEVIATING, or UNSTABLE only through the unchanged persistence branch; never RCT on its own.
  "Sustained" is read by the existing persistence rules. The one named constant,
  `LEVEL_MIN_BASELINE`, is `TAIL_MIN_BASELINE` (4).

## 3. Files

| File | Change |
|---|---|
| `post_office/dkrmm/indicators.py` | registry entry; `backlog_level_deviation` field; marked not evaluable until the monitor fills it |
| `post_office/dkrmm/monitor.py` | `LEVEL_ZONES`, `LEVEL_CAPACITY`, `LEVEL_TOTAL`, `LEVEL_MIN_BASELINE`; per-zone level FIFOs learned under the existing rule; `_fill_backlog_level`; `EVIDENCE["backlog"]` gains the indicator |
| `post_office/api/digest.py` | the indicator row's detail (zones, baseline, capacity, headroom, tick); the operations block gains `level_deviation` and `level_zone` |
| `post_office/ui/live.html`, `post_office/ui/live.py` | the DK-RMM pane's backlog line gains "headroom used" (value and zone); the indicator table gets its row from the registry, as every indicator does |
| `tests/test_dkrmm_backlog_level.py` | new: 23 tests |
| `tests/test_dkrmm.py`, `tests/test_dkrmm_dashboard.py`, `tests/test_dkrmm_operational.py`, `tests/test_api_rcts.py` | 20 becomes 21; the derived set; three rule tests set the persistence counter they depend on; `DKRMM_TREE_SHA` re-pinned |
| `docs/dkrmm-mathematics.md` | section 22 |
| this report, provenance files, `results/m_s_drop_crewai/README.md` | documentation |

## 4. Display and saved data

- **Live page, DK-RMM tab.** The indicator has its own row: value, baseline mean, z, status and
  the assessment tick. Hovering its name shows, per zone and for the total: level, normal level,
  number of baseline readings, capacity, headroom used, level/normal, at capacity and note, plus the
  window settings. The operations block's backlog line shows "headroom used 100% (INTAKE)".
- **Saved data.** Every reading in `dkrmm_assessments.jsonl` carries the value, `evaluable`, `z`,
  `deviation`, `in_evidence`, `baseline` and `indicators.detail.backlog_level`. `/dkrmm/series`
  carries its history.
- **Read from the state, not reconstructed.** All of it comes from the snapshot taken at the
  assessment tick.

## 5. Validation

### 5.1 M-S-DROP and its control, through the existing page workflow

Server: `python main.py --api --rules --no-record --experiment-dir results/m_s_drop_crewai/live_rules_bld --stop-at 2800`.
The ten runs (seeds 11 to 15, M-S-DROP and the N control) were driven from the page as before and
saved in a new run directory. The earlier runs were not touched.

- **Rules-only, for a measurable reason.** These are the rules-only runs because the cloud
  workspace has no Ollama. With the monitor only observing, the event streams are identical to
  those of `live_rules/` in all ten runs (17,603 / 15,048 / 12,936 / 10,948 / 10,743 events for
  M-S-DROP). So the facility is the same and only the DK-RMM readings differ.
- **In the standard mode.** The same command without `--rules`, with a new `--experiment-dir`,
  gives the model-enabled readings. That run is yours to make.

**The full dock with growth at zero (the case the indicator is for):**

| Seed | dock first full | readings with the dock full | of those, growth 0 | new indicator in evidence | `backlog_growth` in evidence | value | z | intake normal level |
|---|---|---|---|---|---|---|---|---|
| 11 | 1141 | 83 | 82 | 82 | 0 | 1.0 | 13.90 | 8 |
| 12 | 1321 | 74 | 73 | 73 | 0 | 1.0 | 11.65 | 3 |
| 13 | 1221 | 79 | 78 | 78 | 0 | 1.0 | 12.71 | 5 |
| 14 | 1161 | 82 | 81 | 81 | 0 | 1.0 | 8.89 | 6 |
| 15 | 1601 | 60 | 59 | 59 | 0 | 1.0 | 15.18 | 5 |

At the last reading (tick 2781) every seed has INTAKE 26 of 26, headroom used 1.0, growth 0.0,
the indicator in evidence, and the state UNSTABLE. The intake's normal level stopped learning when
the post-fault windows became UNSTABLE on operational evidence (the existing rule).

**What changed in the M-S-DROP readings after tick 400 (120 readings per seed):**

| Seed | readings with the backlog kind, before / after | STABLE / RECOVERY / DEVIATING / UNSTABLE / RCT, before | after | first RCT, before / after |
|---|---|---|---|---|
| 11 | 0 / 106 | 0 / 0 / 1 / 91 / 28 | 0 / 0 / 1 / 106 / 13 | 461 / 501 |
| 12 | 3 / 103 | 0 / 0 / 3 / 97 / 20 | 0 / 0 / 3 / 95 / 22 | 461 / 461 |
| 13 | 1 / 105 | 0 / 0 / 3 / 114 / 3 | 0 / 0 / 3 / 117 / 0 | 2421 / none |
| 14 | 0 / 115 | 0 / 0 / 3 / 117 / 0 | 0 / 0 / 3 / 117 / 0 | none / none |
| 15 | 0 / 104 | 0 / 0 / 3 / 96 / 21 | 0 / 0 / 2 / 105 / 13 | 481 / 481 |

- **Fewer RCT readings.** In seeds 11, 13 and 15, 26 readings that were RCT are now UNSTABLE. In
  every one, the three-kind and propagation conditions still held. What no longer held is the
  existing precursor: variance and autocorrelation of the severity series both rising in its later
  half. The new indicator's z enters that series, so its shape changed. Seed 12 gained 2 RCT
  readings. The precursor test and its threshold are unchanged; this is their output with 21
  indicators.
- **Collapse is not affected.** The collapse classification reads operations, not DK-RMM, and the
  event streams are identical.

### 5.2 Normal and the no-drop control

- **The simulation is unchanged.** Normal, seed 1, 2800 ticks through the runner (rules, monitor
  attached), at the previous commit and with this change: 29,580 events, SHA-256 `5e07efbe…`,
  identical. `results/normal/` was not written to.
- **The DK-RMM readings of Normal do change.** Seed 1, 2800 ticks, 140 readings:

  | | STABLE | RECOVERY | DEVIATING | UNSTABLE | RCT |
  |---|---|---|---|---|---|
  | before | 45 | 20 | 39 | 28 | 8 |
  | after | 41 | 19 | 39 | 32 | 9 |

  - 11 of the 140 readings changed state. All 8 earlier RCTs remain, and one more is read at 2761.
  - The indicator's values in Normal stayed between -0.05 and 0.21: a few parcels above a zone's
    normal level, for example 4 on an intake whose normal is 0.
  - Its own past is tight, so such a reading is more than 2 standard deviations away. It was in
    evidence in 16 readings: 241, 261, 861, 881, 1901, 1921, 1941, 1981, 2001, 2021, 2161, 2181,
    2281, 2301, 2441 and 2741.
- **No-drop control (N), seeds 11 to 15.** The indicator was in evidence in 6, 12, 8, 8 and 7
  readings after tick 400, with the dock never full. After tick 400, UNSTABLE readings went from
  21 / 27 / 20 / 10 / 33 to 20 / 28 / 24 / 14 / 33, and RCT readings from 1 / 4 / 1 / 2 / 1 to
  3 / 4 / 1 / 2 / 1.
- **Not corrected.** These are false-alarm candidates of the same kind as the existing indicators'
  on a facility without a fault. Raising the bar for this indicator alone would be a new
  indicator-specific threshold, which the brief rules out unless documented and justified, and
  which is your call.

### 5.3 A behaviour of the unchanged learning rule worth knowing

When the backlog level is the only evidence, the readings are DEVIATING. DEVIATING readings teach
the baselines (`BASELINE_LEARNS_FROM`, unchanged). A plateau then becomes the zone's normal level
once it fills more than half of the zone's past readings: 13 of 24, about 260 ticks. After that it
reads 0 again. With other operational evidence present, as under M-S-DROP, the readings are
UNSTABLE or RCT and the plateau never enters the baseline. Both behaviours are tested:
`test_on_a_plateau_with_no_other_evidence_the_existing_baseline_rule_absorbs_it` and
`test_an_elevated_backlog_that_stops_growing_stays_a_signal`.

## 6. Tests

| Case of the brief | Tests in `tests/test_dkrmm_backlog_level.py` |
|---|---|
| 1. low backlog near normal | `test_a_backlog_at_its_normal_level_reads_near_zero` |
| 2. growing backlog | `test_a_growing_intake_rises_and_counts_as_backlog_evidence` |
| 3. elevated, no longer growing | `test_an_elevated_backlog_that_stops_growing_stays_a_signal`, `test_on_a_plateau_with_no_other_evidence_the_existing_baseline_rule_absorbs_it` |
| 4. full dock, arrivals refused | `test_a_full_dock_refusing_arrivals_reads_one_with_growth_at_zero` |
| 5. zones at different levels | `test_each_zone_is_measured_apart_and_the_value_is_the_fullest`, `test_a_parcel_that_has_left_is_not_in_any_count` |
| 6. empty queues, zero baselines, no capacity, no data | `test_empty_queues_are_a_reading_of_zero_not_a_missing_one`, `test_a_zone_normally_empty_still_has_a_value_against_its_capacity`, `test_unread_capacity_or_no_headroom_gives_no_value`, `test_a_capacity_at_or_below_the_normal_level_has_no_headroom`, `test_unreadable_parcels_leave_it_unread_and_teach_nothing`, `test_a_short_baseline_is_not_read` |
| 7. history and baseline comparison | `test_each_zone_baseline_is_the_median_of_its_learned_levels`, `test_a_formed_baseline_does_not_learn_a_full_dock_called_unstable` |
| 8. through the existing assessment, thresholds intact | `test_the_state_rules_and_thresholds_are_unchanged`, `test_on_its_own_it_is_one_kind_and_one_kind_is_a_deviation`, `test_it_counts_in_the_severity_like_every_up_indicator`, `test_watching_writes_nothing_to_the_building`, `test_registered_as_a_derived_up_indicator_in_the_backlog_kind`, `test_compute_indicators_leaves_it_to_the_monitor` |
| 9. saved and shown | `test_it_is_saved_and_shown_with_its_zone_evidence`, `test_the_pane_paints_its_row_and_the_headroom_line` |

Results, run in the cloud workspace:

- `tests/test_dkrmm_backlog_level.py`: 23 passed.
- The whole suite, including the live page's browser tests: 1103 passed, 7 skipped. Each skip names
  an input this workspace lacks, as before; it was 1080 passed, 7 skipped before this change.
- After the documentation and provenance rows were added, the documentation, provenance, layout
  and Normal-alignment tests were run again: 91 passed, 1 skipped.

## 7. What is unchanged

- **The DK-RMM state machine.** `states.py`, `signals.py` and `record.py` are untouched. In
  `monitor.py`: `EVERY` 20, `WINDOW` 60, `BASELINE` 24, `DEVIATION_Z` 2.0, `UNSTABLE_KINDS` 2,
  `RCT_KINDS` 3, `RCT_PROPAGATION` 0.5, `PERSISTENT` 3, `MIN_ACTIVITY` 24,
  `BASELINE_LEARNS_FROM`, `_classify`, `_evidence`, `_signed_z`, and the twelve evidence kinds and
  their operational/behavioural split. A test pins these values.
- **Every other indicator's calculation.**
- **The simulation.** The scenarios, their configurations, the fault schedules, the arrival
  schedule, communication loss, agent decisions, prompts, rules, the policy gate and the Ollama
  settings. DK-RMM still only reads: the new code reads the snapshot DK-RMM already took.
