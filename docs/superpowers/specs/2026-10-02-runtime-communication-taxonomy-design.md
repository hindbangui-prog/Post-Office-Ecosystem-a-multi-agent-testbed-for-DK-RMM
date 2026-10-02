# Runtime communication taxonomy and visualization (NORMAL scenario)

Date: 2026-10-02. Status: approved by the project owner in conversation; the brief of
2026-10-02 ("Normal-scenario runtime communication taxonomy and visualization", sections 1
to 24) is the requirement text and this document is its design. The specification of
2026-10-01 and its plan remain authoritative for everything not named here.

## 1. Goal and non-goals

The live page must show the complete communication activity of the unperturbed NORMAL
ecosystem as it happens: governance, planner/expert coordination, expert/expert questions,
delegations and responses, expert/sub-agent traffic, robot commands and reports, expert and
environment facility events, task lifecycle, decisions and model calls. It is a labelling and
presentation layer over the existing runtime event stream, which stays the single source of
truth.

Not in scope: perturbations, attack controls, stress batteries, injectors, frozen-agent or
frozen-delegation controls; any change to the seven roles, the Brain abstraction, CrewBrain,
the peer map, synchronous consultation, the rules-first policy, the Ollama integration, the
model configuration, or DK-RMM.

## 2. Invariants (each pinned by a test)

1. No new event is emitted, no topic, actor, target, correlation id or detail key of an
   existing event changes, except: every event gains the two top-level fields
   `interaction_type` and `channel`, and `message` / `subagent_message` events gain the
   detail key `in_reply_to` (the bus message's existing field, previously not logged).
2. DK-RMM code is untouched; a seeded run's indicator vectors, state series, RCT events and
   event counts per topic are identical before and after stamping.
3. No receiver, sender, target or edge is invented. An event without a target shows receiver
   `(none)` and draws no edge.
4. No synthetic dialogue: every request, response, decision and text shown equals a field of
   the underlying event.
5. The model name appears only on `llm_call` and `consult_*` rows and on `decision` rows whose
   `mode` is `llm` (taken from the event's own `source`/linked consultation), never on
   deterministic, robot or environment rows.
6. The filtered alignment baseline still matches (the fingerprint strips the three new keys).
7. The source project is not modified.

## 3. Taxonomy (`post_office/communication/taxonomy.py`)

A pure module with no imports from the simulator. It exposes:

- `CHANNELS`: `A` governance, `B` llm_expert, `C` deterministic, `D` robot, `E` environment,
  `decision`, `system`, each with a label, a colour and a dash style for the UI.
- `TYPES`: the closed set of `interaction_type` values with channel and description.
- `classify(category, topic, actor, target, message_type, *, content_type="") ->
  Classification` (`interaction_type`, `channel`, `fallback`). All arguments may be
  `""`/`None`. `content_type` is the bus message content's `interaction_type`, when the
  caller has it; it is read only for a `CONSULT_REQUEST` (`delegation` when it says so,
  `question` otherwise) and ignored for every other input.
- `table()`: the JSON-serialisable taxonomy served by `GET /taxonomy` and rendered in
  `docs/events.md` by a test that compares the two.

Agent kinds are read from the id, as the floor graph already does: `SUPERVISOR`, `PLANNER`,
the seven expert ids, `SUB-*` sub-agents, robots `R<n>`, `ENVIRONMENT`, `SIMULATION`,
`INTAKE_DOCK`; anything else is `other`.

### 3.1 Types

| Channel | `interaction_type` | Realised by (first matching rule wins, see 3.2) |
|---|---|---|
| decision | `decision` | topic `decision` |
| B | `llm_call` | topic `llm_call` |
| B | `question`, `delegation`, `response` | topics `consult_question`, `consult_delegation`, `consult_response`; messages `CONSULT_REQUEST` (type from `detail.content.interaction_type`, `question` when absent), `CONSULT_RESPONSE` |
| B | `consultation` | topics `consult_opened`, `consult_closed`, `consult_refused`; message `CONSULT_CLOSE`. The one type added beyond the brief: these events exist, are not decisions and are not exchanges; their detail keeps its own `interaction_type` key (`decision` for opened/closed), untouched |
| A | `governance_instruction` | messages `OBJECTIVE`, `POLICY`, `PLAN_APPROVAL`, `PLAN_REJECTION`, `STATUS_REQUEST`, `BROADCAST`; category `supervisor` with actor `SUPERVISOR` (`system_started`, `system_stopped`, `policy_changed`, `intervention_withheld`, `plan_approved`, `plan_rejected`) |
| A | `governance_report` | messages `PLAN_PROPOSAL`, `STATUS_REPORT`; category `supervisor` with actor `PLANNER` (`policy_applied`) |
| A | `task_assignment` | message `TASK_ASSIGNMENT` |
| A | `task_report` | messages `TASK_ACCEPTED`, `TASK_REJECTED`, `TASK_COMPLETED`, `TASK_FAILED`, `TASK_PROGRESS`, `WORK_NOTICE` when sender or receiver is `PLANNER` |
| C | `expert_request` | messages `ROUTE_REQUEST`, `RESOURCE_REQUEST`, `SCHEDULE_REQUEST`, `CHARGE_REQUEST`, `ALERT` |
| C | `expert_response` | messages `ROUTE_RESPONSE`, `RESOURCE_GRANT`, `RESOURCE_DENIAL`, `SCHEDULE_RESPONSE`; a `TASK_*` message between two experts (neither end `PLANNER`), e.g. ROUTING to SCHEDULING `TASK_FAILED` |
| C | `subagent_request` | message `SUBTASK_REQUEST` |
| C | `subagent_response` | message `SUBTASK_RESULT` |
| D | `robot_command` | message `ROBOT_COMMAND`; category `robot` with topic `command_*` |
| D | `robot_report` | message `ROBOT_REPORT`; category `robot` with a robot actor (`moved`, `blocked`, `picked`, `delivered`, `yielded`, ...) |
| E | `environment_action` | categories `parcel`, `resource`, `robot`, `task` with an agent actor (expert, planner, sub-agent or robot) that is not matched above: `parcel_received`, `parcel_refused` (INTAKE), `parcel_classified`, `promise_revised`, `parcel_packed`, `bag_handed_over`, `van_departed`, `parcel_passed_through`, `storage_policy`, `block_resolved`, `errand_handed_over`, `queued_errand_rerouted`, RESOURCE's `charge_*`, `top_up_*`, `recovery_requested` |
| E | `environment_update` | category `battery` (any actor); categories `parcel`, `resource` with actor `ENVIRONMENT`, `SIMULATION`, `INTAKE_DOCK` or empty: `parcel_arrived`, `parcel_lifted`, `parcel_dropped`, `parcel_departed`, `parcel_returned`/`parcel_refused` (ENVIRONMENT), `storage_*`, `charging_*`, `arrival_refused`, `recovery_withdrawn/deferred/completed` |
| E | `task_lifecycle` | category `task` with topic `task_created`, `task_assigned`, `task_started`, `task_completed`, `task_failed`, `task_released`, `task_cancelled`, `overdue`, `queue_question_timed_out` |
| system | `system` | category `simulation`; topics `agent_created`, `agent_removed`, `message_refused`, `message_dropped`, `agent_message_received`; and the explicit fallback for anything unmatched, which the completeness test forbids for every event the seeded runs produce |

### 3.2 Precedence

Rules are evaluated in this order; the first match wins. The order is the brief's, adapted in
one place: a `message` event is classified by its `message_type` before any category rule,
because the category of every bus message is `communication` and carries no semantics.

1. topic `decision`
2. topic `llm_call`
3. topics `consult_*`
4. `message_type` present: CONSULT_* (B); governance types (A); TASK_ASSIGNMENT (A);
   TASK_* with PLANNER at either end (A) else expert_response (C); expert request/response
   types (C); SUBTASK_* (C); ROBOT_COMMAND / ROBOT_REPORT (D)
5. category `supervisor` (A, by actor)
6. category `robot`: topic `command_*` (D robot_command); robot actor (D robot_report);
   otherwise E environment_action
7. category `task`: lifecycle topics (E task_lifecycle); otherwise E environment_action
8. category `battery` (E environment_update)
9. categories `parcel`, `resource`: actor ENVIRONMENT / SIMULATION / INTAKE_DOCK / empty
   (E environment_update); an agent actor (expert, planner, sub-agent or robot)
   (E environment_action); otherwise fallback
10. category `simulation`, lifecycle and bus-housekeeping topics (system)
11. fallback: system, with `interaction_type` `system` and a `fallback: true` marker in the
   classification result (not written to the event) so the completeness test can detect it.

Missing fields are the empty string. Classification is a pure function of its five arguments.

## 4. Stamping

`Event` gains two slots, `interaction_type` and `channel`, written after `detail` in
`as_dict()`. `EventLogger.emit` computes them with `taxonomy.classify(category, topic, actor,
target, detail.get("message_type", ""), content_type=...)`, where `content_type` is
`detail.get("content", {}).get("interaction_type", "")` when `detail["content"]` is a dict
and `""` otherwise, after provenance stamping, before writing the JSONL
line and notifying subscribers, so `events.jsonl`, `recent()`, `since()`, the WebSocket relay
and DK-RMM's `observe` all see the same record. DK-RMM reads `topic`, `actor`, `target` and
`detail`; it ignores the new slots.

`MessageBus` adds `in_reply_to` to the detail of `message` and `subagent_message` events
(empty string when the message has none).

`tools/normal_fingerprint.py` strips `interaction_type`, `channel` and `detail.in_reply_to`
from events before hashing; the recorded baseline is unchanged.

## 5. API

- `GET /events` rows carry the two fields and `detail.in_reply_to` (no change to the route).
- `GET /frame`: each row of `m` gains a sixth element, the channel, and a seventh, the
  interaction type (positional, appended, as the file's convention requires).
- WebSocket `/ws`: `event` messages carry the two fields because they are `as_dict()`.
- `GET /taxonomy`: `taxonomy.table()`: `channels` (id, label, colour, dash, description) and
  `types` (interaction_type, channel, description, `has_receiver` hint, latency kind:
  `ms`, `ticks` or none, `model` true/false). The page fetches it once at load and builds its
  legend, filters and colours from it; the docs table is checked against it by a test.

## 6. Live page

### 6.1 Runtime communication pane (replaces "Latest messages")

Fed by the WebSocket `event` messages (and backfilled from `GET /events?after=` on connect);
a bounded buffer (last 2000 events) kept in the page. Columns: tick, sender (`actor` or
`(none)`), receiver (`target` or `(none)`), interaction type, channel badge, request/message,
response, decision, latency, model, edge (`A -> B` only when both ends exist).

- request/message: `detail.text` for messages; for events without text the existing
  `text` field that `/events` adds via `views.describe`; for a `decision`: `detail.decision`
  and `detail.choice`; nothing is composed beyond joining existing fields with a separator.
- response: a response row (`expert_response`, `subagent_response`, `response`,
  `RESOURCE_GRANT`...) shows its own text in the response column and the request's row id;
  a request row shows the response text of the row whose `detail.in_reply_to` equals its
  `detail.message_id` once that row arrives (consult rows pair by `detail.consultation_id`).
  Both rows stay in the feed; nothing is merged.
- decision: `detail.choice` with `path`/`status` for `decision` rows; `detail.outcome` and
  `choice` for `consult_closed`.
- latency: `latency_ms` from `llm_call`, `consult_response`, `consult_closed` and
  `decision` (mode llm) details; `latency_ticks` = response tick minus request tick for a
  paired deterministic request; otherwise blank. The two are shown with their unit.
- model: `detail.model` for `llm_call` and `consult_*`; for a `decision` with
  `mode == "llm"` the model named in its `source` (`crewai:qwen3:8b` -> `qwen3:8b`);
  otherwise blank.
- filters: chips for the seven channels and a per-type multi-select built from `/taxonomy`;
  a text box for a parcel/task/consultation id. Filtering is client-side.
- chain follow: clicking a row selects its chain key = `correlation_id` when non-empty,
  else `detail.consultation_id`, else `detail.message_id`; rows whose `correlation_id`,
  `detail.consultation_id`, `detail.message_id` or `detail.in_reply_to` equals a key in the
  chain are highlighted, and a `decision` row's `detail.consultation_id` adds that
  consultation's rows. The floor graph receives the highlighted set of (actor, target) pairs
  and emphasises those edges. Entering an id in the box applies the same rule.

### 6.2 Floor graph

The hierarchy stays (SUPERVISOR, PLANNER, the seven experts, sub-agents, robots) and an
`ENVIRONMENT` node is added below the robots. Live edges are coloured and dashed by the
channel of the message on the current tick (`m` rows now carry it): A amber `#b06a1e`,
B teal dashed `#1b8a7a`, C purple `#7a5cc4`, D red `#b1452f`, E grey-green `#5f7f6a`.
An edge is drawn only for rows with a real sender and receiver. Robot reports and
environment-authored events pulse their own node (robot or ENVIRONMENT) without an edge; a
`decision` pulses its actor node (the existing amber ring) without an edge. A legend of the
five classes plus "decision" and "no receiver" is drawn in the pane header. The highlighted
chain from 6.1 is passed to the iframe by `postMessage` and drawn with a thicker stroke.

Events that are not bus messages reach the floor graph through the same WebSocket relay the
feed uses (the shell forwards the compact `{tick, actor, target, channel, type}` to the
iframe); nothing new is served.

## 7. Latency and model semantics

See 6.1. Nothing is estimated: `latency_ms` only where the event carries it, `latency_ticks`
only for a request whose response was observed, model only where the event or its linked
consultation names it. A ROUTING to robot command is `robot_command` even when ROUTING's
decision that tick was model-backed.

## 8. Tests

- `tests/test_taxonomy.py`: every type in the table has a rule that reaches it; precedence
  cases (a `message` with `TASK_FAILED` ROUTING to SCHEDULING is `expert_response`; a
  `robot`/`block_resolved` with an expert actor is `environment_action`; `battery`/`battery_low`
  with a robot actor is `environment_update`; `consult_opened` is `consultation`, not
  `decision`); missing fields; determinism (same inputs, same output, hashable).
- `tests/test_taxonomy_completeness.py`: a 300-tick rules-only run and a 120-tick fake-model
  run (via the existing helpers) produce no fallback classification; every observed
  (category, topic, message_type) combination is listed in the test's expectation table so a
  new source event fails loudly with its name.
- `tests/test_event_stamping.py`: fields present on every event in `events.jsonl`, `/events`
  and a WebSocket relay capture; stripping the new keys gives the pre-change record;
  `message` events carry `in_reply_to`; the recorded alignment baseline still matches.
- `tests/test_dkrmm_stamping_invariance.py`: run the same seeded ecosystem twice, once with
  the classifier replaced by a stub that returns empty strings and once normally; indicator
  vectors, state series, RCT events, `events` counts and per-topic counts are equal.
- `tests/test_feed_integrity.py` (server-side helpers used by the page are mirrored in
  `post_office/ui/feed.py` so they can be unit-tested): receiver `(none)` iff `target == ""`;
  no edge for such rows; request/response pairing by `in_reply_to` and by
  `consultation_id`; `latency_ticks` only for paired rows; model only on B rows and llm
  decisions; every text shown is a substring/field of the event.
- `tests/test_api_taxonomy.py`: `/taxonomy` equals `taxonomy.table()`; `/frame` `m` rows
  carry channel and type; `/events` rows carry the fields.
- `tests/test_live_ui.py` (Playwright, optional extra): feed shows a row for each of A to E,
  decision and system in a fake-model run; a channel filter hides the others; clicking a
  row highlights its chain rows; typing a real parcel id highlights its rows; a decision
  row with a consultation id highlights the consultation rows; the legend lists five
  classes; the consultation pane still renders.
- `tests/test_docs_present.py`: `docs/events.md` taxonomy table matches `/taxonomy`.

## 9. Documentation

`docs/events.md`: the taxonomy table, precedence, receiver, latency, model and correlation
semantics, the no-synthetic-dialogue rule and the DK-RMM invariance statement.
`docs/running.md`: the Runtime communication pane, filters, chain follow and legend.
`docs/dkrmm.md`: one paragraph that the fields are metadata and what the invariance test
proves. Provenance: `events.py`, `bus.py` stay `adapted`; new files `new`.

## 10. Files

New: `post_office/communication/taxonomy.py`, `post_office/ui/feed.py`, the tests above,
this document and its plan. Changed: `post_office/communication/events.py`, `bus.py`,
`post_office/ui/views.py`, `live.html`, `floor.html`, `live.py`, `post_office/api/server.py`,
`tools/normal_fingerprint.py`, `docs/events.md`, `docs/running.md`, `docs/dkrmm.md`,
`docs/provenance_classification.json` (and the regenerated provenance), `tests/test_api_trimmed.py`
(route table gains `/taxonomy`). Untouched: everything under `post_office/agents/`,
`post_office/crew/`, `post_office/dkrmm/`, `post_office/robots/`, `post_office/environment/`,
`post_office/simulation/`, `post_office/discussion/`, `post_office/policy/`.

## 11. Amendments made during implementation

- 2026-10-02, Task 1 (taxonomy module), from its review:
  - `classify` gains a keyword-only `content_type=""` argument, the bus message content's
    `interaction_type`, read only for a `CONSULT_REQUEST` so that a delegation's bus row is
    `delegation` rather than `question`; section 3's signature and section 4's stamping call
    say how it is filled. The five positional arguments and their meaning are unchanged.
  - The `latency` hint of `table()` means "a row of this type may show a latency, in this
    unit": `ms` when the event itself carries `latency_ms` (`decision`, `llm_call`,
    `response`, `consultation`), `ticks` when the row is a request whose reply can be paired
    to it by `in_reply_to` (`task_assignment`, `governance_report` for PLAN_PROPOSAL,
    `expert_request`, `subagent_request`), `none` otherwise (replies included: the latency
    is shown on the request row, section 6.1).
  - `environment_update.has_receiver` is `sometimes`: RESOURCE's re-logs of a robot's
    battery reports under `battery` name RESOURCE as target.
  - Rule 9 of section 3.2: an actor of kind `other` under `parcel`/`resource` falls through
    to the fallback instead of being filed as `environment_action`, so an unknown author is
    named by the completeness test.
