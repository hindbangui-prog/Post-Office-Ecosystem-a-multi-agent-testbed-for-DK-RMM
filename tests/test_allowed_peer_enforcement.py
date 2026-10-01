"""
The preserved peer map decides who may be consulted, and nothing else does (spec 7).

For a consultation the owner's tools are bound to exactly the one peer
`peer_for` names; a tool call naming any other coworker is refused, logged as
`consult_refused`, and reaches no model; a second exchange is refused the same
way; and an owner, decision kind and condition with no peer get no tools.
"""

import json

import pytest
from crewai import Agent

from post_office.agents.reasoning import REASONS, Trigger
from tests.consult_helpers import (ask, ecosystem_on, events,
                                   scheduling_with_equally_placed_robots)
from tests.fake_ollama import _tool_args, consultation_script, text_of

pytestmark = pytest.mark.usefixtures("quiet_crewai_console")

TOOL_NAMES = {"Ask question to coworker", "Delegate work to coworker"}


@pytest.fixture
def executed(monkeypatch):
    """Every `Agent.execute_task` call: (role, tools), in order."""
    seen = []
    original = Agent.execute_task

    def spy(self, task, context=None, tools=None):
        seen.append((self.role, tools))
        return original(self, task, context, tools)

    monkeypatch.setattr(Agent, "execute_task", spy)
    return seen


def _tool_messages(body):
    return [text_of(m) for m in body.get("messages", []) if m.get("role") == "tool"]


def _scripted(owner_turns, peer_reply="R2: clear."):
    """The peer gets `peer_reply`; the owner's n-th call gets `owner_turns[n tool messages]`."""

    def respond(body):
        messages = body.get("messages", [])
        if any("consulted by" in text_of(m) for m in messages
               if m.get("role") in ("system", "user")):
            return peer_reply
        return owner_turns[len(_tool_messages(body))](body)

    return respond


def _call(coworker, question="Which allowed answer do you recommend, and why?"):
    def turn(body):
        tool = body["tools"][0]
        args = _tool_args(tool, coworker)
        if "question" in args:
            args["question"] = question
        return {"tool": tool["function"]["name"], "args": args}
    return turn


def _decide(choice):
    return lambda body: f"DECISION: {choice}"


def test_owner_tools_are_bound_to_exactly_the_peer(fake_ollama, executed):
    fake_ollama.script(consultation_script("R2: clear.", decide=lambda peer: "R2"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    ask(sched)
    owner_role, tools = executed[0]
    assert owner_role == "Scheduling"
    assert {t.name for t in tools} == TOOL_NAMES
    routing = eco.agents["ROUTING"].brain.crew_agent
    assert all(t.agents == [routing] for t in tools)
    assert all("coworkers: Routing\n" in t.description for t in tools)
    # The peer's own task runs with no tools of its own.
    assert executed[1] == ("Routing", None)
    assert routing.tools == [] and routing.allow_delegation is False


def test_a_coworker_outside_the_peer_map_is_refused_without_a_model_call(fake_ollama, executed):
    fake_ollama.script(_scripted([_call("Resource"), _decide("R1")]))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    answer = ask(sched)

    assert answer.choice == "R1" and answer.source == "crewai:qwen3:8b"
    assert not any("consulted by" in json.dumps(r["messages"]) for r in fake_ollama.requests)
    assert [role for role, _ in executed] == ["Scheduling"]
    (refused,) = events(eco, "consult_refused")
    assert refused.actor == "SCHEDULING" and refused.target == "RESOURCE"
    assert "disallowed coworker" in refused.detail["reason"]
    assert refused.detail["interaction_type"] == "question"
    follow_up = _tool_messages(fake_ollama.requests[-1])
    assert follow_up == ["Resource is not available to you for this decision; only Routing is."]
    assert events(eco, "consult_question") == []
    assert not [e for e in events(eco, "message")
                if e.detail.get("message_type", "").startswith("CONSULT_")]


def test_a_second_exchange_is_refused(fake_ollama):
    fake_ollama.script(_scripted([_call("Routing"), _call("Routing", "And the other robot?"),
                                  _decide("R2")]))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    answer = ask(sched)

    assert answer.choice == "R2"
    peer_calls = [r for r in fake_ollama.requests if "consulted by" in json.dumps(r["messages"])]
    assert len(peer_calls) == 1
    assert _tool_messages(fake_ollama.requests[-1]) == [
        "R2: clear.", "You have already consulted Routing for this decision; decide now."]
    (refused,) = events(eco, "consult_refused")
    assert refused.target == "ROUTING" and "second exchange" in refused.detail["reason"]
    assert len(events(eco, "consult_question")) == 1


def lonely(facts):
    """A condition the peer map has no entry for."""
    return Trigger(REASONS.CONTENTION, "nobody to ask about this", rule_sufficient=False)


def test_no_peer_means_no_tools(fake_ollama, executed):
    fake_ollama.script(consultation_script("unused", decide=lambda peer: "R2"))
    eco = ecosystem_on(fake_ollama)
    sched = eco.agents["SCHEDULING"]
    sched.triggers.register("choose_robot", lonely)
    answer = ask(sched)

    assert answer.choice == "R2" and answer.source == "crewai:qwen3:8b"
    assert executed == [("Scheduling", [])]
    assert len(fake_ollama.requests) == 1 and not fake_ollama.requests[0].get("tools")
    (opened,) = events(eco, "consult_opened")
    assert opened.detail["peer"] == "" and opened.target == ""
    assert opened.detail["condition"] == "lonely"
    (closed,) = events(eco, "consult_closed")
    assert closed.detail["outcome"] == "decided" and closed.detail["turns"] == 0
    assert not [e for e in events(eco, "message")
                if e.detail.get("message_type", "").startswith("CONSULT_")]


def test_crewai_coworker_graph_is_never_built():
    """No `Crew` and no all-coworker `AgentTools` anywhere in the model layer."""
    import pathlib

    import post_office.crew as crew

    for path in pathlib.Path(crew.__file__).parent.glob("*.py"):
        source = path.read_text()
        assert "Crew(" not in source and "AgentTools(" not in source, path.name
    assert "peer_for(owner_id, question.kind, condition)" in (
        pathlib.Path(crew.__file__).parent / "consultation.py").read_text()
