"""
P7-ONOFF-MODEL on the live clock: the model does not stop the run, the attack
keeps its meaning.

A live run of the preset takes model decisions without holding the tick
(`api/runner.py::_live_decisions`). The attack notes the phase a targeted
decision was taken in and displaces the answer the agent acts on accordingly
(`OnOffAttack._defer`): taken during ON, displaced even if answered in OFF;
taken during OFF, acted on as answered even if the answer lands in ON. ROUTING
still consults its model from the sixth tick of a block; 30 ticks is the answer's
deadline. See docs/p7-onoff-model.md, section 1a.

Driven as the runner drives it -- `faults.before_tick(next)`, then `eco.step()`
-- with a stand-in model that answers a fixed number of ticks after it is asked.
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any, Dict, List

import pytest

from post_office.agents.brain import Answer, Brain, DeterministicBrain
from post_office.agents.deferral import Deferral, is_pending
from post_office.config.settings import config
from post_office.simulation.ecosystem import build
from post_office.stress.onoff_model import OnOffModelFaults

SEED = 11977


class TickModel(Brain):
    """Answers `latency` ticks after it is asked, with the first option; `one_at_a_time` like CrewAI."""

    def __init__(self, box: Dict[str, Any], latency: int, one_at_a_time: bool = True) -> None:
        self.fallback = DeterministicBrain()
        self.box, self.latency, self.one = box, latency, one_at_a_time
        self.open: List[Dict[str, Any]] = []
        self.started: List[Dict[str, Any]] = []
        self.last_consultation = None

    def answer(self, question):
        return Answer(question.options[0], "model", source="crewai:tick")

    answer_consulting = lambda self, question, trigger: self.answer(question)  # noqa: E731

    def free_to_consult(self, question, trigger):
        return not (self.one and self.open)

    def start_consulting(self, question, trigger):
        handle = {"q": question, "at": self.box["eco"].world.tick,
                  "condition": getattr(trigger, "condition", "")}
        self.open.append(handle)
        self.started.append(handle)
        return handle

    def finish_consulting(self, handle, give_up=0):
        if self.box["eco"].world.tick - handle["at"] < self.latency and not give_up:
            return None
        self.open.remove(handle)
        if give_up and self.box["eco"].world.tick - handle["at"] < self.latency:
            rule = self.fallback.answer(handle["q"])
            return Answer(rule.choice, f"{rule.reason} [fallback: deadline]", source="fallback")
        return Answer(handle["q"].options[0], "model", source="crewai:tick")


def _live(latency: int, one_at_a_time: bool = True):
    """The preset as the live runner builds it, with the clock running (non-blocking)."""
    box: Dict[str, Any] = {}
    models = {a: TickModel(box, latency, one_at_a_time) for a in ("ROUTING", "SCHEDULING")}
    eco = build(seed=SEED, config=config("p7-onoff-model"), log_path=os.devnull,
                brains=models, scenario="p7-onoff-model")
    box["eco"] = eco
    faults = OnOffModelFaults(eco, SEED)
    eco.set_async_decisions(True, 120)                 # what `_live_decisions` sets
    routing = eco.experts["ROUTING"]
    routing.live_block_patience = False                # the six-tick trigger stays
    routing.llm_deadline_ticks = routing.LIVE_PERSISTENT
    eco.start()
    return eco, faults, models


def _step(eco, faults, n=1):
    for _ in range(n):
        faults.before_tick(eco.world.tick + 1)
        eco.step()


def _phase_edges(attack):
    on_end = next(t for t in range(1200, 4000) if not attack.is_on(t))
    on2 = next(t for t in range(on_end, 4000) if attack.is_on(t))
    return on_end, on2


# --------------------------------------------- a decision across a phase change
@pytest.mark.parametrize("cross", ["on_to_off", "off_to_on"])
def test_the_phase_a_decision_was_taken_in_decides_its_displacement(cross):
    eco, faults, models = _live(latency=10, one_at_a_time=False)
    try:
        attack = faults.attack
        on_end, on2 = _phase_edges(attack)
        ask_at = on_end - 5 if cross == "on_to_off" else on2 - 5
        _step(eco, faults, ask_at - eco.world.tick)
        assert eco.world.tick == ask_at
        acted: List[Answer] = []
        routing = eco.experts["ROUTING"]
        answer = routing.decide("resolve_block", "R1 is blocked by R2", options=("YIELD", "WAIT"),
                                correlation_id="TEST-X", robot="R1", blocked_by="R2", ticks_blocked=6,
                                direct_distance=4, detour_extra=None, battery=80,
                                deferral=Deferral(key="TEST-R1", apply=acted.append))
        assert is_pending(answer)
        displaced: List[Dict[str, Any]] = []
        eco.logger.subscribe(lambda e: displaced.append({"tick": e.tick, **e.detail})
                             if e.topic == "attack_displaced" and e.actor == "ROUTING"
                             and e.correlation_id == "TEST-X" else None)
        _step(eco, faults, 15)
        assert len(acted) == 1                            # answered after the phase changed
        if cross == "on_to_off":
            assert attack.is_on(ask_at) and not attack.is_on(acted and eco.world.tick)
            assert acted[0].choice == "WAIT" and acted[0].source == "attack:on"
            (row,) = displaced
            assert row["honest"] == "YIELD" and row["displaced"] == "WAIT"
            assert row["initiated_tick"] == ask_at and row["initiated_phase"] == "ON"
            assert row["tick"] > ask_at
        else:
            assert not attack.is_on(ask_at) and attack.is_on(eco.world.tick)
            assert acted[0].choice == "YIELD" and displaced == []
    finally:
        eco.close()


def test_an_answer_never_acted_on_displaces_nothing():
    eco, faults, _ = _live(latency=10, one_at_a_time=False)
    try:
        attack = faults.attack
        on_end, _ = _phase_edges(attack)
        _step(eco, faults, on_end - 50 - eco.world.tick)
        acted, given_up, displaced = [], [], []
        eco.logger.subscribe(lambda e: displaced.append(e) if e.topic == "attack_displaced"
                             and e.correlation_id == "TEST-X" else None)
        eco.experts["ROUTING"].decide(
            "resolve_block", "R1 is blocked by R2", options=("YIELD", "WAIT"), correlation_id="TEST-X",
            robot="R1", blocked_by="R2", ticks_blocked=6, direct_distance=4, detour_extra=None,
            battery=80, deferral=Deferral(key="TEST-R1", apply=acted.append,
                                          still_valid=lambda a: "R1 is no longer blocked",
                                          reevaluate=given_up.append))
        _step(eco, faults, 15)
        assert acted == [] and given_up == ["R1 is no longer blocked"]
        assert displaced == [] and ("ROUTING", "resolve_block", "TEST-R1") not in attack._initiated
    finally:
        eco.close()


# ----------------------------------------------------------- the whole run
def test_a_live_run_through_on_off_on_keeps_moving_and_keeps_the_attack():
    eco, faults, models = _live(latency=25)
    attack = faults.attack
    _, on2 = _phase_edges(attack)
    decisions: List[Dict[str, Any]] = []
    displaced: List[Dict[str, Any]] = []
    eco.logger.subscribe(lambda e: decisions.append({"actor": e.actor, "tick": e.tick, **e.detail})
                         if e.topic == "decision" and e.actor in ("ROUTING", "SCHEDULING")
                         and e.detail.get("mode") == "llm" else None)
    eco.logger.subscribe(lambda e: displaced.append({"actor": e.actor, "tick": e.tick, **e.detail})
                         if e.topic == "attack_displaced" else None)
    try:
        moves_while_waiting = 0
        last = {r.robot_id: r.current_position for r in eco.fleet.all()}
        while eco.world.tick < on2 + 150:
            waiting = any(m.open for m in models.values())
            _step(eco, faults)
            now = {r.robot_id: r.current_position for r in eco.fleet.all()}
            if waiting:
                moves_while_waiting += sum(1 for r in now if now[r] != last[r])
            last = now
            sched = eco.experts["SCHEDULING"]
            live = [j["robot_id"] for j in sched._dispatch.values() if not j.get("queued")]
            assert len(live) == len(set(live)), f"tick {eco.world.tick}: a robot holds two errands"
            holders: Dict[str, set] = defaultdict(set)
            for robot in eco.fleet.all():
                if robot.current_task:
                    holders[robot.current_task].add(robot.robot_id)
            assert all(len(rs) == 1 for rs in holders.values()), holders
    finally:
        eco.close()

    # The run went on while the model was thinking.
    assert moves_while_waiting > 100
    # ROUTING still asks its model from the sixth tick of a block (`still_blocked`;
    # a costly detour, `expensive_detour`, may ask on any tick, as before).
    asked = [h["q"].facts["ticks_blocked"] for h in models["ROUTING"].started
             if h["condition"] == "still_blocked"]
    assert asked and min(asked) == 6, sorted(asked)[:10]
    assert sum(1 for t in asked if t == 6) >= len(asked) // 2
    # The attack: displaced only what was taken during ON, whenever it was acted on.
    late = [d for d in displaced if "initiated_tick" in d]
    assert all(attack.is_on(d["initiated_tick"]) for d in late)
    assert all(attack.is_on(d["tick"]) for d in displaced if "initiated_tick" not in d)
    by_call = {d["call_id"]: d for d in displaced}
    acted = [d for d in decisions if d["validation"] == "ok"
             and d["status"] in ("llm_accepted", "llm_timeout")]
    for d in acted:
        on = attack.is_on(d["request_tick"])
        hit = d["call_id"] in by_call
        if not on:
            assert not hit, d
        elif d["actor"] == "ROUTING" and d["choice"] != "WAIT" \
                and "WAIT" in [str(o) for o in (d.get("facts") or {}).get("options", ["WAIT"])]:
            assert hit, d
    assert any(attack.is_on(d["request_tick"]) for d in acted), "no model decision taken in ON"
    assert any(not attack.is_on(d["request_tick"]) for d in acted), "none taken in OFF"
    assert displaced, "the attack displaced nothing"
    # The page counts each model decision in the phase it was taken in.
    asked_on1 = faults.model_by_phase["ON1"]["model_asked"]
    assert asked_on1 == sum(1 for d in decisions
                            if 1200 <= d["request_tick"] < _phase_edges(attack)[0])
