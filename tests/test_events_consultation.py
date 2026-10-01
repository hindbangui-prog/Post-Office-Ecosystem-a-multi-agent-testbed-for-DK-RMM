"""
A consultation's evidence is ordinary events and ordinary messages (spec 12).

The three `CONSULT_*` messages are `message` events between two experts, with
the documented content, so DK-RMM's message indicators read them as they read
any expert traffic. Every `consult_*` event carries the decision's fields and
names its sender and receiver.
"""

import pytest

from tests.consult_helpers import ask, events, scheduling_with_equally_placed_robots
from tests.fake_ollama import consultation_script

pytestmark = pytest.mark.usefixtures("quiet_crewai_console")

COMMON = {"consultation_id", "decision_id", "decision", "condition", "interaction_type", "model"}
EXTRA = {"consult_opened": {"peer", "options"},
         "consult_question": {"text", "context"},
         "consult_response": {"text", "latency_ms"},
         "consult_closed": {"outcome", "choice", "turns", "latency_ms"}}


@pytest.fixture
def consulted(fake_ollama):
    fake_ollama.script(consultation_script("R2: its corridor is clear.",
                                           decide=lambda peer: "R2"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    ask(sched)
    return eco


def test_three_consult_messages_with_their_content(consulted):
    messages = [e for e in events(consulted, "message")
                if e.detail["message_type"].startswith("CONSULT_")]
    assert [(e.detail["message_type"], e.actor, e.target) for e in messages] == [
        ("CONSULT_REQUEST", "SCHEDULING", "ROUTING"),
        ("CONSULT_RESPONSE", "ROUTING", "SCHEDULING"),
        ("CONSULT_CLOSE", "SCHEDULING", "ROUTING")]
    request, response, close = (e.detail["content"] for e in messages)
    assert set(request) == {"consultation_id", "decision", "condition", "interaction_type",
                            "text"}
    assert (request["decision"], request["condition"], request["interaction_type"]) == (
        "choose_robot", "equally_placed", "question")
    assert set(response) == {"consultation_id", "text", "latency_ms", "model"}
    assert response["text"] == "R2: its corridor is clear." and response["model"] == "qwen3:8b"
    assert set(close) == {"consultation_id", "outcome", "choice"}
    assert (close["outcome"], close["choice"]) == ("decided", "R2")
    assert {e.correlation_id for e in messages} == {"CSL-0001"}
    assert {c["consultation_id"] for c in (request, response, close)} == {"CSL-0001"}
    assert all(e.category == "communication" for e in messages)


def test_every_consult_event_carries_the_decision_fields(consulted):
    trail = events(consulted, "consult_")
    assert [e.topic for e in trail] == ["consult_opened", "consult_question",
                                        "consult_response", "consult_closed"]
    decision = events(consulted, "decision")[-1]
    for event in trail:
        assert event.category == "agent"
        assert COMMON | EXTRA[event.topic] <= set(event.detail), event.topic
        assert event.detail["consultation_id"] == event.correlation_id == "CSL-0001"
        assert event.detail["decision_id"] == decision.detail["call_id"]
        assert (event.detail["decision"], event.detail["condition"]) == (
            "choose_robot", "equally_placed")
        assert event.detail["model"] == "qwen3:8b"
        assert event.wall_clock
        assert event.tick == decision.tick
    senders = [(e.topic, e.actor, e.target, e.detail["interaction_type"]) for e in trail]
    assert senders == [("consult_opened", "SCHEDULING", "ROUTING", "decision"),
                       ("consult_question", "SCHEDULING", "ROUTING", "question"),
                       ("consult_response", "ROUTING", "SCHEDULING", "response"),
                       ("consult_closed", "SCHEDULING", "ROUTING", "decision")]
    assert trail[0].detail["options"] == ["R1", "R2"] and trail[0].detail["peer"] == "ROUTING"
    assert trail[2].detail["text"] == "R2: its corridor is clear."


def test_llm_call_events_name_agent_and_phase(consulted):
    calls = events(consulted, "llm_call")
    assert [(e.actor, e.detail["agent_role"], e.detail["phase"]) for e in calls] == [
        ("SCHEDULING", "Scheduling", "owner"), ("ROUTING", "Routing", "peer"),
        ("SCHEDULING", "Scheduling", "owner")]
    for e in calls:
        assert COMMON <= set(e.detail) and e.detail["interaction_type"] == "llm_call"
        assert e.detail["status"] == 200 and e.detail["served_model"] == "qwen3:8b"
        assert {"call_id", "url", "requested_model", "latency_ms", "prompt_tokens",
                "completion_tokens"} <= set(e.detail)


def test_a_delegation_is_its_own_event_and_a_message_not_a_delegation(fake_ollama):
    def respond(body):
        tools = body.get("tools") or []
        if tools and not any(m.get("role") == "tool" for m in body["messages"]):
            delegate = next(t for t in tools if "delegate" in t["function"]["name"])
            return {"tool": delegate["function"]["name"],
                    "args": {"task": "Check both corridors.", "context": "T-1 is waiting.",
                             "coworker": "Routing"}}
        return consultation_script("R1: corridor clear.", decide=lambda peer: "R1")(body)

    fake_ollama.script(respond)
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    assert ask(sched).choice == "R1"
    (delegation,) = events(eco, "consult_delegation")
    assert delegation.detail["interaction_type"] == "delegation"
    assert delegation.detail["text"] == "Check both corridors."
    assert delegation.detail["context"] == "T-1 is waiting."
    (request,) = [e for e in events(eco, "message")
                  if e.detail["message_type"] == "CONSULT_REQUEST"]
    assert request.detail["content"]["interaction_type"] == "delegation"
    assert sched.brain.stats()["delegations"] == 1
