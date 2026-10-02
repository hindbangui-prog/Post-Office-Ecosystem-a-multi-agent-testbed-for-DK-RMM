# Events and messages

All runtime evidence goes through the ecosystem's one `EventLogger`
(`post_office/communication/events.py`) and its one `MessageBus`; no second event system
exists. Every logged row has `seq`, `tick`, `wall_clock`, `run_id`, `category`, `topic`,
`actor`, `target`, `correlation_id` and `detail`. `seq` is the logger's own counter and is the
order of record: two rows in the same tick are ordered by `seq`, never by `wall_clock`. The
consultation's rows are written by `post_office/crew/events.py::ConsultEvents`.

## Bus messages

A consultation sends three ordinary expert-to-expert messages. The bus logs each as a
`message` event (category `communication`), exactly as it logs every other expert message,
which is the traffic DK-RMM's message indicators read. They are delivered on the next tick and
dropped unhandled by the receiving agent's `step()`.

| MessageType | From, to | Content |
|-------------|----------|---------|
| `CONSULT_REQUEST` | owner to peer | `consultation_id`, `decision` (kind), `condition`, `interaction_type` (`question` or `delegation`), `text` |
| `CONSULT_RESPONSE` | peer to owner | `consultation_id`, `text`, `latency_ms`, `model` |
| `CONSULT_CLOSE` | owner to peer | `consultation_id`, `outcome`, `choice` (sent only when a request reached the peer) |

Each carries the consultation id as its `correlation_id`.

## Consultation events

Every consultation event has category `agent`, the consultation's `tick`, `actor` (the
sender), `target` (the receiver) and `correlation_id` (the consultation id), and carries in
`detail` the common fields `consultation_id`, `decision_id`, `decision` (the kind),
`condition`, `interaction_type` and `model`, plus its own:

| Topic | actor, target | `interaction_type` | Own detail |
|-------|---------------|--------------------|------------|
| `consult_opened` | owner, peer or "" | `decision` | `peer` (or ""), `options` |
| `consult_question` | owner, peer | `question` | `text`, `context` |
| `consult_delegation` | owner, peer | `delegation` | `text`, `context` |
| `consult_response` | peer, owner | `response` | `text`, `latency_ms` |
| `consult_refused` | owner, the refused coworker or the peer | the refused attempt's type | `reason` (a second exchange, or a disallowed coworker) |
| `consult_closed` | owner, peer or "" | `decision` | `outcome`, `choice`, `turns`, `latency_ms`, and `error` when the model's answer was not used |
| `llm_call` | the calling agent, "" | `llm_call` | `agent_role`, `call_id`, `url`, `requested_model`, `served_model`, `latency_ms`, `prompt_tokens`, `completion_tokens`, `status`, `phase`, `error` |
| `decision` | the deciding agent, "" | (not set) | the source's record, plus `consultation_id`, `peer`, `turns` for a model decision |

The `decision` event is the source's record, unchanged: `decision`, `choice`, `source`,
`reason`, `facts`, `call_id` (the decision id), `mode`, `path`, `trigger`, `trigger_detail`,
`noted`, `validation`, `violation`, `status`, and for a model decision `request_tick`,
`response_tick` and `latency_ms`; when the brain held a consultation for it, its
`consultation_id`, `peer` and `turns` are added. A deterministic decision carries no
wall-clock figure, so the same seed gives the same log on the rules path.

Two `simulation` notices describe the run's model layer: `interception` (`active: []`,
`perturbations: "none"`), always written when the ecosystem is built, and `llm` (`backend:
"ollama"`, `model`, `base_url`, `agents`), written when the ecosystem has CrewBrains. Both come
before `simulation_started`, whose `detail.config` echoes the configuration, including
`interceptors: []`.

## Order

One consultation with a question, as written by `tests/test_consultation_sync.py` (the `seq`
numbers are from that run), reads:

| seq | Row | actor, target |
|-----|-----|---------------|
| 49 | `consult_opened` | SCHEDULING, ROUTING |
| 50 | `llm_call` (phase `owner`) | SCHEDULING |
| 51 | `consult_question` | SCHEDULING, ROUTING |
| 52 | `message` `CONSULT_REQUEST` | SCHEDULING, ROUTING |
| 53 | `llm_call` (phase `peer`) | ROUTING |
| 54 | `consult_response` | ROUTING, SCHEDULING |
| 55 | `message` `CONSULT_RESPONSE` | ROUTING, SCHEDULING |
| 56 | `llm_call` (phase `owner`) | SCHEDULING |
| 57 | `consult_closed` | SCHEDULING, ROUTING |
| 58 | `message` `CONSULT_CLOSE` | SCHEDULING, ROUTING |
| 59 | `decision` | SCHEDULING |

All of them carry the same tick. The test asserts this exact sequence of `consult_*`,
`llm_call` and `decision` rows in `seq` order, the single tick, and that the decision record
carries the consultation's id, its peer and two turns.

## The llm_call record

There is one `llm_call` record per HTTP round trip, made by the transport interceptor
(`OllamaAudit`), not inferred from the reply text. `url` is the address the request went to,
`requested_model` the model in its body, `served_model` the `model` field of Ollama's reply,
`status` the HTTP status (`None` when no response arrived, with `error` saying so), and
`phase` is `owner` or `peer` inside a consultation (`probe` in `tools/verify_ollama.py`). A
record becomes an `llm_call` event, under the consultation's tick, while its consultation is
open. A call that arrives after its consultation was abandoned at the deadline gets
`phase="late"` and is kept only in the service's call list (`GET /llm/calls`,
`llm_calls.json`), so an abandoned worker never writes into the log while the tick has moved
on.

## Retries and fallbacks

`retries`, in `CrewBrain.stats()` and the run reports, counts the extra owner model calls
inside one reasoning loop, summed over the expert's consultations. A clean consultation makes
one owner call without an exchange and two with one (the first call and the post-exchange
call); every owner call beyond that is CrewAI's executor asking the model again inside the
same loop because the previous reply could not be used as it stood (a malformed tool call, a
coworker or tool not on offer, a second exchange refused). CrewAI never re-runs the task
(`max_retry_limit=0`): a model call that fails closes the consultation `model_failed`.
Peer retries are not counted. The figure is measured from the
audit's records of the owner's calls; the OpenAI client's own retries are off, so there is no
hidden HTTP-level retry.

`calls` counts the expert's model decisions (every consultation opened for it) and
`consultations` those in which it actually asked or delegated to its peer: an exchange, so a
model decision the owner settled alone is a call but not a consultation.
`fallbacks` counts decisions the model was asked about and the rule answered, `timeouts` the
consultations closed at the deadline, `parse_failures` replies with no allowed answer and no
`DECISION:` line, and `rejected_answers` replies whose `DECISION:` line named no allowed
answer, as well as an `after_answer` hook result that is off the list or a hook that raises. In the decision paths, `fallback` also counts model answers the policy gate refused
and the rule replaced.

## Reading it back

`ConsultationService.recent()` keeps the last 500 consultations as rows (`id`, `tick`,
`owner`, `peer`, `kind`, `condition`, `decision_id`, `request`, `response`, `decision`,
`source`, `outcome`, `latency_ms`, `model`), served by `GET /consultations`;
`llm_calls()` keeps the last 2000 call records, served by `GET /llm/calls`; `GET
/events?after=&limit=` tails the log by `seq`, and `WS /ws` pushes every event live.
`tools/run_normal.py` writes the whole log to `events.jsonl` and the consultations and calls
to `consultations.json` and `llm_calls.json`.

`ConsultationService.summary()` (the `llm` block of the ecosystem's summary) counts
`model_decisions`, every consultation opened (every `CSL-` id, with or without a peer, however
it closed), and `exchanges`, those in which the owner actually asked or delegated to its peer;
`by_pair` counts only the exchanges, by `owner->peer`, so its values add up to `exchanges`, and
the experts' `CrewBrain.stats()["consultations"]` add up to the same number. `outcomes` and
`mean_latency_ms` cover every model decision.

## Interaction taxonomy

Every event carries two more top-level fields, `interaction_type` and `channel`, written after
`detail` in `as_dict()`. `EventLogger.emit` computes them once per event with
`taxonomy.classify` (`post_office/communication/taxonomy.py`) over the event's `category`,
`topic`, `actor`, `target`, the `message_type` in its detail and, for a bus message, the
content's own `interaction_type`, before the JSONL line is written and the subscribers are
notified. So the same two fields appear on every line of `events.jsonl`, on every row of
`GET /events`, on every `event` message of `WS /ws`, and, for the bus messages of a tick, as
the sixth (channel) and seventh (interaction type) element of each `m` row of `GET /frame`.
The bus also adds the detail key `in_reply_to` to every `message` and `subagent_message`
event: the message's own `in_reply_to`, or the empty string. Nothing else about an event
changed: no event was added, and no topic, actor, target, correlation id or other detail key
of an existing event was altered. The `consult_*` events keep their own `interaction_type`
detail key (`decision` on `consult_opened` and `consult_closed`, see the table above), which
is the consultation's record and is not the stamp: `consult_opened` is stamped
`consultation`, not `decision`.

The taxonomy module imports nothing from the simulator and is a pure function of its
arguments; `GET /taxonomy` serves `taxonomy.table()`, and the live page builds its chips,
legend and colours from that one answer. Agent kinds are read from the id as the floor graph
reads them: `SUPERVISOR`, `PLANNER`, the six expert ids, `SUB-*` sub-agents, robots `R<n>`,
`ENVIRONMENT`, `SIMULATION`, `INTAKE_DOCK`; anything else is `other`.

### Channels

| Channel | Label | Colour | Dash | What it holds |
|---|---|---|---|---|
| A | `governance` | `#b06a1e` | solid | supervisor and planner: objectives, policies, plans, status, task assignments and the reports that come back up |
| B | `llm_expert` | `#1b8a7a` | dashed | the model-backed layer: model calls and the consultations between experts, their questions, delegations and responses |
| C | `deterministic` | `#7a5cc4` | solid | expert to expert and expert to sub-agent requests and responses on the experts' rules |
| D | `robot` | `#b1452f` | solid | commands to robots and the robots' reports |
| E | `environment` | `#5f7f6a` | solid | what agents do to the floor, what the floor reports, and the task lifecycle |
| decision | `decision` | `#d89614` | solid | a decision an agent took, on its rules or through a model |
| system | `system` | `#8a929d` | solid | run lifecycle, bus housekeeping, and the fallback for anything no rule names |

### Interaction types

The table below is printed by `tools/taxonomy_table.py` from `taxonomy.table()`, which is
what `GET /taxonomy` serves; `tests/test_docs_present.py` regenerates it and fails when the
block between the markers differs. `has_receiver` says whether a row of the type has a
target (`always`, `sometimes`, `never`). `latency` says whether a row of the type may show a
latency and in which unit: `ms` when the event itself carries `latency_ms`, `ticks` when the
row is a request whose reply can be paired to it, `none` otherwise (a reply's row shows no
latency; the request's row does). `model` says whether a row of the type may name a model.

<!-- taxonomy:begin -->
| Channel | `interaction_type` | Realised by | `has_receiver` | `latency` | `model` |
|---|---|---|---|---|---|
| decision | `decision` | Topic `decision`: an agent decided, by rule or by model. Carries latency_ms and a model only when its mode is llm. | never | ms | yes |
| B | `llm_call` | Topic `llm_call`: one call to the model server. | never | ms | yes |
| B | `question` | Topic `consult_question`; message CONSULT_REQUEST whose content's interaction_type is not `delegation`: an expert asks its allowed peer for a view. | always | none | yes |
| B | `delegation` | Topic `consult_delegation`; message CONSULT_REQUEST whose content's interaction_type is `delegation`: an expert hands its allowed peer a task inside a consultation. | always | none | yes |
| B | `response` | Topic `consult_response`, message CONSULT_RESPONSE: the peer answers. | always | ms | yes |
| B | `consultation` | Topics `consult_opened`, `consult_closed`, `consult_refused`, message CONSULT_CLOSE: the consultation itself, opened, refused or closed with its outcome. | sometimes | ms | yes |
| A | `governance_instruction` | Messages OBJECTIVE, POLICY, PLAN_APPROVAL, PLAN_REJECTION, STATUS_REQUEST, BROADCAST, and the supervisor's own events. | sometimes | none | no |
| A | `governance_report` | Messages PLAN_PROPOSAL (answered by an approval or rejection), STATUS_REPORT, and the planner's `policy_applied`. | sometimes | ticks | no |
| A | `task_assignment` | Message TASK_ASSIGNMENT from the planner to an expert, answered by TASK_ACCEPTED or TASK_REJECTED. | always | ticks | no |
| A | `task_report` | A TASK_* message or WORK_NOTICE with the planner at either end. | always | none | no |
| C | `expert_request` | Messages ROUTE_REQUEST, RESOURCE_REQUEST, SCHEDULE_REQUEST, CHARGE_REQUEST, ALERT between experts. | always | ticks | no |
| C | `expert_response` | Messages ROUTE_RESPONSE, RESOURCE_GRANT, RESOURCE_DENIAL, SCHEDULE_RESPONSE, and a TASK_* message between two experts. | always | none | no |
| C | `subagent_request` | Message SUBTASK_REQUEST from an expert to its sub-agent. | always | ticks | no |
| C | `subagent_response` | Message SUBTASK_RESULT from a sub-agent to its expert. | always | none | no |
| D | `robot_command` | Message ROBOT_COMMAND, and the `robot` category's `command_*` topics. | always | none | no |
| D | `robot_report` | Message ROBOT_REPORT, and any `robot` category event a robot authors (moved, blocked, picked, delivered, yielded, ...). | sometimes | none | no |
| E | `environment_action` | A `parcel`, `resource`, `robot` or `task` event an agent (expert, planner, sub-agent or robot) authors that is not a command, report or lifecycle step. | sometimes | none | no |
| E | `environment_update` | Every `battery` event (RESOURCE's re-logs of a robot's battery reports name RESOURCE as target), and a `parcel` or `resource` event the floor, the run or the intake dock authors. | sometimes | none | no |
| E | `task_lifecycle` | A `task` event about the task itself: created, assigned, started, completed, failed, released, cancelled, overdue, timed out. | never | none | no |
| system | `system` | The `simulation` category, agent lifecycle, bus housekeeping, and the fallback for anything no rule names. | sometimes | none | no |
<!-- taxonomy:end -->

### Precedence

`classify` tries its rules in this order and the first match wins; a missing argument is the
empty string. The order is the one of the design's section 3.2: a `message` event is
classified by its `message_type` before any category rule, because the category of every bus
message is `communication` and says nothing about it.

1. Topic `decision` is `decision`.
2. Topic `llm_call` is `llm_call` (B).
3. Topics `consult_question`, `consult_delegation`, `consult_response` are `question`,
   `delegation`, `response`; `consult_opened`, `consult_closed`, `consult_refused` are
   `consultation` (all B).
4. A `message_type` on a carried message, that is, when the topic is not one of the bus's
   housekeeping topics `message_refused`, `message_dropped`, `agent_message_received` (which
   carry a `message_type` too and would otherwise be filed as the message they refused):
   `CONSULT_REQUEST` is `delegation` when the content's `interaction_type` says so and
   `question` otherwise; `CONSULT_RESPONSE` is `response` and `CONSULT_CLOSE` `consultation`
   (B); `OBJECTIVE`, `POLICY`, `PLAN_APPROVAL`, `PLAN_REJECTION`, `STATUS_REQUEST`,
   `BROADCAST` are `governance_instruction` and `PLAN_PROPOSAL`, `STATUS_REPORT`
   `governance_report` (A); `TASK_ASSIGNMENT` is `task_assignment` (A); `TASK_ACCEPTED`,
   `TASK_REJECTED`, `TASK_COMPLETED`, `TASK_FAILED`, `TASK_PROGRESS`, `WORK_NOTICE` are
   `task_report` (A) when `PLANNER` is the actor or the target and `expert_response` (C)
   otherwise; `ROUTE_REQUEST`, `RESOURCE_REQUEST`, `SCHEDULE_REQUEST`, `CHARGE_REQUEST`,
   `ALERT` are `expert_request` and `ROUTE_RESPONSE`, `RESOURCE_GRANT`, `RESOURCE_DENIAL`,
   `SCHEDULE_RESPONSE` `expert_response` (C); `SUBTASK_REQUEST` and `SUBTASK_RESULT` are
   `subagent_request` and `subagent_response` (C); `ROBOT_COMMAND` and `ROBOT_REPORT` are
   `robot_command` and `robot_report` (D). An unknown message type matches nothing here and
   falls through.
5. Category `supervisor`: actor `SUPERVISOR` is `governance_instruction`, actor `PLANNER`
   `governance_report` (A); any other actor falls through.
6. Category `robot`: a topic starting `command_` is `robot_command`, a robot actor
   `robot_report` (D), anything else `environment_action` (E).
7. Category `task`: the lifecycle topics `task_created`, `task_assigned`, `task_started`,
   `task_completed`, `task_failed`, `task_released`, `task_cancelled`, `overdue`,
   `queue_question_timed_out` are `task_lifecycle`; anything else is `environment_action`
   (E).
8. Category `battery` is `environment_update` (E), whoever the actor is.
9. Categories `parcel` and `resource`: an actor `ENVIRONMENT`, `SIMULATION`, `INTAKE_DOCK`
   or none is `environment_update`; an agent actor (supervisor, planner, expert, sub-agent
   or robot) is `environment_action` (E); an actor of kind `other` falls through, so an
   unknown author is named by the completeness test instead of being filed as an action.
10. Category `simulation`, and the topics `agent_created`, `agent_removed`,
    `message_refused`, `message_dropped`, `agent_message_received`, are `system`.
11. Anything else is `system` with a `fallback` marker in the classification result. The
    marker is not written to the event; `tests/test_taxonomy_completeness.py` classifies every
    event of a 300-tick rules-only run and a 120-tick fake-model run and fails on any fallback
    and on any (category, topic, message type) triple outside its expectation table, so a new
    source event names itself.

### Receiver

A row's receiver is the event's `target`, or `(none)` when the event has none, and an edge
exists only when both `actor` and `target` are non-empty. No receiver, sender or edge is
inferred from the detail: a `decision`, an `llm_call`, a robot's `moved` or `picked`, a
`battery_band` and a `parcel_arrived` show `(none)` and draw nothing on the graph, while a
`ROBOT_REPORT` message, which has a receiver, shows it.

### Pairing

A reply names its request through the detail key `in_reply_to`, and `post_office/ui/feed.py`
pairs rows by it (the page's JavaScript mirrors every rule of `feed.py`, and
`tests/test_feed_integrity.py` pins them on the events of seeded runs). A `message` or
`subagent_message` row whose `in_reply_to` equals an earlier row's `message_id` is that row's
reply: a `TASK_ACCEPTED` or `TASK_REJECTED` answering a `TASK_ASSIGNMENT`, a `PLAN_APPROVAL`
or `PLAN_REJECTION` answering a `PLAN_PROPOSAL`, a `ROUTE_RESPONSE`, `RESOURCE_GRANT` or
`RESOURCE_DENIAL` answering its request, a `SUBTASK_RESULT` answering its `SUBTASK_REQUEST`.
The bus leaves `in_reply_to` empty on the `CONSULT_RESPONSE` message, so the `CONSULT_REQUEST`
and `CONSULT_RESPONSE` message rows pair by their `correlation_id`, the consultation id. The
`consult_question` or `consult_delegation` event row pairs with the `consult_response` event
row of the same `detail.consultation_id`. In each case the reply goes to the earliest
unanswered request that precedes it, one reply per request, message rows only with message
rows and event rows only with event rows; a reply that names no row in the buffer stays
unpaired. Both rows stay in the feed, the request row showing the reply's text in its response
column and each carrying the other's `seq`; rows are never merged.

### Latency

`latency_ms` is shown only where the event itself carries `detail.latency_ms`: `llm_call`,
`consult_response`, `consult_closed` and a `decision` whose `mode` is `llm`. `latency_ticks`
is the reply's tick minus the request's tick, shown only on a paired request row whose type's
`latency` hint is `ticks` (`task_assignment`, `governance_report`, `expert_request`,
`subagent_request`). A row with neither shows nothing; no latency is estimated.

### Model

A model is named on `llm_call` and `consult_*` rows from their own `detail.model`. A
`decision` row names a model only when its `mode` is `llm`: the model of the consultation its
`detail.consultation_id` points to when that consultation's rows are in the buffer, else the
configured model (what `GET /settings` names) when its `detail.source` starts with `crewai:`,
which is the record that the model answered. The source is never parsed for a name: the
model's own name holds a colon (`qwen3:8b`), the gate appends a status after it
(`crewai:qwen3:8b:rule-after-refusal`) and a `fallback:` source names no model. A
deterministic decision and every row on channels C, D, E and `system` name no model.

### No synthetic dialogue

Every string a row shows is a field of its event, `views.describe` of the event, or a join of
named fields with a separator: the request column is `detail.text` of a message (or
`describe` when the message has none), `detail.text` of a `consult_question` or
`consult_delegation`, `decision -> choice` of a `decision`, and `describe` otherwise; the
response column is `detail.text` of a response row or its paired reply's text; the decision
column is `choice (path, status)` of a `decision` and `outcome: choice` of a `consult_closed`.
`tests/test_feed_integrity.py` recomputes each from the event's own fields.

### Stamping is metadata

DK-RMM reads `topic`, `actor`, `target` and `detail`; it never reads the two stamped slots.
`tests/test_dkrmm_stamping_invariance.py` runs the same seeded ecosystem twice with the
monitor attached, once with the classifier replaced by a stub that writes empty strings and
once normally, and asserts that the monitor's state, its indicator, z, count and state series,
its transitions and RCT events, the logger's total and its per-topic counts are identical,
while the two runs' stamps are shown to differ. The alignment baseline is unchanged: the
fingerprint strips the stamp before hashing ([alignment-baseline.md](alignment-baseline.md)).

### Bus twin and event twin

A consultation exchange appears twice in the log, as the design intends: as the `message`
rows of the `CONSULT_REQUEST`, `CONSULT_RESPONSE` and `CONSULT_CLOSE` the bus carried, which
is the traffic DK-RMM's message indicators count, and as the `consult_question` or
`consult_delegation`, `consult_response` and `consult_closed` events the consultation wrote.
Both twins carry the same interaction type and channel (`question`, `response`,
`consultation` on B), and in the feed the dimmed topic under the type (`message` against
`consult_question`) tells them apart.
