"""
Phase 3: the message bus, the hierarchy it enforces, and the event log.

The important tests here are the negative ones. Anybody can make a message
arrive; the question is whether a message that should not exist is stopped and
written down.
"""

from __future__ import annotations

import json
import os

from post_office.communication import (AgentKind, Directory, EventCategory,
                                       EventLogger, MessageBus, MessageType,
                                       read_events)


def ecosystem():
    """A miniature hierarchy: supervisor, planner, two experts, two sub-agents."""
    directory = Directory()
    logger = EventLogger(run_id="test")
    bus = MessageBus(directory, logger)
    bus.register("SUPERVISOR", AgentKind.SUPERVISOR, role="supervisor")
    bus.register("PLANNER", AgentKind.PLANNER, role="planner",
                 parent_id="SUPERVISOR")
    bus.register("SORTING", AgentKind.EXPERT, role="sorting",
                 parent_id="PLANNER")
    bus.register("ROUTING", AgentKind.EXPERT, role="routing",
                 parent_id="PLANNER")
    bus.register("SUB-BARCODE", AgentKind.SUBAGENT, role="barcode",
                 parent_id="SORTING")
    bus.register("SUB-ROUTE", AgentKind.SUBAGENT, role="route planning",
                 parent_id="ROUTING")
    bus.register("R1", AgentKind.ROBOT, role="transport", parent_id="ROUTING")
    return bus, logger


# ---------------------------------------------------------------- delivery
def test_a_message_arrives_on_the_next_tick_not_this_one():
    bus, _ = ecosystem()
    bus.advance(1)
    bus.send("SORTING", "SUB-BARCODE", MessageType.SUBTASK_REQUEST,
             {"parcel_id": "P-0001"}, correlation_id="P-0001")
    assert bus.peek("SUB-BARCODE") == []      # not yet: same tick
    bus.advance(2)
    bus.deliver()
    inbox = bus.inbox("SUB-BARCODE")
    assert len(inbox) == 1
    assert inbox[0].content["parcel_id"] == "P-0001"
    assert bus.inbox("SUB-BARCODE") == []     # reading empties it


def test_a_sender_cannot_forge_another_agents_identity():
    bus, _ = ecosystem()
    send = bus.sender_for("SUB-BARCODE")
    message = send("SORTING", MessageType.SUBTASK_RESULT, {"ok": True})
    assert message.sender == "SUB-BARCODE"


# ---------------------------------------------------- the hierarchy is real
def test_a_subagent_may_talk_to_its_parent():
    bus, _ = ecosystem()
    assert bus.send("SUB-BARCODE", "SORTING", MessageType.SUBTASK_RESULT) is not None


def test_a_subagent_may_not_talk_to_the_supervisor():
    bus, logger = ecosystem()
    assert bus.send("SUB-BARCODE", "SUPERVISOR", MessageType.STATUS_REPORT) is None
    assert bus.log.refused == 1
    refusal = bus.log.refusals()[-1]
    assert "only address its parent" in refusal["reason"]
    assert any(e.topic == "message_refused" for e in logger.recent(20))


def test_a_subagent_may_not_talk_to_another_experts_subagent():
    bus, _ = ecosystem()
    assert bus.send("SUB-BARCODE", "SUB-ROUTE", MessageType.SUBTASK_REQUEST) is None


def test_an_expert_may_not_reach_into_another_experts_subagent():
    bus, _ = ecosystem()
    assert bus.send("ROUTING", "SUB-BARCODE", MessageType.SUBTASK_REQUEST) is None
    assert "must go through it" in bus.log.refusals()[-1]["reason"]


def test_the_supervisor_talks_only_to_the_planner():
    bus, _ = ecosystem()
    assert bus.send("SUPERVISOR", "PLANNER", MessageType.OBJECTIVE) is not None
    assert bus.send("SUPERVISOR", "SORTING", MessageType.OBJECTIVE) is None


def test_experts_may_consult_each_other():
    bus, _ = ecosystem()
    assert bus.send("SORTING", "ROUTING", MessageType.ROUTE_REQUEST) is not None


def test_a_robot_reports_to_an_expert_and_not_to_the_planner():
    bus, _ = ecosystem()
    assert bus.send("R1", "ROUTING", MessageType.ROBOT_REPORT) is not None
    assert bus.send("R1", "PLANNER", MessageType.ROBOT_REPORT) is None


def test_an_unknown_receiver_is_refused_rather_than_crashing_the_run():
    bus, _ = ecosystem()
    assert bus.send("PLANNER", "NOBODY", MessageType.TASK_ASSIGNMENT) is None
    assert "unknown receiver" in bus.log.refusals()[-1]["reason"]


# ------------------------------------------------------------------- the log
def test_every_message_is_in_the_log_including_the_refused_ones():
    bus, _ = ecosystem()
    bus.send("SORTING", "SUB-BARCODE", MessageType.SUBTASK_REQUEST)
    bus.send("SUB-BARCODE", "SUPERVISOR", MessageType.STATUS_REPORT)
    assert bus.log.sent == 1 and bus.log.refused == 1


def test_a_correlation_id_gathers_one_parcels_whole_story():
    bus, _ = ecosystem()
    for pair, kind in (("SORTING SUB-BARCODE", MessageType.SUBTASK_REQUEST),
                       ("SUB-BARCODE SORTING", MessageType.SUBTASK_RESULT),
                       ("SORTING PLANNER", MessageType.TASK_COMPLETED)):
        a, b = pair.split()
        bus.send(a, b, kind, correlation_id="P-0007")
    bus.send("SORTING", "ROUTING", MessageType.ROUTE_REQUEST,
             correlation_id="P-0008")
    thread = bus.log.thread("P-0007")
    assert len(thread) == 3
    assert [m.message_type for m in thread] == [
        MessageType.SUBTASK_REQUEST, MessageType.SUBTASK_RESULT,
        MessageType.TASK_COMPLETED]


def test_the_interaction_graph_needs_no_knowledge_of_parcels():
    bus, _ = ecosystem()
    bus.send("SORTING", "SUB-BARCODE", MessageType.SUBTASK_REQUEST)
    bus.send("SORTING", "SUB-BARCODE", MessageType.SUBTASK_REQUEST)
    bus.send("SUB-BARCODE", "SORTING", MessageType.SUBTASK_RESULT)
    counts = bus.log.interaction_counts()
    assert counts["SORTING->SUB-BARCODE"] == 2
    assert counts["SUB-BARCODE->SORTING"] == 1


def test_a_subagent_message_is_marked_as_one_in_the_event_log():
    # The spec asks for sub-agent communication to be distinguishable in the
    # logs, so a monitor can count it separately.
    bus, logger = ecosystem()
    bus.send("SUB-BARCODE", "SORTING", MessageType.SUBTASK_RESULT)
    topics = [e.topic for e in logger.recent(10, category=EventCategory.COMMUNICATION)]
    assert "subagent_message" in topics


# ----------------------------------------------------------------- the file
def test_the_event_log_round_trips_through_a_file(tmp_path):
    path = os.path.join(str(tmp_path), "run.events.jsonl")
    with EventLogger(run_id="rt", path=path) as logger:
        logger.emit(EventCategory.PARCEL, "parcel_arrived", tick=1,
                    actor="ENV", correlation_id="P-0001", zone="INTAKE")
        logger.emit(EventCategory.ROBOT, "moved", tick=2, actor="R1", cells=1)
    rows = list(read_events(path))
    assert [r["topic"] for r in rows] == ["parcel_arrived", "moved"]
    assert rows[0]["correlation_id"] == "P-0001"
    assert rows[0]["detail"]["zone"] == "INTAKE"
    json.dumps(rows)


def test_a_live_subscriber_sees_events_as_they_happen():
    # This is the mechanism the WebSocket stream is built on.
    seen = []
    logger = EventLogger(run_id="sub")
    stop = logger.subscribe(seen.append)
    logger.emit(EventCategory.SIMULATION, "started", tick=0)
    stop()
    logger.emit(EventCategory.SIMULATION, "stopped", tick=1)
    assert [e.topic for e in seen] == ["started"]


def test_a_broken_subscriber_does_not_stop_the_run():
    logger = EventLogger(run_id="sub")
    logger.subscribe(lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    logger.emit(EventCategory.SIMULATION, "started", tick=0)
    assert logger.total == 1


def test_a_sink_lets_the_environment_log_without_importing_the_logger():
    from post_office.environment import build_environment
    logger = EventLogger(run_id="sink")
    env = build_environment(storage_capacity=1)
    env.set_event_sink(logger.sink_for(EventCategory.RESOURCE, actor="ENVIRONMENT"))
    env.claim_storage("P-0001")
    env.claim_storage("P-0002")
    topics = [e.topic for e in logger.recent(10)]
    assert "storage_claimed" in topics and "storage_refused" in topics


# ------------------------------------------------------------------- the tree
def test_the_directory_reports_the_hierarchy_as_a_tree():
    bus, _ = ecosystem()
    tree = bus.directory.tree()
    assert tree["roots"][0]["agent_id"] == "SUPERVISOR"
    planner = tree["roots"][0]["children"][0]
    assert planner["agent_id"] == "PLANNER"
    experts = {c["agent_id"] for c in planner["children"]}
    assert experts == {"SORTING", "ROUTING"}


def test_a_new_run_starts_its_log_from_empty(tmp_path):
    """
    The log belongs to the run, not to the folder.

    It used to be opened for appending, so every run in a session piled onto
    the one before it in the same file: the first line of `run.events.jsonl`
    was from whenever the file was first created, weeks of runs were
    interleaved by nothing but a `run_id` field, and the file on the machine
    this was written on had reached 1.4 GB. Starting a run initialises its
    log, which is also what makes the file worth opening afterwards -- what is
    in it is this run and nothing else.
    """
    path = os.path.join(str(tmp_path), "run.events.jsonl")
    with EventLogger(run_id="first", path=path) as logger:
        logger.emit(EventCategory.PARCEL, "parcel_arrived", tick=1, actor="ENV")
        logger.emit(EventCategory.ROBOT, "moved", tick=2, actor="R1")
    assert len(list(read_events(path))) == 2

    with EventLogger(run_id="second", path=path) as logger:
        logger.emit(EventCategory.ROBOT, "moved", tick=1, actor="R2")

    rows = list(read_events(path))
    assert [r["run_id"] for r in rows] == ["second"], \
        "the new run's log still holds the previous run's events"
