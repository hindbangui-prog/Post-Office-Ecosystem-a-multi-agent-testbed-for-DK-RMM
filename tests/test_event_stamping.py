"""
Every event is stamped with its interaction type and channel (spec 2.1, 4, 8).

The logger computes `taxonomy.classify` once per event and writes the result
onto the event, so `events.jsonl`, `recent()`, `since()` and every subscriber
see the same two fields. The bus adds `in_reply_to` to the detail of the
messages it carries. Nothing else about an event changes: a run stamped by a
stub classifier, with the three new keys removed, is the same record as a run
stamped normally with the same keys removed.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

import pytest

from post_office.communication import EventCategory, EventLogger, read_events
from post_office.communication import events as events_module
from post_office.communication.taxonomy import Classification, classify
from post_office.config.settings import normal_config
from post_office.simulation.ecosystem import build

#: The keys `as_dict()` wrote before stamping, in their order.
OLD_KEYS = ["seq", "tick", "wall_clock", "run_id", "category", "topic", "actor", "target",
            "correlation_id", "detail"]
NEW_KEYS = ["interaction_type", "channel"]

TICKS = 60


def _content_type(detail: dict) -> str:
    content = detail.get("content")
    if isinstance(content, dict):
        return str(content.get("interaction_type", "") or "")
    return ""


def _expected(category, topic, actor, target, detail) -> Classification:
    return classify(category, topic, actor, target, detail.get("message_type", ""),
                    content_type=_content_type(detail))


def _run(log_path: str, run_id: str, ticks: int = TICKS):
    eco = build(seed=1, config=normal_config(), run_id=run_id, scenario="normal",
                log_path=log_path)
    eco.start()
    try:
        for _ in range(ticks):
            eco.step()
        events = eco.logger.recent(limit=10 ** 7)
        assert len(events) == eco.logger.total
        since = eco.logger.since(after=0, limit=10 ** 7)
        eco.logger.flush()
    finally:
        eco.close()
    return events, since


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    path = os.path.join(str(tmp_path_factory.mktemp("stamping")), "events.jsonl")
    events, since = _run(path, "stamping")
    rows = list(read_events(path))
    return {"events": events, "since": since, "rows": rows}


# ------------------------------------------------------------ the two fields
def test_every_kept_event_is_stamped_with_what_classify_says(run):
    assert len(run["events"]) > 500
    for event in run["events"]:
        want = _expected(event.category, event.topic, event.actor, event.target, event.detail)
        assert event.interaction_type, (event.seq, event.topic)
        assert event.channel, (event.seq, event.topic)
        assert (event.interaction_type, event.channel) == \
            (want.interaction_type, want.channel), (event.seq, event.topic)


def test_since_returns_the_same_stamped_events(run):
    assert [e.seq for e in run["since"]] == [e.seq for e in run["events"]]
    for event in run["since"]:
        assert event.interaction_type and event.channel


def test_every_line_of_the_jsonl_log_is_stamped(run):
    rows = run["rows"]
    assert len(rows) == len(run["events"])
    for row in rows:
        want = _expected(row["category"], row["topic"], row["actor"], row["target"],
                         row["detail"])
        assert row["interaction_type"] == want.interaction_type, (row["seq"], row["topic"])
        assert row["channel"] == want.channel, (row["seq"], row["topic"])
        assert row["interaction_type"] and row["channel"]


def test_as_dict_writes_the_old_keys_first_then_the_two_new_ones(run):
    for event in run["events"]:
        assert list(event.as_dict().keys()) == OLD_KEYS + NEW_KEYS
    for row in run["rows"]:
        assert list(row.keys()) == OLD_KEYS + NEW_KEYS


# ---------------------------------------------------------------- in_reply_to
def _messages(run) -> List:
    return [e for e in run["events"] if e.topic in ("message", "subagent_message")]


def test_message_events_carry_in_reply_to(run):
    messages = _messages(run)
    assert messages
    for event in messages:
        assert "in_reply_to" in event.detail, (event.seq, event.detail.get("message_type"))
        assert isinstance(event.detail["in_reply_to"], str)


def test_a_reply_names_the_request_it_answers(run):
    by_id: Dict[str, object] = {e.detail["message_id"]: e for e in _messages(run)}
    pairs = {"SUBTASK_RESULT": {"SUBTASK_REQUEST"},
             "ROUTE_RESPONSE": {"ROUTE_REQUEST"},
             "RESOURCE_GRANT": {"RESOURCE_REQUEST"}}
    seen = set()
    for event in _messages(run):
        kind = event.detail.get("message_type")
        if kind not in pairs or kind in seen:
            continue
        reply_to = event.detail["in_reply_to"]
        assert reply_to, (event.seq, kind)
        request = by_id[reply_to]
        assert request.detail["message_type"] in pairs[kind], (event.seq, kind)
        assert request.actor == event.target and request.target == event.actor
        assert request.seq < event.seq
        seen.add(kind)
    assert "SUBTASK_RESULT" in seen
    assert seen & {"ROUTE_RESPONSE", "RESOURCE_GRANT"}


def test_a_message_without_a_reply_target_has_an_empty_in_reply_to(run):
    requests = [e for e in _messages(run)
                if e.detail.get("message_type") in ("OBJECTIVE", "TASK_ASSIGNMENT")]
    assert requests
    for event in requests:
        assert event.detail["in_reply_to"] == ""


def test_a_refused_message_does_not_gain_in_reply_to():
    from post_office.communication import AgentKind, Directory, MessageBus, MessageType

    directory = Directory()
    logger = EventLogger(run_id="refused")
    bus = MessageBus(directory, logger)
    bus.register("SUPERVISOR", AgentKind.SUPERVISOR)
    bus.register("PLANNER", AgentKind.PLANNER)
    bus.register("ROUTING", AgentKind.EXPERT)
    assert bus.send("SUPERVISOR", "ROUTING", MessageType.OBJECTIVE, {}, in_reply_to="M-1") \
        is None
    refused = [e for e in logger.recent(limit=100) if e.topic == "message_refused"]
    assert len(refused) == 1
    assert "in_reply_to" not in refused[0].detail
    assert refused[0].interaction_type == "system" and refused[0].channel == "system"
    carried = [e for e in logger.recent(limit=100) if e.topic == "message"]
    assert carried == []


# ------------------------------------------------------- the delegation case
def test_a_consult_request_whose_content_says_delegation_is_a_delegation():
    logger = EventLogger(run_id="unit")
    delegation = logger.emit(EventCategory.COMMUNICATION, "message", tick=3,
                             actor="ROUTING", target="SCHEDULING", correlation_id="C-1",
                             message_id="M-1", message_type="CONSULT_REQUEST",
                             content={"interaction_type": "delegation", "task": "x"},
                             text="please", in_reply_to="")
    question = logger.emit(EventCategory.COMMUNICATION, "message", tick=3,
                           actor="ROUTING", target="SCHEDULING", correlation_id="C-2",
                           message_id="M-2", message_type="CONSULT_REQUEST",
                           content={"interaction_type": "question"}, text="?",
                           in_reply_to="")
    bare = logger.emit(EventCategory.COMMUNICATION, "message", tick=3,
                       actor="ROUTING", target="SCHEDULING", correlation_id="C-3",
                       message_id="M-3", message_type="CONSULT_REQUEST",
                       content="not a dict", text="", in_reply_to="")
    assert (delegation.interaction_type, delegation.channel) == ("delegation", "B")
    assert (question.interaction_type, question.channel) == ("question", "B")
    assert (bare.interaction_type, bare.channel) == ("question", "B")
    assert delegation.as_dict()["interaction_type"] == "delegation"
    assert "fallback" not in delegation.as_dict()


def test_a_subscriber_sees_the_stamped_event():
    seen = []
    logger = EventLogger(run_id="sub", also=seen.append)
    logger.emit(EventCategory.ROBOT, "moved", tick=1, actor="R1", cells=1)
    assert seen[0].interaction_type == "robot_report" and seen[0].channel == "D"


# ------------------------------------------------------- the pre-change record
def _bare(rows: List[dict]) -> List[dict]:
    """The rows without the three new keys and without the per-run noise."""
    out = []
    for row in rows:
        row = dict(row)
        row.pop("interaction_type", None)
        row.pop("channel", None)
        row.pop("wall_clock", None)
        row.pop("run_id", None)
        detail = dict(row.get("detail") or {})
        detail.pop("in_reply_to", None)
        row["detail"] = detail
        out.append(row)
    return out


def test_removing_the_new_keys_gives_the_record_a_stub_classifier_gives(run, tmp_path,
                                                                        monkeypatch):
    def stub(*args, **kwargs):
        return Classification("", "", False)

    monkeypatch.setattr(events_module.taxonomy, "classify", stub)
    # The same run id: `simulation_started` writes it into its detail.
    path = os.path.join(str(tmp_path), "events.jsonl")
    stubbed_events, _ = _run(path, "stamping")
    stubbed_rows = list(read_events(path))
    assert stubbed_rows, "the stubbed run logged nothing"
    assert all(r["interaction_type"] == "" and r["channel"] == "" for r in stubbed_rows)
    assert all(e.interaction_type == "" and e.channel == "" for e in stubbed_events)

    # The in-memory events, through the same JSON the file is written with, and
    # the file itself: both equal the stubbed run once the three keys are gone.
    normal_rows = json.loads(json.dumps([e.as_dict() for e in run["events"]], default=str))
    assert _bare(normal_rows) == _bare(stubbed_rows)
    assert _bare(run["rows"]) == _bare(stubbed_rows)
