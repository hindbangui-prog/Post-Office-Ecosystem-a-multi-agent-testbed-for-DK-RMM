# DK-RMM

DK-RMM, the Dragon-King Runtime Monitoring Model, is the independent runtime monitoring and
assessment layer. `post_office/dkrmm/` (`monitor.py`, `indicators.py`, `signals.py`,
`states.py`, `record.py`) is copied unchanged from the source, so its indicators, thresholds,
evidence kinds, state transitions and RCT criteria are the source's. It is attached from the
first run, and in this phase it observes and assesses only.

## Attaching and ticking

`DKRMM(eco).attach()` subscribes the monitor's `observe` to `eco.logger`; subscribing is its
only connection to the run. `observe` appends the event to the monitor's window and returns.
Whoever drives the run calls `monitor.tick()` after each `eco.step()`: `main.py`,
`tools/run_normal.py`, and `SimulationRunner._tick` under the API (the runner holds the monitor
beside the ecosystem, not inside it, and attaches a fresh one on every reset). `tick()` makes an
assessment every 20 ticks over a 60-tick window, comparing each of the twelve indicators with
its own baseline of the last 24 windows; an indicator two standard deviations or more off its
baseline is evidence. The evidence is grouped into six kinds (refusal, retry, congestion,
chatter, herding, spread), and the operational state is one of five: `STABLE`, `DEVIATING`,
`UNSTABLE`, `RCT`, `RECOVERY`. A window with fewer than 24 events is read as `STABLE` with the
stated reason that too little is happening to read collective behaviour.

Because the monitor is ticked by the driver outside the agents' tick work, a consultation can
neither observe nor be affected by an assessment in progress: the tick, consultations
included, is over before `monitor.tick()` runs.

## Observe and assess only

The monitor's only output is its `Assessment` history. The API serves it (`GET /dkrmm/state`,
`/dkrmm/series`, `/dkrmm/indicators`), the live page shows it in the DK-RMM pane, and
`tools/run_normal.py` writes it to `results/normal/s<seed>/dkrmm.json` (the final state and the
run record from `dkrmm.record.build_record`: state series, transitions, RCT events). Nothing
reads it back into prompts, messages, agent state, environment state or decisions, and there is
no intervention path. The copied monitor still has the source's person-only gate (a reading is
discovered, then validated or dismissed by a person); no route serves it in this phase, and
`tests/test_dkrmm.py` checks that `POST /dkrmm/validate`, `/activate` and `/dismiss` answer 404.

## How a consultation appears to it

The monitor sees a consultation as the `CONSULT_REQUEST`, `CONSULT_RESPONSE` and
`CONSULT_CLOSE` `message` events between two experts, the `consult_*` and `llm_call` agent
events, and the `decision`. No DK-RMM topic or indicator registration was needed, and none was
made: the three messages are ordinary expert messages, so `message_frequency`,
`interaction_density`, `agent_coupling` and `behavioural_similarity` count them exactly as they
counted the source's discussion messages.

The model layer's own agent events (`consult_opened`, `consult_question`,
`consult_delegation`, `consult_response`, `consult_refused`, `consult_closed` and one
`llm_call` per model call) are agent events like any other, so they also enter the monitor's
window and its actor profiles, and they move indicator values. A 400-tick probe on the fake
Ollama (seed 1, `PYTHONHASHSEED=0`, `normal_config()`, every expert on the model, the owner
asking its peer and deciding on its first allowed answer) fed one monitor the whole stream and
a second the same stream without those agent events: 19 of the 20 assessments differed, for
example at tick 381 `behavioural_similarity` 0.3046 against 0.3107 and the window's events 821
against 688 (at tick 21 `acting_agents` 13 against 11 and `propagation_across_agents` 0.0769
against 0.0909 too), while the DK-RMM states were identical in all 20. DK-RMM's code is not
changed in this phase. Whether the model layer's bookkeeping events should count as agent
behaviour for the indicators, or be left out of the monitor's window, is a design question for
the researcher, recorded in [limitations.md](limitations.md).

The delegation semantics were verified in the source's `dkrmm/indicators.py`, in the branch
that counts `message` and `subagent_message` events. `delegation_frequency` counts messages
whose receiver is a sub-agent (expert to sub-agent, work handed down the hierarchy), and
`tool_call_frequency` counts messages whose sender is a sub-agent (the answer coming back up).
Neither counts expert-to-expert traffic. Prototype II keeps that meaning unchanged: a
`CONSULT_REQUEST` with `interaction_type = "delegation"` is a message between two experts, so it
contributes to `message_frequency` and coupling and never to `delegation_frequency`. The
question/delegation distinction lives in the message content and the `consult_*` events, for
the UI and the analysis, not in the indicator.

`tests/test_dkrmm_receives_consultations.py` attaches the monitor as a run does, runs one
consultation on the fake Ollama for each interaction type, and asserts that the monitor's
window holds the three `CONSULT_*` messages in order between SCHEDULING and ROUTING with the
request's `interaction_type`, and the one `decision` carrying the consultation id; that
`assess()` runs over it; and that the consultation's own rows count as three messages, zero
delegations and zero tool calls, adding three messages and no delegation to the window.

## Stamping is metadata

Every event now carries `interaction_type` and `channel`, the runtime communication taxonomy's
labels ([events.md](events.md)), and the bus's carried messages carry `in_reply_to` in their
detail. The monitor reads `topic`, `actor`, `target` and `detail` and never the two stamped
slots, so the labels are metadata to it. `tests/test_dkrmm_stamping_invariance.py` proves it
on the run rather than by inspection: the same seeded ecosystem (seed 1, `normal_config()`,
300 ticks) is built twice with DK-RMM attached and ticked after every step, once with the
classifier in `events.py` replaced by a stub that stamps empty strings and once normally, and
the test asserts equality of `monitor.state()`, the run record's `indicator_series`,
`z_series`, `count_series`, `state_series`, `transitions` and `rct_events`, the logger's total
and its per-topic counts, after checking that the stubbed run's stamps are all empty and the
normal run's are not. DK-RMM's code is unchanged by the taxonomy.

## Independence

DK-RMM consumes the event stream and nothing else. It does not import CrewAI, `CrewBrain`,
agent objects, the consultation service or the Ollama settings; `crew/` and `agents/` do not
import `dkrmm`; and no prompt, tool or context mentions its state.
`tests/test_dkrmm_independence.py` holds this two ways: importing every `post_office.dkrmm`
module in a fresh interpreter leaves `crewai` and the model layer out of `sys.modules`, and a
static scan of the imports of every module under `post_office/crew/` and `post_office/agents/`
finds no `dkrmm`. The rules-only alignment test ([alignment-baseline.md](alignment-baseline.md))
additionally pins DK-RMM's readings, states and RCT ticks to the source's on four recorded runs.
