# Synchronous peer consultation

When an expert's rule is insufficient, the expert's CrewAI agent decides, and it may consult
exactly one peer: the one the source's peer map names for that decision and condition. The
peer's answer comes back before the owner decides, and the owner's decision is then validated
and executed by the simulator. The code is `post_office/crew/consultation.py` (the service),
`post_office/crew/tools.py` (the two tools) and `post_office/crew/events.py` (the record).

## Real time

"Real time" in this project has one operational meaning: At a simulation decision point, the
owner synchronously consults an allowed peer, receives the response before finalizing its
decision, and the resulting decision is then validated and executed by the simulator. It is
not unrestricted continuous chat between agents: there is at most one exchange per decision,
it happens inside the decision that needs it, and nothing is said between decisions. The live
page shows consultations as their events arrive; that is observability only and changes
nothing about the exchange.

## The peer map

`post_office/discussion/peers.py` is copied unchanged and is the only source of truth for who
may be consulted. `peer_for(owner, kind, condition)` looks up the owner id, the decision kind
and the name of the trigger condition that fired, and returns a peer id or `None`.

| Owner | Decision kind | Condition | Peer |
|-------|---------------|-----------|------|
| PLANNER | `release_work` | `contention`, `no_robots` | SCHEDULING |
| PLANNER | `release_work` | `shelves_filling` | RESOURCE |
| INTAKE | `accept_parcel` | `dock_backing_up` | PLANNER |
| INTAKE | `accept_parcel` | `no_destination` | SORTING |
| SORTING | `classify_destination` | `no_shelf`, `shelves_tight` | RESOURCE |
| SORTING | `classify_destination` | `paid_parcel` | DISPATCH |
| SCHEDULING | `choose_robot` | `nobody_able`, `paid_errand_thin_robot` | RESOURCE |
| SCHEDULING | `choose_robot` | `equally_placed` | ROUTING |
| SCHEDULING | `choose_next_task` | `already_late`, `competing_tasks`, `promoted_work` | DISPATCH |
| ROUTING | `resolve_block` | `low_on_charge` | RESOURCE |
| ROUTING | `resolve_block` | `still_blocked`, `expensive_detour` | SCHEDULING |
| RESOURCE | `allocate_charge_point` | `points_contested`, `laden_rival` | SCHEDULING |
| RESOURCE | `accept_into_storage` | `shelves_near_ceiling`, `more_coming` | DISPATCH |
| DISPATCH | `release_parcel` | `past_the_promise`, `promise_before_departure`, `van_too_small` | SCHEDULING |

These are the source's 24 entries; `tests/test_discussion_peers.py` holds them verbatim and
asserts the table equals them. A decision whose trigger has no condition name, or whose
owner, kind and condition have no entry, has no peer: the owner decides alone, with no tools.
CrewAI's own coworker graph is never built: every agent has `allow_delegation=False`, there is
no `Crew`, and the only tools an owner ever holds are bound to its one peer.

## One exchange

`ConsultationService.run(owner_id, question, trigger, rule_answer)` takes these steps.

First the peer is looked up and a consultation id `CSL-0001`, `CSL-0002`, ... is minted, and
`consult_opened` is written. If the owner or the peer is still busy with a consultation that
was abandoned at its deadline, the consultation closes at once as `timeout` and the rule
answers, rather than running two CrewAI loops on one agent.

The owner's CrewAI `Task` is `render(question)`, the source model brain's rendering
(`Decision: <kind>`, the prompt, `Facts:` in sorted order, `Allowed answers:` one per line);
then, when there is a peer, "You may ask <Peer> one question with the tool `Ask question to
coworker`, or delegate one sub-question with `Delegate work to coworker`; the answer is advice,
the decision is yours."; then "End with exactly one line `DECISION: <one allowed answer>`."
The expected output is "a DECISION line".

When there is a peer the owner gets two tools, `AskPeerTool` and `DelegateToPeerTool`,
subclasses of CrewAI's `AskQuestionTool` and `DelegateWorkTool` built with
`agents=[peer_agent]`. They share one `ConsultationContext`, which allows one exchange per
consultation. When the owner uses one, the tool builds a `ConsultRequest` (owner to peer,
`question` or `delegation`), passes it through the communication layer's `on_request`, writes
`consult_question` or `consult_delegation`, sends `CONSULT_REQUEST` on the bus and reads the
peer's briefing from the live world at that moment (`briefing_for` from the copied
`discussion/briefings.py`). It then hands the text to CrewAI's own tool implementation with the
briefing as context, prefixed with "You are consulted by <Owner>; answer in at most three
sentences; recommend, do not act.", and CrewAI runs `peer.execute_task(...)`: the peer's own
model call, with no tools. The reply, stripped of hidden reasoning, becomes a
`ConsultResponse`, passes through `on_response`, is written as `consult_response`, is sent as
`CONSULT_RESPONSE` and is returned into the owner's reasoning loop as the tool's result.

A second use of either tool returns "You have already consulted <Peer> for this decision;
decide now." and a call naming any other coworker returns "<Name> is not available to you for
this decision; only <Peer> is."; neither asks a model, and both are written as
`consult_refused`. If the request or the response is withheld by the communication layer, or
the peer's own model call fails, the owner's tool returns "no answer from <Peer>" and the
consultation is marked so that it closes as `peer_failed` if no decision follows.

The owner's `execute_task(task, tools=...)` runs in a worker thread that the tick's thread
joins with `CONSULT_DEADLINE_S` (default 300 s). The tick blocks for that time; the simulated
clock does not move during a consultation. The owner's final text is read with
`crew/parse.py::parse_choice`: hidden reasoning is removed first; a `DECISION:` line, when
there is one, is authoritative (`discussion/prompts.py::parse_decision`); without one, the
source model brain's heuristics apply in its order (the first visible line matched exactly,
then a token of that line, then the one option the whole reply mentions). The parsed answer
passes through `AgentHooks.after_answer` and is checked against the options again.

## Outcomes

`consult_closed` is written with one of five outcomes, and `CONSULT_CLOSE` is sent to the
peer when a request reached it.

| Outcome | When | Answer |
|---------|------|--------|
| `decided` | the reply named an allowed answer | `Answer(choice, <last visible line>, source="crewai:<model>", confidence=1.0)` |
| `no_valid_decision` | the reply named no allowed answer, or a hook returned one off the list | the rule's answer, `source="fallback"` |
| `timeout` | the deadline passed, or a needed expert was still busy | the rule's answer, `source="fallback"` |
| `model_failed` | the owner's model call raised (Ollama down, HTTP 500, ...) | the rule's answer, `source="fallback"` |
| `peer_failed` | the peer gave no answer and the owner reached no decision | the rule's answer, `source="fallback"` |

A fallback's reason is the rule's reason with `[fallback: <why>]` appended, so a record says
why the model's answer was not used. On a timeout the worker is abandoned, not killed (CrewAI
cannot be cancelled): its consultation is marked closed, so a tool use it still makes writes
nothing and asks nothing, its result is discarded, and its later model calls are kept in the
service's call list with `phase="late"` but not written as events. `drain()` waits for
abandoned workers, and `PostOfficeEcosystem.close()` calls it.

## Simulator authority

The model never touches world state. The only way a consultation influences the world is the
`Answer.choice` returned to `BaseAgent.decide`. That choice must be one of the question's
admissible options (checked by the parser and again after `after_answer`), must pass
`world.gate.check(Proposal(...))` (schema, then policy, then the state of the floor), and is
then applied by the agent's own Python, which calls the same environment, task-registry and
robot APIs the rules path calls. An answer the gate refuses is replaced by the rule's answer,
with `source` ending in `:rule-after-refusal`. `tests/test_simulator_authority.py` asserts that
an off-list owner answer and an off-list hook answer never reach the gate, that an admissible
answer the world refuses is replaced by the rule, and that no module under `post_office/crew/`
imports `environment`, `tasks`, `robots` or `state` (it may import `discussion.briefings`,
which reads).

## Consultant, not controller

The peer is a consultant. Its CrewAI task runs with no tools, so it cannot call anything; its
text is advice that the owner may follow or not; and only the owner's parsed `DECISION:` line
becomes an `Answer`. The `CONSULT_*` messages that reach either expert on the next tick are
dropped in `BaseAgent.step()`: they are the record of an exchange that has already finished
inside the decision that asked for it. `tests/test_consultation_causality.py` shows that the
peer's words are what the owner acted on: with the fake peer recommending R2 ("R2: its
corridor is clear; ...") the owner decides `R2`, with the peer recommending R1 it decides
`R1`, the owner's follow-up request contains the peer's text in a `tool` message, and the
peer's own request offered no tools. `tests/test_consultation_sync.py` asserts that the whole exchange happens inside one
`decide`, in event order, with the tick unchanged.
