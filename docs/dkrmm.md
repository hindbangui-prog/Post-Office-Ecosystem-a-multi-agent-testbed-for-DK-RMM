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
`/dkrmm/series`, `/dkrmm/indicators`, `/dkrmm/rcts`), the live page shows it in the DK-RMM pane,
the API server records it (see below), and `tools/run_normal.py` writes it to
`results/normal/s<seed>/dkrmm.json` (the final state and the run record from
`dkrmm.record.build_record`: state series, transitions, RCT events). Nothing reads it back into
prompts, messages, agent state, environment state or decisions, and there is no intervention
path.

## The gate

The copied monitor has the source's person-only gate: a reading is `DISCOVERED`, and a person
may validate it (`VALIDATED`), act on a validated one (`ACTIVE`), or dismiss it (`DISMISSED`,
kept, since a false positive is evidence about the model). The API serves it as in the source:
`POST /dkrmm/validate`, `/dkrmm/activate` and `/dkrmm/dismiss` take `{by, note}` (at most 80 and
500 characters) and call the monitor's existing `validate`, `activate` and `dismiss`, which set
the current reading's status, `decided_by`, `decided_at` and `note` and nothing else; they
answer 409 when there is nothing to decide (no reading yet, or an activation of a reading that
is not validated), and the live page's DK-RMM pane has the three buttons
([running.md](running.md)). A verdict is a person's statement about a reading. It changes no
indicator, threshold, state, transition or RCT criterion, and no later assessment reads it.
Nothing in the run can reach the gate: it is an HTTP door only. Like the source, the routes do
not take the runner's step lock, so a verdict never waits for a tick that is inside a
consultation; the monitor is the runner's at the moment of deciding, and if a reset replaced it
meanwhile the verdict is asked again of the new one. `tests/test_dkrmm.py` drives the gate over
the wire (activation before validation refused, then validate and activate), and
`tests/test_api_rcts.py` covers the 409 cases, the bounds and the races with a reset.

## The recorder and the RCT explainer

Two of the source's observability modules are back, reading DK-RMM from outside and never
changing it. The recorder (`observability/run_record.py`) is driven by the API runner: after
`monitor.tick()`, in its own exception guard, it writes the run record whenever there is
a new reading and, for each RCT, a file with the reading (`Assessment.as_dict()`) and its
explanation computed from the run's own events; after a gate verdict the runner has it write
again. A recorder that fails leaves the run and the monitor going. Its writes are serialised by
the runner's record lock, under which a reset swaps the monitor and the recorder together, and
a gate write is skipped when the recorder is not of the runner's current run. Where the files
go, and how to switch recording off, is in [running.md](running.md).

The RCT explainer (`observability/rct_explain.py`, `explain(events, tick)`) lays out, for one
reading, the events of its window (the 60 ticks up to the reading, from tick 0 for an early
reading) by the evidence kind each feeds (congestion, retry, refusal, spread), by topic and by
agent; the messages in the window and how many of them were consultation messages
(`CONSULT_*`); the expert consultations open in the window or closed at most one window before
it; and the window's trouble count against the windows DK-RMM compared it with. It serves
`GET /dkrmm/explain?tick=`, the "explain this reading" box and the saved RCT files. Where the
source read expert discussions, it reads consultations: a consultation is its
`consult_opened` event (owner, peer, decision, options), its `consult_closed` event (outcome,
choice) and its `CONSULT_REQUEST` message; the result keeps the source's keys `discussions`
and `discussion_messages`, which the RCT log page reads.

A consultation is linked to a trouble event of the window, logged once it had opened, when they
share a subject. The link is strong when the event concerns a task or parcel among the
consultation's options or its choice, and weak when the only thing in common is a robot. This is
the source's rule unchanged, and it says little about most consultations here: a `choose_robot`
consultation's options are robot ids, so it can link only weakly, and since its options cover
most of the fleet, nearly every robot event links weakly to it; a consultation whose options are
actions (RELEASE or HOLD, ACCEPT or REFUSE, WAIT, zones, small numbers, stations) never links at
all. So "0% strongly linked to a consultation" does not mean that consultations played no part.
A link is evidence, not proof of cause; the causal test is a run with consultations off.

DK-RMM's own code is unchanged by all of this: `post_office/dkrmm/` is the source's, and
`tests/test_api_rcts.py::test_dkrmm_is_unchanged` pins the tree hash of that folder (with a
second check against `main` by git where git can say). The gate methods, the record builder and
the history the recorder and the explainer read were all there before.

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
