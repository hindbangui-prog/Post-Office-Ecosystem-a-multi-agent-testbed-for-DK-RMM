"""
Every model call of a consultation is an `llm_call` event under its tick (spec 12).

A clean owner -> peer -> owner consultation makes three model calls, owner,
peer, owner, each written while the consultation is open with the transport's
own record: served model, latency, URL, and the tick the decision was taken
in. A tool call CrewAI cannot read (malformed JSON arguments) makes CrewAI's
executor loop once more: that extra owner call is a real `llm_call` too, and
is what `retries` counts.
"""

import pytest

from post_office.agents.reasoning import REASONS, Trigger
from tests.consult_helpers import (ask, ecosystem_on, events,
                                   scheduling_with_equally_placed_robots)
from tests.fake_ollama import _tool_args, consultation_script, text_of

pytestmark = pytest.mark.usefixtures("quiet_crewai_console")


def _tool_messages(body):
    return [text_of(m) for m in body.get("messages", []) if m.get("role") == "tool"]


def _is_peer(body):
    return any("consulted by" in text_of(m) for m in body.get("messages", [])
               if m.get("role") in ("system", "user"))


def test_one_consultation_is_three_llm_call_events(fake_ollama):
    fake_ollama.script(consultation_script("R2: its corridor is clear.",
                                           decide=lambda peer: "R2"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    tick = eco.world.tick
    assert ask(sched).choice == "R2"

    calls = events(eco, "llm_call")
    assert [(e.actor, e.detail["phase"]) for e in calls] == [
        ("SCHEDULING", "owner"), ("ROUTING", "peer"), ("SCHEDULING", "owner")]
    (closed,) = events(eco, "consult_closed")
    for e in calls:
        assert e.tick == tick == closed.tick
        assert e.detail["consultation_id"] == e.correlation_id == "CSL-0001"
        assert e.detail["served_model"] == "qwen3:8b"
        assert e.detail["requested_model"] == "qwen3:8b"
        assert e.detail["latency_ms"] > 0
        assert e.detail["url"].endswith("/v1/chat/completions")
        assert e.detail["status"] == 200
        assert e.detail["prompt_tokens"] > 0 and e.detail["completion_tokens"] > 0
        assert e.seq < closed.seq
    assert len({e.detail["call_id"] for e in calls}) == 3
    # The service's own record of the calls is the same three.
    rows = eco.crew.llm_calls()
    assert [(r["phase"], r["tick"], r["consultation_id"]) for r in rows] == [
        ("owner", tick, "CSL-0001"), ("peer", tick, "CSL-0001"), ("owner", tick, "CSL-0001")]
    assert sched.brain.stats()["retries"] == 0


def test_a_malformed_tool_call_costs_one_more_model_call_and_counts_as_a_retry(fake_ollama):
    def respond(body):
        if _is_peer(body):
            return "R2: its corridor is clear."
        tool = body["tools"][0] if body.get("tools") else None
        seen = _tool_messages(body)
        if not seen:   # the first owner turn: a tool call whose arguments are not JSON
            return {"tool": tool["function"]["name"],
                    "raw_args": '{"question": "Which robot, R1 or R2?", "context": '}
        if len(seen) == 1:   # CrewAI told it the arguments did not parse: a proper call
            return {"tool": tool["function"]["name"], "args": _tool_args(tool, "Routing")}
        return "DECISION: R2"

    fake_ollama.script(respond)
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    tick = eco.world.tick
    answer = ask(sched)

    assert answer.choice == "R2" and answer.source == "crewai:qwen3:8b"
    calls = events(eco, "llm_call")
    print("\nllm_call events:", [(e.actor, e.detail["phase"]) for e in calls])
    assert [(e.actor, e.detail["phase"]) for e in calls] == [
        ("SCHEDULING", "owner"), ("SCHEDULING", "owner"), ("ROUTING", "peer"),
        ("SCHEDULING", "owner")]
    assert {e.tick for e in calls} == {tick}
    # The second owner call is CrewAI's own loop answering the parse error.
    retry = fake_ollama.requests[1]
    (parse_error,) = _tool_messages(retry)
    assert "Failed to parse tool arguments as JSON" in parse_error
    # The malformed call reached no peer and used no exchange.
    assert len(events(eco, "consult_question")) == 1
    assert events(eco, "consult_refused") == []
    peers = [r for r in fake_ollama.requests if _is_peer(r)]
    assert len(peers) == 1
    stats = sched.brain.stats()
    assert stats["retries"] == 1 and stats["consultations"] == 1
    (closed,) = events(eco, "consult_closed")
    assert closed.detail["outcome"] == "decided" and closed.detail["turns"] == 2


def lonely(facts):
    """A condition the peer map has no entry for."""
    return Trigger(REASONS.CONTENTION, "nobody to ask about this", rule_sufficient=False)


def test_a_decision_without_a_peer_has_no_retry(fake_ollama):
    """One owner call, nothing asked: one call is expected, and nothing is extra."""
    fake_ollama.script(lambda body: "DECISION: R2")
    eco = ecosystem_on(fake_ollama)
    sched = eco.agents["SCHEDULING"]
    sched.triggers.register("choose_robot", lonely)
    assert ask(sched).choice == "R2"
    assert [e.detail["phase"] for e in events(eco, "llm_call")] == ["owner"]
    assert sched.brain.stats()["retries"] == 0
