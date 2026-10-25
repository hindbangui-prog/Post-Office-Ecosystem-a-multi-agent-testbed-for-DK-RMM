"""
The idle gate (`post_office.simulation.activity`).

While no robot holds an errand the facility is idle, and a decision whose
trigger would call the model is answered by the expert's rule instead; from
the first robot errand on, the facility is active for the rest of the run and
the rule-first, model-when-insufficient path is exactly as before.

Unit tests drive one agent and the gate by hand; the integration tests run
Normal with the seven experts on the fake Ollama, and Normal on the rules.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from post_office.agents.base import BaseAgent
from post_office.agents.brain import Answer, Brain, DeterministicBrain
from post_office.agents.reasoning import REASONS, Trigger
from post_office.simulation.activity import ACTIVE, IDLE, ActivityGate

GATE_TOPICS = {"ecosystem_idle", "ecosystem_active", "llm_skipped_idle"}


# ------------------------------------------------------------------ fakes
class _Log:
    def __init__(self):
        self.events = []

    def emit(self, category, topic, **fields):
        self.events.append(SimpleNamespace(topic=topic, **fields))
        return None

    def topics(self):
        return [e.topic for e in self.events]


class _Robot(SimpleNamespace):
    pass


class _Fleet:
    def __init__(self, n=3):
        self.robots = [_Robot(robot_id=f"R{i}", current_task=None) for i in range(1, n + 1)]

    def all(self):
        return list(self.robots)

    def status_counts(self):
        return {"IDLE": sum(1 for r in self.robots if r.current_task is None)}


class _CountingBrain(Brain):
    """A model stand-in: counts the calls and answers 'b'."""

    name = "counting"

    def __init__(self):
        self.fallback = DeterministicBrain()
        self.calls = 0

    def answer(self, question):
        self.calls += 1
        return Answer("b", "model", source="crewai:fake")


class _Agent(BaseAgent):
    """One decision, `pick`, whose rule says 'a' and whose trigger always fires."""

    def install_rules(self):
        self.rules().register("pick", lambda q: Answer("a", "rule"))

    def install_triggers(self):
        self.triggers.register("pick", lambda facts: Trigger(REASONS.CONFLICT, "always"))


def _setup():
    log = _Log()
    fleet = _Fleet()
    gate = ActivityGate(fleet, SimpleNamespace(parcels={"P1": 1}), log)
    world = SimpleNamespace(tick=5, activity=gate, logger=log, gate=None)
    brain = _CountingBrain()
    agent = _Agent("EXPERT", "expert", brain=brain)
    agent.world = world
    return agent, brain, gate, fleet, log, world


# -------------------------------------------------------------- the gate
def test_the_gate_is_idle_until_a_robot_holds_an_errand_and_then_stays_active():
    _agent, _brain, gate, fleet, log, _world = _setup()
    gate.announce(0)
    assert gate.state == IDLE and log.topics() == ["ecosystem_idle"]
    for tick in (1, 2, 3):
        gate.observe(tick)
    assert gate.idle and gate.activated_at is None
    fleet.robots[1].current_task = "T-1"
    gate.observe(4)
    assert gate.state == ACTIVE and gate.activated_at == 4
    active = [e for e in log.events if e.topic == "ecosystem_active"]
    assert len(active) == 1 and active[0].robot == "R2" and active[0].task == "T-1"
    # The errand ends and the fleet is parked again: still active.
    fleet.robots[1].current_task = None
    for tick in (5, 6, 7):
        gate.observe(tick)
    assert gate.state == ACTIVE
    assert log.topics().count("ecosystem_active") == 1


# --------------------------------------------------------- one decision
def test_while_idle_a_firing_trigger_takes_the_rule_and_the_model_is_not_called():
    agent, brain, gate, _fleet, log, _world = _setup()
    answer = agent.decide("pick", "pick one", options=("a", "b"))
    assert brain.calls == 0
    assert answer.choice == "a"
    record = agent.decisions[-1]
    assert record["mode"] == "deterministic" and record["path"] == "deterministic"
    assert record["trigger"] == ""
    assert record["llm_skipped"] == "idle" and record["skipped_trigger"] == "conflict"
    assert record["handling"] == "idle_rule"
    assert agent.idle_skips == 1 and agent.reasoned == 0
    skipped = [e for e in log.events if e.topic == "llm_skipped_idle"]
    assert len(skipped) == 1 and skipped[0].agent == "EXPERT" and skipped[0].trigger == "conflict"
    decision = [e for e in log.events if e.topic == "decision"][-1]
    assert decision.llm_skipped == "idle" and decision.mode == "deterministic"
    assert gate.skipped == 1


def test_once_active_the_same_decision_goes_to_the_model_as_before():
    agent, brain, gate, fleet, log, _world = _setup()
    fleet.robots[0].current_task = "T-9"
    gate.observe(5)
    answer = agent.decide("pick", "pick one", options=("a", "b"))
    assert brain.calls == 1 and answer.choice == "b"
    record = agent.decisions[-1]
    assert record["mode"] == "llm" and record["trigger"] == "conflict"
    assert "llm_skipped" not in record
    assert "llm_skipped_idle" not in log.topics()


def test_a_routine_decision_is_untouched_by_the_gate():
    agent, brain, _gate, _fleet, log, _world = _setup()
    agent.triggers = type(agent.triggers)()          # no condition: routine
    answer = agent.decide("pick", "pick one", options=("a", "b"))
    assert answer.choice == "a" and brain.calls == 0
    assert "llm_skipped" not in agent.decisions[-1]
    assert "llm_skipped_idle" not in log.topics()


def test_while_idle_a_decision_with_no_rule_answer_takes_the_default_and_no_model():
    """Nothing rule-based to answer with (the rule raises): still no model call, and no crash."""
    agent, brain, gate, _fleet, log, _world = _setup()

    def broken(question):
        raise RuntimeError("rule broke")

    agent.rules().register("pick", broken)
    answer = agent.decide("pick", "pick one", options=("a", "b"))
    assert brain.calls == 0
    assert answer.choice == "a" and answer.confidence == 0.0 and answer.source == "default"
    record = agent.decisions[-1]
    assert record["handling"] == "idle_no_rule" and record["mode"] == "deterministic"
    assert "RuntimeError: rule broke" in record["rule_error"]
    skipped = [e for e in log.events if e.topic == "llm_skipped_idle"]
    assert len(skipped) == 1 and skipped[0].answered_by == "default_option"
    assert "rule broke" in skipped[0].rule_error
    assert gate.skipped == 1 and gate.no_rule == 1


def test_without_a_gate_the_decision_path_is_the_original_one():
    agent, brain, _gate, _fleet, _log, world = _setup()
    world.activity = None
    agent.decide("pick", "pick one", options=("a", "b"))
    assert brain.calls == 1 and agent.decisions[-1]["mode"] == "llm"


# ----------------------------------------------------------- real runs

@pytest.mark.usefixtures("quiet_crewai_console")
def test_normal_on_the_model_makes_no_model_call_while_idle_and_resumes_after(fake_ollama):
    from post_office.config.settings import llm_brains, normal_config
    from post_office.simulation.ecosystem import build

    events = []
    eco = build(seed=1, config=normal_config(), log_path=os.devnull,
                brains=llm_brains(settings=fake_ollama.settings, verify=False))
    try:
        gate = eco.activity
        assert gate is not None and eco.world.activity is gate and gate.idle
        eco.logger.subscribe(events.append)
        eco.start()
        requests_at_activation = None
        for _ in range(300):
            eco.step()
            if gate.activated_at == eco.world.tick and requests_at_activation is None:
                requests_at_activation = len(fake_ollama.requests)
        active_at = gate.activated_at
        assert active_at is not None, "the fleet should take an errand early in the run"
        # Not a clock cut-off: activation is the tick after the first errand.
        assert 0 < active_at < 100

        # Idle phase: no request reached the model, no model decision, no
        # consultation; every firing trigger was skipped and logged.
        assert requests_at_activation == 0
        decisions = [e for e in events if e.topic == "decision"]
        before = [e for e in decisions if e.tick < active_at]
        assert before and all(e.detail["mode"] == "deterministic" for e in before)
        assert not [e for e in events if e.topic.startswith("consult_") and e.tick < active_at]
        skipped = [e for e in events if e.topic == "llm_skipped_idle"]
        assert skipped, "seed 1 has triggers firing before the fleet moves"
        assert all(e.tick < active_at for e in skipped)
        assert gate.skipped == len(skipped)
        assert gate.no_rule == 0
        assert all(e.detail["answered_by"] == "rule" for e in skipped)
        marked = [e for e in before if e.detail.get("llm_skipped") == "idle"]
        assert len(marked) == len(skipped)
        active = [e for e in events if e.topic == "ecosystem_active"]
        assert len(active) == 1 and active[0].tick == active_at

        # Active phase: rule first, model when the rule is insufficient,
        # exactly as before (tests/test_rules_first.py checks the shares).
        after = [e for e in decisions if e.tick >= active_at]
        assert not [e for e in after if e.detail.get("llm_skipped")]
        on_model = set(eco.crew.agents)
        mine = [e for e in after if e.actor in on_model]
        modes = {(e.detail["mode"], bool(e.detail["trigger"])) for e in mine}
        assert modes == {("deterministic", False), ("llm", True)}, modes
        assert len(fake_ollama.requests) > 0
        assert eco.crew.summary()["model_decisions"] == sum(
            1 for e in mine if e.detail["mode"] == "llm")
        summary = eco.summary()["activity"]
        assert summary["state"] == "active" and summary["activated_at"] == active_at
        assert summary["llm_calls_skipped"] == len(skipped)
        assert sum(row["idle_skipped"] for row in eco.reasoning_summary().values()) == len(skipped)
    finally:
        eco.close()


def test_a_rules_only_run_has_no_gate_and_logs_nothing_new():
    from post_office.config.settings import normal_config
    from post_office.simulation.ecosystem import build

    eco = build(seed=1, config=normal_config(), log_path=os.devnull)
    topics = set()
    eco.logger.subscribe(lambda e: topics.add(e.topic))
    try:
        assert eco.activity is None and eco.world.activity is None
        eco.start()
        for _ in range(60):
            eco.step()
        assert not topics & GATE_TOPICS
        assert eco.summary()["activity"] is None
        assert all(row["idle_skipped"] == 0 for row in eco.reasoning_summary().values())
    finally:
        eco.close()


def test_the_monitor_never_reads_the_gates_notices():
    # This copy keeps Prototype II's DK-RMM; its monitor skips the notices.
    from post_office.dkrmm.monitor import IDLE_GATE_TOPICS

    assert GATE_TOPICS <= IDLE_GATE_TOPICS
