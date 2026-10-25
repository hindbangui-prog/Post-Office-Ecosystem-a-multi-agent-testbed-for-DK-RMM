"""
A slow model must not stop the live floor.

The live page used to freeze -- every robot, the clock and the page -- for as
long as any expert's model was thinking: `ConsultationService.run` joined the
CrewAI worker on the tick's own thread (up to `CONSULT_DEADLINE_S`), and the
runner holds its step lock for the whole tick. With `async_decisions` (set by
the live runner for every preset that is not a study) a decision the rule
cannot settle is handed to the model and the tick goes on: only the parcel,
robot or task in question waits, its caller's `Deferral` applies the answer on
the tick it arrives -- after the caller's own `still_valid` check and the
policy gate -- and a model that does not answer within `llm_deadline_ticks`
gives way to the rule.

The first part drives the decision path with a stand-in model whose answer is
released by hand, so "slow" is exact rather than timed. The last test runs the
real live runner on CrewAI against the fake Ollama server answering slowly.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from post_office.agents.base import BaseAgent
from post_office.agents.brain import Answer, Brain, DeterministicBrain
from post_office.agents.deferral import Deferral, is_pending
from post_office.agents.reasoning import REASONS, Trigger
from post_office.config.settings import EXPERTS, normal_config
from post_office.simulation.ecosystem import build


# ------------------------------------------------------------ a slow model
class SlowModel(Brain):
    """
    A model behind the async seam (`start_consulting` / `finish_consulting`) that
    answers only when `release()` is called: until then every question it was
    given is "still thinking". One question at a time, like a CrewAI expert.
    """

    name = "slow"

    def __init__(self, choose=None) -> None:
        self.fallback = DeterministicBrain()
        self.choose = choose or (lambda question: question.options[-1])
        self.started: List[Dict[str, Any]] = []
        self.sync_calls = 0
        self.last_consultation = None

    # the synchronous seam, which the live path must not use
    def answer(self, question):
        self.sync_calls += 1
        return Answer(self.choose(question), "slow model, asked inline", source="crewai:slow")

    answer_consulting = lambda self, question, trigger: self.answer(question)  # noqa: E731

    # the asynchronous seam
    def free_to_consult(self, question, trigger) -> bool:
        return not any(not h["done"] for h in self.started)

    def start_consulting(self, question, trigger):
        handle = {"question": question, "done": False, "released": False}
        self.started.append(handle)
        return handle

    def finish_consulting(self, handle, give_up: int = 0):
        if give_up and not handle["released"]:
            handle["done"] = True
            rule = self.fallback.answer(handle["question"])
            return Answer(rule.choice, f"{rule.reason} [fallback: no decision within the "
                                       f"decision's deadline of {give_up} ticks]",
                          source="fallback")
        if not handle["released"]:
            return None
        handle["done"] = True
        return Answer(self.choose(handle["question"]), "slow model", source="crewai:slow")

    def release(self) -> None:
        for handle in self.started:
            handle["released"] = True

    @property
    def outstanding(self) -> int:
        return sum(1 for h in self.started if not h["done"])


# ------------------------------------------------- the decision path, by hand
class _Log:
    def __init__(self):
        self.events = []

    def emit(self, category, topic, **fields):
        self.events.append(SimpleNamespace(topic=topic, **fields))
        return self.events[-1]


class _Gate:
    """The policy gate's shape: an answer off the list, or one named `refused`, is refused."""

    def check(self, proposal):
        if proposal.choice not in tuple(proposal.options):
            return SimpleNamespace(ok=False, stage="schema", violation="not an option")
        if proposal.choice == "refused":
            return SimpleNamespace(ok=False, stage="state", violation="refused is no longer free")
        return SimpleNamespace(ok=True, stage="ok", violation="")


class _Expert(BaseAgent):
    """One decision kind, a rule that answers `rule`, and a trigger that always fires."""

    def __init__(self, brain):
        super().__init__("EXPERT", "test expert", brain=brain)

    def install_rules(self):
        rules = self.rules()
        if rules is not None:
            rules.register("pick", lambda q: Answer("rule", "the rule's choice"))

    def install_triggers(self):
        self.triggers.register("pick", lambda facts: Trigger(REASONS.AMBIGUITY, "hard case"))


def _expert(choose=None, deadline=0):
    model = SlowModel(choose)
    agent = _Expert(model)
    agent.async_decisions = True
    agent.llm_deadline_ticks = deadline
    agent.world = SimpleNamespace(tick=10, logger=_Log(), gate=_Gate(), activity=None)
    return agent, model


def _deferral(subject="P-1", valid=lambda answer: ""):
    seen = {"applied": [], "reevaluated": []}
    deferral = Deferral(key=subject, apply=lambda a: seen["applied"].append(a),
                        still_valid=valid, reevaluate=lambda why: seen["reevaluated"].append(why))
    return deferral, seen


def _ask(agent, deferral, options=("rule", "model", "refused")):
    return agent.decide("pick", "which?", options=options, correlation_id="P-1",
                        deferral=deferral)


def _records(agent):
    return [e for e in agent.world.logger.events if e.topic == "decision"]


def test_an_insufficient_rule_hands_the_decision_to_the_model_without_waiting():
    agent, model = _expert()
    deferral, seen = _deferral()
    answer = _ask(agent, deferral)
    assert is_pending(answer) and model.sync_calls == 0 and model.outstanding == 1
    assert agent.pending_decisions()[0]["kind"] == "pick" and seen["applied"] == []
    assert _records(agent) == []                       # recorded when it is decided


def test_the_answer_is_applied_on_the_tick_it_arrives_after_the_gate():
    agent, model = _expert(choose=lambda q: "model")
    deferral, seen = _deferral()
    _ask(agent, deferral)
    for agent.world.tick in range(11, 15):             # ticks go by; the model thinks
        agent._collect_decisions()
    assert seen["applied"] == []
    model.release()
    agent.world.tick = 15
    agent._collect_decisions()
    assert [a.choice for a in seen["applied"]] == ["model"]
    record = _records(agent)[-1]
    assert record.request_tick == 10 and record.response_tick == 15
    assert record.mode == "llm" and record.validation == "ok" and record.status == "llm_accepted"
    assert record.rule_choice == "rule" and agent.pending_decisions() == []


def test_a_stale_answer_is_not_applied_and_the_decision_is_taken_again():
    agent, model = _expert(choose=lambda q: "model")
    deferral, seen = _deferral(valid=lambda a: "P-1 has left the dock")
    _ask(agent, deferral)
    model.release()
    agent.world.tick = 12
    agent._collect_decisions()
    assert seen["applied"] == [] and seen["reevaluated"] == ["P-1 has left the dock"]
    record = _records(agent)[-1]
    assert record.validation == "stale" and record.status == "llm_rejected"
    assert record.violation == "P-1 has left the dock"


def test_an_answer_the_gate_refuses_is_replaced_by_the_rule_and_checked_again():
    agent, model = _expert(choose=lambda q: "refused")
    checked: List[Any] = []
    deferral, seen = _deferral(valid=lambda a: checked.append(a.choice) or "")
    _ask(agent, deferral)
    model.release()
    agent._collect_decisions()
    assert checked == ["refused", "rule"]              # the model's, then the rule's
    assert [a.choice for a in seen["applied"]] == ["rule"]
    assert "rule-after-refusal" in seen["applied"][0].source
    assert _records(agent)[-1].validation == "state" and agent.gate_refusals == 1


def test_a_model_that_does_not_answer_in_time_gives_way_to_the_rule():
    agent, model = _expert(choose=lambda q: "model", deadline=5)
    deferral, seen = _deferral()
    _ask(agent, deferral)
    agent.world.tick = 14
    agent._collect_decisions()
    assert seen["applied"] == []                       # 4 ticks: still waiting
    agent.world.tick = 15
    agent._collect_decisions()
    assert [a.choice for a in seen["applied"]] == ["rule"]
    assert _records(agent)[-1].status == "llm_timeout"


def test_the_same_subject_is_not_asked_twice_while_its_question_is_out():
    agent, model = _expert()
    first, seen_first = _deferral()
    second, seen_second = _deferral()
    assert is_pending(_ask(agent, first)) and is_pending(_ask(agent, second))
    assert len(model.started) == 1
    model.release()
    agent._collect_decisions()
    assert seen_first["applied"] == [] and len(seen_second["applied"]) == 1  # newest picture


def test_another_subject_gets_the_rule_while_the_model_is_busy():
    agent, model = _expert()
    _ask(agent, _deferral("P-1")[0])
    deferral, _ = _deferral("P-2")
    answer = _ask(agent, deferral)
    assert answer.choice == "rule" and len(model.started) == 1
    record = _records(agent)[-1]
    assert record.mode == "deterministic" and record.handling == "busy_rule"
    assert record.llm_skipped == "busy" and record.skipped_trigger == REASONS.AMBIGUITY
    assert agent.busy_skips == 1


def test_the_subject_holds_while_its_question_is_with_the_model():
    """Even where the rule could now answer, the subject waits for its model answer."""
    agent, model = _expert(choose=lambda q: "model")
    deferral, seen = _deferral()
    _ask(agent, deferral)
    agent.triggers = type(agent.triggers)()             # now the rule would be sufficient
    held, seen_held = _deferral()
    assert is_pending(_ask(agent, held)) and len(model.started) == 1
    model.release()
    agent._collect_decisions()
    # Applied once, through the newest picture of the subject.
    assert seen["applied"] == [] and [a.choice for a in seen_held["applied"]] == ["model"]
    assert _records(agent)[-1].validation == "ok"


def test_a_step_by_hand_decides_now_and_the_pending_answer_is_overtaken():
    agent, model = _expert()
    deferral, seen = _deferral()
    _ask(agent, deferral)
    agent.async_decisions = False                       # the clock stopped; a tick by hand
    agent.triggers = type(agent.triggers)()
    now = _ask(agent, _deferral()[0])
    assert now.choice == "rule"
    model.release()
    agent._collect_decisions()
    assert seen["applied"] == [] and seen["reevaluated"] == []
    assert _records(agent)[-1].validation == "stale"


def test_without_async_decisions_the_model_is_asked_inline_as_before():
    agent, model = _expert(choose=lambda q: "model")
    agent.async_decisions = False
    deferral, seen = _deferral()
    answer = _ask(agent, deferral)
    assert answer.choice == "model" and model.sync_calls == 1 and model.started == []
    assert seen["applied"] == []                       # the caller applies it, as always


# ------------------------------------------------- the whole floor, slow model
def _positions(eco):
    return {r.robot_id: (r.current_position.as_dict() if r.current_position else None)
            for r in eco.fleet.all()}


def test_the_fleet_and_the_clock_keep_going_while_a_model_is_thinking():
    """
    Normal, every expert on a model that does not answer for 300 ticks. The
    clock advances, robots on their errands keep moving and finish work, while
    the decisions the model holds wait; once it answers, each answer is checked
    and applied (or rejected as stale) and no robot or task is double-booked.
    """
    models = {agent_id: SlowModel() for agent_id in EXPERTS}
    eco = build(seed=1, config={**normal_config(), "async_decisions": True,
                                "llm_deadline_ticks": 0}, log_path=None, brains=models)
    try:
        eco.start()
        while not any(m.outstanding for m in models.values()):
            eco.step()
            assert eco.world.tick < 400, "no decision reached the model"
        asked_at = eco.world.tick
        before = _positions(eco)
        done_before = eco.summary()["tasks"].get("COMPLETED", 0)
        moved = set()
        for _ in range(300):
            eco.step()
            moved |= {r for r, p in _positions(eco).items() if p != before[r]}
        held = {a: agent.pending_decisions() for a, agent in eco.experts.items()
                if agent.pending_decisions()}
        held.update({"PLANNER": eco.planner.pending_decisions()}
                    if eco.planner.pending_decisions() else {})
        assert eco.world.tick == asked_at + 300
        assert held, "the slow model's decisions are still waiting"
        assert len(moved) >= 3, f"only {sorted(moved)} moved while the model was thinking"
        assert eco.summary()["tasks"].get("COMPLETED", 0) > done_before

        for model in models.values():
            model.release()
        decided = []
        eco.logger.subscribe(lambda e: decided.append(e.detail)
                             if e.topic == "decision" and e.detail.get("mode") == "llm" else None)
        eco.step()
        assert decided and all(d["request_tick"] <= asked_at + 300 < d["response_tick"]
                               for d in decided)
        assert {d["validation"] for d in decided} <= {"ok", "stale", "schema", "policy", "state"}
        for _ in range(50):
            eco.step()
        scheduling = eco.experts["SCHEDULING"]
        live = [j["robot_id"] for j in scheduling._dispatch.values() if not j.get("queued")]
        assert len(live) == len(set(live)), "a robot holds two live errands"
        assigned = [t for t in eco.world.tasks.all() if t.assigned_robot and t.is_open]
        by_robot: Dict[str, int] = {}
        for task in assigned:
            if task.status.value == "IN_PROGRESS":
                by_robot[task.assigned_robot] = by_robot.get(task.assigned_robot, 0) + 1
        assert all(n == 1 for n in by_robot.values()), by_robot
    finally:
        eco.close()


def test_headless_runs_still_wait_for_the_model():
    """`normal_config()` alone (every tool, every experiment) keeps the old timing."""
    models = {agent_id: SlowModel(choose=lambda q: q.options[0]) for agent_id in EXPERTS}
    eco = build(seed=1, config=normal_config(), log_path=None, brains=models)
    try:
        eco.start()
        for _ in range(150):
            eco.step()
        assert not any(m.started for m in models.values())
        assert sum(m.sync_calls for m in models.values()) > 0
    finally:
        eco.close()


# --------------------------------------------- the live runner on CrewAI
def test_the_live_page_keeps_ticking_while_ollama_is_slow(fake_ollama):
    """
    The live runner (the loop behind the page) on Normal, every expert on CrewAI,
    the fake Ollama taking 1.5 s per reply. Watched from outside the tick, as the
    page is: while a consultation is in flight the published tick goes on and
    robots move; the consultation closes `decided` and its answer is recorded
    with the ticks it was asked and answered on.
    """
    pytest.importorskip("crewai")
    from post_office.api.runner import SimulationRunner
    from post_office.crew.console import quiet

    with quiet():
        _watch_the_live_page(fake_ollama, SimulationRunner)


def _watch_the_live_page(fake_ollama, SimulationRunner):
    fake_ollama.delay(1.5)
    runner = SimulationRunner(seed=1, settings=fake_ollama.settings, tick_seconds=0.02,
                              verify_model=False)
    decided = []
    runner.eco.logger.subscribe(lambda e: decided.append(e.detail)
                                if e.topic == "decision" and e.detail.get("mode") == "llm"
                                else None)
    try:
        assert runner.llm_agents and not runner.eco.async_decisions   # a step by hand waits
        runner.start()
        assert runner.eco.async_decisions                             # the running clock does not
        windows = []
        end = time.monotonic() + 12.0
        while time.monotonic() < end:
            if runner.busy():
                tick = runner.last_frame["snapshot"]["tick"]
                cells = {r.robot_id: r.current_position for r in runner.eco.fleet.all()}
                time.sleep(0.8)
                if runner.busy():
                    windows.append((tick, runner.last_frame["snapshot"]["tick"], cells,
                                    {r.robot_id: r.current_position
                                     for r in runner.eco.fleet.all()}))
            time.sleep(0.05)
    finally:
        runner.stop()
        runner.close()
    assert windows, "no consultation was in flight long enough to watch"
    assert all(after > before for before, after, _, _ in windows), \
        "the clock stood still while the model was thinking"
    assert any(a != b for _, _, a, b in windows), "no robot moved while the model was thinking"
    asked = [d for d in decided if d["status"] == "llm_accepted"]
    assert asked and all(d["response_tick"] > d["request_tick"] for d in asked)
