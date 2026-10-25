"""
SCHEDULING on the live clock: a model's assignment is carried out, not timed out.

On the live clock (`async_decisions`) a model answer arrives many ticks after
its question. Two things used to throw valid answers away for that alone:

- `choose_next_task` left its shortlist open while the model thought, so the
  next conversation was shown the same tasks and the rule dispatched one first:
  every model answer arrived to find "T-0033 is no longer waiting";
- the dispatch timers (`DISPATCH_TIMEOUT`, `ERRAND_TIMEOUT`, `QUEUE_PATIENCE`)
  were measured on a clock that stopped for the model, and released a dispatch
  whose clearance was still with RESOURCE's model ("no answer in 31 ticks").

Now a pending `choose_next_task` holds its shortlist (urgent tasks excepted),
the timers allow for the model's deadline, and an answer is rejected only when
its task or robot has genuinely gone. These tests drive SCHEDULING with a model
that answers a fixed number of ticks after it is asked.
"""

from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from typing import Any, Dict, List

from post_office.agents.brain import Answer, Brain, DeterministicBrain
from post_office.agents.deferral import is_pending
from post_office.config.settings import normal_config
from post_office.simulation.ecosystem import build


class TickModel(Brain):
    """Answers `latency` ticks after it was asked, with `choose(question)`; one question at a time."""

    name = "tick-model"

    def __init__(self, eco_box: Dict[str, Any], latency: int, choose=None) -> None:
        self.fallback = DeterministicBrain()
        self.box, self.latency = eco_box, latency
        self.choose = choose or (lambda q: q.options[0])
        self.open: List[Dict[str, Any]] = []
        self.started: List[Dict[str, Any]] = []
        self.last_consultation = None

    def answer(self, question):
        return Answer(self.choose(question), "model", source="crewai:tick")

    answer_consulting = lambda self, question, trigger: self.answer(question)  # noqa: E731

    def free_to_consult(self, question, trigger):
        return not self.open

    def start_consulting(self, question, trigger):
        handle = {"q": question, "at": self.box["eco"].world.tick}
        self.open.append(handle)
        self.started.append(handle)
        return handle

    def finish_consulting(self, handle, give_up=0):
        if self.box["eco"].world.tick - handle["at"] < self.latency:
            return None
        self.open.remove(handle)
        return Answer(self.choose(handle["q"]), "model", source="crewai:tick")


def _seeded_choice(question):
    digest = hashlib.sha256(question.decision_id.encode()).hexdigest()
    return random.Random(int(digest, 16)).choice(list(question.options))


def _live(latency: int, policy: str = "insufficient", choose=None, seed: int = 1):
    box: Dict[str, Any] = {}
    model = TickModel(box, latency, choose)
    eco = build(seed=seed, config={**normal_config(), "async_decisions": True,
                                   "llm_deadline_ticks": 120},
                log_path=None, brains={"SCHEDULING": model})
    box["eco"] = eco
    eco.experts["SCHEDULING"].consult_policy = policy
    eco.start()
    return eco, model


# ------------------------------------------------------- the held shortlist
def test_a_pending_next_task_holds_its_shortlist_and_gives_back_the_rest():
    eco, model = _live(latency=10 ** 6, policy="always")
    try:
        sched = eco.experts["SCHEDULING"]
        while not sched._held:
            eco.step()
            assert eco.world.tick < 300, "no next-task question reached the model"
        (asked, held), = sched._held.items()
        assert held and held <= sched._claiming
        assert not any(sched._urgent(t) for t in held)          # urgent work is never held
        # The next question to the queue is not shown the held tasks.
        for _ in range(5):
            eco.step()
        shown = [h["q"] for h in model.started if h["q"].kind == "choose_next_task"]
        assert set(shown[0].options) >= held
        chosen = sorted(held)[0]
        sched._next_task_chosen(asked, list(shown[0].options), Answer(chosen, "model"))
        assert asked not in sched._held
        assert not (held - {chosen}) & sched._claiming          # the rest is given back
        assert chosen in sched._claiming or chosen in sched._dispatch
    finally:
        eco.close()


def test_the_hold_is_not_staleness_but_a_task_assigned_elsewhere_is():
    eco, _ = _live(latency=10 ** 6, policy="always")
    try:
        sched = eco.experts["SCHEDULING"]
        while not sched._held:
            eco.step()
        (asked, held), = sched._held.items()
        candidates = sorted(held)
        deferral = sched._next_task_deferral(asked, candidates)
        assert deferral.still_valid(Answer(candidates[0], "model")) == ""
        task = eco.world.tasks.get(candidates[0])
        task.assign("SCHEDULING", eco.world.tick, "SCHEDULING", robot_id="R1")
        assert "no longer waiting" in deferral.still_valid(Answer(candidates[0], "model"))
        deferral.reevaluate("gone")
        assert asked not in sched._held and not (held & sched._claiming - {candidates[0]})
    finally:
        eco.close()


# ------------------------------------------------------- the dispatch timers
def test_a_dispatch_waiting_on_a_model_is_not_given_up_on_the_paperwork_timer():
    eco, _ = _live(latency=1)
    try:
        sched = eco.experts["SCHEDULING"]
        sched._dispatch["T-X"] = {"robot_id": "R1", "stage": "clearance",
                                  "since": eco.world.tick - (sched.DISPATCH_TIMEOUT + 5)}
        released = []
        sched._abandon = lambda task_id, reason, cause="": released.append((task_id, reason))
        eco.world.model_busy_tick = eco.world.tick               # a model decision is out
        sched._sweep_stale()
        assert released == []                                    # within the model's allowance
        sched._dispatch["T-X"]["since"] = eco.world.tick - (sched.DISPATCH_TIMEOUT + 121)
        sched._sweep_stale()
        assert released and released[0][0] == "T-X"              # a lost reply is still caught
        # No model thinking anywhere: a lost message is caught as quickly as
        # ever (a collapse scenario that drops messages depends on it).
        released.clear()
        eco.world.model_busy_tick = eco.world.tick - 50
        sched._dispatch["T-X"]["since"] = eco.world.tick - (sched.DISPATCH_TIMEOUT + 5)
        sched._sweep_stale()
        assert released and released[0][0] == "T-X"
        sched.async_decisions = False                            # the headless clock: as before
        released.clear()
        eco.world.model_busy_tick = eco.world.tick
        sched._sweep_stale()
        assert released and released[0][0] == "T-X"
    finally:
        eco.close()


# ---------------------------------------------------- from answer to errand
def test_the_robot_the_model_chooses_is_assigned_and_starts_the_task():
    """
    Every SCHEDULING decision through a model answering 40 ticks later. Each
    accepted `choose_robot` ends with that robot assigned and on that task;
    the clock and the other robots go on meanwhile; nothing is booked twice.
    """
    eco, model = _live(latency=40, policy="always", choose=_seeded_choice, seed=2)
    decided: List[Dict[str, Any]] = []
    eco.logger.subscribe(lambda e: decided.append({"corr": e.correlation_id, **e.detail})
                         if e.topic == "decision" and e.actor == "SCHEDULING"
                         and e.detail.get("mode") == "llm" else None)
    try:
        sched = eco.experts["SCHEDULING"]
        moved_while_pending = 0
        last = {r.robot_id: r.current_position for r in eco.fleet.all()}
        for _ in range(1200):
            pending = bool(sched.pending_decisions())
            eco.step()
            now = {r.robot_id: r.current_position for r in eco.fleet.all()}
            if pending:
                moved_while_pending += sum(1 for r in now if now[r] != last[r])
            last = now
            live = [j["robot_id"] for j in sched._dispatch.values() if not j.get("queued")]
            assert len(live) == len(set(live)), f"tick {eco.world.tick}: a robot holds two errands"
            holders: Dict[str, set] = defaultdict(set)
            for robot in eco.fleet.all():
                if robot.current_task:
                    holders[robot.current_task].add(robot.robot_id)
            assert all(len(rs) == 1 for rs in holders.values()), holders
        assert moved_while_pending > 50, "robots stood still while the model was thinking"

        chosen = [d for d in decided if d["decision"] == "choose_robot"
                  and d["status"] == "llm_accepted" and d["validation"] == "ok"]
        assert chosen, "no model robot choice was accepted"
        for d in chosen:
            task = next(t for t in eco.world.tasks.all() if d["corr"] in (t.task_id, t.parcel_id)
                        and any(h["tick"] >= d["response_tick"] for h in t.history))
            after = [h for h in task.history if h["tick"] >= d["response_tick"]]
            assigned = next(h for h in after if h["status"] == "ASSIGNED")
            started = next(h for h in after if h["status"] == "IN_PROGRESS")
            assert assigned["robot"] == started["robot"] == d["choice"], (d, after)
            assert started["tick"] - d["response_tick"] <= 10
        rejected = [d for d in decided if d["validation"] == "stale"]
        assert all(("no longer" in d["violation"] or "taken" in d["violation"])
                   for d in rejected), rejected
    finally:
        eco.close()


def test_a_slow_next_task_answer_is_applied_rather_than_overtaken():
    eco, model = _live(latency=80, choose=_seeded_choice)
    decided: List[Dict[str, Any]] = []
    eco.logger.subscribe(lambda e: decided.append(e.detail)
                         if e.topic == "decision" and e.actor == "SCHEDULING"
                         and e.detail.get("decision") == "choose_next_task"
                         and e.detail.get("mode") == "llm" else None)
    try:
        for _ in range(1500):
            eco.step()
        assert decided
        applied = [d for d in decided if d["status"] == "llm_accepted"]
        assert len(applied) >= 0.6 * len(decided), [d.get("violation") for d in decided]
        assert all(d["response_tick"] - d["request_tick"] >= 80 for d in applied)
    finally:
        eco.close()
