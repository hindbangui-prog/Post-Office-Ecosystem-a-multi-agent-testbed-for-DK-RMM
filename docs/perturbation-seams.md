# Perturbation seams

No perturbation is implemented in this phase. The places where perturbations will later
attach exist, are documented here, and are inert: in NORMAL every one of them is identity or
`None`, and a configuration that asks for anything else is refused.

## The four seams

| Seam | Where | NORMAL behaviour | Future perturbations it would carry |
|------|-------|------------------|-------------------------------------|
| Communication | `crew/interception.py::CommunicationLayer.on_request(req) -> req or None` and `on_response(resp) -> resp or None`, on every consultation exchange; the existing `MessageBus.delay_rule` on every bus message | identity; `delay_rule` is `None` | message delay, loss, duplication, reordering, corruption, isolation, frozen delegation, repeated delegation, flooding; delay or drop of any expert message on the bus |
| Agent execution | `crew/interception.py::AgentHooks.before_prompt(agent_id, text) -> text`, `before_llm_call(agent_id)`, `after_answer(agent_id, answer) -> answer`; the existing `BaseAgent.facts_filter` | identity; `facts_filter` is `None` | prompt or context perturbation, stale information, forced consultation, agent freeze, abnormal proposals |
| LLM call | the CrewAI transport interceptor (`crew/audit.py::OllamaAudit`, a `BaseInterceptor` that a perturbing interceptor could wrap) | audit only: records, never changes a request or reply | model response delay, response corruption |
| Environment and resources | the configuration knobs of `config/settings.py` and the environment, task and fleet APIs | the NORMAL values | route closure, resource reduction, robot failure, slowdown, arrival surge, timing changes |

`Interception` bundles the two consultation layers. `Interception.inert()` is the NORMAL
arrangement, `Interception.active` says whether anything other than the identity layers is
installed, and `from_config(cfg)` is how the ecosystem builds the one its consultation service
uses: an empty `interceptors` list gives the inert arrangement, and anything else raises
`NotImplementedError("perturbations are not part of this phase")`. Before that,
`PostOfficeEcosystem._refuse_perturbations` turns away any configuration with a non-empty
`interceptors` list or a truthy `perturbations` key, with `ValueError`, before the event logger
opens a file. A run therefore cannot build silently mislabelled as NORMAL.

The run record says what is in force rather than leaving it to be inferred. The ecosystem
writes a `simulation`/`interception` notice with `{active: [], perturbations: "none"}` when it
is built, and `simulation_started.detail.config` carries `interceptors: []`.
`tests/test_seams_noop.py` asserts that the identity layers hand back exactly what they are
given, that an empty interceptor list is the inert arrangement and any other is refused, that a
NORMAL run's notice and `simulation_started` say so, that the service gets its interception
from the configuration, and that an inert consultation carries every word unchanged.

Two hook results are checked again before they can matter. A `None` from `on_request` or
`on_response` means the message did not get through: the owner's tool returns "no answer from
<Peer>". Whatever `after_answer` returns is checked against the question's options, and an
answer outside them closes the consultation as `no_valid_decision` with the rule's answer, so
nothing off the list reaches the policy gate.

## The lock rule

The communication layer is called under the consultation service's lock, and only while the
consultation is open (the `guarded` block in `crew/tools.py` checks `ctx.closed` first), so a
worker abandoned at its deadline never drives the layer, writes the log or reads the live
world while the tick has moved on. The consequence for future work: a layer must return
promptly. A delay or freeze perturbation must not sleep inside `on_request` or `on_response`,
because the tick's thread needs that lock to close a consultation at its deadline and would
wait for the sleeping hook instead. It must defer instead:
return `None` (the message is lost, or the peer is unreachable), or hold the exchange outside
the lock (the peer's own model call in `tools.py` already runs outside it, bounded by
`CONSULT_DEADLINE_S`). Holding an exchange across simulated ticks would need a mechanism the
synchronous protocol does not have today, because the tick does not advance while a
consultation is open.

## Unavailable, frozen and degraded

These are three separate future mechanisms, not three degrees of one.

An unavailable agent is one that cannot be reached at all: no peer is registered for the case,
or the request never arrives. `on_request` returning `None` models it. The owner's tool answers
"no answer from <Peer>" at once, no `consult_question` or `CONSULT_REQUEST` is written, and the
owner decides alone or falls back.

A frozen agent receives the request and never answers. The request is on record
(`consult_question` and `CONSULT_REQUEST`), the response is withheld, either by `on_response`
returning `None` or by an exchange held past the deadline, and no `consult_response` or
`CONSULT_RESPONSE` follows.

A degraded agent answers, but late or wrongly: the exchange is held for a while and then
passed, or `on_response` hands back altered advice. The record shows a complete exchange whose
latency or text differs from the peer's own.

## The frozen-delegation path

A frozen-delegation experiment would attach without touching the normal architecture. A
`CommunicationLayer` withholds the frozen peer's response. The owner's tool returns "no answer
from <Peer>" into the owner's reasoning loop, and the consultation is marked as having lost its
peer. If the owner then reaches no allowed decision the consultation closes as `peer_failed`,
or as `timeout` if the deadline passes first; the owner falls back to its rule exactly as it
does today on a model failure, with the reason in the decision record. (An owner that decides
alone after hearing "no answer" closes as `decided`; the record still shows the request without
a response.) What DK-RMM sees is the event stream: the `CONSULT_REQUEST` with its
`interaction_type`, the missing `CONSULT_RESPONSE`, the `consult_closed` outcome and the
fallback `decision`. `tests/test_consultation_fallbacks.py` already exercises the tail of this
path with a test layer whose `on_request` withholds every request (the consultation closes as
`peer_failed`, the reason says "no answer from Routing", and the peer's model is never asked)
and with a deadline (`timeout`).
