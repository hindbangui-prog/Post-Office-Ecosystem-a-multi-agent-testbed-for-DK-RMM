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

Missing fields are the empty string. Classification is a pure function of its six arguments:
the five positional fields and the keyword-only `content_type`.

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
- 2026-10-02, Task 2 (stamping, bus `in_reply_to`, fingerprint, DK-RMM invariance):
  - `tools/normal_fingerprint.py` strips `interaction_type`, `channel` and `detail.in_reply_to`
    through two constants beside `STRIP`, `STAMP_KEYS` and `STAMP_DETAIL_KEYS`, applied in
    `filter_rows` on both sides the way `wall_clock` and `run_id` are, rather than by adding
    them to `STRIP`: the baseline file records `STRIP` and
    `test_the_baseline_records_its_provenance_and_filter` compares the two, so the recorded
    `strip` and `tests/data/normal_baseline_filtered.json` stay as they were and were not
    regenerated (section 4's "strips" and invariant 6 hold; the baseline does not itself name
    the stamp, `docs/alignment-baseline.md` does).
  - Section 8's `/events` and WebSocket relay captures listed under
    `tests/test_event_stamping.py` are in Task 3's `tests/test_api_taxonomy.py` instead:
    Task 2 covered the logger (`recent()`, `since()`, the JSONL file and an `also=`
    subscriber, which is the mechanism the relay sits on) and Task 3 the API it feeds.
  - `post_office/communication/bus.py` was classed `unchanged` in the provenance record, not
    `adapted` as section 9 assumed; the one-line `in_reply_to` addition makes it `adapted`.
- 2026-10-02, Task 3 (API and feed helpers):
  - The served route table is spec 16 of 2026-10-01 plus `GET /taxonomy`; the route-table
    test (`tests/test_api_trimmed.py`, `SPEC_ROUTES`) lists it, and nothing else is added.
    `/taxonomy` is a pure table and answers with or without a runner.
  - `/frame`: the topic of a message row's classification is the one the bus gave the
    message's event (`subagent_message` when the directory record of the sender is a
    sub-agent, which is every `SUB-*` id), with the content's `interaction_type` as
    `content_type`, so the row's channel and type are the stamp of the event.
  - `feed.py` (section 6.1, 7), as ruled in the Task 3 review (I1): the model of a
    `decision` with `mode == "llm"` is (1) the model of the linked consultation
    (`detail.consultation_id`) when its rows are at hand, (2) else the configured model
    (what `/settings` names; `model_of(..., configured_model=)`, which the page passes) when
    `detail.source` starts with `crewai:`, that is, when the model answered, (3) else None.
    The source is never parsed for a name: the model's own name has a colon in it
    (`qwen3:8b`), the gate appends a status after it (`crewai:qwen3:8b:rule-after-refusal`),
    and a `fallback:refused` source names no model at all. Section 6.1's "the model named in
    its `source`" reads as "the model of its linked consultation, else the configured model
    when the source is the model's". Spec 2.5 is unchanged in substance: the model is
    taken from the linked consultation or from the fact, in the event's own source, that the
    configured model answered.
  - `feed.py` pairing (section 6.1), as ruled in the Task 3 review (M1): the bus twins of a
    consultation exchange, the CONSULT_REQUEST and CONSULT_RESPONSE message rows (whose
    `in_reply_to` the bus leaves empty), pair by `correlation_id`, the consultation id, one
    response per request, message rows only; the `consult_question` / `consult_delegation`
    and `consult_response` event rows keep pairing by `detail.consultation_id`. A message
    row never pairs with an event row.
  - `feed_row` carries `paired_seq` (M7): the response's seq on a paired request row, the
    request's seq on a paired response row, None when unpaired; the caller passes the other
    row of the pair (`paired_response` or `paired_request`) from `pair()`.
  - `feed.py`: a request row's response column shows the reply row's own text whatever the
    reply's type: `detail.text` of a response-kind reply, else the reply's `detail.text`
    or `describe` of it (a PLAN_APPROVAL answering a PLAN_PROPOSAL, a TASK_ACCEPTED answering
    a TASK_ASSIGNMENT; the `ticks` latency hint of `governance_report` and
    `task_assignment` already pairs these). Nothing beyond the reply's fields is shown.
  - `feed.py` imports `views.describe` besides the taxonomy, because section 6.1 renders a
    message without text as `describe` does and one copy of that rendering is the point.
- 2026-10-02, Task 4 (live page), from its build and two review rounds:
  - The shell (`live.html`) owns the event buffer (section 6.1's last 2000 events): it is
    tailed from the log rather than replayed from its start. On connect a one-row probe of
    `GET /events` gives the newest seq and the page fetches the last 2000; a gap in the live
    sequence is paged from the buffer's tail until the gap closes; a reconnect tails again;
    the relay's `reset` empties the buffer.
  - The Runtime communication pane is a fifth tab of the shell beside the four of 2026-10-01,
    not a replacement of the floor's list: the floor's "Latest messages" list is renamed
    "Runtime communication" and is fed by `postMessage` with the newest forty rows of the
    tab's buffer (every event, not only bus messages), each coloured by its class, so the
    floor shows the same rows the tab does. The pulses (newest tick's non-message events) and
    the chain reach the floor the same way; the taxonomy is posted in once.
  - The graph canvas is sized to the room the pane gives it (`fitGraph`), and the six tiers,
    ENVIRONMENT included, are spread over that height with the tree's own weights, so the
    whole hierarchy is on screen without scrolling; the class legend is in the graph's header.
  - The per-type filter is a grouped chip list behind a "types" summary rather than a
    `<select multiple>`; the chips show the taxonomy's own labels (`A governance`,
    `B llm_expert`) verbatim.
  - The type cell shows the interaction type with the event's topic dimmed under it and the
    bus message type as its tooltip, so the bus twin of a consultation exchange (`question` /
    `message`) and its event twin (`question` / `consult_question`) are told apart by the
    topic, and the paired row's seq is the response cell's tooltip on both rows of a pair.
  - The chain summary counts the chain's rows and edges among the rows the filters leave; the
    floor receives the whole chain.
- 2026-10-02, Task 5 (documentation and provenance):
  - `docs/events.md` carries the interaction type table between `<!-- taxonomy:begin -->` and
    `<!-- taxonomy:end -->`, printed by `tools/taxonomy_table.py` from `taxonomy.table()`;
    `tests/test_docs_present.py` regenerates it and asserts the block equals it (section 5's
    docs check).

