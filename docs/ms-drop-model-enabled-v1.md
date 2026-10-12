# M-S-DROP with the model enabled: what the LLM agents do when every message is dropped

This report completes the M-S-DROP study for model-enabled runs. It answers one question: when
CrewAI and the local model (qwen3:8b on Ollama) are enabled, what happens to the agents'
decisions once every message is dropped from tick 400? The question is answered from runs that
actually executed, and every number below is read from their files.

**Correction.** The first M-S-DROP schema (`docs/img/ms-drop-crewai.svg`, kept unchanged) said
that no model-enabled M-S-DROP run existed and that experts "still decide" after tick 400. Both
statements are wrong:

- **The runs exist.** All five model-enabled runs had been made on your machine on 2026-10-12
  (05:42 to 06:47 UTC) into `results/collapse_scenarios/MS-DROP/`, but they had never been
  analysed.
- **After tick 400 the experts almost stop deciding.** They make 0 to 6 decisions per run, all
  answered by the rule, and never consult the model.

The corrected schema is `docs/img/ms-drop-crewai-v2.svg`.

## 1. Sources

| Label | What | Where | How it was made |
|---|---|---|---|
| model-enabled | M-S-DROP, seeds 11 to 15, 2800 ticks, model mode | `results/collapse_scenarios/MS-DROP/s11` to `s15` (your machine) | `tools/run_collapse_scenarios.py` in model mode (`done.json` and `verify.json` say `"mode": "model"`), classified by `--analyze` against `--control-from results/c2_near_system_override` (`results/collapse_scenarios/summary.json`) |
| matched no-drop control | Normal, the same seeds and ticks, model mode | `results/c2_near_system_override/N/s11` to `s15` (your machine) | the C2-NEAR driver, condition N; the same configuration as the model-enabled runs (the `simulation_started` events differ only in the run name) |
| rules-only | M-S-DROP, seeds 11 to 15, 2800 ticks, `--rules` | `results/m_s_drop_crewai/rules_only/MS-DROP/` | rerun on 2026-10-12 with the current code; each event stream is identical to the original rules-only campaign's (hashes in section 9), so the earlier rules-only figures stand |
| analysis | every table below | `results/m_s_drop_crewai/analysis/analysis.json` and `analysis.md` | `tools/analyze_ms_drop_model.py` (section 8) |

The model settings are those recorded in every model-enabled `verify.json`: model `qwen3:8b`,
digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`, `http://localhost:11434`,
temperature 0.0, seed 42, `max_tokens` 512, thinking off, consult deadline 300 s, timeout 120 s.
Every model request in these runs was served by that model, as the per-seed counts of
`served_by_configured_model` show (149, 168, 153, 147 and 120 calls), with no other model serving.

The scenario fingerprint in the runs (`7df72940…`) is the current one. The runs were made with the
code of 2026-10-11 and 2026-10-12. Since then only DK-RMM, the user interface, the API and one
validation tool have changed; the simulation, agents, bus, CrewAI layer and fault code are byte for
byte the same. So everything in this report about agents, messages and operations holds for today's
code. The DK-RMM readings on the model-enabled runs are the exception: they come from the monitor as
it was before the extension of 2026-10-12 (section 7).

## 2. The pathways, as verified

**Rule first, then the model.**
1. An agent calls `BaseAgent.decide`, and the Python rule answers first.
2. When the rule records a trigger (its "insufficient" condition), the decision is eligible for
   the model.
3. With `consult_policy` "insufficient", every eligible decision went to the model. Eligible and
   consulted are equal in every model-enabled run: 697 of 697 before the fault.
4. CrewAI runs the owner agent, which may make one tool call to a peer.
5. The owner's `DECISION:` line is parsed, and the policy gate (`_validate`) checks the answer.
6. A `decision` event records who answered (`status`: `deterministic`, `llm_accepted` or
   `llm_rejected`) and the gate's verdict (`validation`).

**Where decisions come from.** The decisions that can reach the model are made inside message
handlers:
- SCHEDULING's `choose_next_task` and `choose_robot` run in `_sub_result`, on SUB-QUEUE's or
  SUB-ASSIGNMENT's delivered answer (`agents/scheduling_agent.py:736` onwards).
- ROUTING's `resolve_block` runs in `_sub_result`, on SUB-COLLISION's answer to a robot's report
  (`agents/routing_agent.py:270` onwards).
- INTAKE's `accept_parcel` runs in `_sub_result`, on its sub-agents' answers about a parcel that
  PLANNER handed it by TASK_ASSIGNMENT (`agents/intake_agent.py:212` onwards). That is two
  delivered messages.

The agents keep asking on their own clock. SCHEDULING asks SUB-QUEUE each tick it has room (in
`tick_work`), and robots report to ROUTING. But the answers that open a decision never arrive. A
decision the model could answer therefore needs at least one delivered message first.

**CrewAI and the bus.** A consultation runs inside the tick, in-process:
- the owner and peer are CrewAI agents in one thread;
- the peer is reached through a CrewAI tool;
- the model is reached over local HTTP (`/v1/chat/completions`), not over the bus.

The bus only receives record copies (CONSULT_REQUEST, CONSULT_RESPONSE, CONSULT_CLOSE) after the
fact. The evidence comes from the runs. All 20 peer exchanges in the five model-enabled runs, and
all 24 before tick 400 in the controls, have their response in the same tick as the question (tick
gap 0). The bus cannot deliver anything in less than one tick. Before the fault, each record copy
was delivered at the next tick.

**From decision to effect.** A decision takes effect in one of two ways:
- **A direct write to the shared state.** For example, SCHEDULING writes `task_assigned` in the
  task registry when it picks a robot.
- **A message.** For example, a ROUTE_REQUEST, a RESOURCE_REQUEST or a ROBOT_COMMAND.

A robot acts only on a ROBOT_COMMAND it has received. It then writes `command_<operation>` inside
`RobotAgent.handle` (`agents/robot_agent.py:144`), after carrying the command out. The analysis
counts these stages separately:
- model call;
- model answer parsed and accepted by the gate;
- message sent;
- message delivered or dropped (matched by message id);
- command applied (the robot's `command_*` event).

## 3. Commands

How your model-enabled runs and their classification were made (as recorded in
`results/collapse_scenarios/summary.json`, `out` and `control_from`):

```
$env:PYTHONHASHSEED = "0"
python tools/run_collapse_scenarios.py --scenario all --seeds 11 12 13 14 15 --ticks 2800 --control-from results/c2_near_system_override
python tools/run_collapse_scenarios.py --analyze --control-from results/c2_near_system_override
```

How this report's analysis was made (from the repository root, with the rules-only runs under
`results/m_s_drop_crewai/rules_only/`):

```
python tools/analyze_ms_drop_model.py --model results/collapse_scenarios/MS-DROP --model-summary results/collapse_scenarios/summary.json --rules results/m_s_drop_crewai/rules_only/MS-DROP --rules-summary results/m_s_drop_crewai/rules_only/summary.json --control results/c2_near_system_override/N --out results/m_s_drop_crewai/analysis
```

How the rules-only runs were regenerated:

```
python tools/run_collapse_scenarios.py --scenario ms-drop --rules --seeds 11 12 13 14 15 --ticks 2800 --out <dir>
```

## 4. Results for the five model-enabled runs

### 4.1 Decisions and model calls

"Pre" is ticks 0 to 399, "post" tick 400 to the end.

| Seed | decisions pre | eligible pre | consulted pre (share) | model calls pre (ok / failed) | peer calls | latency mean / median / max (ms) | model answer accepted | model answer refused by gate | no valid decision | decisions post | eligible post | consulted post | model calls post |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 11 | 923 | 141 | 141 (1.0) | 149 (149 / 0) | 4 | 468 / 297 / 11123 | 132 | 9 | 0 | 1 | 0 | 0 | 0 |
| 12 | 870 | 156 | 156 (1.0) | 168 (168 / 0) | 6 | 440 / 294 / 2808 | 139 | 17 | 0 | 0 | 0 | 0 | 0 |
| 13 | 837 | 143 | 143 (1.0) | 153 (153 / 0) | 5 | 444 / 298 / 3982 | 123 | 20 | 0 | 2 | 0 | 0 | 0 |
| 14 | 886 | 141 | 141 (1.0) | 147 (147 / 0) | 3 | 395 / 307 / 3001 | 135 | 5 | 1 | 6 | 0 | 0 | 0 |
| 15 | 730 | 116 | 116 (1.0) | 120 (120 / 0) | 2 | 399 / 301 / 3999 | 105 | 11 | 0 | 0 | 0 | 0 | 0 |

Over the five runs, 737 model calls were made, all before tick 400, and every one returned HTTP
200 without an error. There were no retries: no consultation made more owner calls than the
expected one, or two after a peer exchange, which is consistent with `max_retry_limit=0` in
`crew/roles.py`.

Of 697 consultations, 696 closed `decided` and one (seed 14, tick 151) closed
`no_valid_decision`. That decision was recorded as `llm_failed` and fell back to the rule's
answer. 62 model answers were refused by the gate at the `state` stage
and replaced by the rule's answer. The gate refused no model answer at the `policy` or `schema`
stage.

By agent, summed over the five runs before the fault:

| Agent | decisions | by rule | eligible | model calls | model answers accepted | refused by gate (rule / model) |
|---|---:|---:|---:|---:|---:|---|
| SCHEDULING | 1139 | 671 | 468 | 488 | 405 | 403 / 62 |
| ROUTING | 909 | 683 | 226 | 246 | 226 | 0 / 0 |
| INTAKE | 125 | 122 | 3 | 3 | 3 | 0 / 0 |
| PLANNER, RESOURCE, SORTING, DISPATCH | 2073 | 2073 | 0 | 0 | 0 | 0 / 0 |

After tick 400 the model-enabled runs made 9 decisions in total: 1, 0, 2, 6 and 0 per seed, all by
rule. None was eligible, and there was no consultation and no model call. The matched no-drop
control shows what the same seeds do after tick 400 when messages are delivered:

| Seed | control consultations after 400 | control model calls after 400 | control model answers accepted after 400 |
|---|---:|---:|---:|
| 11 | 284 | 328 | 273 |
| 12 | 295 | 339 | 288 |
| 13 | 217 | 255 | 214 |
| 14 | 265 | 301 | 251 |
| 15 | 234 | 294 | 229 |

So the drop takes the model's consultation rate after tick 400 from 1295 consultations (1517 model
calls) over the five control runs to zero.

### 4.2 Messages, commands and operations after the fault

| Seed | messages sent post | dropped post | delivered post | pending at end | robot commands sent / dropped / applied post | tasks started post | last robot command applied | last parcel out | first arrival refused after 400 | backlog at end |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|
| 11 | 798 | 796 | 0 | 2 | 0 / 0 / 0 | 0 | 391 | 583 | 1418 | 36 |
| 12 | 2247 | 2245 | 0 | 2 | 2 / 2 / 0 | 0 | 383 | 583 | 1318 | 32 |
| 13 | 2242 | 2240 | 0 | 2 | 2 / 2 / 0 | 0 | 399 | 625 | 1323 | 32 |
| 14 | 2244 | 2241 | 0 | 3 | 2 / 2 / 0 | 0 | 394 | 625 | 1348 | 34 |
| 15 | 2247 | 2244 | 0 | 3 | 2 / 2 / 0 | 0 | 399 | 583 | 1615 | 30 |

"Pending at end" means sent on the last tick, so the drop that would come at the next delivery
never happened. Over the five runs, the messages sent after the fault were:

| Message type | Count |
|---|---:|
| ROBOT_REPORT (robots reporting to ROUTING every tick) | 6403 |
| SUBTASK_REQUEST (SCHEDULING and RESOURCE asking their sub-agents) | 2615 |
| STATUS_REPORT (PLANNER to SUPERVISOR) | 605 |
| TASK_ASSIGNMENT (PLANNER to INTAKE) | 130 |
| TASK_COMPLETED | 13 |
| ROBOT_COMMAND (park orders) | 8 |
| RESOURCE_REQUEST | 4 |

None was delivered. The parcels that left after tick 400 (7, 9, 8, 9 and 8 per seed) were parcels
already at the dispatch door: vans leave on the timetable, outside the bus. No task was started
after the fault in any model-enabled run.

The stages, by phase, over the five runs:

| Stage | before tick 400 | from tick 400 |
|---|---:|---:|
| model calls | 737 | 0 |
| model answers accepted by the gate | 634 | 0 |
| messages sent after those decisions | 702 | 0 |
| ... of which delivered | 699 | 0 |
| ... of which dropped | 3 (all from one decision at tick 399, section 6) | 0 |
| model decisions followed by a robot command applied with the same correlation id | 298 | 0 |

The message attribution in the third row is by position in the log: the messages the deciding
agent sent in the same tick, after its decision and before its next one. The log has no explicit
link between a decision and a message.

## 5. Rules-only against model-enabled, per seed

Each cell is rules-only / model-enabled. Both are M-S-DROP, the same seed, 2800 ticks, the fault
at tick 400, and the collapse criterion unchanged (`COLLAPSE` in `stress/collapse.py`; each mode
is classified against the N control of its own mode).

| Measurement | s11 | s12 | s13 | s14 | s15 |
|---|---|---|---|---|---|
| model calls (pre / post) | n/a / 149, 0 | n/a / 168, 0 | n/a / 153, 0 | n/a / 147, 0 | n/a / 120, 0 |
| decisions eligible for the model (pre / post) | 146, 0 / 141, 0 | 132, 0 / 156, 0 | 150, 0 / 143, 0 | 117, 0 / 141, 0 | 119, 0 / 116, 0 |
| successful model responses | n/a / 149 | n/a / 168 | n/a / 153 | n/a / 147 | n/a / 120 |
| gate refusals, all (rule answers; model answers) | 78 (78; n/a) / 105 (96; 9) | 94 (94; n/a) / 91 (74; 17) | 83 (83; n/a) / 87 (67; 20) | 99 (99; n/a) / 110 (105; 5) | 76 (76; n/a) / 72 (61; 11) |
| decisions after the fault | 2401 / 1 | 0 / 0 | 11 / 2 | 0 / 6 | 0 / 0 |
| messages attempted after the fault | 2956 / 798 | 2974 / 2247 | 2240 / 2242 | 1519 / 2244 | 1527 / 2247 |
| messages dropped (the fault's own counter) | 2960 / 803 | 2974 / 2251 | 2242 / 2245 | 1523 / 2244 | 1531 / 2251 |
| parcels dispatched | 13 / 15 | 14 / 14 | 13 / 15 | 15 / 18 | 14 / 17 |
| backlog at end | 31 / 36 | 32 / 32 | 32 / 32 | 32 / 34 | 33 / 30 |
| arrivals refused | 48 / 41 | 41 / 41 | 35 / 33 | 43 / 38 | 31 / 31 |
| collapse outcome / tick | COLLAPSED 722 / COLLAPSED 722 | COLLAPSED 708 / COLLAPSED 791 | COLLAPSED 666 / COLLAPSED 666 | COLLAPSED 666 / COLLAPSED 708 | COLLAPSED 698 / COLLAPSED 750 |
| critical stop tick | 983 / 983 | 941 / 983 | 941 / 1025 | 983 / 1025 | 983 / 983 |

Rules-only seed 11's 2401 decisions after the fault are PLANNER's `release_work`, answered by the
rule once a tick from 400 to 2800. That loop does not occur in the model-enabled seed 11, whose
facility stood in a different state at tick 400.

**Observed:**
- Both modes collapse in every seed, under the same criterion.
- The model-enabled runs collapse at the same tick or later: 0, +83, 0, +42 and +52 ticks.
- They dispatch the same number of parcels or 1 to 3 more.
- After the fault, both modes send messages that are all dropped, and both make almost no
  decisions.
- The model-enabled runs make no model call after the fault, so after tick 400 the two modes run
  the same Python code.

**Not established:** these runs do not show that the model caused the later collapse or the extra
parcels.
- The model-enabled and rules-only runs differ from the first consultation onwards, because the
  model answered differently from the rule, so their facilities enter tick 400 in different
  states.
- The model's own output also varies from run to run on the same prompts, even at temperature 0
  with a fixed seed. Model run and control share configuration and seed, yet first differ at tick
  107, 21, 59, 138 and 17 (seed 11 to 15). That difference is in the text of a peer's answer, in a
  token count, or (seed 15, tick 17) in the choice itself.

A difference between modes after the fault is therefore a difference between two starting states.
It is not an effect of the model acting during the fault, because the model did not act during the
fault.

## 6. Does a model decision have any effect once its messages are dropped?

**In the five model-enabled runs, the situation does not arise after tick 400.** No model call is
made, because no decision the model could answer is reached once nothing is delivered.

**The case that is closest happens on the last tick before the fault.** Model-enabled seed 15,
tick 399:
1. SCHEDULING's `choose_robot` for task T-0121 was eligible (`contention`) and consulted the model
   (CSL-0116, 361 ms). The model answered R5, and the gate accepted it (`validation` ok).
2. SCHEDULING wrote the assignment into the task registry (`task_assigned` T-0121 to R5) and sent
   ROUTE_REQUEST to ROUTING and RESOURCE_REQUEST to RESOURCE. Both were dropped at tick 400.
3. No ROBOT_COMMAND for T-0121 was ever sent or applied. R5's only events after that tick are
   battery reports.
4. At tick 430 SCHEDULING released the task: `task_released`, "no answer in 31 ticks at stage
   routing", status back to CREATED.

The decision's only effect was a 31-tick reservation in the task registry, which was then undone.
It moved no robot and no parcel.

The tick before, in the same run, shows the other side. At tick 398 ROUTING's `resolve_block`
consulted the model (CSL-0115, 292 ms), which answered REROUTE. The `set_route` command was
delivered, and R3 applied it at tick 399 (`command_set_route`).

So a model decision has an operational effect when the message that carries it is delivered, and
none beyond a registry entry when it is dropped. Under M-S-DROP the second kind is limited to
decisions made on tick 399, because from tick 400 nothing reaches the agents that would let them
decide.

## 7. DK-RMM

DK-RMM stayed observational in every run. It subscribes to the event log and reads state; it sends
nothing and writes nothing. The Normal event streams are identical with and without it (checked in
the DK-RMM extension's validation), and here the rules-only event streams are identical between
runs whose monitor differed (section 9). It does not restore communication or change a decision.

**The model-enabled runs' DK-RMM readings come from the monitor as it was before the 2026-10-12
extension.** That monitor has no communication failure rate, backlog or throughput indicator. After
the fault it read mostly STABLE, and never RCT:

| Seed | windows from 400 (of 120): STABLE / DEVIATING / UNSTABLE / RECOVERY / RCT | first DEVIATING / UNSTABLE after 400 | final |
|---|---|---|---|
| 11 | 92 / 11 / 9 / 8 / 0 | 461 / 521 | STABLE |
| 12 | 78 / 12 / 20 / 10 / 0 | 441 / 481 | DEVIATING |
| 13 | 65 / 26 / 12 / 17 / 0 | 461 / 501 | DEVIATING |
| 14 | 67 / 23 / 17 / 13 / 0 | 461 / 481 | STABLE |
| 15 | 74 / 19 / 15 / 12 / 0 | 461 / 481 | STABLE |

**The extended monitor on the rules-only runs.** These event streams are identical to the original
rules-only ones. The communication failure rate reaches 1.0 at tick 461 in every seed, and from
tick 400:

| Seed | windows from 400: DEVIATING / UNSTABLE / RCT | first DEVIATING / UNSTABLE / RCT | final |
|---|---|---|---|
| 11 | 1 / 91 / 28 | 401 / 421 / 461 | UNSTABLE |
| 12 | 3 / 97 / 20 | 401 / 601 / 461 | RCT |
| 13 | 3 / 114 / 3 | 401 / 461 / 2421 | UNSTABLE |
| 14 | 3 / 117 / 0 | 401 / 461 / none | UNSTABLE |
| 15 | 3 / 96 / 21 | 401 / 461 / 481 | RCT |

The extended monitor's readings on the model-enabled runs are not available, because those runs
were made before the extension. Section 10 gives the command that produces them.

## 8. Tests and checks

| Check | Result |
|---|---|
| `tests/test_ms_drop_model_analysis.py`: 10 tests on a hand-built run. Rule versus model decisions, eligibility share, model calls counted from `llm_call` events only, same-tick peer exchange, drops matched by message id in the sending phase, robot commands sent, dropped and applied kept apart, decision chains, operations, DK-RMM reading, refusal to overwrite or to write into `results/normal` | 10 passed |
| Drop activates at 400 and holds: `stress_fault_activated` at tick 400 and `message_dropped` from 400 to 2798..2800 in all ten M-S-DROP runs; zero messages delivered after the fault, and zero late deliveries | holds in all ten |
| Rules-only results unchanged: the regenerated rules-only event streams are identical to the original campaign's (excluding wall clock and run id): s11 `f322558a730bab00`, s12 `5f415a6a3557b190`, s13 `41621841d9013310`, s14 `7a6bc93762b8caff`, s15 `f5845f15e23d723e` | identical |
| Model calls come from the runtime: every count comes from `llm_call` events, and they agree with the drivers' own served-model counts in `verify.json` (149, 168, 153, 147, 120) | agree |
| The whole suite without the three browser files, which includes the collapse-scenario tests (fault at 400, held to the end, no restoration path) and the Normal guards and alignment tests (the Normal scenario unchanged). The browser files were not rerun: nothing in the page changed in this work. | 1021 passed, 5 skipped |

## 9. What is not available, and why

- **The extended DK-RMM monitor on the model-enabled runs.** The runs predate the extension, and
  the monitor reads the live state at each assessment (backlog, saturation), so it cannot be
  replayed faithfully from the log. A rerun is needed (section 10).
- **Intake, sorting, storage and dispatch backlogs by zone.** The saved run files record only the
  total backlog per tick (`series.csv`). A rerun under the current code records the by-zone
  backlog of the last assessment in `dkrmm.json` (`state.current.snapshot.by_zone`).
- **An exact counterfactual.** The model's answers are not reproducible run to run (section 5), so
  model run and control diverge before the fault in every seed. The control shows what the
  facility does without the drop. It does not show what the same run would have done.
- **Model consultation under the drop.** It cannot be measured in these runs, because there was
  none. Whether a model decision whose ROBOT_COMMAND is dropped has any effect is therefore shown
  only by the tick-399 case in seed 15, where the dropped messages were a route and a resource
  request rather than a robot command.

## 10. To complete the DK-RMM readings

Run on your machine, with Ollama serving qwen3:8b. This writes a separate results directory and
does not touch any existing run (the driver never overwrites a run directory):

```
$env:PYTHONHASHSEED = "0"
python tools/run_collapse_scenarios.py --scenario ms-drop --seeds 11 12 13 14 15 --ticks 2800 --out results/m_s_drop_crewai/model_rerun --control-from results/c2_near_system_override
python tools/run_collapse_scenarios.py --analyze --out results/m_s_drop_crewai/model_rerun --control-from results/c2_near_system_override
python tools/analyze_ms_drop_model.py --model results/m_s_drop_crewai/model_rerun/MS-DROP --model-summary results/m_s_drop_crewai/model_rerun/summary.json --rules results/m_s_drop_crewai/rules_only/MS-DROP --rules-summary results/m_s_drop_crewai/rules_only/summary.json --control results/c2_near_system_override/N --out results/m_s_drop_crewai/analysis_rerun
```

The earlier model-enabled runs took between 53 and 81 seconds each on your machine, judging by
the file times in their directories.
