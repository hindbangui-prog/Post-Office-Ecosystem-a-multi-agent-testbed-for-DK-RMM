"""
The runtime communication feed's rules, as pure functions over event dicts.

The live page's "Runtime communication" pane (taxonomy design, section 6.1) is
built in the browser from the WebSocket's `event` payloads and the rows of
`GET /events`. The rules it applies, which row is a reply to which, where a
latency may be shown, which rows may name a model, what the chain of a row is,
are written here first and mirrored line for line by the page's JavaScript, so
they can be tested on the events of a seeded run without a browser.

Every function takes an event as a dict in the `as_dict()` shape (or an
`/events` row, which is that plus `text`). Nothing here invents a field: a
receiver is the event's `target` or `(none)`, an edge exists only when both
ends do, every text is a detail field of the event (or of the row it is paired
with) or `views.describe` of that event, a latency is shown only where the event carries one or its reply was observed,
and a model is named only where the event, its source or the consultation it
points to names one. The taxonomy module is the only account of what a type
is; this module reads its hints and never repeats its tables.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ..communication import taxonomy
from .views import describe

#: What a row shows for a missing sender or receiver (spec 2.3).
NONE = "(none)"

#: The bus's two carried-message topics; a refused message is housekeeping.
MESSAGE_TOPICS = frozenset({"message", "subagent_message"})

#: The request topics of a consultation, answered by `consult_response`.
CONSULT_REQUEST_TOPICS = frozenset({"consult_question", "consult_delegation"})

#: The interaction types whose rows show their own text in the response column
#: even when unpaired (section 6.1); every other type's response column is its
#: paired reply's, or its own text when the row is itself a paired reply.
RESPONSE_TYPES = frozenset({"response", "expert_response", "subagent_response"})

#: The detail keys an event may link a chain by, besides `correlation_id`.
CHAIN_DETAIL_KEYS = ("consultation_id", "message_id", "in_reply_to", "parcel_id", "task_id")


# ------------------------------------------------------------------ fields
def _detail(event: Dict[str, Any]) -> Dict[str, Any]:
    detail = event.get("detail")
    return detail if isinstance(detail, dict) else {}


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _hint(event: Dict[str, Any]) -> Optional[taxonomy.InteractionType]:
    """The taxonomy's row for the event's stamped type; None when unstamped."""
    return taxonomy.TYPES.get(_text(event.get("interaction_type")))


def sender_of(event: Dict[str, Any]) -> str:
    """`actor`, or `(none)`."""
    return _text(event.get("actor")) or NONE


def receiver_of(event: Dict[str, Any]) -> str:
    """`target`, or `(none)` (spec 2.3): no receiver is ever inferred."""
    return _text(event.get("target")) or NONE


def edge_of(event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """`(actor, target)` when both are non-empty; None otherwise, and no edge is drawn."""
    actor, target = _text(event.get("actor")), _text(event.get("target"))
    if actor and target:
        return (actor, target)
    return None


# ------------------------------------------------------------------- texts
def request_text_of(event: Dict[str, Any]) -> str:
    """
    The request / message column (section 6.1).

    A message: `detail.text` when it has one, else its type and the scalar
    fields of its content exactly as `views.describe` renders them. A
    `consult_question` / `consult_delegation`: `detail.text`. A `decision`:
    `decision -> choice`. Anything else: `describe(event)`. Nothing is
    composed beyond joining existing fields with a separator.
    """
    topic = _text(event.get("topic"))
    detail = _detail(event)
    if topic in MESSAGE_TOPICS:
        return _text(detail.get("text")) or describe(event)
    if topic in CONSULT_REQUEST_TOPICS:
        return _text(detail.get("text"))
    if topic == "decision":
        return f"{_text(detail.get('decision'))} -> {_text(detail.get('choice'))}"
    return describe(event)


def response_text_of(event: Dict[str, Any]) -> str:
    """`detail.text` of a response-kind row (`response`, `expert_response`,
    `subagent_response`); "" for every other row."""
    if _text(event.get("interaction_type")) in RESPONSE_TYPES:
        return _text(_detail(event).get("text"))
    return ""


def reply_text_of(response_event: Dict[str, Any]) -> str:
    """
    What a request row shows in its response column once its reply arrived:
    the reply row's own text. `response_text_of` when the reply is a
    response-kind row; otherwise (a PLAN_APPROVAL answering a PLAN_PROPOSAL, a
    TASK_ACCEPTED answering a TASK_ASSIGNMENT) the reply's `detail.text`, or
    its type and content as `describe` renders them, which is
    `request_text_of` of the reply row. Still only the reply's own fields.
    """
    return response_text_of(response_event) or request_text_of(response_event)


def decision_text_of(event: Dict[str, Any]) -> str:
    """
    The decision column: for a `decision`, `choice (path, status)` with the
    fields the event has; for `consult_closed`, `outcome: choice`; "" otherwise.
    """
    topic = _text(event.get("topic"))
    detail = _detail(event)
    if topic == "decision":
        text = _text(detail.get("choice"))
        inside = [_text(detail.get(key)) for key in ("path", "status") if detail.get(key)]
        if inside:
            text += f" ({', '.join(inside)})"
        return text
    if topic == "consult_closed":
        text = _text(detail.get("outcome"))
        if detail.get("choice"):
            text += f": {_text(detail.get('choice'))}"
        return text
    return ""


# ----------------------------------------------------------------- pairing
def pair_key_of(event: Dict[str, Any]) -> str:
    """The id a reply would name: `detail.message_id` for a message,
    `detail.consultation_id` for a `consult_*` row, "" otherwise."""
    topic = _text(event.get("topic"))
    detail = _detail(event)
    if topic in MESSAGE_TOPICS:
        return _text(detail.get("message_id"))
    if topic.startswith("consult_"):
        return _text(detail.get("consultation_id"))
    return ""


def reply_to_of(event: Dict[str, Any]) -> str:
    """The id this row answers: `detail.in_reply_to` for a message, the
    consultation id for a `consult_response`, "" otherwise."""
    topic = _text(event.get("topic"))
    detail = _detail(event)
    if topic in MESSAGE_TOPICS:
        return _text(detail.get("in_reply_to"))
    if topic == "consult_response":
        return _text(detail.get("consultation_id"))
    return ""


def _ordered(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda row: int(row.get("seq") or 0))


def pair(rows: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    """
    Request seq -> response seq, as strings (the page keys an object by them).

    A message pairs by `in_reply_to == message_id`; a `consult_response` event
    pairs to the earliest unanswered `consult_question` / `consult_delegation`
    event of its consultation that precedes it; a CONSULT_RESPONSE message, whose
    `in_reply_to` the bus leaves empty, pairs likewise to the earliest unanswered
    CONSULT_REQUEST message of the same `correlation_id` (the consultation id).
    Message rows pair only with message rows and event rows only with event
    rows. One response per request, the first to arrive; a response that names
    no request the rows hold stays unpaired.
    """
    paired: Dict[str, str] = {}
    by_message_id: Dict[str, int] = {}
    requests_by_consultation: Dict[str, List[int]] = {}
    bus_requests_by_correlation: Dict[str, List[int]] = {}

    def _answer(requests: List[int], seq: int) -> None:
        for request_seq in requests:
            if request_seq < seq and str(request_seq) not in paired:
                paired[str(request_seq)] = str(seq)
                return

    for row in _ordered(rows):
        seq = int(row.get("seq") or 0)
        topic = _text(row.get("topic"))
        detail = _detail(row)
        if topic in MESSAGE_TOPICS:
            message_id = _text(detail.get("message_id"))
            if message_id and message_id not in by_message_id:
                by_message_id[message_id] = seq
            reply_to = _text(detail.get("in_reply_to"))
            request_seq = by_message_id.get(reply_to) if reply_to else None
            if request_seq is not None and request_seq < seq \
                    and str(request_seq) not in paired:
                paired[str(request_seq)] = str(seq)
            message_type = _text(detail.get("message_type"))
            correlation_id = _text(row.get("correlation_id"))
            if message_type == "CONSULT_REQUEST" and correlation_id:
                bus_requests_by_correlation.setdefault(correlation_id, []).append(seq)
            elif message_type == "CONSULT_RESPONSE" and correlation_id:
                _answer(bus_requests_by_correlation.get(correlation_id, []), seq)
        elif topic in CONSULT_REQUEST_TOPICS:
            consultation_id = _text(detail.get("consultation_id"))
            if consultation_id:
                requests_by_consultation.setdefault(consultation_id, []).append(seq)
        elif topic == "consult_response":
            _answer(requests_by_consultation.get(_text(detail.get("consultation_id")), []),
                    seq)
    return paired


# ----------------------------------------------------------------- latency
def latency_of(event: Dict[str, Any],
               response: Optional[Dict[str, Any]] = None) -> Dict[str, Optional[float]]:
    """
    `{"latency_ms", "latency_ticks"}`, each None unless known (section 7);
    the milliseconds a float, the ticks a whole number.

    `latency_ms` is the event's own `detail.latency_ms` (an `llm_call`, a
    `consult_response`, a `consult_closed`, a `decision` whose mode is llm).
    `latency_ticks` is `response.tick - event.tick` when a paired response is
    given and the event's type hint says `ticks`. Nothing is estimated.
    """
    latency_ms = _number(_detail(event).get("latency_ms"))
    latency_ticks: Optional[int] = None
    hint = _hint(event)
    if response is not None and hint is not None and hint.latency == "ticks":
        ticks = _number(response.get("tick"))
        start = _number(event.get("tick"))
        if ticks is not None and start is not None:
            latency_ticks = int(ticks - start)     # ticks are whole numbers
    return {"latency_ms": latency_ms, "latency_ticks": latency_ticks}


# ------------------------------------------------------------------- model
def models_by_consultation(rows: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    """consultation id -> the model its `consult_*` rows name."""
    out: Dict[str, str] = {}
    for row in rows:
        if _text(row.get("topic")).startswith("consult_"):
            detail = _detail(row)
            consultation_id, model = _text(detail.get("consultation_id")), _text(detail.get("model"))
            if consultation_id and model and consultation_id not in out:
                out[consultation_id] = model
    return out


#: The prefix the CrewBrain writes on a decision's `source` when the model
#: answered (`crew/consultation.py`: `crewai:<model>`); a status the gate
#: appends (`:refused`, `:rule-after-refusal`) follows the model's name, and
#: `fallback...` means the rule answered because no model did.
CREWAI_SOURCE_PREFIX = "crewai:"


def model_of(event: Dict[str, Any],
             by_consultation: Optional[Dict[str, str]] = None,
             configured_model: Optional[str] = None) -> Optional[str]:
    """
    The model a row may name (spec 2.5): `detail.model` for `llm_call` and
    `consult_*`; for a `decision` whose `mode` is llm, (1) the model of the
    consultation `detail.consultation_id` points to when `by_consultation`
    knows it, (2) else `configured_model` (the model `/settings` names, which
    the caller passes) when `detail.source` starts with `crewai:`, that is,
    when the model answered, (3) else None; None for everything else.

    The source is never parsed for a name: the model's own name has a colon
    in it (`qwen3:8b`) and the gate appends a status after it
    (`crewai:qwen3:8b:rule-after-refusal`), so no split can say where the name
    ends, and `fallback:refused` names no model at all.
    """
    topic = _text(event.get("topic"))
    detail = _detail(event)
    if topic == "llm_call" or topic.startswith("consult_"):
        return _text(detail.get("model")) or None
    if topic == "decision" and _text(detail.get("mode")) == "llm":
        consultation_id = _text(detail.get("consultation_id"))
        if consultation_id and by_consultation and by_consultation.get(consultation_id):
            return by_consultation[consultation_id]
        if _text(detail.get("source")).startswith(CREWAI_SOURCE_PREFIX) and configured_model:
            return str(configured_model)
    return None


# ------------------------------------------------------------------- chain
def chain_keys_of(event: Dict[str, Any]) -> Set[str]:
    """The non-empty ids among `correlation_id`, `detail.consultation_id`,
    `detail.message_id`, `detail.in_reply_to`, `detail.parcel_id`, `detail.task_id`."""
    detail = _detail(event)
    keys = {_text(event.get("correlation_id"))}
    keys.update(_text(detail.get(key)) for key in CHAIN_DETAIL_KEYS)
    keys.discard("")
    return keys


def _select(rows: List[Dict[str, Any]], keys: Set[str]) -> Set[int]:
    """The seqs of the rows sharing a key with `keys`, closed once over the
    consultations the selected `decision` rows name (section 6.1)."""
    if not keys:
        return set()
    def _seq(row: Dict[str, Any]) -> int:
        return int(row.get("seq") or 0)

    selected = {_seq(row) for row in rows if chain_keys_of(row) & keys}
    named = {_text(_detail(row).get("consultation_id")) for row in rows
             if _seq(row) in selected and _text(row.get("topic")) == "decision"}
    named.discard("")
    if named:
        selected |= {_seq(row) for row in rows if chain_keys_of(row) & named}
    return selected


def chain_select(rows: Iterable[Dict[str, Any]], seed_event: Dict[str, Any]) -> Set[int]:
    """The seqs of the rows in the seed's chain: every row sharing a key with
    the seed, plus the rows of any consultation a selected `decision` names."""
    rows = list(rows)
    selected = _select(rows, chain_keys_of(seed_event))
    if seed_event.get("seq") is not None:
        selected.add(int(seed_event["seq"]))
    return selected


def chain_select_by_id(rows: Iterable[Dict[str, Any]], identifier: str) -> Set[int]:
    """The same rule for an id typed into the page's box."""
    identifier = _text(identifier)
    return _select(list(rows), {identifier} if identifier else set())


# ----------------------------------------------------------------- the row
def feed_row(event: Dict[str, Any], paired_response: Optional[Dict[str, Any]] = None,
             by_consultation: Optional[Dict[str, str]] = None,
             configured_model: Optional[str] = None,
             paired_request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    One display row of the pane, every field from the helpers above.

    The two text columns read as one exchange on both rows of a pair. A reply
    row (one given its `paired_request`: a response-kind row, or a governance
    or task reply such as a TASK_ACCEPTED answering a TASK_ASSIGNMENT) shows
    the request's text in `request` (`request_text_of` of the request row) and
    its own text in `response` (`reply_text_of` of itself). An unpaired
    response-kind row shows nothing in `request` and its own text in
    `response`. Every other row shows its own text in `request` and, once its
    reply is given, the reply's text in `response` (`reply_text_of`); both
    rows stay in the feed. `paired_seq` is the other row of the pair, from
    `pair()`: the response's seq on a request row (`paired_response`), the
    request's seq on a response row (`paired_request`), None when unpaired.
    `configured_model` is what `/settings` names, for `model_of`. `edge` is
    `[actor, target]` or None, `chain_keys` a sorted list.
    """
    latency = latency_of(event, paired_response)
    paired = paired_response if paired_response is not None else paired_request
    paired_seq = None if paired is None or paired.get("seq") is None else int(paired["seq"])
    if paired_request is not None:
        request = request_text_of(paired_request)
        response = reply_text_of(event)
    elif _text(event.get("interaction_type")) in RESPONSE_TYPES:
        request = ""
        response = response_text_of(event)
    else:
        request = request_text_of(event)
        response = reply_text_of(paired_response) if paired_response is not None else ""
    edge = edge_of(event)
    return {
        "seq": event.get("seq"),
        "tick": event.get("tick"),
        "sender": sender_of(event),
        "receiver": receiver_of(event),
        "interaction_type": _text(event.get("interaction_type")),
        "channel": _text(event.get("channel")),
        "request": request,
        "response": response,
        "decision": decision_text_of(event),
        "latency_ms": latency["latency_ms"],
        "latency_ticks": latency["latency_ticks"],
        "model": model_of(event, by_consultation, configured_model),
        "edge": None if edge is None else list(edge),
        "paired_seq": paired_seq,
        "chain_keys": sorted(chain_keys_of(event)),
    }


__all__ = ["NONE", "MESSAGE_TOPICS", "CONSULT_REQUEST_TOPICS", "RESPONSE_TYPES",
           "CHAIN_DETAIL_KEYS", "CREWAI_SOURCE_PREFIX", "sender_of", "receiver_of", "edge_of",
           "request_text_of", "response_text_of", "reply_text_of", "decision_text_of",
           "pair_key_of", "reply_to_of", "pair", "latency_of", "models_by_consultation",
           "model_of", "chain_keys_of", "chain_select", "chain_select_by_id", "feed_row"]
