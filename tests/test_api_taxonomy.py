"""
The API carries the taxonomy (spec 5, 8): `/taxonomy`, the stamped `/events` rows, the
WebSocket relay and the `/frame` message rows.

`GET /taxonomy` is `taxonomy.table()` and nothing else, served no-store like the other
reads. Every `/events` row and every `event` message on the socket carries
`interaction_type` and `channel`, and a message row's detail carries `in_reply_to`. Each
`m` row of `/frame` has seven elements, the last two being the channel and the
interaction type `classify` gives for the first five, equal to the stamp of the message's
own event.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from post_office.api import server
from post_office.api.runner import SimulationRunner
from post_office.communication import taxonomy
from post_office.crew.console import quiet
from tests.fake_ollama import FakeOllama, deciding_script

MESSAGE_TOPICS = {"message", "subagent_message"}


@pytest.fixture(scope="module")
def fake():
    made = FakeOllama()
    made.script(deciding_script("Take the first: its way is clear."))
    try:
        yield made
    finally:
        made.stop()


@pytest.fixture(scope="module")
def served(fake):
    """A model-mode runner stepped past the first consultations, and a client over it."""
    with quiet():
        runner = SimulationRunner(settings=fake.settings, tick_seconds=0)
        previous = server.use(runner)
        try:
            runner.eco.start()
            runner.step(25)
            with TestClient(server.app) as test_client:
                yield test_client, runner
        finally:
            server.use(previous)
            runner.close()


# ------------------------------------------------------------------ /taxonomy
def test_the_taxonomy_route_serves_the_table(served):
    client, _ = served
    response = client.get("/taxonomy")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    body = response.json()
    assert body == taxonomy.table()
    assert body == json.loads(json.dumps(body))
    assert {c["id"] for c in body["channels"]} == set(taxonomy.CHANNELS)
    assert [t["interaction_type"] for t in body["types"]] == list(taxonomy.TYPES)


def test_the_taxonomy_route_answers_without_a_runner():
    previous = server.use(None)
    try:
        with TestClient(server.app) as client:
            assert client.get("/taxonomy").json() == taxonomy.table()
    finally:
        server.use(previous)


# -------------------------------------------------------------------- /events
def _expected(row) -> taxonomy.Classification:
    detail = row.get("detail") or {}
    content = detail.get("content")
    content_type = content.get("interaction_type", "") if isinstance(content, dict) else ""
    return taxonomy.classify(row["category"], row["topic"], row["actor"], row["target"],
                             detail.get("message_type", ""), content_type=content_type)


def test_every_events_row_carries_the_two_fields_and_messages_in_reply_to(served):
    client, _ = served
    rows = client.get("/events", params={"limit": 2000}).json()["events"]
    assert len(rows) > 200
    messages = 0
    for row in rows:
        assert row["interaction_type"] in taxonomy.TYPES, row["seq"]
        assert row["channel"] in taxonomy.CHANNELS, row["seq"]
        want = _expected(row)
        assert (row["interaction_type"], row["channel"]) == \
            (want.interaction_type, want.channel), row["seq"]
        assert "text" in row
        if row["topic"] in MESSAGE_TOPICS:
            messages += 1
            assert "in_reply_to" in row["detail"], row["seq"]
            assert isinstance(row["detail"]["in_reply_to"], str)
    assert messages > 50
    assert {row["channel"] for row in rows} >= {"A", "B", "C", "D", "E", "decision"}


# ------------------------------------------------------------------------ /ws
def test_the_socket_relays_events_with_the_two_fields(served):
    client, runner = served
    with client.websocket_connect("/ws") as socket:
        hello = socket.receive_json()
        assert hello["type"] == "hello"
        # Step until twenty events have been logged, then read exactly what
        # the relay owes: one `event` payload per event and one `tick` per step.
        before = runner.eco.logger.total
        ticks = 0
        with quiet():
            while runner.eco.logger.total - before < 20:
                runner.step(1)
                ticks += 1
        emitted = runner.eco.logger.total - before
        payloads = [socket.receive_json() for _ in range(emitted + ticks)]
    assert {p["type"] for p in payloads} == {"event", "tick"}
    events = [p for p in payloads if p["type"] == "event"]
    assert len(events) == emitted >= 20
    assert [p["seq"] for p in events] == list(range(before + 1, before + emitted + 1))
    for payload in events:
        assert payload["interaction_type"] in taxonomy.TYPES, payload["seq"]
        assert payload["channel"] in taxonomy.CHANNELS, payload["seq"]
        want = _expected(payload)
        assert (payload["interaction_type"], payload["channel"]) == \
            (want.interaction_type, want.channel), payload["seq"]
        if payload["topic"] in MESSAGE_TOPICS:
            assert "in_reply_to" in payload["detail"]


# --------------------------------------------------------------------- /frame
def _said_at(eco, tick: int):
    """The bus messages of one tick, in the order `frame_of` lists them."""
    return [m for m in eco.bus.log.recent(400) if m.tick == tick]


def _stamps(runner):
    """message_id -> (channel, interaction_type) as the logger stamped the
    `message` / `subagent_message` event of each carried bus message."""
    return {str(event.detail.get("message_id") or ""): (event.channel, event.interaction_type)
            for event in runner.eco.logger.recent(limit=10 ** 7)
            if event.topic in MESSAGE_TOPICS}


def _check_m_rows(rows, messages, stamps=None) -> int:
    """
    Each row's last two elements are `classify` of its first five, recomputed
    with the content's `interaction_type` from the bus message the row was
    built from (the row itself does not carry the content). The topic is not
    recomputed: `classify` has no rule reading `message` against
    `subagent_message`, so the test cannot tell the two apart and does not
    claim to; `views._channel_and_type` names it as the bus does. With
    `stamps`, the two elements must also equal the stamp of the message's own
    event, so the frame's recomputation and the logger's agree row for row.
    """
    assert len(rows) == len(messages)
    for row, m in zip(rows, messages):
        assert len(row) == 7, row
        sender, receiver, text, correlation_id, message_type, channel, kind = row
        assert (sender, receiver, message_type) == (m.sender, m.receiver, m.message_type.value)
        assert isinstance(channel, str) and isinstance(kind, str)
        assert channel in taxonomy.CHANNELS and kind in taxonomy.TYPES
        content_type = m.content.get("interaction_type", "") if isinstance(m.content, dict) else ""
        want = taxonomy.classify("communication", "message", sender, receiver, message_type,
                                 content_type=content_type)
        assert (channel, kind) == (want.channel, want.interaction_type), row
        if stamps is not None:
            assert m.message_id in stamps, (m.tick, m.message_id)
            assert (channel, kind) == stamps[m.message_id], row
    return len(rows)


def test_the_frame_rows_carry_channel_and_type_after_the_first_five(served):
    client, runner = served
    frame = client.get("/frame").json()
    assert frame["m"] == runner.last_frame["frame"]["m"]
    stamps = _stamps(runner)
    _check_m_rows(frame["m"], _said_at(runner.eco, int(runner.last_frame["tick"])), stamps)
    # The served frame holds one tick; the builder holds the recent ticks, so
    # every message type the run has produced so far is checked as well.
    from post_office.ui.views import frame_of

    checked = 0
    types = set()
    for tick in range(0, int(runner.eco.world.tick) + 1):
        rows = frame_of(runner.eco, tick=tick)["m"]
        checked += _check_m_rows(rows, _said_at(runner.eco, tick), stamps)
        types.update(row[4] for row in rows)
    assert checked > 50
    assert {"TASK_ASSIGNMENT", "SUBTASK_REQUEST", "SUBTASK_RESULT", "CONSULT_REQUEST"} <= types


def test_a_frame_row_keeps_its_first_five_elements(served):
    _, runner = served
    from post_office.ui.views import frame_of

    tick = int(runner.eco.world.tick)
    said = [m for m in runner.eco.bus.log.recent(400) if m.tick == tick]
    rows = frame_of(runner.eco, tick=tick)["m"]
    assert len(rows) == len(said)
    for m, row in zip(said, rows):
        assert row[:5] == [m.sender, m.receiver, m.text or m.message_type.value,
                           m.correlation_id, m.message_type.value]
