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

`retries`, in `CrewBrain.stats()` and the run reports, counts the owner's model calls beyond
the first call and the post-exchange call, summed over the expert's consultations. A clean
consultation makes one owner call without an exchange and two with one; every owner call
beyond that is CrewAI's executor asking the model again because the previous reply could not
be used as it stood (a tool call whose arguments did not parse, a coworker or tool not on
offer, a second exchange refused). It also counts CrewAI's agent-level re-run after an HTTP
error (`max_retry_limit=1`). Peer retries are not counted. The figure is measured from the
audit's records of the owner's calls; the OpenAI client's own retries are off, so there is no
hidden HTTP-level retry.

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
