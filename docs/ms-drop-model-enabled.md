# M-S-DROP with the model enabled, run through the live page

Version 2 (2026-10-12). Version 1 of this report, which analysed the five model-enabled runs made
earlier by `tools/run_collapse_scenarios.py`, is kept unchanged as
[`ms-drop-model-enabled-v1.md`](ms-drop-model-enabled-v1.md). Nothing in it is withdrawn. This version
adds the live-page experiment and the four measurements version 1 could not make:

- the decision-to-action pathway, linked by identifiers;
- the backlog per zone, per tick;
- every DK-RMM reading of the current monitor, as it was made;
- a run that stops by itself at tick 2800 and is kept on disk.

**Status of the model-enabled live runs: not yet run.** The live page can now run, record and show
them (section 4). They have to run on your machine, where Ollama serves qwen3:8b, and none had been
kept when this version was written. Every model-enabled cell in this report is marked *pending*.
None is estimated. Section 5 gives the rules-only M-S-DROP and its no-drop control, run through the
same page. Section 9 lists what is still missing.

## 1. What the existing page and backend already did, and what they lacked

Inspected before any change (`post_office/api/runner.py`, `api/server.py`, `ui/live.html`,
`ui/live.py`, `communication/bus.py`, `communication/events.py`, `observability/run_record.py`,
`stress/collapse_scenarios.py`, `stress/measure.py`, `main.py`):

| Question | Finding |
|---|---|
| How a run is started and watched | `python main.py --api` serves the page. The page's **scenario** selector, the study strip's **seed** selector (11 to 15) and **Start**, **Reset** and **speed** drive `POST /simulation/reset` and `/simulation/start`. The page polls `/summary`, `/frame`, `/consultations`, `/llm/calls` and `/dkrmm/*`, and takes every event from `WS /ws`. |
| Seed, model and M-S-DROP | The `ms-drop` preset exists. Choosing it rebuilds the run on seed 11, and any seed can be picked on the strip. Mode is fixed at server start: model by default, `--rules` for rules-only. In model mode `require_model` checks the model first, and again at every reset. |
| Live or precomputed | Live. Every figure comes from the runner's published frame after each tick. Nothing is precomputed. |
| Fault at 400 | `CollapseFaults.before_tick(world.tick + 1)` runs inside the step lock, just before `eco.step()`, exactly as in the driver. At tick 400 it installs `DropAll` as the bus's `delay_rule` and logs `stress_fault_activated`. Nothing removes the rule. |
| Why no consultation after 400 | Every decision the model can answer is taken in a message handler (`_sub_result` of SCHEDULING, ROUTING and INTAKE). It runs only when a sub-agent's reply is delivered. From tick 400 no message is delivered, so no such decision is reached. Measured again below: 0 eligible decisions after the fault in every M-S-DROP run. |
| What was missing | A run did not stop at 2800 (it ticked until paused). Nothing kept the run's events, series, per-zone backlog or DK-RMM readings per run: `RunRecorder` wrote only DK-RMM's record and the RCTs, to `results/live`. The page could not link a decision to the messages, deliveries and robot commands that followed it. On-time delivery logs no event at all: the bus logs a send, a drop and a late delivery, never an on-time arrival. |

## 2. What was added (opt-in; Normal unchanged)

| File | What it adds |
|---|---|
| `main.py` | `--experiment-dir PATH` and `--stop-at N` (with `--api`). `--experiment-dir` needs `--stop-at` and is refused under `results/normal`. Without them nothing changes. |
| `post_office/api/runner.py` | `stop_at`: the run stops itself at that tick, under the step lock, and a Start after that does not tick. `experiment_dir`: at a run's first Start (tick 0) on a collapse preset or its N control (`c2near-n`, `default`), an `ExperimentRecorder` keeps the run. A pause keeps it `incomplete`, a reset or server stop closes it `incomplete`, a crash closes it `failed`, and the stop tick closes it `complete`. A zone series and a decision tracer are kept beside every run, for the page. |
| `post_office/observability/experiment.py` | The run directory `<root>/<scenario>/s<seed>/`, in the driver's layout (`definition.json`, `events.jsonl`, `series.csv`, `measurement.json`, `dkrmm.json`, `summary.json`, `verify.json` with the served-model check, `done.json` only when complete). Added beside them: `zone_backlog.csv`, `dkrmm_assessments.jsonl`, `decision_traces.jsonl`, `message_traces.jsonl`, `trace_summary.json` and `status.json`. An existing directory is never written into; a repeated run goes to `s<seed>-2`. |
| `post_office/observability/zone_backlog.py` | One row per tick: intake, sorting, storage, dispatch, carried (on a robot), other, total. Each parcel is counted once, by `current_zone`, and the six columns sum to `len(env.parcels)`. Also `loaded_on_van` (part of dispatch, not added to the sum) and the tick's arrivals, dock refusals, departures on a van, returns and refusals after arrival, read from the counters `generator.created`, `generator.refused`, `env.dispatched_count`, `env.returned_count` and `env.refused_count`. Each row is checked against the previous total plus arrivals minus the three ways out (`reconciled`). |
| `post_office/observability/decision_trace.py` | Decision and message traces, linked only by identifiers the run wrote (the module docstring lists each link and its basis): decision to consultation (`decision_id` = `call_id`), to the reply it answered (`content.operation`, subject, `in_reply_to`), to the messages and registry events it emitted (same agent, same tick, carrying its subject), to later robot commands on the same task id. Message to drop (`message_dropped.message_id`), to on-time receipt (the receiver taking it from its inbox), to late receipt (`agent_message_received`) and to replies (`in_reply_to`). ROBOT_COMMAND to the robot's `command_<operation>` (sender, robot, correlation id, the tick it was taken). Transport to the parcel's lift and drop (parcel id and robot id). |
| `post_office/communication/bus.py` | `watch_inbox`: read-only observers of `inbox()`. It is the only evidence of on-time delivery, since that logs no event. An empty list costs one `if`. |
| `post_office/api/server.py` | `GET /zones`, `GET /decision-traces`, and `/summary`'s `kept` (where the run is kept, its status and stop tick). |
| `post_office/ui/live.html`, `ui/live.py` | In the existing panes: the **Backlog by zone** chart in the DK-RMM pane (every tick, a dashed line at the fault), a **Decision → action** table under the consultations (eligibility, the model's consultation and calls, the gate, each message's delivery and the robot command applied), a **RUN KEPT** line on the study strip, and "kept" on the run line. No new page, pane or control. |
| `tools/analyze_live_ms_drop.py` | Reads kept run directories into `analysis.json` and `analysis.md`. It never overwrites. |
| `tools/zone_backlog_figure.py` | The per-seed zone figure (standard library only). |

Nothing emits an event. A run's event stream is the same with or without the new observers
(section 7).

## 3. Commands

On your machine, model-enabled (Ollama serving qwen3:8b):

```
python main.py --api --experiment-dir results/m_s_drop_crewai/live --stop-at 2800
```

In the page, for each condition and seed:

1. Choose the scenario: *M-S-DROP · all messages dropped from 400*, or *C2-NEAR · N control* for the no-drop control.
2. Choose the seed on the strip and set the speed to 512×.
3. Press **Start**.

The RUN KEPT line names the folder and shows `complete` at tick 2800.

Rules-only, the same way, with `--rules` and another root. This is how section 5 was produced, in
a headless Chromium driving the same page:

```
python main.py --api --rules --experiment-dir results/m_s_drop_crewai/live_rules --stop-at 2800
```

Analysis, figure and collapse classification:

```
python tools/analyze_live_ms_drop.py --condition rules=results/m_s_drop_crewai/live_rules --condition model=results/m_s_drop_crewai/live --out results/m_s_drop_crewai/live_analysis
python tools/zone_backlog_figure.py --run "model, M-S-DROP=results/m_s_drop_crewai/live/MS-DROP" --run "model, N control=results/m_s_drop_crewai/live/N" --title "Backlog by zone, model-enabled, run through the live page" --out docs/img/ms-drop-zone-backlog-model.svg
python tools/run_collapse_scenarios.py --analyze --out results/m_s_drop_crewai/live
```

## 4. The model-enabled live runs

*Pending.* Not run in the accessible environment; no model-enabled run has been kept under
`results/m_s_drop_crewai/live`. When the ten runs exist (MS-DROP and N, seeds 11 to 15), the
command in section 3 fills, per seed and phase:

- decisions, eligible, consulted, model accepted or rejected;
- model calls with the served model and failures, and latency;
- the four pathway message kinds by delivery;
- robot commands applied;
- the zone table;
- DK-RMM;
- the collapse verdict.

The model-enabled results available today are those of version 1, made by the driver with the
monitor as it was before the operational indicators.

## 5. Rules-only M-S-DROP and its control, run through the page

Ten runs, seeds 11 to 15, M-S-DROP and N (the `c2near-n` preset: the Normal configuration, no
fault), 2800 ticks, all `complete`. Kept in `results/m_s_drop_crewai/live_rules/`; the analysis is
`results/m_s_drop_crewai/live_rules_analysis/analysis.md`. The driver's own classification of these
directories (`tools/run_collapse_scenarios.py --analyze --out results/m_s_drop_crewai/live_rules`) is
`live_rules/summary.json` and agrees with section 5.4.

**Correction made during this work.** A first set of these ten runs could link a later robot
command to a decision through a parcel id. For example, seed 11's transport command for T-0115
was attached to SORTING's decision on its parcel. A later command now joins a decision only on a
task id: `content.task_id`, or a correlation id that the registry created as a task. A test checks
this. The ten runs were made again through the page with the corrected code. Their event streams
are identical to the first set's, and they replace it in `live_rules/`.

**The page runs the driver's experiment.** Each event stream equals the driver's run of the same
seed, excluding wall clock and run id (17,603 / 15,048 / 12,936 / 10,948 / 10,743 events for
M-S-DROP, 35,680 / 33,622 / 31,937 / 31,939 / 28,706 for N). Two lines differ: the stop reason, and
the driver's `collapse_scenario` marker at tick 0, which the page does not log. Every `series.csv`
column is equal except `events` in the tick-1 row, which counts that marker.

### 5.1 Decisions, and why the model would not be asked after the fault

| Seed | decisions before 400 | eligible before 400 | decisions from 400 | eligible from 400 |
|---|---|---|---|---|
| 11 | 930 | 146 | 2,401 (all PLANNER `release_work`) | 0 |
| 12 | 828 | 132 | 0 | 0 |
| 13 | 842 | 150 | 11 | 0 |
| 14 | 874 | 117 | 0 | 0 |
| 15 | 823 | 119 | 0 | 0 |

The no-drop control, from tick 400: 2,585 / 2,324 / 2,024 / 2,003 / 1,615 decisions, of which
401 / 360 / 385 / 333 / 278 are eligible. In model mode the eligible decisions are the ones that
consult (version 1: 697 of 697 before the fault).

### 5.2 The pathway messages, by delivery

Sent / received on time / dropped / pending at the end. Robot commands also show how many were
applied. Phases are split by the tick the message was sent. A message sent at tick 399 is
delivered or dropped at 400, so the "before" phase shows a few drops.

| Seed | phase | ROUTE_REQUEST | RESOURCE_REQUEST | TASK_ASSIGNMENT | ROBOT_COMMAND |
|---|---|---|---|---|---|
| 11 | before | 40 / 40 / 0 / 0 | 40 / 40 / 0 / 0 | 119 / 119 / 0 / 0 | 240 / 239 / 1 / 0, applied 239 |
| 11 | from 400 | 0 | 1 / 0 / 1 / 0 | 18 / 0 / 18 / 0 | 3 / 0 / 3 / 0, applied 0 |
| 12 | before | 50 / 50 / 0 / 0 | 50 / 50 / 0 / 0 | 124 / 124 / 0 / 0 | 198 / 198 / 0 / 0, applied 198 |
| 12 | from 400 | 0 | 2 / 0 / 2 / 0 | 26 / 0 / 26 / 0 | 3 / 0 / 3 / 0, applied 0 |
| 13 | before | 45 / 45 / 0 / 0 | 45 / 45 / 0 / 0 | 123 / 123 / 0 / 0 | 214 / 213 / 1 / 0, applied 213 |
| 13 | from 400 | 0 | 0 | 23 / 0 / 23 / 0 | 2 / 0 / 2 / 0, applied 0 |
| 14 | before | 51 / 51 / 0 / 0 | 51 / 51 / 0 / 0 | 141 / 140 / 1 / 0 | 191 / 191 / 0 / 0, applied 191 |
| 14 | from 400 | 0 | 2 / 0 / 2 / 0 | 20 / 0 / 20 / 0 | 2 / 0 / 2 / 0, applied 0 |
| 15 | before | 47 / 47 / 0 / 0 | 47 / 47 / 0 / 0 | 122 / 122 / 0 / 0 | 205 / 205 / 0 / 0, applied 205 |
| 15 | from 400 | 0 | 2 / 0 / 2 / 0 | 26 / 0 / 26 / 0 | 1 / 0 / 1 / 0, applied 0 |

In the control every robot command received was applied, with three exceptions: one each in N
seeds 11 and 14, and one sent on seed 15's last tick and still pending. Seeds 11 and 14 are
RESOURCE's `charge` commands that the robot declined in its report ("already on an errand"). The
trace records them as "taken, and no matching command event".

The last robot command applied was at tick 399, 389, 399, 399 and 397. The last van left at tick
583, 541, 541, 583 and 583, carrying parcels already loaded before the fault.

### 5.3 Backlog by zone

![Backlog by zone, rules-only](img/ms-drop-zone-backlog-rules.svg)

| Seed | tick | intake | sorting | storage | dispatch | on a robot | total |
|---|---|---|---|---|---|---|---|
| 11 | 399 | 8 | 2 | 1 | 6 | 2 | 19 |
| 11 | 2800 | 26 | 2 | 0 | 2 | 1 | 31 |
| 12 | 399 | 0 | 1 | 2 | 7 | 3 | 13 |
| 12 | 2800 | 26 | 2 | 2 | 1 | 1 | 32 |
| 13 | 399 | 5 | 2 | 1 | 6 | 2 | 16 |
| 13 | 2800 | 26 | 2 | 0 | 3 | 1 | 32 |
| 14 | 399 | 6 | 2 | 2 | 5 | 2 | 17 |
| 14 | 2800 | 26 | 0 | 3 | 2 | 1 | 32 |
| 15 | 399 | 0 | 2 | 3 | 6 | 2 | 13 |
| 15 | 2800 | 26 | 1 | 3 | 2 | 1 | 33 |

Only intake grows after the fault. The other zones freeze at what the last delivered commands
left. Intake reaches the dock's cap of 26 at tick 1132, 1306, 1215, 1149 and 1587. The first dock
refusal follows at tick 1195, 1318, 1248, 1196 and 1615, and refusals total 48, 41, 35, 43 and 31.
Arrivals from tick 400 are 18, 26, 22, 20 and 26. Departures on a van from tick 400 are 6, 7, 6,
5 and 6, all before tick 600.

The control at tick 2800 has 4, 7, 4, 6 and 6 parcels inside, never more than 2 at intake, and
no dock refusal. Every row of all ten runs reconciles.

### 5.4 Collapse (criterion unchanged, against N of the same seed)

| Seed | outcome | criterion | collapse tick | first degraded tick |
|---|---|---|---|---|
| 11 | COLLAPSED | sustained degradation + critical stop | 722 | 722 |
| 12 | COLLAPSED | sustained degradation + critical stop | 708 | 708 |
| 13 | COLLAPSED | sustained degradation + critical stop | 666 | 666 |
| 14 | COLLAPSED | sustained degradation + critical stop | 666 | 666 |
| 15 | COLLAPSED | sustained degradation + critical stop | 698 | 666 |

## 6. Decision to action: traces

Every decision of a kept run is one line of `decision_traces.jsonl`, and the same view is on the
page's Decision → action table. Each link names its basis (section 2). Summed over the five
rules-only seeds:

| Stage | M-S-DROP before 400 | M-S-DROP from 400 | N control before 400 | N control from 400 |
|---|---|---|---|---|
| decisions | 4,297 | 2,412 | 4,297 | 10,551 |
| answering a reply taken that tick (request identified) | 1,849 | 0 | 1,849 | 6,534 |
| eligible for the model (rule recorded a trigger) | 664 | 0 | 664 | 1,757 |
| consulted (rules-only: never) | 0 | 0 | 0 | 0 |
| refused by the gate (`policy` or `state`), rule used again | 430 | 0 | 430 | 443 |
| decisions that sent a message carrying their subject | 1,656 | 0 | 1,656 | 5,905 |
| those messages / received on time | 1,909 / 1,907 | 0 | 1,909 / 1,909 | 6,762 / 6,762 |
| robot commands among them / applied | 486 / 485 | 0 | 486 / 486 | 2,038 / 2,038 |
| later robot commands on the same task / applied | 572 / 560 | 0 | 569 / 569 | 1,873 / 1,873 |

Before 400 the two conditions are the same run, so their first columns agree except where a later
link crosses the fault. From 400 on, the M-S-DROP decisions are all PLANNER's `release_work`
(2,401 in seed 11 and 11 in seed 13, none in the other seeds). It needs no reply, is never
eligible, and sends nothing that carries its subject.

Three traces from seed 11, as the files record them:

1. **A decision whose effect reached a robot.** Tick 382, SCHEDULING `choose_robot` for T-0115:
   - It answers SUB-ASSIGNMENT's reply M-002736 (to request M-002724); T-0115 was assigned by
     M-002598.
   - The rule's first pick was refused by the gate (`state`: R3 was delivering), and the rule chose
     again, R3.
   - Registry: `task_assigned` R3. ROUTE_REQUEST M-002740 and RESOURCE_REQUEST M-002741 were both
     received at 383 and answered by ROUTE_RESPONSE M-002761 and RESOURCE_GRANT M-002764 at 385.
   - Then, on the same task id: `task_started` at 386, and transport command M-002769 sent at 386,
     received by R3 at 387 and applied (`command_transport`) at 387.
2. **A decision whose effect landed just before the fault.** Tick 398, ROUTING `resolve_block` for
   T-0115 (eligible: still blocked after 6 ticks; rule answer YIELD, gate ok). ROBOT_COMMAND
   M-002833 `yield` was received by R3 at 399 and applied (`command_yield`) at 399. The next
   command on T-0115, `set_route` M-002837 sent at 399, was dropped at 400. T-0115 was released at
   527, and the `abort` sent then (M-003006) was dropped at 528.
3. **A decision whose request never came back.** Tick 399, SCHEDULING `choose_next_task` chose
   T-0106 (eligible: conflict). Its SUBTASK_REQUEST M-002838 to SUB-ASSIGNMENT was dropped at 400,
   so the `choose_robot` that would answer it never happens.

The model-enabled traces (consultation, model calls and served model on each eligible decision)
are *pending* (section 4). The tests check the same fields on a fake-Ollama run.

## 7. DK-RMM

DK-RMM is the current monitor (operational indicators of 2026-10-12, `DKRMM_TREE_SHA` unchanged by
this work). Every reading is kept as it was made in `dkrmm_assessments.jsonl`: values, baselines,
z, evaluable, evidence and state. It observes only. Nothing in this work changes it.

| Seed | readings | from 400: STABLE / RECOVERY / DEVIATING / UNSTABLE / RCT | first DEVIATING / UNSTABLE / RCT from 400 | final |
|---|---|---|---|---|
| 11 | 140 | 0 / 0 / 1 / 91 / 28 | 401 / 421 / 461 | UNSTABLE |
| 12 | 140 | 0 / 0 / 3 / 97 / 20 | 401 / 601 / 461 | RCT |
| 13 | 140 | 0 / 0 / 3 / 114 / 3 | 401 / 461 / 2421 | UNSTABLE |
| 14 | 140 | 0 / 0 / 3 / 117 / 0 | 401 / 461 / none | UNSTABLE |
| 15 | 140 | 0 / 0 / 3 / 96 / 21 | 401 / 461 / 481 | RCT |

These are the same readings version 1 reported for the driver's rules-only runs, as expected from
identical event streams.

**Intake accumulating while DK-RMM reads STABLE.** Investigated against the readings themselves:

- **With the current monitor it does not happen under M-S-DROP.** From tick 400 no reading is
  STABLE or RECOVERY, in any seed (the study strip's four-state view paints RECOVERY green, so both
  were counted). The monitor reads DEVIATING from 401 and UNSTABLE or RCT after that.
- **It did happen in version 1's model-enabled runs.** Those were read by the monitor as it was
  before the operational indicators: STABLE in 92, 78, 65, 67 and 74 of 120 windows after the
  fault. That monitor had no communication failure rate, backlog or throughput indicator. Adding
  them was the fix, made earlier on 2026-10-12. The model-enabled live runs will show the current
  monitor's readings (section 4).
- **What drives the current readings is not the backlog.** In every one of the 120 post-fault
  readings of each seed the evidence includes the communication failure rate. Agent coupling and
  interaction density follow. `backlog_growth` is in evidence in 0, 3, 1, 0 and 0 readings.
- **Why the backlog indicator stays quiet.** By its documented definition (indicator 14 of
  `docs/dkrmm-operational-indicators.md`), it is the change in parcels inside per tick since the
  last reading, compared with its baseline. Intake fills slowly. The largest post-fault value is
  0.10, 0.10, 0.15, 0.10 and 0.10 parcels a tick (at most 3 parcels in a 20-tick window). The
  pre-fault readings already range from -0.15 to +0.10. The largest z after the fault is 1.79,
  2.10, 2.68, 1.81 and 1.92. What grows is the level, over about 40 windows, and the level is not
  an indicator. Each reading's snapshot does record it: `by_zone` shows INTAKE 26 at tick 2781 in
  every seed.

**Verdict: not a defect by the documented criteria, so no change was made.** The indicator
computes what its definition says. Catching a slow rise in level would need a new indicator or a
new rule, that is, a new formula. That is your decision and is listed as an open question in
section 9.

## 8. Tests and checks

| Check | Result |
|---|---|
| `tests/test_live_experiment.py`, 13 tests. Observers change no event. An inbox watcher sees every take and alters none. A runner without the options never stops and writes nothing. The stop tick ends a run, and Start does not tick past it. Pause gives incomplete; reset gives a new `-2` directory, never an overwrite. Non-experiment presets are not kept. The CLI guards (stop tick needed, `results/normal` refused). Zone rows sum, reconcile and agree with `series.csv`. Under M-S-DROP the fault fires at 400 and holds: every message sent from 400 to 449 is dropped and no robot command is applied after 400. Every trace link is backed by its identifiers. The trace summary splits at 400 with 0 eligible decisions after it. A fake-Ollama model run records mode, identity and served models, and its consulted decisions carry their model calls. The API reads `/zones`, `/decision-traces` and `/summary.kept`, and the page carries the new elements. | 13 passed |
| Whole suite, including the browser tests of the live page | SUITE_RESULT |
| Normal unchanged: the Normal run (seed 1, 2800 ticks, through the runner) at the previous commit `cd62474` and with this work | identical, 29,580 events, SHA-256 `5e07efbe…` |
| Live page against the driver: the ten rules-only runs | identical event streams (section 5) |
| Existing results untouched: nothing written outside `results/m_s_drop_crewai/live_rules/`, `live_rules_analysis/`, the results README, the new docs and the code; version 1 of the report and schemas v1 and v2 unchanged | checked |

## 9. Still missing

- **All model-enabled live measurements** (section 4). They need your machine and qwen3:8b. Until
  they exist, there are no model-enabled rows for traces, zone backlog or the current monitor's
  readings.
- **The intake-level question for DK-RMM** (section 7). Whether a slow rise in level should count as
  evidence is a design decision. Today's monitor has no indicator for it.
- **Robot command declined.** A robot that declines a command (`charge_declined`) reports it in a
  ROBOT_REPORT that carries no `in_reply_to`. The trace marks the command as taken and not applied,
  but cannot link the refusal itself to the command.
- **On-time delivery has no event.** The trace takes it from the inbox observer, so it exists only in
  runs made with this code, not in older event logs.
