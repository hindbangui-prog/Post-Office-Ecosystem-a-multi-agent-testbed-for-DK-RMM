"""
The feed helpers invent nothing (spec 2.3 to 2.5, 6.1, 7, 8).

`post_office/ui/feed.py` is what the live page's JavaScript mirrors, so the rules
are pinned here, on the events of two seeded runs: 120 ticks with the seven
CrewBrains on the fake Ollama (every consultation answered by the
`deciding_script`, the fake serving `qwen3:8b`), and 60 ticks on the experts'
rules. Every assertion recomputes from the event's own fields: no receiver
without a target, no edge without a receiver, every text a field of the event
or `describe` of it, pairing only by `in_reply_to` and `consultation_id`,
latency only where the event carries it or its reply was observed, a model
only on channel B rows and on model-backed decisions.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from post_office.communication.taxonomy import TYPES
from post_office.config.settings import normal_config
from post_office.crew.console import quiet
from post_office.simulation.ecosystem import build
from post_office.ui import feed
from post_office.ui.views import describe
from tests.consult_helpers import ecosystem_on
from tests.fake_ollama import FakeOllama, deciding_script

MESSAGE_TOPICS = {"message", "subagent_message"}
RESPONSE_TYPES = {"response", "expert_response", "subagent_response"}
MODEL = "qwen3:8b"


def _rows(eco) -> List[Dict[str, Any]]:
    events = eco.logger.recent(limit=10 ** 7)
    assert len(events) == eco.logger.total, "the logger dropped events; raise keep_events"
    return [event.as_dict() for event in events]


@pytest.fixture(scope="module")
def model_rows():
    fake = FakeOllama()
    fake.script(deciding_script("Take the first: its way is clear."))
    try:
        with quiet():
            eco = ecosystem_on(fake)
            try:
                for _ in range(120):
                    eco.step()
                rows = _rows(eco)
            finally:
                eco.close()
        assert fake.requests, "the fake served no model call"
    finally:
        fake.stop()
    return rows


@pytest.fixture(scope="module")
def rules_rows():
    eco = build(seed=1, config=normal_config(), run_id="feed-rules", scenario="normal")
    eco.start()
    try:
        for _ in range(60):
            eco.step()
        return _rows(eco)
    finally:
        eco.close()


@pytest.fixture(scope="module", params=["model", "rules"])
def rows(request, model_rows, rules_rows):
    return model_rows if request.param == "model" else rules_rows


def _detail(row) -> dict:
    return row.get("detail") or {}


def _by_seq(rows) -> Dict[int, dict]:
    return {row["seq"]: row for row in rows}


# ----------------------------------------------------------- receiver and edge
def test_the_receiver_is_none_exactly_when_there_is_no_target(rows):
    without = 0
    for row in rows:
        receiver = feed.receiver_of(row)
        if row["target"] == "":
            without += 1
            assert receiver == "(none)", row["seq"]
        else:
            assert receiver == row["target"], row["seq"]
    assert without > 0


def test_an_edge_exists_exactly_when_both_ends_do(rows):
    drawn = 0
    for row in rows:
        edge = feed.edge_of(row)
        if feed.receiver_of(row) == "(none)" or not row["actor"]:
            assert edge is None, row["seq"]
        else:
            drawn += 1
            assert edge == (row["actor"], row["target"]), row["seq"]
    assert drawn > 0


# ------------------------------------------------------------------- the texts
def test_every_request_text_is_a_field_of_the_event_or_describe_of_it(rows):
    for row in rows:
        detail = _detail(row)
        text = feed.request_text_of(row)
        if row["topic"] in MESSAGE_TOPICS:
            if detail.get("text"):
                assert text == detail["text"], row["seq"]
            else:
                assert text == describe(row), row["seq"]
        elif row["topic"] in ("consult_question", "consult_delegation"):
            assert text == str(detail.get("text") or ""), row["seq"]
        elif row["topic"] == "decision":
            assert text == f"{detail.get('decision')} -> {detail.get('choice')}", row["seq"]
        else:
            assert text == describe(row), row["seq"]


def test_every_response_text_is_the_rows_own_text_and_only_on_response_rows(rows):
    seen = 0
    for row in rows:
        text = feed.response_text_of(row)
        if row["interaction_type"] in RESPONSE_TYPES:
            seen += 1
            assert text == str(_detail(row).get("text") or ""), row["seq"]
        else:
            assert text == "", row["seq"]
    assert seen > 0


def test_every_decision_text_is_built_from_the_named_detail_fields(rows):
    decisions = closed = 0
    for row in rows:
        detail = _detail(row)
        text = feed.decision_text_of(row)
        if row["topic"] == "decision":
            decisions += 1
            inside = [str(detail[k]) for k in ("path", "status") if detail.get(k)]
            want = str(detail.get("choice") or "")
            if inside:
                want += f" ({', '.join(inside)})"
            assert text == want, row["seq"]
        elif row["topic"] == "consult_closed":
            closed += 1
            want = str(detail.get("outcome") or "")
            if detail.get("choice"):
                want += f": {detail['choice']}"
            assert text == want, row["seq"]
        else:
            assert text == "", row["seq"]
    assert decisions > 0


# --------------------------------------------------------------------- pairing
def test_pairing_follows_in_reply_to_and_consultation_id_only(rows):
    by_seq = _by_seq(rows)
    pairs = feed.pair(rows)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in pairs.items())
    responses = list(pairs.values())
    assert len(responses) == len(set(responses)), "a response paired twice"
    messages_by_id = {_detail(r)["message_id"]: r for r in rows if r["topic"] in MESSAGE_TOPICS}
    for request_seq, response_seq in pairs.items():
        request, response = by_seq[int(request_seq)], by_seq[int(response_seq)]
        assert request["seq"] < response["seq"]
        if response["topic"] in MESSAGE_TOPICS:
            assert request["topic"] in MESSAGE_TOPICS, "a message paired with an event"
            if _detail(response).get("message_type") == "CONSULT_RESPONSE":
                assert _detail(request)["message_type"] == "CONSULT_REQUEST"
                assert request["correlation_id"] == response["correlation_id"] != ""
            else:
                assert _detail(response)["in_reply_to"] == _detail(request)["message_id"]
        else:
            assert response["topic"] == "consult_response"
            assert request["topic"] in ("consult_question", "consult_delegation")
            assert _detail(request)["consultation_id"] == _detail(response)["consultation_id"]
    # Every SUBTASK_RESULT pairs to the SUBTASK_REQUEST whose message_id it names.
    results = [r for r in rows if _detail(r).get("message_type") == "SUBTASK_RESULT"]
    assert results
    for result in results:
        request = messages_by_id[_detail(result)["in_reply_to"]]
        assert _detail(request)["message_type"] == "SUBTASK_REQUEST"
        assert pairs.get(str(request["seq"])) == str(result["seq"]), result["seq"]
    # A message naming nothing stays unpaired, the CONSULT_RESPONSE bus row
    # apart, which the bus sends without `in_reply_to` and which pairs by its
    # correlation id (the consultation's).
    for row in rows:
        if row["topic"] in MESSAGE_TOPICS and not _detail(row)["in_reply_to"] \
                and _detail(row).get("message_type") != "CONSULT_RESPONSE":
            assert str(row["seq"]) not in responses


def test_every_consult_response_pairs_to_a_request_of_its_consultation(model_rows):
    pairs = feed.pair(model_rows)
    by_seq = _by_seq(model_rows)
    responses = [r for r in model_rows if r["topic"] == "consult_response"]
    assert responses
    paired = {int(v): int(k) for k, v in pairs.items()}
    for response in responses:
        request = by_seq[paired[response["seq"]]]
        assert request["topic"] in ("consult_question", "consult_delegation")
        assert _detail(request)["consultation_id"] == _detail(response)["consultation_id"]
        assert request["actor"] == response["target"] and request["target"] == response["actor"]


def test_every_consult_response_bus_row_pairs_to_the_request_of_its_correlation(model_rows):
    """The bus twins of a consultation exchange pair by `correlation_id`, message rows only."""
    pairs = feed.pair(model_rows)
    by_seq = _by_seq(model_rows)
    paired = {int(v): int(k) for k, v in pairs.items()}
    responses = [r for r in model_rows if _detail(r).get("message_type") == "CONSULT_RESPONSE"]
    requests = [r for r in model_rows if _detail(r).get("message_type") == "CONSULT_REQUEST"]
    assert responses and requests
    for response in responses:
        assert _detail(response)["in_reply_to"] == ""      # what the bus writes
        request = by_seq[paired[response["seq"]]]
        assert request["topic"] in MESSAGE_TOPICS
        assert _detail(request)["message_type"] == "CONSULT_REQUEST"
        assert request["correlation_id"] == response["correlation_id"]
        assert request["actor"] == response["target"] and request["target"] == response["actor"]
    # One response per request: no two responses share a request.
    answered = [paired[r["seq"]] for r in responses]
    assert len(answered) == len(set(answered))
    assert set(answered) <= {r["seq"] for r in requests}


def test_pair_keys_and_reply_targets_are_the_events_own_ids(rows):
    for row in rows:
        detail = _detail(row)
        key = feed.pair_key_of(row)
        reply_to = feed.reply_to_of(row)
        if row["topic"] in MESSAGE_TOPICS:
            assert key == detail["message_id"]
            assert reply_to == detail["in_reply_to"]
        elif row["topic"].startswith("consult_"):
            assert key == detail["consultation_id"]
            if row["topic"] == "consult_response":
                assert reply_to == detail["consultation_id"]
            else:
                assert reply_to == ""
        else:
            assert key == "" and reply_to == ""


# --------------------------------------------------------------------- latency
def test_latency_ms_only_where_the_event_carries_it_and_ticks_only_when_paired(rows):
    by_seq = _by_seq(rows)
    pairs = feed.pair(rows)
    paired = {int(k): by_seq[int(v)] for k, v in pairs.items()}
    with_ms = with_ticks = 0
    for row in rows:
        response = paired.get(row["seq"])
        got = feed.latency_of(row, response)
        assert set(got) == {"latency_ms", "latency_ticks"}
        carried = _detail(row).get("latency_ms")
        if isinstance(carried, (int, float)) and not isinstance(carried, bool):
            with_ms += 1
            assert got["latency_ms"] == float(carried), row["seq"]
            assert row["topic"] in ("llm_call", "consult_response", "consult_closed",
                                    "decision"), row["seq"]
            if row["topic"] == "decision":
                assert _detail(row)["mode"] == "llm"
        else:
            assert got["latency_ms"] is None, row["seq"]
        if response is not None and TYPES[row["interaction_type"]].latency == "ticks":
            with_ticks += 1
            assert got["latency_ticks"] == response["tick"] - row["tick"], row["seq"]
            assert got["latency_ticks"] >= 0
        else:
            assert got["latency_ticks"] is None, row["seq"]
        # Without a paired response there are never ticks, whatever the hint.
        assert feed.latency_of(row)["latency_ticks"] is None
    assert with_ticks > 0


# ----------------------------------------------------------------------- model
def test_the_model_appears_only_on_channel_b_rows_and_model_backed_decisions(rows):
    by_consultation = feed.models_by_consultation(rows)
    named = 0
    for row in rows:
        model = feed.model_of(row, by_consultation)
        detail = _detail(row)
        if model is not None:
            named += 1
            assert model == MODEL, row["seq"]
            assert row["channel"] == "B" or (row["topic"] == "decision"
                                             and detail.get("mode") == "llm"), row["seq"]
        if row["channel"] in ("D", "E", "system", "A", "C"):
            assert model is None, row["seq"]
        if row["topic"] == "decision" and detail.get("mode") != "llm":
            assert model is None, row["seq"]
        if row["topic"] == "llm_call" or row["topic"].startswith("consult_"):
            assert model == detail["model"], row["seq"]
    if any(r["topic"] == "llm_call" for r in rows):
        assert named > 0
    else:
        assert named == 0


def test_a_model_backed_decision_names_the_model_of_its_consultation(model_rows):
    by_consultation = feed.models_by_consultation(model_rows)
    decisions = [r for r in model_rows
                 if r["topic"] == "decision" and _detail(r).get("mode") == "llm"]
    assert decisions
    for row in decisions:
        source = str(_detail(row).get("source") or "")
        consultation_id = _detail(row).get("consultation_id") or ""
        model = feed.model_of(row, by_consultation)
        assert source.startswith("crewai:") and consultation_id in by_consultation, row["seq"]
        assert model == by_consultation[consultation_id] == MODEL
        # Without the consultation's rows, only the configured model is left;
        # the source is never parsed, whatever follows the model's name in it.
        assert feed.model_of(row, {}) is None
        assert feed.model_of(row, None) is None
        assert feed.model_of(row, {}, configured_model=MODEL) == MODEL


def _decision(source: str, consultation_id: str = "") -> dict:
    detail = {"decision": "choose_robot", "choice": "R1", "mode": "llm", "source": source}
    if consultation_id:
        detail["consultation_id"] = consultation_id
    return {"seq": 1, "tick": 3, "category": "agent", "topic": "decision", "actor": "SCHEDULING",
            "target": "", "correlation_id": "", "detail": detail,
            "interaction_type": "decision", "channel": "decision"}


@pytest.mark.parametrize("source, with_configured", [
    ("crewai:qwen3:8b", MODEL),
    ("crewai:qwen3:8b:rule-after-refusal", MODEL),
    ("fallback:rule-after-refusal", None),
    ("fallback:refused", None),
])
def test_the_source_is_never_parsed_for_a_model_name(source, with_configured):
    """
    No consultation names the model (the brain's service raised, or the rows
    the page holds no longer include the consultation): a `crewai:` source
    gives the configured model, a `fallback` source gives None whatever follows
    its colon, and without a configured model nothing is named.
    """
    row = _decision(source)
    assert feed.model_of(row, {}) is None
    assert feed.model_of(row, None) is None
    assert feed.model_of(row, {}, configured_model=MODEL) == with_configured
    assert feed.model_of(row, {"CSL-0009": "other:1b"}, configured_model=MODEL) == with_configured
    # The linked consultation wins over the configured model when it is known.
    linked = _decision(source, "CSL-0001")
    assert feed.model_of(linked, {"CSL-0001": "other:1b"}, configured_model=MODEL) == "other:1b"
    assert feed.model_of(linked, {}, configured_model=MODEL) == with_configured
    # A rule decision never names a model, whatever its source says.
    rule = _decision(source)
    rule["detail"]["mode"] = "deterministic"
    assert feed.model_of(rule, {"CSL-0001": MODEL}, configured_model=MODEL) is None
    assert feed.feed_row(row, configured_model=MODEL)["model"] == with_configured


# ------------------------------------------------------------------- the chain
def test_chain_keys_are_the_events_own_identifiers(rows):
    for row in rows:
        detail = _detail(row)
        want = {row["correlation_id"]} | {detail.get(k) for k in (
            "consultation_id", "message_id", "in_reply_to", "parcel_id", "task_id")}
        want = {str(v) for v in want if v}
        assert feed.chain_keys_of(row) == want, row["seq"]


def test_a_decisions_chain_includes_the_consultation_it_names(model_rows):
    decisions = [r for r in model_rows if r["topic"] == "decision"
                 and _detail(r).get("consultation_id")]
    assert decisions
    for seed in decisions:
        selected = feed.chain_select(model_rows, seed)
        consultation_id = _detail(seed)["consultation_id"]
        consultation = {r["seq"] for r in model_rows
                        if consultation_id in feed.chain_keys_of(r)}
        assert consultation and consultation <= selected
        assert seed["seq"] in selected
        # Nothing selected is unrelated: every row shares a key with the seed,
        # or belongs to a consultation a selected decision names.
        keys = feed.chain_keys_of(seed)
        named = {_detail(r)["consultation_id"] for r in model_rows
                 if r["seq"] in selected and r["topic"] == "decision"
                 and _detail(r).get("consultation_id")}
        for seq in selected:
            row = next(r for r in model_rows if r["seq"] == seq)
            assert feed.chain_keys_of(row) & (keys | named), seq


def test_a_parcel_id_selects_its_rows_and_nothing_else(rules_rows):
    parcel_ids = sorted({_detail(r).get("parcel_id") for r in rules_rows
                         if _detail(r).get("parcel_id")})
    assert parcel_ids
    checked = 0
    for parcel_id in parcel_ids[:5]:
        selected = feed.chain_select_by_id(rules_rows, parcel_id)
        want = {r["seq"] for r in rules_rows
                if r["correlation_id"] == parcel_id or _detail(r).get("parcel_id") == parcel_id}
        assert selected == want, parcel_id
        checked += len(want)
    assert checked > 10


def test_chain_select_by_id_on_the_model_run_adds_only_named_consultations(model_rows):
    parcel_ids = sorted({_detail(r).get("parcel_id") for r in model_rows
                         if _detail(r).get("parcel_id")})
    for parcel_id in parcel_ids[:5]:
        selected = feed.chain_select_by_id(model_rows, parcel_id)
        direct = {r["seq"] for r in model_rows
                  if r["correlation_id"] == parcel_id or _detail(r).get("parcel_id") == parcel_id}
        assert direct <= selected
        named = {_detail(r)["consultation_id"] for r in model_rows
                 if r["seq"] in direct and r["topic"] == "decision"
                 and _detail(r).get("consultation_id")}
        extra = {r["seq"] for r in model_rows if feed.chain_keys_of(r) & named}
        assert selected == direct | extra, parcel_id


def test_an_unknown_id_selects_nothing(rows):
    assert feed.chain_select_by_id(rows, "NO-SUCH-ID") == set()
    assert feed.chain_select_by_id(rows, "") == set()


# ---------------------------------------------------------------- the display
def test_every_feed_row_is_json_and_recomputes_from_the_helpers(rows):
    by_seq = _by_seq(rows)
    pairs = feed.pair(rows)
    by_consultation = feed.models_by_consultation(rows)
    requests_by_response = {int(v): int(k) for k, v in pairs.items()}
    keys = {"tick", "sender", "receiver", "interaction_type", "channel", "request",
            "response", "decision", "latency_ms", "latency_ticks", "model", "edge", "seq",
            "paired_seq", "chain_keys"}
    paired_rows = 0
    for row in rows:
        response = by_seq.get(int(pairs.get(str(row["seq"]), -1)))
        request = by_seq.get(requests_by_response.get(row["seq"], -1))
        assert response is None or request is None, "a row is both a request and a reply"
        shown = feed.feed_row(row, response, by_consultation, MODEL, paired_request=request)
        assert set(shown) == keys, row["seq"]
        json.dumps(shown)
        assert shown["seq"] == row["seq"] and shown["tick"] == row["tick"]
        if response is not None:
            paired_rows += 1
            assert shown["paired_seq"] == response["seq"]
        elif request is not None:
            paired_rows += 1
            assert shown["paired_seq"] == request["seq"]
        else:
            assert shown["paired_seq"] is None
        assert shown["sender"] == (row["actor"] or "(none)")
        assert shown["receiver"] == feed.receiver_of(row)
        assert shown["interaction_type"] == row["interaction_type"]
        assert shown["channel"] == row["channel"]
        assert shown["request"] == feed.request_text_of(row)
        if row["interaction_type"] in RESPONSE_TYPES:
            assert shown["response"] == feed.response_text_of(row)
        elif response is not None:
            assert shown["response"] == feed.reply_text_of(response)
            # The reply's own fields and nothing else.
            reply_detail = _detail(response)
            assert shown["response"] in (reply_detail.get("text"), describe(response))
        else:
            assert shown["response"] == ""
        assert shown["decision"] == feed.decision_text_of(row)
        latency = feed.latency_of(row, response)
        assert shown["latency_ms"] == latency["latency_ms"]
        assert shown["latency_ticks"] == latency["latency_ticks"]
        assert shown["model"] == feed.model_of(row, by_consultation, MODEL)
        edge = feed.edge_of(row)
        assert shown["edge"] == (None if edge is None else list(edge))
        assert shown["chain_keys"] == sorted(feed.chain_keys_of(row))
    assert paired_rows == 2 * len(pairs)


def test_a_paired_request_row_shows_its_reply(model_rows):
    by_seq = _by_seq(model_rows)
    pairs = feed.pair(model_rows)
    shown = 0
    for request_seq, response_seq in pairs.items():
        request, response = by_seq[int(request_seq)], by_seq[int(response_seq)]
        row = feed.feed_row(request, response)
        if _detail(response).get("text"):
            shown += 1
            assert row["response"] == _detail(response)["text"]
    assert shown > 0
