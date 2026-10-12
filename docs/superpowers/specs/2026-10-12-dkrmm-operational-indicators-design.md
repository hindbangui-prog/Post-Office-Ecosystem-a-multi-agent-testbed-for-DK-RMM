# DK-RMM operational and early-warning indicators: design

## 1. Findings: why M-S-DROP reads STABLE while the dock fills

Pipeline (unchanged code, read on 2026-10-12): `EventLogger.subscribe` ->
`DKRMM.observe` (appends to a 20000-event deque, remembers `task_created`
ticks) -> every `EVERY = 20` ticks `assess(now)` takes the events of the last
`WINDOW = 60` ticks -> `compute_indicators` (twelve values, `counts`) ->
`zscore` of each against its own last `BASELINE = 24` window values ->
`severity = mean(max(0, z))` -> `_classify` (evidence kinds from `EVIDENCE`,
confirmed kinds, persistence, propagation, dragon-king and precursors on the
severity series) -> `Assessment` -> `monitor.state()/series()/history` ->
`/dkrmm/state`, `/dkrmm/indicators` (`indicator_rows`: name, about, value, z)
-> the DK-RMM tab and the top badge.

Five causes, all in the measurement or classification, none only in the page:

1. **Only upward deviations count.** `_classify` tests `z >= DEVIATION_Z` and
   `severity` keeps `max(0, z)`. Under a total message drop, tool calls,
   interaction density, task switching, coupling and latency all *fall*;
   their negative z-scores are discarded. The comment in the code says it:
   "an indicator that has gone quiet is not evidence of a crisis".
2. **`message_frequency` counts attempts, not deliveries.** The bus logs the
   `message` event at `send` (bus.py:193) and the drop at `deliver`
   (`message_dropped`, bus.py:229). The senders keep sending (SCHEDULING asks
   SUB-QUEUE every tick, ROUTING re-asks), so the attempted rate stays near
   baseline and nothing in the twelve reads `message_dropped` or
   `agent_message_received`.
3. **No operational indicator exists.** Nothing measures parcels inside the
   building, parcels leaving, arrivals turned away, robots usable, charge
   points, routes. The twelve are shape-of-behaviour indicators by design
   (indicators.py docstring, "content-agnostic").
4. **The rolling baseline absorbs the fault.** Each indicator's baseline is
   its own last 24 windows, updated every window whatever the state. After
   24 windows (480 ticks) under a fault, the fault is the baseline and a
   sustained deviation reads as normal.
5. **The quiet rule.** A window with fewer than `MIN_ACTIVITY = 24` events is
   STABLE by rule, so a facility that goes silent is "too quiet to read".
   M-S-DROP is not quiet (senders keep talking), but C-S-STARVE late in the
   run is, and the rule then hides a dead facility.

`zscore` already handles a dead-flat baseline that moves (returns 3.0), so an
indicator that is 0 in Normal and 1 under a fault is detectable.

## 2. What is preserved

- The simulation: no change to the bus, agents, gate, scenarios, configs,
  seeds, prompts, settings, drivers' fault definitions. DK-RMM emits no event
  and writes nothing into the run; it only subscribes and, new in this work,
  reads the world state at assessment time (read-only).
- The twelve existing indicator names, their formulas and `counts`, the
  `BehaviouralIndicators` fields, `EVERY`, `WINDOW`, `BASELINE`,
  `DEVIATION_Z`, `UNSTABLE_KINDS`, `RCT_KINDS`, `RCT_PROPAGATION`,
  `PERSISTENT`, `MIN_POINTS`, `DRAGON_FACTOR`, `TAIL_POINTS`, the precursor
  and dragon-king tests, the state vocabulary and the human gate.
- Normal's event stream is byte for byte the same (checked by hash). Normal's
  DK-RMM *assessments* may change where the classifier changes (section 6);
  the before/after state counts are reported, not hidden.

## 3. Data sources (existing, read-only)

Events (already logged): `message`, `subagent_message` (sent),
`message_dropped`, `agent_message_received` (`late_by`), `message_refused`,
`parcel_arrived`, `arrival_refused`, `parcel_refused`, `parcel_returned`,
`van_departed` (`parcels`), `task_created`, `task_started`,
`task_completed`, `task_failed`, the decision/refusal/retry/switch topics
already used. State reads at assessment time, via `self._eco` (read-only,
never written): `eco.env.parcels` (status, zone), `eco.env.parcels_in(zone)`,
`eco.generator.refused`, `eco.env.stations` (count, occupancy),
`eco.env.departures._bay` / `routes` (vans at bay), `eco.fleet.all()` (robot
status, battery), `eco.env.storage` (used, capacity), `eco.world.tasks.counts()`,
`eco.config["max_on_dock"]`, `eco.bus.directory` (declared structure),
`eco.bus._held` (messages held now). If a read is unavailable the indicator
is marked not evaluable, never filled with a normal-looking number.

## 4. The indicator registry (18 base and derived)

Base indicators are computed from one window's events and one state snapshot;
derived indicators are computed from indicator histories kept by the monitor.
Every indicator value is a float; every indicator also has `evaluable`
(bool) and `counts`/`detail` for the page. Units in brackets.

### 4.1 Existing twelve (unchanged formulas; definitions made explicit)

| name | base/derived | definition |
|---|---|---|
| message_frequency | base | attempted bus messages (`message` + `subagent_message`) per tick [msg/tick]. Direction: two-sided (a fall is evidence when corroborated, see 6). |
| interaction_density | base | distinct ordered (sender, receiver) pairs seen / (active x (active-1)), active = agents that emitted any event [0..1]. Two-sided. |
| delegation_frequency | base | messages from a non-sub-agent to a sub-agent per tick (expert-to-expert consultation is not delegation; CONSULT_* messages are not sub-agent messages) [msg/tick]. |
| retry_frequency | base | `RETRY_TOPICS` events per tick. |
| guardrail_events | base | refusals per tick: `REFUSAL_TOPICS` (door, shelf, charge refused/unavailable, message refused, returned) plus decisions refused at the `policy` or `state` stage. New `counts` split: `gate_rejections` (policy/state), `intake_rejections` (`parcel_refused`, `arrival_refused`, `parcel_returned`), `resource_denials` (`charge_refused`, `charge_unavailable`, `storage_refused`), `message_refusals`. The rate is unchanged; the split is recorded. |
| tool_call_frequency | base | messages from a sub-agent per tick [msg/tick]. |
| task_switching | base | `SWITCH_TOPICS` events per tick (task released, assigned, errand handed over, yield and step-aside commands). |
| execution_latency | base | mean ticks from `task_created` to `task_started` for tasks started in the window [ticks]. New beside it: `execution_latency_p95` (recorded in detail, used by tail_deviation). |
| agent_coupling | base | active agents / roster [0..1]. Documented as the **active-agent fraction**, not a coupling measure; name kept for compatibility, `about` text corrected. |
| behavioural_similarity | base | mean pairwise cosine of the 16 busiest agents' topic-count profiles [0..1]. Direction: two-sided (a change from normal similarity, not high similarity as such). |
| persistence_of_deviation | derived | consecutive assessments (this one excluded) whose state was not STABLE [assessments]. |
| propagation_across_agents | derived (per window) | affected acting agents / acting agents. Acting = emitted a non-message event. Affected = emitted a `TROUBLE_TOPICS` event or a policy/state refusal, **or** (new) sent a message that was dropped, or received a late message. |

### 4.2 New base indicators

| name | definition | not evaluable when |
|---|---|---|
| communication_failure_rate | (dropped + late) / attempted in the window, where attempted = `message` + `subagent_message` events, dropped = `message_dropped`, late = `agent_message_received` with `late_by > 0` (each message counted once: a dropped message has no late event) [0..1]. Counts: attempted, delivered = attempted - dropped, dropped, late, `held_now` (bus `_held`). | attempted == 0 |
| backlog_growth | (backlog_now - backlog_prev) / EVERY, backlog = parcels inside the building (status not DISPATCHED/REFUSED/RETURNED, i.e. `len(eco.env.parcels)`) read at assessment [parcels/tick]. Detail: backlog_now, by zone (intake dock, sorting, storage, dispatch door, carried), unfinished tasks (`tasks.counts` minus COMPLETED/FAILED/CANCELLED), `increasing_for` (consecutive assessments with growth > 0), `acceleration` = growth_now - growth_prev. A parcel is counted once (by its own record). | first assessment (no previous) |
| task_completion_rate | parcels that left on vans in the window (`van_departed.parcels`) / span [parcels/tick]. Detail: incoming = `parcel_arrived` + `arrival_refused` (demand) per tick, `completion_gap` = incoming - completed per tick, tasks completed (`task_completed`) per tick. Direction: down (a fall is evidence); the gap is a second kind. | never (0 is a value) |
| resource_saturation | max over categories of utilisation in [0..1]; categories recorded: robots = (roster robots - usable) / roster, usable = IDLE or WAITING with battery above reserve and not flat; charge_points = occupied / points, or 1.0 when points == 0 and any robot needs charge; routes = closed / declared routes; storage = used / capacity; dock = parcels on the dock / `max_on_dock`. Aggregation = the bottleneck (max), documented; each category is shown. | roster == 0 |
| dependency_graph_divergence | 1 - weighted Jaccard between the observed edge-weight map W_now (ordered (sender, receiver) message counts in the window) and the baseline map W_base (mean weight per edge over the baseline windows) [0..1]. Detail: `unexpected` = observed edges not in the declared structure (directory parent/child plus the expert-to-robot command edges and the peer map), `missing` = declared edges with baseline weight > 0 and weight 0 now, `weight_change` = L1 distance / total baseline weight. Reuses the directory as the declared graph; no second network representation. | no baseline windows yet |
| activity_synchronization | mean pairwise Pearson correlation of the per-tick event-count series of the acting agents in the window (ticks binned by `event.tick`) [-1..1]. Direction: two-sided. | fewer than 2 acting agents or fewer than 4 ticks |

### 4.3 New derived indicator

| name | definition | not evaluable when |
|---|---|---|
| tail_deviation | max over the tail metrics of (p95_now / p95_baseline), tail metrics: task wait (created to started) in ticks, message delay (`late_by`), backlog by zone (the max zone backlog) [ratio]. Detail per metric: p95_now, p95_baseline, ratio. p95 = nearest-rank over the window's values; baseline p95 = median of the past windows' p95 values. | fewer than 4 baseline windows, or no values in the window for every metric |

Registry entries: the existing twelve first, then the six in the order above
(communication_failure_rate, backlog_growth, task_completion_rate,
resource_saturation, dependency_graph_divergence, activity_synchronization,
tail_deviation), each with `about` text, `kind` ("base"/"derived") and
`direction` ("up", "down", "both"). The series, page and record read the
registry, so they extend without hand lists.

## 5. Baseline treatment

- Each indicator keeps its rolling baseline of `BASELINE = 24` windows as
  today.
- **Correction (documented):** a window assessed UNSTABLE or RCT does not
  enter any baseline (`BASELINE_LEARNS_FROM = (STABLE, DEVIATING, RECOVERY)`,
  configurable). The monitor does not learn its normal from windows it judged
  unstable. STABLE and DEVIATING windows still enter it, so an ordinary busy
  spell keeps shaping the baseline as before.
- A not-evaluable value does not enter the baseline and yields z = 0 with
  `evaluable = False` recorded; the page shows "n/a", never 0.
- `zscore` is unchanged (dead-flat baseline that moves gives 3.0).

## 6. State assessment (changes, with the reason for each)

1. **Direction-aware evidence.** `EVIDENCE` entries carry the direction per
   indicator. A deviation counts when `z >= DEVIATION_Z` for "up", `z <=
   -DEVIATION_Z` for "down", `|z| >= DEVIATION_Z` for "both". Kinds:

   | kind | indicators (direction) |
   |---|---|
   | refusal | guardrail_events (up) |
   | retry | retry_frequency (up) |
   | congestion | execution_latency (up), task_switching (up) |
   | chatter | message_frequency (both), delegation_frequency (up), tool_call_frequency (up), interaction_density (both) |
   | herding | behavioural_similarity (both), agent_coupling (both) |
   | spread | propagation_across_agents (up) |
   | delivery | communication_failure_rate (up) |
   | backlog | backlog_growth (up) |
   | throughput | task_completion_rate (down), completion_gap (up) |
   | saturation | resource_saturation (up) |
   | structure | dependency_graph_divergence (up) |
   | synchrony | activity_synchronization (both) |
   | tail | tail_deviation (up) |

   A falling `message_frequency` or `interaction_density` counts only when
   at least one operational kind (delivery, backlog, throughput, saturation)
   is also present in the same window; a quiet facility with normal output is
   not deviating. This is the "do not read silence as health, but do not read
   it as crisis either" rule.
2. **Severity** = mean over indicators of the deviation in the configured
   direction (max(0, z) for up, max(0, -z) for down, |z| for both), so the
   dragon-king and precursor tests see downward operational deviations.
3. **Quiet rule narrowed.** Below `MIN_ACTIVITY` events, the behavioural
   kinds (refusal, retry, congestion, chatter, herding, spread, structure,
   synchrony) are not evaluated; the operational kinds (delivery, backlog,
   throughput, saturation, tail) are, because they are read from parcel
   events and state, not from chatter. Evidence text says which kinds were
   not evaluated.
4. **Sustained operational deterioration.** Unchanged persistence rule: kinds
   present -> DEVIATING; a kind confirmed in two consecutive windows twice
   over -> UNSTABLE; any kind for `PERSISTENT = 3` windows -> UNSTABLE. The
   operational kinds enter these rules like any other. No threshold is added
   that declares UNSTABLE or RCT from one indicator.
5. **RCT rule unchanged**: `RCT_KINDS = 3` kinds with one confirmed,
   propagation >= 0.5, and dragon-king or precursors. Propagation now counts
   dropped-sender and late-receiver agents as affected (4.1), so a
   communication failure that reaches the population can satisfy it; a
   backlog alone cannot.
6. All thresholds live in `monitor.py` constants with their rationale; the
   new ones: `MIN_SYNC_AGENTS = 2`, `TAIL_P = 0.95`, `TAIL_MIN_BASELINE = 4`,
   `BASELINE_LEARNS_FROM`. No scenario-specific numbers.

## 7. Dashboard

- `/dkrmm/indicators` rows gain: `kind`, `direction`, `baseline` (mean of
  the baseline window values, null when fewer than 4), `evaluable`,
  `deviation` ("up"/"down"/"none" against `DEVIATION_Z`), `in_evidence`
  (the kind it fed this window, or null), `detail` (counts and per-category
  values). The page's indicator table shows name, about, value (or "n/a"),
  baseline, z with direction arrow, and a status cell (ok / deviating up /
  deviating down / n/a).
- A short "operations" block above the table: delivery (attempted,
  delivered, dropped, late, failure rate), backlog (now, per tick, zones),
  throughput (completed, incoming, gap), resources (per category).
- The badge stays the assessment's state; next to it an "observed" line
  lists the evidence kinds present this window and the kinds not evaluated,
  so STABLE with "delivery failure 100% observed, criteria for UNSTABLE not
  met" is distinguishable from plain STABLE. Values are tagged with the
  assessment tick; a row older than the current assessment is shown as
  stale.
- The study strip's four-state view is unchanged.

## 8. Validation

- Normal (rules, seed 1, 300 and 2800 ticks): event stream hash equal before
  and after; DK-RMM state counts before and after reported side by side.
- M-S-DROP (rules, seed 11, 2800): attempted vs delivered per window,
  failure rate 1.0 from the first window after 400, backlog growth > 0 then
  0 at the dock cap, throughput 0, resource saturation (dock 1.0), the
  assessment sequence and the first tick of DEVIATING / UNSTABLE / RCT if
  reached.
- M-S-DELAY (rules, seed 11, 2800): late messages counted with `late_by ==
  10`, no drops, the failure rate equal to the routing share of traffic,
  latency p95 and tail deviation.
- Tests: section 9 of the task brief, one test per item, in
  `tests/test_dkrmm_operational.py`; `tests/test_dkrmm_math.py` updated only
  where a formula changed (severity, propagation), each change documented in
  `docs/dkrmm-mathematics.md`.
