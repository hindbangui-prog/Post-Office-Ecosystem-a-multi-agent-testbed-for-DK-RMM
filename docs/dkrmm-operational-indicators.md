# DK-RMM operational and early-warning indicators: what was built, tested and measured

This document reports the extension of DK-RMM made on 2026-10-12 from the design note
`docs/superpowers/specs/2026-10-12-dkrmm-operational-indicators-design.md`: eight
operational and early-warning indicators beside the original twelve, a direction-aware
classifier, a baseline that no longer learns from windows it judged unstable, and the
DK-RMM tab that shows all of it. The formulas are in `docs/dkrmm-mathematics.md`, section 21;
this document gives the registry, the tests, the validation runs and the honest findings. Every
number below is read from `validation.json` and `validation.md`, written by
`tools/validate_dkrmm_indicators.py` (rules only, no model, `PYTHONHASHSEED=0`, Normal on
seed 1, M-S-DROP and M-S-DELAY on seed 11, 2800 ticks, the fault applied at tick 400), or from
the test runs named in section 7.

## 1. Files changed or added

Commits `909c905`, `473e423`, `f5c7424`, `4bdb118` (the extension) and this one (tests,
validation, report).

| File | Change |
|---|---|
| `post_office/dkrmm/indicators.py` | registry of twenty with `kind`, `direction`, `about` (`INDICATOR_META`, `BASE_INDICATORS`, `DERIVED_INDICATORS`); `evaluable` flags and `detail` on `BehaviouralIndicators`; the guardrail split; delivery, throughput, saturation and synchronization computed from the window; p95 of the waits; the edge map |
| `post_office/dkrmm/operations.py` | new: the read-only state snapshot (`snapshot_state`, `declared_edges`) |
| `post_office/dkrmm/monitor.py` | direction-aware evidence (`deviates`, `_evidence`, `CORROBORATED_FALL`), directional severity (`directional`), `_signed_z`, the quiet rule narrowed to the behavioural kinds, baseline learning (`BASELINE_LEARNS_FROM`), the three monitor-held indicators (backlog growth, graph divergence, tail deviation), the per-indicator `evaluable`, `deviation`, `in_evidence`, `baseline` and `not_evaluated` on `Assessment`; tail folded into the congestion kind; delivered count floored at 0 |
| `post_office/dkrmm/__init__.py` | exports the registry constants and `snapshot_state` |
| `post_office/api/digest.py` | `monitor_digest` gains `observed`, `not_evaluated`, `operations`; `indicator_rows` gains `kind`, `direction`, `baseline`, `evaluable`, `deviation`, `in_evidence`, `detail`, `tick`, `status` |
| `post_office/api/server.py` | `/dkrmm/indicators` wording (the indicators, not the twelve) |
| `post_office/ui/live.html` | the DK-RMM pane: observed line, operations block, the indicator table with kind tag, direction arrow, value, baseline, z, status, and the stale marking |
| `post_office/ui/live.py` | the same pane rendered server-side (`ops_html`, `indicator_row_html`, `dkrmm_html`) |
| `docs/dkrmm-mathematics.md` | section 21 (the extension's mathematics, with both versions of each changed formula); this commit corrects the constants table of 21.7 (four operational kinds, four corroborated falls) and links this report |
| `docs/provenance.md`, `docs/provenance.json`, `docs/provenance_classification.json` | the DK-RMM package reclassified (`adapted`, `operations.py` `new`); this commit adds the tool, the new tests, this report and the design note |
| `tests/test_dkrmm_dashboard.py` | new: the rows, the digest, the pane and the endpoint |
| `tests/test_dkrmm_math.py` | severity divisor is the number of indicator names (twenty) |
| `tests/test_dkrmm.py` | the three signed indicators may go below zero |
| `tests/test_api_trimmed.py`, `tests/test_live_ui.py` | a row that could not be read is `None` and `n/a`; the pane has one row per registry entry |
| `tests/test_api_rcts.py` | `DKRMM_TREE_SHA` re-pinned for the extension (unchanged by this commit: no DK-RMM code changed) |
| `tests/test_normal_alignment.py` | the source's DK-RMM readings are no longer compared (the world and the event stream still are) |
| `tests/test_dkrmm_operational.py` | new (this commit): one test per item of the brief, 26 tests |
| `tools/validate_dkrmm_indicators.py` | new (this commit): the validation driver |
| `docs/dkrmm-operational-indicators.md` | new (this commit): this report |
| `README.md` | links this report |

## 2. The indicator registry

Twenty indicators, in registry order. "Events" means the window's event stream; "state" means
the snapshot `operations.snapshot_state(eco)` takes at the assessment tick, read-only.

| # | Name | Kind | Direction | About | Data source | Evaluable when |
|---|---|---|---|---|---|---|
| 1 | message_frequency | base | both | messages attempted per tick, of any kind; a fall counts when the facility's output is also off | events: `message`, `subagent_message` | always |
| 2 | interaction_density | base | both | how much of the possible conversation is actually happening | events: ordered (sender, receiver) pairs over agents that emitted any event | always (0 with fewer than two active agents) |
| 3 | delegation_frequency | base | up | work handed down to sub-agents per tick | events: messages from a non-sub-agent to a `SUB-` agent | always |
| 4 | retry_frequency | base | up | attempts abandoned and begun again per tick | events: `RETRY_TOPICS` | always |
| 5 | guardrail_events | base | up | refusals per tick: the policy gate, the intake gate, a full shelf | events: `REFUSAL_TOPICS` plus `decision` with validation `policy` or `state`; split into gate, intake, resource, message | always |
| 6 | tool_call_frequency | base | up | answers coming back up from sub-agents per tick | events: messages whose sender is a `SUB-` agent | always |
| 7 | task_switching | base | up | how often work changes hands, per tick | events: `SWITCH_TOPICS` | always |
| 8 | execution_latency | base | up | mean ticks from a task being created to it being started | events: `task_started` against the monitor's memory of `task_created`; p95 recorded beside it | always (0 with no task started) |
| 9 | agent_coupling | base | both | share of the roster that emitted any event this window; an active-agent fraction, not a coupling measure | events: active agents / roster | always |
| 10 | behavioural_similarity | base | both | how alike the agents' activity is; a move away from its normal similarity, in either direction, is the signal | events: topic-count profiles of the 16 busiest agents | always |
| 11 | persistence_of_deviation | derived | up | consecutive windows the facility has been off its baseline | the monitor's `_persistence` | always |
| 12 | propagation_across_agents | derived | up | share of the acting agents showing the deviation, not just feeling it | events: `TROUBLE_TOPICS`, governed refusals, `message_dropped` senders, late `agent_message_received` receivers, over acting agents | always (0 with no acting agent) |
| 13 | communication_failure_rate | base | up | share of attempted messages that were dropped or delivered late | events: `message` + `subagent_message` attempted, `message_dropped`, `agent_message_received` with `late_by > 0`; `held_now` from state | attempted > 0 |
| 14 | backlog_growth | derived | up | parcels inside the building, change per tick since the last reading | state: `len(env.parcels)` now and at the previous assessment | from the second assessment on, both readings present |
| 15 | task_completion_rate | base | down | parcels that left on vans per tick; a fall is the signal | events: `van_departed.parcels` | always (0 is a reading) |
| 16 | completion_gap | base | up | parcels arriving per tick minus parcels leaving per tick | events: `parcel_arrived` + `arrival_refused`, less 15 | always |
| 17 | resource_saturation | base | up | the tightest of robots, charge points, routes, storage and the dock, as a share of its capacity | state: `fleet`, `env.stations`, `env.departures.routes` and `_bay`, `env.storage`, parcels on INTAKE against `generator.max_on_dock` | roster of robots > 0 and at least one category readable |
| 18 | dependency_graph_divergence | derived | up | how far this window's who-talks-to-whom is from its baseline shape | events: the edge map of attempted messages; the monitor's baseline of edge maps; `bus.directory` for the declared set in the detail | at least one baseline window of edges |
| 19 | activity_synchronization | base | both | how much the acting agents' activity rises and falls together | events: per-tick event counts of the acting agents | at least 2 acting agents, the window spans at least 4 ticks, and at least one pair with variance |
| 20 | tail_deviation | derived | up | the worst-case waits and backlogs against their own baseline p95 | events: waits and `late_by`; state: parcels by zone; the monitor's baseline of p95s | some metric has values this window, at least 4 baseline p95s and a baseline median above 0 |

## 3. Formulas and baselines

Notation as in `docs/dkrmm-mathematics.md`: $W_k$ the window of assessment $k$, $\Delta_k$ its
span in ticks (at most 60), $E = 20$ the ticks between assessments, $\Sigma_k$ the state
snapshot, $B = 24$ the baseline length. Each indicator's baseline is the FIFO of its own last
$B$ readings, and $z$ is the population z-score of this window's value against that FIFO
(`signals.zscore`, unchanged: 0 with fewer than 4 points, $\pm 3$ on a dead-flat baseline
that moved, the sign taken from the raw difference by `DKRMM._signed_z`).

| Indicator | Formula | Source | Baseline |
|---|---|---|---|
| communication_failure_rate | $x_{13} = \min(1, (n^{drop} + n^{late}) / n^{att})$, not evaluable with $n^{att} = 0$; counts `attempted`, `delivered` $= \max(0, n^{att} - n^{drop})$, `dropped`, `late`, `held_now`; the raw ratio kept in the detail | events | its own last 24 evaluable readings |
| backlog_growth | $x_{14} = (b_k - b_{k-1}) / E$ with $b_k =$ `len(env.parcels)`; detail: backlog now, by zone, unfinished tasks, `increasing_for`, `acceleration` $= x_{14,k} - x_{14,k-1}$ | state, two snapshots | its own last 24 evaluable readings |
| task_completion_rate | $x_{15} = \sum_{\texttt{van\_departed} \in W_k} \pi(e) / \Delta_k$ | events | its own last 24 readings |
| completion_gap | $x_{16} = (n^{arr} + n^{aref}) / \Delta_k - x_{15}$ | events | its own last 24 readings |
| resource_saturation | $x_{17} = \max_c u_c$ over the evaluable categories: robots $1 - \lvert\texttt{available}\rvert / \lvert\texttt{fleet}\rvert$; charge points occupied / points, or 1 when there are no points and a robot needs one; routes closed / declared; storage used / capacity; dock parcels on INTAKE / `max_on_dock`; each capped at 1 | state | its own last 24 evaluable readings |
| dependency_graph_divergence | $x_{18} = 1 - J(\mathbf{w}_k, \bar{\mathbf{w}}_k)$, $J$ the weighted Jaccard (sum of minima over sum of maxima over the union of edges), $\bar{\mathbf{w}}_k$ the per-edge mean over the baseline windows' edge maps; detail `unexpected` (observed edges outside the declared set), `missing` (declared edges with baseline weight above 0 and weight 0 now), `weight_change` (L1 distance over total baseline weight) | events for $\mathbf{w}_k$, state (the directory) for the declared set | a FIFO of the last 24 learned edge maps, kept by the monitor |
| activity_synchronization | $x_{19} =$ mean Pearson correlation over pairs of acting agents of their per-tick event-count series over the window's tick range; a pair with a flat series is skipped | events | its own last 24 evaluable readings |
| tail_deviation | $x_{20} = \max_m q_{0.95}(V_{m,k}) / \mathrm{med}(\mathcal{B}^m_k)$ over the metrics task wait, message delay (`late_by`) and zone backlog; $q_p$ the nearest-rank percentile; a metric with no values, fewer than 4 baseline p95s or a baseline median of 0 contributes no ratio (noted as such in the detail) | events (waits, `late_by`), state (by zone) | one FIFO of the last 24 learned p95s per metric, kept by the monitor |

The baseline learning rule (section 21.4 of the mathematics): a window's reading enters a
baseline when it was evaluable and either the baseline does not yet hold its full 24 windows
or the window's final state is one of `BASELINE_LEARNS_FROM` = (STABLE, DEVIATING, RECOVERY).
A window the monitor called UNSTABLE or RCT teaches nothing to a formed baseline. The reason is
finding 4 of the design note: a baseline updated every window whatever the state has, after 24
windows under a fault, become the fault, and a sustained deviation then reads as normal. The
second clause (learn from every window until formed) exists because without it the monitor
froze on its five start-up windows (Normal, seed 1: UNSTABLE from tick 101 to the end of a
500-tick run), and a handful of start-up windows is not a normal worth protecting. The z-score
is computed against the baseline before this window joins it, and `_classify` reads no
baseline, so scoring first and learning after changes no verdict.

## 4. Base versus derived

The criterion: a base indicator is computed from one window's events and one state snapshot
and nothing else; a derived indicator needs a history the monitor keeps across assessments.

- Base (15): message_frequency, interaction_density, delegation_frequency, retry_frequency,
  guardrail_events, tool_call_frequency, task_switching, execution_latency, agent_coupling,
  behavioural_similarity, communication_failure_rate, task_completion_rate, completion_gap,
  resource_saturation, activity_synchronization.
- Derived (5): persistence_of_deviation (the persistence counter), propagation_across_agents
  (kept as the model lists it, though computed per window), backlog_growth (two snapshots),
  dependency_graph_divergence (the FIFO of edge maps), tail_deviation (the FIFOs of p95s).

`BASE_INDICATORS` and `DERIVED_INDICATORS` partition `INDICATOR_NAMES`
(`test_base_and_derived_partition_the_registry_and_the_twelve_lead_it`).

## 5. Classifier changes, with the reason for each

1. **Direction-aware evidence.** Each indicator carries a direction. A deviation counts when
   $z \ge 2$ for "up", $z \le -2$ for "down", $\lvert z \rvert \ge 2$ for "both". Reason:
   finding 1 of the design note; under a total message drop, tool calls, density, switching
   and latency all fall, and a classifier that discards negative z sees nothing.
2. **Corroborated fall.** A fall of message_frequency, interaction_density, agent_coupling or
   behavioural_similarity (`CORROBORATED_FALL`) counts only when an operational kind
   (delivery, backlog, throughput, saturation) is present in the same window; a rise always
   counts. Two corrections were made in validation on Normal, seed 1, and are documented in the
   code and in section 21.2 of the mathematics: the tail statistic was folded into the
   congestion kind (ticks 1481 to 1501: congestion and a separate tail kind made UNSTABLE out
   of a single slow queue, the same waits read twice), and the falls of coupling and similarity
   were added to the corroborated set (tick 1381: both fell in a lull and read as herding; the
   design note named only message frequency and density).
3. **Directional severity.** Severity is the mean over the twenty names of the part of $z$
   that counts in the indicator's direction, divided by 20 whether or not every indicator was
   evaluable. Reason: the dragon-king and precursor tests run on the severity series and would
   otherwise never see a downward operational deviation.
4. **Quiet rule narrowed.** Below `MIN_ACTIVITY` = 24 events the behavioural kinds are not
   evaluated (and the evidence says so); the operational kinds are, because they come from
   parcel events and the state of the building, not from chatter. Reason: finding 5; a dead
   facility is silent.
5. **Propagation extension.** The sender of a dropped message and the receiver of a late one
   are affected; the denominator stays the acting agents. Reason: so that a communication
   failure that reaches the population can satisfy the RCT propagation condition.
6. **Baseline learning.** Section 3 above.

Unchanged: the persistence rule (`PERSISTENT` = 3), `UNSTABLE_KINDS` = 2 confirmed kinds,
the RCT rule (`RCT_KINDS` = 3 kinds, one confirmed, propagation at or above 0.5, and a
dragon-king or a slowing-down reading), the state words, the human gate, `EVERY`, `WINDOW`,
`BASELINE`, `DEVIATION_Z`, `MIN_ACTIVITY`, the precursor and dragon-king tests. No single
indicator can declare UNSTABLE or RCT: one kind in one window is DEVIATING and nothing more
(`test_one_kind_in_one_window_is_deviating_and_rct_keeps_its_four_conditions`), and a
delivery failure rate of 1.0 is one kind of evidence that enters the rules like any other.

## 6. Dashboard changes

- API rows (`/dkrmm/indicators`, `indicator_rows`): `name`, `about`, `kind`, `direction`,
  `value` (None when not evaluable), `baseline` (mean of the baseline, None with fewer than
  four points), `z`, `evaluable`, `deviation` ("up", "down", "none"), `in_evidence` (the
  kind it fed, or None), `detail` (the counts and per-category values behind it), `tick`,
  `status` ("ok", "deviating up", "deviating down", "n/a").
- The page's indicator table: one row per registry entry with the name (hover shows the
  detail as "key: value" lines), a `base`/`derived` tag, a direction arrow (up, down, both),
  the monitor's sentence, the value or "n/a", the baseline or "-", z with sign and the status
  cell.
- The operations block above the table: delivery (attempted, delivered, dropped, late,
  failure rate), backlog (now, per tick, by zone, unfinished tasks), throughput (completed per
  tick, incoming per tick, gap), resources (one percentage per category).
- The observed line beside the badge: the evidence kinds present this window and the kinds
  not evaluated, so "delivery observed; behavioural kinds not evaluated" is told apart from
  "no evidence kinds".
- Stale marking: every row carries the assessment tick it was read at; when the rows are older
  than the current assessment (or their fetch failed while the state's succeeded), the table is
  dimmed and a note gives both ticks.

The two screenshots shown with this report are "DK-RMM tab, Normal seed 1 tick 421" and
"ms-drop seed 11 tick 841"; they are not embedded here.

## 7. Test results

All three commands run with `PYTHONHASHSEED=0 .venv/bin/python -m pytest -q -p no:cacheprovider`.

| Command | Result |
|---|---|
| `tests/test_dkrmm_operational.py` (this commit; one test per item of the brief) | 26 passed |
| the full suite less the three browser files (`--ignore=tests/test_live_ui.py --ignore=tests/test_live_c2near.py --ignore=tests/test_live_collapse_ui.py`), `tests/test_dkrmm_dashboard.py` and `tests/test_dkrmm_math.py` among them | 1011 passed, 5 skipped (9 min 32 s) |
| the three browser files, `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers` | 45 passed (3 min 43 s) |

No test of this file exposed a bug in the extension; no code under `post_office/dkrmm/` was
changed by this commit, so `DKRMM_TREE_SHA` stands.

## 8. Evidence from the validation runs

### 8.1 Normal, seed 1: the observer property and the state counts

The event stream (every event, less `run_id` and `wall_clock`, hashed in order) is the same
with the monitor attached and without it: `4c0b7b8c08b858af09…` at 300 ticks (4771 events either
way) and `633055469f5ece29ce…` at 2800 ticks (29580 events either way); `hash_equal` is `True`
in both. The full digests are in `validation.json`.

State counts, before (commit a586d26, the code without the extension, run from a worktree in a
subprocess) and after:

| Run | | STABLE | DEVIATING | UNSTABLE | RCT | RECOVERY | assessments |
|---|---|---|---|---|---|---|---|
| 300 ticks | before | 8 | 4 | 1 | 0 | 2 | 15 |
| 300 ticks | after | 6 | 5 | 1 | 0 | 3 | 15 |
| 2800 ticks | before | 81 | 28 | 9 | 6 | 16 | 140 |
| 2800 ticks | after | 47 | 38 | 38 | 0 | 17 | 140 |

At 300 ticks two of the 15 windows differ: tick 161 (STABLE before, DEVIATING after, backlog)
and 181 (STABLE before, RECOVERY after). At 2800 ticks 68 of 140 differ; the whole list is in
`validation.md`. The windows where the state changed most are these:

| tick | before | after | after kinds |
|---|---|---|---|
| 981 | RECOVERY | UNSTABLE | refusal |
| 1001 | DEVIATING | UNSTABLE | refusal, congestion |
| 1021 | RECOVERY | UNSTABLE | refusal, congestion |
| 1041 | STABLE | UNSTABLE | refusal, congestion |
| 1061 | STABLE | UNSTABLE | refusal |
| 1081 | DEVIATING | UNSTABLE | refusal, chatter |
| 1721 to 1881 | DEVIATING (4), RECOVERY (2), STABLE (2), UNSTABLE (1, at 1841) | UNSTABLE (all 9 windows) | structure, synchrony, chatter, refusal |
| 2041 | RCT | UNSTABLE | refusal, congestion, spread, saturation |
| 2081, 2101 | RCT | UNSTABLE | refusal, congestion, chatter, spread |
| 2161 to 2321 | STABLE (5), DEVIATING (2), RECOVERY (2) | UNSTABLE (all 9 windows) | refusal, saturation, backlog, retry, congestion |
| 2681 | RCT | DEVIATING | refusal, retry, congestion, spread, saturation |
| 2701, 2721 | RCT | UNSTABLE | refusal, retry, congestion, chatter, spread, synchrony / structure |

**The honest finding.** Normal now reads UNSTABLE more often: 38 windows against 9 at 2800
ticks (and 1 against 1 at 300). The cause is the baseline learning rule. Take ticks 941 to
1081: the policy gate refuses 7 to 10 decisions per window (`gate_rejections`, 0.117 to 0.167
per tick) against a refusal baseline of 0.026 per tick. Before, every window entered the
baseline, the baseline rose with the spell, and the spell read RECOVERY, STABLE, DEVIATING
from 981 on. After, the windows called UNSTABLE at 941 and 961 do not enter the baseline, so
the baseline stays at 0.026 and the same refusals keep reading at z of 2.9 to 4.4 until the
spell ends at 1101 (RECOVERY). The same mechanism holds the run at 2161 to 2241 (3 to 5
refusals a window against a baseline of 0.003 per tick, z 2.5 to 4.0, with saturation beside
it at 2181 and 2201); the run at 1721 to 1881 is a different case, activity synchronization
far above its baseline (z 3.0 to 16.6) with the structure and chatter kinds beside it. This is
a calibration trade-off, not a defect to hide: the monitor no longer
learns its normal from windows it called abnormal, which is what M-S-DROP needed (section 8.2),
and the price is that a sustained spell within Normal is also held against the pre-spell
baseline. The other side of the same change is that Normal's six RCT verdicts before are zero
after: at 2041, 2081, 2101, 2681, 2701 and 2721 the kinds are there (four to six) and
propagation is 0.54 to 0.58, but neither the dragon-king nor the slowing-down statistic held on
the new severity series (`is_dragon` False and `slowing_down` False at each of those ticks,
read from the assessments), so the RCT rule did not fire. Whether an ordinary Normal run should
ever read RCT is a calibration question this work does not settle.

### 8.2 M-S-DROP, seed 11, 2800 ticks (every message dropped at delivery from tick 400)

State counts: STABLE 8, DEVIATING 8, UNSTABLE 94, RCT 28, RECOVERY 2 over 140 assessments.
First ticks after the fault: DEVIATING 401, UNSTABLE 421, RCT 461 (the facility had also read
DEVIATING at 81 and UNSTABLE at 101 during start-up, as Normal does). The first window after
400 with a failure rate at or above 0.99 is 461; the windows at 401, 421 and 441 still cover
ticks before the fault (the window is 60 ticks) and read 0.029, 0.150 and 0.333. Backlog growth
was above 0 after the fault (maximum 0.1 parcels per tick); the dock reached its cap of 26 at
tick 1141 (growth 0.05 in that window) and growth was 0.0 in every window after it. Parcels
departed after the fault: 6, on three vans (tick 416: 1, tick 541: 4, tick 583: 1), parcels
already at the dispatch door when the bus went silent; every `task_completion_rate` from tick
661 on is 0.0 (the window ending at 641 still covers tick 583). `resource_saturation` reached 1.0 (its dock category: 26 of 26). Dropped can
exceed attempted in a window (for example 78 attempted, 79 dropped at 481) because the bus logs
the send one tick before the drop; the rate is clamped and `delivered` floored at 0, as section
21.1 of the mathematics documents.

Per window, every window from 381 to 621 and then every fifth (att. = attempted, deliv. =
delivered, drop. = dropped, compl. rate = task_completion_rate, gap = completion_gap,
saturation = resource_saturation, dock = its dock category, divergence =
dependency_graph_divergence, tail = tail_deviation):

| tick | state | att. | deliv. | drop. | late | fail. rate | backlog | growth | compl. rate | gap | saturation | dock | divergence | tail | kinds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 381 | DEVIATING | 345 | 345 | 0 | 0 | 0.000 | 19 | -0.100 | 0.067 | -0.067 | 0.800 | 0.308 | 0.363 | 5.094 | congestion |
| 401 | DEVIATING | 310 | 301 | 9 | 0 | 0.029 | 19 | 0.000 | 0.033 | -0.033 | 1.000 | 0.308 | 0.446 | 5.094 | congestion, delivery |
| 421 | UNSTABLE | 200 | 170 | 30 | 0 | 0.150 | 18 | -0.050 | 0.050 | -0.050 | 0.600 | 0.308 | 0.552 | 1.000 | delivery |
| 441 | UNSTABLE | 165 | 110 | 55 | 0 | 0.333 | 19 | 0.050 | 0.017 | 0.000 | 0.600 | 0.346 | 0.654 | 1.125 | delivery |
| 461 | RCT | 73 | 0 | 73 | 0 | 1.000 | 19 | 0.000 | 0.017 | 0.000 | 0.600 | 0.346 | 0.878 | 1.125 | chatter, herding, delivery, structure |
| 481 | RCT | 78 | 0 | 79 | 0 | 1.000 | 19 | 0.000 | 0.000 | 0.017 | 0.600 | 0.346 | 0.879 | 1.125 | chatter, herding, delivery, structure |
| 501 | RCT | 80 | 1 | 79 | 0 | 0.988 | 19 | 0.000 | 0.000 | 0.000 | 0.600 | 0.346 | 0.880 | 1.125 | chatter, herding, spread, delivery |
| 521 | RCT | 77 | 0 | 79 | 0 | 1.000 | 19 | 0.000 | 0.000 | 0.000 | 0.600 | 0.346 | 0.881 | 1.125 | chatter, herding, spread, delivery |
| 541 | RCT | 81 | 0 | 84 | 0 | 1.000 | 15 | -0.200 | 0.067 | -0.067 | 0.600 | 0.346 | 0.877 | 1.125 | chatter, herding, spread, delivery |
| 561 | RCT | 79 | 0 | 79 | 0 | 1.000 | 15 | 0.000 | 0.067 | -0.067 | 0.600 | 0.346 | 0.882 | 1.125 | chatter, herding, spread, delivery |
| 581 | RCT | 78 | 0 | 80 | 0 | 1.000 | 15 | 0.000 | 0.067 | -0.067 | 0.600 | 0.346 | 0.879 | 1.125 | chatter, herding, spread, delivery |
| 601 | RCT | 77 | 0 | 80 | 0 | 1.000 | 16 | 0.050 | 0.083 | -0.050 | 0.600 | 0.423 | 0.884 | 1.375 | chatter, herding, delivery |
| 621 | RCT | 77 | 1 | 76 | 0 | 0.987 | 16 | 0.000 | 0.017 | 0.017 | 0.600 | 0.423 | 0.887 | 1.375 | chatter, herding, delivery |
| 721 | UNSTABLE | 76 | 0 | 79 | 0 | 1.000 | 18 | 0.000 | 0.000 | 0.033 | 0.600 | 0.500 | 0.886 | 1.625 | chatter, herding, delivery |
| 821 | UNSTABLE | 75 | 0 | 77 | 0 | 1.000 | 22 | 0.050 | 0.000 | 0.033 | 0.654 | 0.654 | 0.886 | 2.125 | chatter, herding, delivery |
| 921 | UNSTABLE | 79 | 1 | 78 | 0 | 0.987 | 28 | 0.050 | 0.000 | 0.067 | 0.885 | 0.885 | 0.882 | 2.875 | chatter, herding, delivery |
| 1021 | UNSTABLE | 75 | 0 | 78 | 0 | 1.000 | 29 | 0.050 | 0.000 | 0.017 | 0.923 | 0.923 | 0.889 | 3.000 | chatter, herding, delivery |
| 1121 | UNSTABLE | 73 | 0 | 75 | 0 | 1.000 | 30 | 0.000 | 0.000 | 0.000 | 0.962 | 0.962 | 0.891 | 3.125 | chatter, herding, delivery |
| 1221 | UNSTABLE | 75 | 1 | 74 | 0 | 0.987 | 31 | 0.000 | 0.000 | 0.033 | 1.000 | 1.000 | 0.892 | 3.250 | chatter, herding, spread, delivery |
| 1321 | UNSTABLE | 74 | 0 | 76 | 0 | 1.000 | 31 | 0.000 | 0.000 | 0.017 | 1.000 | 1.000 | 0.892 | 3.250 | chatter, herding, spread, delivery |
| 1421 | UNSTABLE | 72 | 0 | 75 | 0 | 1.000 | 31 | 0.000 | 0.000 | 0.017 | 1.000 | 1.000 | 0.894 | 3.250 | chatter, herding, spread, delivery |
| 1521 | UNSTABLE | 75 | 1 | 74 | 0 | 0.987 | 31 | 0.000 | 0.000 | 0.050 | 1.000 | 1.000 | 0.892 | 3.250 | chatter, herding, spread, delivery |
| 1621 | UNSTABLE | 74 | 0 | 77 | 0 | 1.000 | 31 | 0.000 | 0.000 | 0.050 | 1.000 | 1.000 | 0.892 | 3.250 | chatter, herding, spread, delivery |
| 1721 | UNSTABLE | 73 | 0 | 75 | 0 | 1.000 | 31 | 0.000 | 0.000 | 0.017 | 1.000 | 1.000 | 0.891 | 3.250 | herding, delivery |
| 1821 | UNSTABLE | 75 | 1 | 74 | 0 | 0.987 | 31 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.892 | 3.250 | chatter, herding, delivery |
| 1921 | UNSTABLE | 74 | 0 | 77 | 0 | 1.000 | 31 | 0.000 | 0.000 | 0.050 | 1.000 | 1.000 | 0.892 | 3.250 | chatter, herding, spread, delivery |
| 2021 | UNSTABLE | 73 | 0 | 75 | 0 | 1.000 | 31 | 0.000 | 0.000 | 0.050 | 1.000 | 1.000 | 0.891 | 3.250 | herding, delivery |
| 2121 | UNSTABLE | 75 | 1 | 74 | 0 | 0.987 | 31 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.892 | 3.250 | chatter, herding, delivery |
| 2221 | RCT | 74 | 0 | 77 | 0 | 1.000 | 31 | 0.000 | 0.000 | 0.017 | 1.000 | 1.000 | 0.892 | 3.250 | chatter, herding, spread, delivery |
| 2321 | RCT | 73 | 0 | 74 | 0 | 1.000 | 31 | 0.000 | 0.000 | 0.050 | 1.000 | 1.000 | 0.891 | 3.250 | chatter, herding, spread, delivery |
| 2421 | UNSTABLE | 75 | 1 | 74 | 0 | 0.987 | 31 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 0.892 | 3.250 | chatter, herding, delivery |
| 2521 | UNSTABLE | 74 | 0 | 77 | 0 | 1.000 | 31 | 0.000 | 0.000 | 0.017 | 1.000 | 1.000 | 0.892 | 3.250 | chatter, herding, spread, delivery, synchrony |
| 2621 | RCT | 73 | 0 | 75 | 0 | 1.000 | 31 | 0.000 | 0.000 | 0.033 | 1.000 | 1.000 | 0.891 | 3.250 | chatter, herding, spread, delivery |
| 2721 | UNSTABLE | 75 | 1 | 74 | 0 | 0.987 | 31 | 0.000 | 0.000 | 0.017 | 1.000 | 1.000 | 0.892 | 3.250 | herding, delivery |

Two things to read off the table. The delivery kind is present in every window from 401 to
the end, and from 461 on the state never returns below UNSTABLE; the RCT windows are exactly
those in which the remaining conditions also held (three or more kinds, one confirmed,
propagation at or above 0.5, and here always the slowing-down reading, never the dragon-king
one), and no UNSTABLE window after the fault met all of them. The backlog kind is absent after
the fault even though the backlog grows: the growth is 0.05 to 0.1 parcels per tick against a
baseline mean of 0.010 to 0.013 per tick, and its z reaches at most 1.79, under the threshold
of 2; the dock's saturation is read instead (1.0 from tick 1141). The structure kind read the
collapsed graph at 461 and 481 (divergence 0.877 to 0.894 from 461 on, against 0.228 to 0.446
in the windows before the fault) and then stopped: the divergence indicator's own baseline did not
reach its 24 windows until the assessment at 481 (its first evaluable reading is at tick 21),
and until then it learned from every window, so it took the readings of 461 and 481 (z 2.43
and 2.12) as its last two points; its mean rose from 0.464 to 0.499 and
its spread widened, and from 501 on the same divergence reads z 1.91 to 1.95, under the
threshold. This is the unformed-baseline clause of the learning rule at work, the same limit as
the message-delay tail in M-S-DELAY (section 9).

### 8.3 M-S-DELAY, seed 11, 2800 ticks (every routing-related message delayed 10 ticks from tick 400)

State counts: STABLE 8, DEVIATING 8, UNSTABLE 113, RCT 9, RECOVERY 2. First ticks after the
fault: DEVIATING 401 (congestion, carried over from before the fault; the first delayed
message arrives at tick 410), UNSTABLE 421 (the first window with the delivery kind), RCT 541.
No window reached a failure rate of 0.99; the per-window rate after the fault ranged from 0.0
(the window ending at 401) to 0.8904, mean 0.3596.

From the events: 2389 `agent_message_received` events with `late_by > 0`, none before the
fault, every one with `late_by = 10` (the scenario's `DELAY_TICKS`); 0 `message_dropped`
events; 7993 messages attempted in the run, 5150 of them from tick 400 on. The routing share of
the attempted messages after the fault is 2387 of 5150 = 0.4635, and it is the same number
whichever way it is read (sender or receiver is ROUTING; sender or receiver in the routing
group ROUTING, SUB-ROUTE, SUB-COLLISION; the scenario's own `is_routing_related` rule with the
route message types and the routing robot commands): the only routing-related messages in this
run have ROUTING itself at one end. Over the whole run after the fault, late over attempted is
2389 of 5150 = 0.4639, which equals the routing share to within two messages: four routing
messages sent at tick 399 were held by the rule installed at 400 and arrived late at 410 (in
the numerator, not in the denominator), and two routing messages sent on the last tick, 2800,
were still pending when the run ended (in the denominator, not in the numerator). Per window
the rate wanders around that share because the window counts sends and late arrivals in the
same 60 ticks while each late arrival belongs to a send 11 ticks earlier, and because the mix of
traffic changes: from 421 to 1481 the rate ranged from 0.060 to 0.890; once the facility stalls
(the dock at its cap from 1421, the last task started in the window ending at 1481), the
attempted traffic falls to 48 to 87 messages a window of which 8 to 17 arrive late, and the
rate reads 0.123 to 0.313.

Latency and tail: before the fault `execution_latency` was 73.7 to 76.0 ticks with a p95 of
326 (a slow queue already DEVIATING on congestion at 361 to 401); after it the p95 of the
task wait went to 143 (461 to 501), 282 (521 to 561), 217 (581 to 621) and 263 (681 to 721)
against a baseline p95 of 64 to 66.5, so `tail_deviation` read 2.234, 4.241, 3.263 and 3.955;
from tick 901 the few tasks that start wait 1 tick (ratio 0.015) and after the window ending
at 1481 no task starts at all. The message-delay metric has p95 10 in every window after 421; its baseline is "too
short" until 501 and then 10, so its ratio is 1.0 throughout (section 9). The zone-backlog
metric rises from 8 (baseline 8) to 26 (ratio 3.25) as the dock fills. The facility stalls as
in M-S-DROP: parcels departed after the fault 10, the last at tick 666; `task_completion_rate`
0.0 from 741 on; the dock at its cap of 26 from tick 1421; backlog growth 0.0 after that.

Per window, every window from 381 to 701 and then every tenth:

| tick | state | att. | late | fail. rate | latency | latency p95 | tail | backlog | compl. rate | dock | kinds |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 381 | DEVIATING | 345 | 0 | 0.000 | 73.667 | 326.000 | 5.094 | 19 | 0.067 | 0.308 | congestion |
| 401 | DEVIATING | 319 | 0 | 0.000 | 76.000 | 326.000 | 5.094 | 19 | 0.033 | 0.308 | congestion |
| 421 | UNSTABLE | 268 | 16 | 0.060 | 24.333 | 37.000 | 0.875 | 18 | 0.050 | 0.269 | delivery |
| 441 | UNSTABLE | 307 | 37 | 0.120 | 12.667 | 37.000 | 1.000 | 19 | 0.017 | 0.308 | delivery |
| 461 | UNSTABLE | 253 | 60 | 0.237 | 36.500 | 143.000 | 2.234 | 19 | 0.017 | 0.308 | delivery |
| 481 | UNSTABLE | 259 | 83 | 0.321 | 41.000 | 143.000 | 2.234 | 19 | 0.000 | 0.308 | delivery |
| 501 | UNSTABLE | 239 | 106 | 0.444 | 86.000 | 143.000 | 2.150 | 19 | 0.000 | 0.308 | retry, congestion, delivery |
| 521 | UNSTABLE | 257 | 123 | 0.479 | 132.333 | 282.000 | 4.241 | 19 | 0.000 | 0.269 | retry, congestion, delivery |
| 541 | RCT | 255 | 138 | 0.541 | 161.000 | 282.000 | 4.241 | 15 | 0.067 | 0.269 | congestion, chatter, delivery |
| 561 | RCT | 246 | 149 | 0.606 | 209.000 | 282.000 | 4.241 | 15 | 0.067 | 0.269 | congestion, chatter, delivery |
| 581 | RCT | 270 | 180 | 0.667 | 141.000 | 217.000 | 3.263 | 15 | 0.067 | 0.269 | congestion, chatter, delivery |
| 601 | UNSTABLE | 319 | 202 | 0.633 | 93.667 | 217.000 | 3.263 | 14 | 0.100 | 0.269 | congestion, delivery |
| 621 | UNSTABLE | 328 | 213 | 0.649 | 72.400 | 217.000 | 3.263 | 14 | 0.033 | 0.231 | congestion, delivery |
| 641 | UNSTABLE | 301 | 191 | 0.635 | 1.000 | 1.000 | 1.000 | 12 | 0.067 | 0.231 | delivery |
| 661 | RCT | 227 | 148 | 0.652 | 1.000 | 1.000 | 1.000 | 12 | 0.033 | 0.192 | chatter, spread, delivery |
| 681 | UNSTABLE | 244 | 111 | 0.455 | 126.000 | 263.000 | 3.955 | 13 | 0.050 | 0.269 | congestion, delivery |
| 701 | UNSTABLE | 232 | 98 | 0.422 | 126.000 | 263.000 | 3.955 | 13 | 0.017 | 0.308 | congestion, delivery |
| 901 | UNSTABLE | 235 | 146 | 0.621 | 1.000 | 1.000 | 1.875 | 20 | 0.000 | 0.577 | spread, delivery, throughput |
| 1101 | UNSTABLE | 186 | 144 | 0.774 | 1.000 | 1.000 | 2.250 | 23 | 0.000 | 0.692 | delivery |
| 1301 | UNSTABLE | 165 | 123 | 0.746 | 1.000 | 1.000 | 2.625 | 26 | 0.000 | 0.808 | herding, delivery |
| 1501 | UNSTABLE | 80 | 16 | 0.200 | 0.000 | n/a | 3.250 | 31 | 0.000 | 1.000 | herding, delivery, structure |
| 1701 | UNSTABLE | 61 | 13 | 0.213 | 0.000 | n/a | 3.250 | 31 | 0.000 | 1.000 | herding, delivery, structure |
| 1901 | UNSTABLE | 66 | 12 | 0.182 | 0.000 | n/a | 3.250 | 31 | 0.000 | 1.000 | chatter, herding, delivery, structure |
| 2101 | UNSTABLE | 59 | 13 | 0.220 | 0.000 | n/a | 3.250 | 31 | 0.000 | 1.000 | chatter, herding, delivery, structure |
| 2301 | UNSTABLE | 70 | 12 | 0.171 | 0.000 | n/a | 3.250 | 31 | 0.000 | 1.000 | chatter, herding, delivery, structure |
| 2501 | UNSTABLE | 71 | 12 | 0.169 | 0.000 | n/a | 3.250 | 31 | 0.000 | 1.000 | chatter, herding, delivery, structure |
| 2701 | UNSTABLE | 84 | 13 | 0.155 | 0.000 | n/a | 3.250 | 31 | 0.000 | 1.000 | herding, delivery, structure |

The tail detail per metric at selected windows (p95 now / baseline p95 / ratio):

| tick | task wait | message delay | zone backlog | tail_deviation |
|---|---|---|---|---|
| 401 | 326 / 64 / 5.094 | n/a (no values this window) | 8 / 8 / 1.000 | 5.094 |
| 421 | 37 / 66.5 / 0.556 | 10 / n/a (baseline too short) | 7 / 8 / 0.875 | 0.875 |
| 461 | 143 / 64 / 2.234 | 10 / n/a (baseline too short) | 8 / 8 / 1.000 | 2.234 |
| 501 | 143 / 66.5 / 2.150 | 10 / 10 / 1.000 | 8 / 8 / 1.000 | 2.150 |
| 521 | 282 / 66.5 / 4.241 | 10 / 10 / 1.000 | 8 / 8 / 1.000 | 4.241 |
| 701 | 263 / 66.5 / 3.955 | 10 / 10 / 1.000 | 8 / 8 / 1.000 | 3.955 |
| 901 | 1 / 66.5 / 0.015 | 10 / 10 / 1.000 | 15 / 8 / 1.875 | 1.875 |
| 1101 | 1 / 66.5 / 0.015 | 10 / 10 / 1.000 | 18 / 8 / 2.250 | 2.250 |
| 1501 | n/a (no values this window) | 10 / 10 / 1.000 | 26 / 8 / 3.250 | 3.250 |
| 2781 | n/a (no values this window) | 10 / 10 / 1.000 | 26 / 8 / 3.250 | 3.250 |

## 9. What the brief asked for that is not implemented, or only partly

- `held_now` is a state read (the length of the bus's `_held` list at the assessment tick),
  recorded in the delivery counts and shown in the operations block. It is not an indicator:
  it has no baseline, no z and no kind.
- The declared dependency graph reuses the agent directory (parent/child links both ways plus
  every pair `may_send` allows). There is no second network representation, and the
  divergence indicator compares a realised window with realised baseline windows; the declared
  set only labels edges as `unexpected` or `missing` in the detail.
- `tail_deviation` is one derived indicator that takes the maximum over three tail metrics
  (task wait, message delay, zone backlog), not three indicators, and it belongs to the
  congestion kind rather than to a kind of its own.
- A baseline that is still forming when a fault hits learns the fault: the divergence
  indicator in M-S-DROP (section 8.2) and the message-delay tail metric in M-S-DELAY below. The
  learning rule protects a formed baseline only; a fault that starts before every baseline has
  its 24 windows (the divergence baseline is complete at tick 481, one assessment later than the
  others because its first reading is at 21) is absorbed by the baselines still forming.
- The message-delay tail metric has no Normal baseline: Normal has no late message, so the
  metric's FIFO is empty until the fault, then fills with the fault's own p95 (10 ticks) because
  an unformed baseline learns from every window. In M-S-DELAY its ratio is therefore 1.0 from
  tick 501 on, and the delay is detected by the delivery kind, not by the tail. A baseline that
  only ever saw the fault cannot say the fault is abnormal; this is the limit of measuring each
  indicator against its own empirical past.
- The backlog kind did not fire after the fault in M-S-DROP or M-S-DELAY: the growth of one
  parcel every 20 to 40 ticks is within Normal's own variation of the backlog. The dock's
  saturation and the structure kind carried that part of the picture instead.
- `completion_gap` is registered as an indicator of its own (the design note kept it in the
  detail only) because the throughput kind reads it.
- `propagation_across_agents` is listed as derived (the model's wording) though it is computed
  from the window alone; `persistence_of_deviation` is the only indicator whose value comes
  from the monitor's counter rather than from the window or the state.
- No null distribution, bootstrap or significance level was added, no threshold declares
  UNSTABLE or RCT from a single indicator, and the monitor still takes no action on any state.
- The validation driver runs the three scenarios on one seed each (Normal 1, faults 11) and
  does not cover C-S-STARVE or C-S-PARTITION.
