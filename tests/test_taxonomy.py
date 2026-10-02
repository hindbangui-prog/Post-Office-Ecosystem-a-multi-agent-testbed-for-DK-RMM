"""
The runtime communication taxonomy classifies an event from five fields (spec 3).

Each precedence case of spec 3.2 has a test here; the rest pins what every
caller relies on: every type in the table is reachable, missing fields do not
raise, the classification is a pure function and hashable, the table is JSON,
and an unknown message type falls back (so the completeness test can see it).
"""

from __future__ import annotations

import json
import re

import pytest

from post_office.communication import taxonomy
from post_office.communication.taxonomy import (CHANNELS, TYPES, Classification,
                                                agent_kind, classify, table)


def _of(category="", topic="", actor="", target="", message_type=""):
    return classify(category, topic, actor, target, message_type)


# ---------------------------------------------------------------- precedence
def test_1_decision_topic_wins_over_everything():
    got = _of("agent", "decision", "SORTING")
    assert (got.interaction_type, got.channel, got.fallback) == ("decision", "decision", False)
    # Even a decision carrying a message type or a robot actor is a decision.
    assert _of("robot", "decision", "R1", "", "ROBOT_COMMAND").interaction_type == "decision"


def test_2_llm_call_topic_is_llm_call_on_channel_b():
    got = _of("agent", "llm_call", "ROUTING")
    assert (got.interaction_type, got.channel) == ("llm_call", "B")


def test_3_consult_topics_are_question_delegation_response_or_consultation():
    assert _of("agent", "consult_question", "SCHEDULING", "ROUTING").interaction_type == "question"
    assert _of("agent", "consult_delegation", "SCHEDULING", "ROUTING").interaction_type == "delegation"
    assert _of("agent", "consult_response", "ROUTING", "SCHEDULING").interaction_type == "response"
    for topic in ("consult_opened", "consult_closed", "consult_refused"):
        got = _of("agent", topic, "SCHEDULING", "ROUTING")
        assert got.interaction_type == "consultation", topic
        assert got.channel == "B"


def test_3_consult_opened_is_consultation_not_decision():
    got = _of("agent", "consult_opened", "SCHEDULING", "ROUTING")
    assert got.interaction_type == "consultation"
    assert got.interaction_type != "decision" and got.channel == "B"


def test_4_message_type_is_read_before_any_category_rule():
    # The category of every bus message is `communication`; the type decides.
    assert _of("communication", "message", "SUPERVISOR", "PLANNER",
               "OBJECTIVE").interaction_type == "governance_instruction"
    assert _of("communication", "message", "ROUTING", "R1",
               "ROBOT_COMMAND").interaction_type == "robot_command"
    # And it decides even under another category, as the spec orders it.
    assert _of("robot", "moved", "R1", "ROUTING", "ROBOT_REPORT").interaction_type == "robot_report"


def test_4_consult_messages_are_channel_b():
    assert _of("communication", "message", "SCHEDULING", "ROUTING",
               "CONSULT_REQUEST").interaction_type == "question"
    assert _of("communication", "message", "ROUTING", "SCHEDULING",
               "CONSULT_RESPONSE").interaction_type == "response"
    close = _of("communication", "message", "SCHEDULING", "ROUTING", "CONSULT_CLOSE")
    assert (close.interaction_type, close.channel) == ("consultation", "B")


@pytest.mark.parametrize("message_type", ["OBJECTIVE", "POLICY", "PLAN_APPROVAL",
                                          "PLAN_REJECTION", "STATUS_REQUEST", "BROADCAST"])
def test_4_governance_instructions(message_type):
    got = _of("communication", "message", "SUPERVISOR", "PLANNER", message_type)
    assert (got.interaction_type, got.channel) == ("governance_instruction", "A")


@pytest.mark.parametrize("message_type", ["PLAN_PROPOSAL", "STATUS_REPORT"])
def test_4_governance_reports(message_type):
    got = _of("communication", "message", "PLANNER", "SUPERVISOR", message_type)
    assert (got.interaction_type, got.channel) == ("governance_report", "A")


def test_4_task_assignment():
    got = _of("communication", "message", "PLANNER", "SORTING", "TASK_ASSIGNMENT")
    assert (got.interaction_type, got.channel) == ("task_assignment", "A")


@pytest.mark.parametrize("message_type", ["TASK_ACCEPTED", "TASK_REJECTED", "TASK_COMPLETED",
                                          "TASK_FAILED", "TASK_PROGRESS", "WORK_NOTICE"])
def test_4_task_messages_with_planner_at_either_end_are_task_reports(message_type):
    up = _of("communication", "message", "SORTING", "PLANNER", message_type)
    down = _of("communication", "message", "PLANNER", "SORTING", message_type)
    assert (up.interaction_type, up.channel) == ("task_report", "A")
    assert (down.interaction_type, down.channel) == ("task_report", "A")


def test_4_task_failed_between_two_experts_is_expert_response():
    got = _of("communication", "message", "ROUTING", "SCHEDULING", "TASK_FAILED")
    assert (got.interaction_type, got.channel) == ("expert_response", "C")


@pytest.mark.parametrize("message_type", ["ROUTE_REQUEST", "RESOURCE_REQUEST",
                                          "SCHEDULE_REQUEST", "CHARGE_REQUEST", "ALERT"])
def test_4_expert_requests(message_type):
    got = _of("communication", "message", "SCHEDULING", "ROUTING", message_type)
    assert (got.interaction_type, got.channel) == ("expert_request", "C")


@pytest.mark.parametrize("message_type", ["ROUTE_RESPONSE", "RESOURCE_GRANT",
                                          "RESOURCE_DENIAL", "SCHEDULE_RESPONSE"])
def test_4_expert_responses(message_type):
    got = _of("communication", "message", "ROUTING", "SCHEDULING", message_type)
    assert (got.interaction_type, got.channel) == ("expert_response", "C")


def test_4_subagent_messages():
    req = _of("communication", "message", "SORTING", "SUB-BARCODE", "SUBTASK_REQUEST")
    res = _of("communication", "subagent_message", "SUB-BARCODE", "SORTING", "SUBTASK_RESULT")
    assert (req.interaction_type, req.channel) == ("subagent_request", "C")
    assert (res.interaction_type, res.channel) == ("subagent_response", "C")


def test_4_robot_messages():
    cmd = _of("communication", "message", "ROUTING", "R1", "ROBOT_COMMAND")
    rep = _of("communication", "message", "R1", "SCHEDULING", "ROBOT_REPORT")
    assert (cmd.interaction_type, cmd.channel) == ("robot_command", "D")
    assert (rep.interaction_type, rep.channel) == ("robot_report", "D")


def test_5_supervisor_category_by_actor():
    for topic in ("system_started", "system_stopped", "policy_changed",
                  "intervention_withheld", "plan_approved", "plan_rejected"):
        got = _of("supervisor", topic, "SUPERVISOR")
        assert (got.interaction_type, got.channel) == ("governance_instruction", "A"), topic
    got = _of("supervisor", "policy_applied", "PLANNER")
    assert (got.interaction_type, got.channel) == ("governance_report", "A")


def test_6_robot_category_command_topics_are_robot_commands():
    for topic in ("command_set_route", "command_step_aside", "command_transport",
                  "command_yield", "command_park", "command_abort", "command_charge"):
        got = _of("robot", topic, "ROUTING", "R1")
        assert (got.interaction_type, got.channel) == ("robot_command", "D"), topic


def test_6_robot_category_with_robot_actor_is_a_robot_report():
    for topic in ("moved", "blocked", "picked", "delivered", "yielded", "stalled",
                  "arrived_at_pickup", "arrived_at_dropoff", "passed_via", "yield_failed",
                  "charging_started", "battery_low", "pick_failed", "parked"):
        got = _of("robot", topic, "R3")
        assert (got.interaction_type, got.channel) == ("robot_report", "D"), topic


def test_6_block_resolved_with_an_expert_actor_is_environment_action():
    got = _of("robot", "block_resolved", "ROUTING", "R1")
    assert (got.interaction_type, got.channel) == ("environment_action", "E")


def test_7_task_category_lifecycle_topics_and_actions():
    for topic in ("task_created", "task_assigned", "task_started", "task_completed",
                  "task_failed", "task_released", "task_cancelled", "overdue",
                  "queue_question_timed_out"):
        got = _of("task", topic, "SCHEDULING")
        assert (got.interaction_type, got.channel) == ("task_lifecycle", "E"), topic
    assert _of("task", "task_created", "").interaction_type == "task_lifecycle"
    for topic in ("errand_handed_over", "queued_errand_rerouted"):
        got = _of("task", topic, "SCHEDULING", "R1")
        assert (got.interaction_type, got.channel) == ("environment_action", "E"), topic


def test_8_battery_low_with_a_robot_actor_is_environment_update():
    got = _of("battery", "battery_low", "R2")
    assert (got.interaction_type, got.channel) == ("environment_update", "E")
    for topic in ("battery_band", "battery_empty", "charging_started", "charging_finished",
                  "charging_interrupted", "charging_unavailable", "charge_declined"):
        assert _of("battery", topic, "R1").interaction_type == "environment_update", topic
        assert _of("battery", topic, "ENVIRONMENT").interaction_type == "environment_update"


def test_9_parcel_and_resource_by_actor():
    for actor in ("ENVIRONMENT", "SIMULATION", "INTAKE_DOCK", ""):
        got = _of("parcel", "parcel_arrived", actor)
        assert (got.interaction_type, got.channel) == ("environment_update", "E"), actor
        got = _of("resource", "storage_claimed", actor)
        assert (got.interaction_type, got.channel) == ("environment_update", "E"), actor
    assert _of("parcel", "arrival_refused", "INTAKE_DOCK").interaction_type == "environment_update"
    assert _of("parcel", "parcel_refused", "ENVIRONMENT").interaction_type == "environment_update"
    assert _of("parcel", "parcel_refused", "INTAKE").interaction_type == "environment_action"
    for actor in ("INTAKE", "PLANNER", "SUB-PACKING", "R1"):
        got = _of("parcel", "parcel_classified", actor)
        assert (got.interaction_type, got.channel) == ("environment_action", "E"), actor
    for topic in ("charge_unavailable", "top_up_started", "recovery_requested", "storage_policy"):
        assert _of("resource", topic, "RESOURCE", "R1").interaction_type == "environment_action"
    for topic in ("recovery_withdrawn", "recovery_deferred", "recovery_completed"):
        assert _of("resource", topic, "SIMULATION", "R1").interaction_type == "environment_update"


def test_10_simulation_and_housekeeping_topics_are_system():
    for topic in ("simulation_started", "simulation_stopped", "interception", "llm"):
        got = _of("simulation", topic, "SIMULATION")
        assert (got.interaction_type, got.channel, got.fallback) == ("system", "system", False)
    for topic in ("agent_created", "agent_removed"):
        got = _of("agent", topic, "SUB-BARCODE", "SORTING")
        assert (got.interaction_type, got.fallback) == ("system", False), topic
    # Bus housekeeping is system even though the detail names a message type.
    for topic in ("message_refused", "message_dropped", "agent_message_received"):
        got = _of("communication", topic, "SORTING", "ROUTING", "TASK_ASSIGNMENT")
        assert (got.interaction_type, got.channel, got.fallback) == ("system", "system", False)


def test_11_fallback_is_system_and_marked():
    got = _of("weather", "rain", "SKY")
    assert (got.interaction_type, got.channel, got.fallback) == ("system", "system", True)


def test_a_message_with_an_unknown_type_falls_back():
    got = _of("communication", "message", "SORTING", "ROUTING", "NO_SUCH_TYPE")
    assert got.fallback is True
    assert (got.interaction_type, got.channel) == ("system", "system")


# ----------------------------------------------------------------- the table
def test_every_type_is_produced_by_some_input():
    inputs = [
        ("agent", "decision", "SORTING", "", ""),
        ("agent", "llm_call", "SORTING", "", ""),
        ("agent", "consult_question", "SCHEDULING", "ROUTING", ""),
        ("agent", "consult_delegation", "SCHEDULING", "ROUTING", ""),
        ("agent", "consult_response", "ROUTING", "SCHEDULING", ""),
        ("agent", "consult_opened", "SCHEDULING", "ROUTING", ""),
        ("communication", "message", "SUPERVISOR", "PLANNER", "OBJECTIVE"),
        ("communication", "message", "PLANNER", "SUPERVISOR", "STATUS_REPORT"),
        ("communication", "message", "PLANNER", "SORTING", "TASK_ASSIGNMENT"),
        ("communication", "message", "SORTING", "PLANNER", "TASK_COMPLETED"),
        ("communication", "message", "SCHEDULING", "ROUTING", "ROUTE_REQUEST"),
        ("communication", "message", "ROUTING", "SCHEDULING", "ROUTE_RESPONSE"),
        ("communication", "message", "SORTING", "SUB-BARCODE", "SUBTASK_REQUEST"),
        ("communication", "subagent_message", "SUB-BARCODE", "SORTING", "SUBTASK_RESULT"),
        ("communication", "message", "ROUTING", "R1", "ROBOT_COMMAND"),
        ("robot", "moved", "R1", "", ""),
        ("parcel", "parcel_classified", "SORTING", "", ""),
        ("parcel", "parcel_arrived", "ENVIRONMENT", "", ""),
        ("task", "task_created", "", "", ""),
        ("simulation", "simulation_started", "SIMULATION", "", ""),
    ]
    produced = {classify(*args).interaction_type for args in inputs}
    assert produced == set(TYPES)
    assert all(not classify(*args).fallback for args in inputs)


def test_every_type_names_a_channel_and_the_channels_are_the_seven():
    assert list(CHANNELS) == ["A", "B", "C", "D", "E", "decision", "system"]
    for channel in CHANNELS.values():
        assert channel.label and channel.colour.startswith("#") and channel.dash
    for name, entry in TYPES.items():
        assert entry.interaction_type == name
        assert entry.channel in CHANNELS, name
        assert entry.has_receiver in ("always", "sometimes", "never"), name
        assert entry.latency in ("ms", "ticks", "none"), name
        assert isinstance(entry.model, bool), name
        assert entry.description, name


def test_the_classification_channel_matches_the_type_table():
    for args in [("agent", "decision", "X", "", ""), ("robot", "moved", "R1", "", ""),
                 ("communication", "message", "A", "B", "ROUTE_REQUEST"),
                 ("battery", "battery_low", "R1", "", ""), ("weather", "rain", "", "", "")]:
        got = classify(*args)
        assert got.channel == TYPES[got.interaction_type].channel


def test_table_round_trips_through_json():
    data = table()
    again = json.loads(json.dumps(data, sort_keys=True))
    assert again == data
    assert set(data) == {"channels", "types"}
    assert [c["id"] for c in data["channels"]] == list(CHANNELS)
    assert {"id", "label", "colour", "dash", "description"} <= set(data["channels"][0])
    assert [t["interaction_type"] for t in data["types"]] == list(TYPES)
    for row in data["types"]:
        assert set(row) == {"interaction_type", "channel", "description", "has_receiver",
                            "latency", "model"}
        assert row["has_receiver"] in ("always", "sometimes", "never")
        assert row["latency"] in ("ms", "ticks", "none")
        assert isinstance(row["model"], bool)
    # The table is a fresh copy each time: a caller cannot change the module's.
    data["types"].clear()
    assert table()["types"]


def test_model_is_true_only_on_channel_b_and_decision():
    for row in table()["types"]:
        assert row["model"] is (row["channel"] in ("B", "decision")), row["interaction_type"]


# -------------------------------------------------------------- robustness
@pytest.mark.parametrize("empty", [None, ""])
def test_missing_fields_do_not_raise(empty):
    got = classify(empty, empty, empty, empty, empty)
    assert isinstance(got, Classification)
    assert (got.interaction_type, got.channel, got.fallback) == ("system", "system", True)
    assert classify("robot", "moved", "R1", empty, empty).interaction_type == "robot_report"
    assert classify(empty, empty, "SUPERVISOR", "PLANNER", "POLICY").interaction_type == (
        "governance_instruction")


def test_classification_is_deterministic_and_hashable():
    args = ("communication", "message", "ROUTING", "SCHEDULING", "TASK_FAILED")
    first, second = classify(*args), classify(*args)
    assert first == second and hash(first) == hash(second)
    assert len({first, second}) == 1
    with pytest.raises(Exception):
        first.channel = "A"  # type: ignore[misc]


def test_agent_kinds_are_read_from_the_id():
    assert agent_kind("SUPERVISOR") == "supervisor"
    assert agent_kind("PLANNER") == "planner"
    for expert in ("INTAKE", "SORTING", "SCHEDULING", "ROUTING", "RESOURCE", "DISPATCH"):
        assert agent_kind(expert) == "expert", expert
    assert agent_kind("SUB-BARCODE") == "subagent"
    assert agent_kind("R1") == agent_kind("R12") == "robot"
    assert agent_kind("ENVIRONMENT") == "environment"
    assert agent_kind("SIMULATION") == "simulation"
    assert agent_kind("INTAKE_DOCK") == "intake_dock"
    assert agent_kind("ROBOT") == agent_kind("Rx") == agent_kind("someone") == "other"
    assert agent_kind("") == agent_kind(None) == "none"


def test_the_module_imports_nothing_from_the_simulator():
    import post_office.communication.taxonomy as module

    source = open(module.__file__, encoding="utf-8").read()
    imports = re.findall(r"^\s*(?:from|import)\s+(\S+)", source, re.MULTILINE)
    assert imports, "the module has import statements"
    for name in imports:
        assert not name.startswith(".") and not name.startswith("post_office"), name
    assert taxonomy.__name__ == "post_office.communication.taxonomy"
