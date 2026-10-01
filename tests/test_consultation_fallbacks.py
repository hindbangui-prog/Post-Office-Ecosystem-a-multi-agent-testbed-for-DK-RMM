"""
Every way a consultation can fail ends in the rule's answer, said plainly (spec 8.5).

A reply with no allowed answer, a failing model, a deadline passed, an answer
off the list and a peer that never answers all close the consultation with
their own outcome and hand `decide` the rule's answer marked `[fallback: ...]`.
Nothing the model said outside the allowed answers ever reaches the gate.
"""

import time

import pytest

from post_office.crew.interception import CommunicationLayer
from tests.consult_helpers import ask, events, scheduling_with_equally_placed_robots
from tests.fake_ollama import consultation_script, text_of

pytestmark = pytest.mark.usefixtures("quiet_crewai_console")

RULE_CHOICE = "R1"   # SCHEDULING's rule for the tests' question


def _closed(eco):
    (closed,) = events(eco, "consult_closed")
    return closed


def _decision(eco):
    return events(eco, "decision")[-1]


def test_no_decision_line_falls_back(fake_ollama):
    fake_ollama.script(lambda body: "I cannot tell from here.")
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    answer = ask(sched)

    assert answer.source == "fallback" and answer.choice == RULE_CHOICE
    assert answer.reason.endswith("[fallback: no allowed answer in the reply]")
    assert _closed(eco).detail["outcome"] == "no_valid_decision"
    assert _closed(eco).detail["choice"] is None
    assert _decision(eco).detail["path"] == "fallback"
    stats = sched.brain.stats()
    assert stats["parse_failures"] == 1 and stats["fallbacks"] == 1


def test_model_failure_falls_back(fake_ollama):
    fake_ollama.fail_with(500)
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    answer = ask(sched)

    assert answer.source == "fallback" and answer.choice == RULE_CHOICE
    closed = _closed(eco)
    assert closed.detail["outcome"] == "model_failed" and closed.detail["error"]
    stats = sched.brain.stats()
    assert stats["reachable"] is False and stats["last_error"]
    calls = eco.crew.llm_calls()
    assert calls and all(c["status"] == 500 and c["phase"] == "owner" for c in calls)


def test_deadline_falls_back_to_rule(fake_ollama):
    fake_ollama.script(consultation_script("R2: clear.", decide=lambda peer: "R2"))
    fake_ollama.delay(2)
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama, consult_deadline_s=0.5)
    started = time.perf_counter()
    answer = ask(sched)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.5
    assert answer.source == "fallback" and answer.choice == RULE_CHOICE
    assert "[fallback: no decision within 0.5 s]" in answer.reason
    closed = _closed(eco)
    assert closed.detail["outcome"] == "timeout"
    assert sched.brain.stats()["timeouts"] == 1
    assert eco.crew.busy("SCHEDULING")

    # The abandoned worker finishes on its own; what it does after the
    # deadline is discarded: no event, no message, no peer call, phase "late".
    assert eco.crew.drain(15)
    assert not eco.crew.busy("SCHEDULING")
    after = [e for e in events(eco) if e.seq > closed.seq and e.topic != "decision"]
    assert after == []
    assert not any("consulted by" in str(r["messages"]) for r in fake_ollama.requests)
    calls = eco.crew.llm_calls()
    assert calls and all(c["phase"] == "late" for c in calls)


def test_a_busy_expert_is_not_asked_again(fake_ollama):
    fake_ollama.script(consultation_script("R2: clear.", decide=lambda peer: "R2"))
    fake_ollama.delay(1)
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama, consult_deadline_s=0.2)
    ask(sched)
    asked = len(fake_ollama.requests)
    answer = ask(sched)
    assert answer.source == "fallback"
    assert "still running a consultation past its deadline" in answer.reason
    assert [e.detail["outcome"] for e in events(eco, "consult_closed")] == ["timeout", "timeout"]
    assert eco.crew.drain(15)
    assert len(fake_ollama.requests) == asked + 1   # the first worker's second owner call only


def test_inadmissible_decision_falls_back(fake_ollama, monkeypatch):
    fake_ollama.script(consultation_script("R9 is best.", decide=lambda peer: "R9"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    seen = []
    check = eco.world.gate.check

    def watching(proposal):
        seen.append(proposal.choice)
        return check(proposal)

    monkeypatch.setattr(eco.world.gate, "check", watching)
    answer = ask(sched, options=("R1", "R2"))

    assert answer.source == "fallback" and answer.choice == RULE_CHOICE
    assert "R9" not in seen and seen == [RULE_CHOICE]
    assert "[fallback: the DECISION line named no allowed answer]" in answer.reason
    assert _closed(eco).detail["outcome"] == "no_valid_decision"
    assert sched.brain.stats()["rejected_answers"] == 1


class _Swallow(CommunicationLayer):
    """A communication layer that loses every request on its way to the peer."""

    def on_request(self, req):
        return None


def test_a_peer_that_never_answers_closes_as_peer_failed(fake_ollama):
    def respond(body):
        tools = [m for m in body["messages"] if m.get("role") == "tool"]
        if tools:
            return "Without Routing I cannot say." if "no answer from Routing" in text_of(
                tools[-1]) else "DECISION: R2"
        return consultation_script("R2", decide=lambda peer: "R2")(body)

    fake_ollama.script(respond)
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    eco.crew.interception.communication = _Swallow()
    answer = ask(sched)

    assert answer.source == "fallback" and answer.choice == RULE_CHOICE
    assert _closed(eco).detail["outcome"] == "peer_failed"
    assert "no answer from Routing" in answer.reason
    assert events(eco, "consult_question") == []
    assert not any("consulted by" in str(r["messages"]) for r in fake_ollama.requests)


def test_a_service_that_raises_falls_back(fake_ollama, monkeypatch):
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)

    def boom(*args, **kwargs):
        raise RuntimeError("service broke")

    monkeypatch.setattr(eco.crew, "run", boom)
    answer = ask(sched)
    assert answer.source == "fallback" and answer.choice == RULE_CHOICE
    assert answer.reason.endswith("[fallback: RuntimeError: service broke]")
    stats = sched.brain.stats()
    assert stats["reachable"] is False and stats["last_error"] == "RuntimeError: service broke"
    assert fake_ollama.requests == []
