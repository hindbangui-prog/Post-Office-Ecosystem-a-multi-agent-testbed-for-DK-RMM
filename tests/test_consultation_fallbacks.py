"""
Every way a consultation can fail ends in the rule's answer, said plainly (spec 8.5).

A reply with no allowed answer, a failing model, a deadline passed, an answer
off the list and a peer that never answers all close the consultation with
their own outcome and hand `decide` the rule's answer marked `[fallback: ...]`.
Nothing the model said outside the allowed answers ever reaches the gate.
"""

import threading
import time

import pytest

from post_office.crew import consultation
from post_office.crew.consultation import JOIN_STEP_S, join_until
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


class _Joins(threading.Thread):
    """A thread that records the timeout of every `join` on it."""

    def __init__(self, seconds):
        self.release = threading.Event()
        super().__init__(target=self.release.wait, args=(seconds,), daemon=True)
        self.timeouts = []

    def join(self, timeout=None):
        self.timeouts.append(timeout)
        super().join(timeout)


def test_the_join_loop_waits_in_short_steps_and_keeps_the_deadline():
    """Short joins let Ctrl-C reach the tick's thread on Windows; the deadline still holds."""
    worker = _Joins(10)
    worker.start()
    started = time.monotonic()
    join_until(worker, 0.7)
    took = time.monotonic() - started
    assert worker.is_alive() and 0.7 <= took < 0.7 + 0.3
    assert len(worker.timeouts) >= 3 and all(0 < t <= JOIN_STEP_S for t in worker.timeouts)
    worker.release.set()
    started = time.monotonic()
    join_until(worker, 5)
    assert not worker.is_alive() and time.monotonic() - started < 0.3


def test_ctrl_c_while_waiting_abandons_the_worker_and_is_raised(fake_ollama, monkeypatch):
    fake_ollama.script(consultation_script("R2: clear.", decide=lambda peer: "R2"))
    fake_ollama.delay(0.5)
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)

    def interrupted(worker, timeout_s, step_s=JOIN_STEP_S):
        raise KeyboardInterrupt

    with monkeypatch.context() as patched:
        patched.setattr(consultation, "join_until", interrupted)
        with pytest.raises(KeyboardInterrupt):
            ask(sched)
    assert eco.crew.busy("SCHEDULING")
    assert eco.crew.drain(15)
    # The abandoned worker wrote nothing after the interrupt: no question, no close.
    assert events(eco, "consult_question") == [] and events(eco, "consult_closed") == []
    assert all(c["phase"] == "late" for c in eco.crew.llm_calls())


class _Recording(CommunicationLayer):
    """An identity layer that remembers every call it was given."""

    def __init__(self):
        self.calls = []

    def on_request(self, req):
        self.calls.append(("request", req.consultation_id))
        return req

    def on_response(self, resp):
        self.calls.append(("response", resp.consultation_id))
        return resp


def test_an_abandoned_worker_drives_no_layer_and_reads_no_world(fake_ollama):
    """After the deadline the worker's tool use reaches neither the layer nor the briefing."""
    fake_ollama.script(consultation_script("R2: clear.", decide=lambda peer: "R2"))
    fake_ollama.delay(1)
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama, consult_deadline_s=0.3)
    layer = _Recording()
    eco.crew.interception.communication = layer
    briefed = []
    source = eco.crew.briefing_source
    eco.crew.briefing_source = lambda agent_id: briefed.append(agent_id) or source(agent_id)
    answer = ask(sched)
    assert answer.source == "fallback" and _closed(eco).detail["outcome"] == "timeout"

    assert eco.crew.drain(15)
    # The owner's late reply was a tool call; the tool ran in the abandoned
    # worker and stopped before the layer, the briefing and the peer.
    late = eco.crew.llm_calls()
    assert [c["phase"] for c in late] == ["late", "late"]
    assert layer.calls == [] and briefed == []
    assert not any("consulted by" in str(r["messages"]) for r in fake_ollama.requests)


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


def _has_tool_message(body):
    return any(m.get("role") == "tool" for m in body.get("messages", []))


def test_a_failure_after_the_exchange_is_not_re_run(fake_ollama):
    """
    The owner asks, the peer answers, and the owner's post-exchange call (the
    one request that carries a `tool` message) fails with HTTP 500.

    CrewAI never re-runs the task (`max_retry_limit=0`): a re-run would start
    over with fresh messages, discard the peer's reply and have the owner's
    second ask refused. The consultation closes `model_failed`, the rule
    answers, and the fake sees no owner request after the failing one.
    """
    fake_ollama.script(consultation_script("R2: it is nearer.", decide=lambda peer: "R2"))
    fake_ollama.fail_when(_has_tool_message, 500)
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    answer = ask(sched)

    assert answer.source == "fallback" and answer.choice == RULE_CHOICE
    closed = _closed(eco)
    assert closed.detail["outcome"] == "model_failed" and closed.detail["error"]
    assert len(events(eco, "consult_question")) == len(events(eco, "consult_response")) == 1
    roles = [("peer" if any("consulted by" in text_of(m) for m in r["messages"]
                            if m.get("role") in ("system", "user")) else "owner")
             for r in fake_ollama.requests]
    # One owner call (the tool call), one peer call, one failing owner call; nothing after.
    assert roles == ["owner", "peer", "owner"]
    assert [_has_tool_message(r) for r in fake_ollama.requests] == [False, False, True]
    assert [c["status"] for c in eco.crew.llm_calls()] == [200, 200, 500]
    (row,) = eco.crew.recent()
    assert row["outcome"] == "model_failed" and row["response"] == "R2: it is nearer."
    assert row["source"] == "fallback" and row["decision"] == RULE_CHOICE
    stats = sched.brain.stats()
    assert stats["retries"] == 0 and stats["reachable"] is False and stats["consultations"] == 1


class _Raising(CommunicationLayer):
    """A communication layer whose request hook raises."""

    def on_request(self, req):
        raise RuntimeError("layer broke")


def test_an_exchange_block_that_raises_marks_the_peer_failed(fake_ollama):
    """
    An exception escaping the guarded request block is not raised into
    CrewAI's tool handling: the exchange counts as used, the owner is told
    "no answer from Routing", and without a decision the consultation closes
    `peer_failed` with the exception named.
    """
    seen = []

    def respond(body):
        tools = [m for m in body["messages"] if m.get("role") == "tool"]
        if tools:
            seen.append(text_of(tools[-1]))
            return "Without Routing I cannot say."
        return consultation_script("R2", decide=lambda peer: "R2")(body)

    fake_ollama.script(respond)
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    eco.crew.interception.communication = _Raising()
    answer = ask(sched)

    assert answer.source == "fallback" and answer.choice == RULE_CHOICE
    closed = _closed(eco)
    assert closed.detail["outcome"] == "peer_failed"
    assert "no answer from Routing" in answer.reason
    assert seen and "no answer from Routing" in seen[-1]
    assert events(eco, "consult_question") == []
    assert not any("consulted by" in str(r["messages"]) for r in fake_ollama.requests)
    # Exactly the expected owner calls of a consultation with an exchange.
    assert len(fake_ollama.requests) == 2
    stats = sched.brain.stats()
    assert stats["retries"] == 0 and stats["consultations"] == 0
    assert eco.crew.summary()["exchanges"] == 0


def test_a_rule_that_raises_still_lets_the_model_decide(fake_ollama):
    """`fallback.answer` raising is caught: the service runs with no rule answer."""
    fake_ollama.script(consultation_script("R2: clear.", decide=lambda peer: "R2"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)

    def broken(question):
        raise RuntimeError("rule broke")

    sched.brain.fallback.register("choose_robot", broken)
    answer = ask(sched)
    assert answer.source == "crewai:qwen3:8b" and answer.choice == "R2"
    assert sched.brain.stats()["last_error"] == "rule raised RuntimeError: rule broke"
