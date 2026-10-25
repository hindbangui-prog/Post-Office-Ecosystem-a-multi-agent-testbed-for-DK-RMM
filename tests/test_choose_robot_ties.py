"""
SCHEDULING `choose_robot`: routine ties are the rule's, the model only for a real gap.

`equally_placed` (two able robots within two cells) used to mark the rule
insufficient, on the belief that the rule's tie-break was the walk. It is not:
`which_robot` ranks able robots by distance, then charge, then robot id when
the job is urgent, and otherwise by charge among those within six cells of the
nearest, then robot id -- so a tie has one answer, the same on every call. The model was
asked anyway and named a different robot on each call, sometimes against the
measured distance and charge. Now the condition is noted, the rule answers,
and the model is asked only when no robot can finish the errand
(`nobody_able`).

Driven by hand on one agent with a stand-in model, the facility active and
Normal's rule coverage, as `test_scheduling_rule_first.py` does.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest

from post_office.agents.brain import Answer, Brain, DeterministicBrain
from post_office.agents.scheduling_agent import SchedulingAgent
from post_office.simulation.activity import ActivityGate


class _Log:
    def __init__(self):
        self.events = []

    def emit(self, category, topic, **fields):
        self.events.append(SimpleNamespace(topic=topic, **fields))


class _Model(Brain):
    """A model that names a different option on every call: the inconsistency seen live."""

    def __init__(self):
        self.fallback = DeterministicBrain()
        self.calls = 0

    def answer(self, question):
        self.calls += 1
        options = list(question.options)
        return Answer(options[-self.calls % len(options)], "model", source="crewai:fake")


class _Gate:
    def check(self, proposal):
        ok = proposal.choice in tuple(proposal.options)
        return SimpleNamespace(ok=ok, stage="ok" if ok else "schema",
                               violation="" if ok else "not an option")


def _scheduling():
    log = _Log()
    fleet = SimpleNamespace(all=lambda: [SimpleNamespace(robot_id="R1", current_task="T-0")],
                            status_counts=lambda: {})
    gate = ActivityGate(fleet, SimpleNamespace(parcels={}), log)
    gate.observe(30)                                   # the floor is working
    model = _Model()
    agent = SchedulingAgent(brain=model)
    agent.rule_coverage = "authoritative"              # what normal_config() sets
    agent.world = SimpleNamespace(tick=30, activity=gate, logger=log, gate=_Gate())
    return agent, model


def _robot(distance, battery, cost=None):
    return {"distance": distance, "battery": battery,
            "cost": round(distance * 0.55, 1) if cost is None else cost,
            "can_finish": True}


def _ask(agent, robots, able=None, priority="NORMAL", slack=900, options=None):
    return agent.decide("choose_robot", "Which robot takes T-0030?",
                        options=tuple(options or sorted(robots)),
                        correlation_id="T-0030", robots=robots,
                        able=sorted(robots) if able is None else able,
                        priority=priority, slack=slack)


# --------------------------------------------------------- equal candidates
def test_equally_placed_robots_are_assigned_by_the_rule_without_the_model():
    agent, model = _scheduling()
    robots = {"R1": _robot(20, 99.8), "R2": _robot(21, 99.8), "R3": _robot(20, 99.8)}
    answer = _ask(agent, robots)
    record = agent.decisions[-1]
    assert model.calls == 0
    assert record["handling"] == "rule_sufficient" and record["mode"] == "deterministic"
    assert record["trigger"] == "" and record["noted"] == "contention"
    assert answer.choice == "R3"          # all charged alike: the robot id breaks it
    assert answer.reason.endswith("tied on charge, broken by robot id")


def test_the_same_tie_gets_the_same_robot_on_every_call_and_in_any_option_order():
    """T-0030 used to get R1 on one call and R2 on the next. One answer now."""
    agent, model = _scheduling()
    robots = {"R1": _robot(20, 99.8), "R2": _robot(21, 99.8), "R4": _robot(22, 99.8),
              "R5": _robot(20, 99.8)}
    choices = {_ask(agent, robots, options=order).choice
               for order in itertools.permutations(sorted(robots))}
    assert choices == {"R5"} and model.calls == 0


# -------------------------------------------------- deterministic tie-break
def test_a_tie_on_charge_is_broken_by_robot_id_and_the_reason_says_so():
    agent, _ = _scheduling()
    answer = _ask(agent, {"R1": _robot(19, 99.8), "R5": _robot(20, 99.8)})
    assert answer.choice == "R5"
    assert "tied on charge, broken by robot id" in answer.reason
    assert "99.8%" in answer.reason and "20 cells away" in answer.reason


def test_no_tie_note_when_charge_decides():
    agent, _ = _scheduling()
    answer = _ask(agent, {"R1": _robot(19, 99.8), "R5": _robot(20, 90)})
    assert answer.choice == "R1" and "tied" not in answer.reason


def test_a_better_charged_robot_far_beyond_the_nearest_is_not_sent():
    """Charge decides only among robots within six cells of the nearest."""
    agent, _ = _scheduling()
    assert _ask(agent, {"R1": _robot(3, 60), "R2": _robot(10, 99)}).choice == "R1"


def test_charge_still_comes_first_among_robots_close_enough():
    agent, _ = _scheduling()
    answer = _ask(agent, {"R1": _robot(10, 70), "R2": _robot(12, 90)})
    assert answer.choice == "R2" and "tied" not in answer.reason


def test_a_robot_that_cannot_finish_is_never_chosen_over_one_that_can():
    agent, model = _scheduling()
    robots = {"R1": {**_robot(1, 20), "can_finish": False}, "R2": _robot(2, 60)}
    assert _ask(agent, robots, able=["R2"]).choice == "R2" and model.calls == 0


# ------------------------------------------------------------- urgent tasks
@pytest.mark.parametrize("priority,slack", [("URGENT", 900), ("NORMAL", 150)])
def test_urgent_work_takes_the_nearest_able_robot(priority, slack):
    agent, model = _scheduling()
    answer = _ask(agent, {"R1": _robot(4, 50), "R2": _robot(6, 95)},
                  priority=priority, slack=slack)
    assert answer.choice == "R1" and model.calls == 0
    assert "little time left" in answer.reason


def test_urgent_tie_on_distance_goes_to_the_better_charged_robot():
    agent, model = _scheduling()
    answer = _ask(agent, {"R1": _robot(4, 50), "R2": _robot(4, 95), "R3": _robot(5, 99)},
                  priority="URGENT")
    assert answer.choice == "R2" and model.calls == 0
    assert agent.decisions[-1]["noted"] == "contention"


def test_urgent_errand_with_a_low_nearest_robot_is_still_the_rules():
    """`paid_errand_thin_robot` fires, but every able robot can finish: the rule's."""
    agent, model = _scheduling()
    answer = _ask(agent, {"R1": _robot(3, 30), "R2": _robot(9, 95)}, priority="URGENT")
    assert answer.choice == "R1" and model.calls == 0


# ------------------------------------------------- justified model fallback
def test_nobody_able_to_finish_goes_to_the_model_with_its_reason():
    agent, model = _scheduling()
    robots = {"R1": {**_robot(5, 15), "can_finish": False},
              "R2": {**_robot(6, 14), "can_finish": False}}
    _ask(agent, robots, able=[])
    record = agent.decisions[-1]
    assert model.calls == 1
    assert record["handling"] == "llm_insufficient" and record["trigger"] == "contention"
    assert record["trigger_detail"] == "2 robots, none able"
    assert record["rule_choice"] == "R1"           # what the rule would have sent


def test_a_model_reply_off_the_list_is_replaced_by_the_rule():
    agent, model = _scheduling()
    model.answer = lambda q: Answer("R9", "made up", source="crewai:fake")
    robots = {"R1": {**_robot(5, 15), "can_finish": False},
              "R2": {**_robot(6, 14), "can_finish": False}}
    answer = _ask(agent, robots, able=[])
    assert answer.choice == "R1" and agent.decisions[-1]["validation"] == "schema"


# ----------------------------------------------- no needless reconsideration
def test_a_taken_robot_costs_one_new_decision_not_one_per_taken_robot():
    """
    Conversations opened in one tick share a snapshot of the free robots. When
    the robot chosen was taken meanwhile, every robot already taken is dropped
    at once: before, T-0035 was asked five times in one tick (R5, R4, R3, R2,
    R1) as they were dropped one by one.
    """
    agent, model = _scheduling()
    robots = {r: _robot(20, 99.8) for r in ("R1", "R2", "R3", "R4", "R5")}
    content = {"robots": robots, "able": sorted(robots), "priority": "NORMAL", "slack": 900}
    free = {"R4"}
    chosen = []
    agent._takeable = lambda robot_id: robot_id in free
    agent._robot_chosen = lambda task_id, robot_id: chosen.append((task_id, robot_id))
    before = len(agent.decisions)
    agent._robot_answer("T-0035", {}, content, sorted(robots), Answer("R1", "rule"))
    assert chosen == [("T-0035", "R4")]
    assert len(agent.decisions) - before == 1 and model.calls == 0


def test_when_every_robot_was_taken_the_task_is_released_without_asking_again():
    agent, _ = _scheduling()
    robots = {r: _robot(20, 99.8) for r in ("R1", "R2")}
    content = {"robots": robots, "able": sorted(robots), "priority": "NORMAL", "slack": 900}
    agent._claiming.add("T-0030")
    agent._takeable = lambda robot_id: False
    agent._robot_chosen = lambda *a: pytest.fail("nothing is free")
    before = len(agent.decisions)
    agent._robot_answer("T-0030", {}, content, sorted(robots), Answer("R1", "rule"))
    assert len(agent.decisions) == before and "T-0030" not in agent._claiming
