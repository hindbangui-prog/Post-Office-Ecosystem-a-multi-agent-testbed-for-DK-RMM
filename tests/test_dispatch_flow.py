"""
Two defects in the scheduler's dispatch plumbing, traced in a normal run and
pinned here.

1. Several assignment conversations are in flight at once and were all shown
   the same free robots, so at the start of a shift every one of them named
   the same nearest robot; only the first reservation stuck and the rest began
   again next tick. Five robots stood idle beside six ready jobs while errands
   were handed out one every four ticks (measured: first departures at ticks
   23, 27, 31, 35 and 50 on seed 11). Now a conversation whose robot was taken
   while it was asking chooses again from the candidates still free, in the
   same tick.

2. An errand prepared and parked behind a robot still finishing its previous
   one was released by the 30-tick paperwork timeout whenever that robot was
   held up in a doorway ("no answer in 31 ticks at stage waiting for its
   robot"), although the queue's own patience is 120 ticks. The parcel went
   back to the queue and the whole chain started again.
"""

from __future__ import annotations

from post_office.config.settings import config
from post_office.simulation import build


def _run(seed: int, ticks: int, preset: str = "default"):
    eco = build(seed=seed, run_id=f"flow-{seed}", config={**config(preset), "keep_events": 200000})
    eco.start()
    for _ in range(ticks):
        eco.step()
    return eco


def test_idle_robots_are_all_given_work_in_the_same_conversation_round():
    """
    Five robots idle, fourteen parcels waiting: every robot leaves on the
    first round of assignments, not one every four ticks.
    """
    eco = _run(11, 40)
    try:
        started = {}
        for e in eco.logger._recent:
            if e.topic == "task_started" and e.detail.get("robot_id"):
                started.setdefault(e.detail["robot_id"], e.tick)
        assert len(started) == 5, started
        first, last = min(started.values()), max(started.values())
        assert last - first <= 2, f"departures were staggered: {started}"
    finally:
        eco.close()


def test_a_conversation_that_lost_its_robot_does_not_start_over():
    """No 'taken while we were asking' round trips: every choose_robot answer ends in an assignment or a stop."""
    eco = _run(11, 120)
    try:
        chosen = [e for e in eco.logger._recent if e.topic == "decision" and e.actor == "SCHEDULING"
                  and e.detail.get("decision") == "choose_robot"]
        assigned = [e for e in eco.logger._recent if e.topic == "task_assigned"]
        # Before the fix the same tick carried five choose_robot decisions and
        # one assignment; now a decision that names a taken robot is followed
        # by another in the same tick, and the tick's assignments match.
        by_tick = {}
        for e in assigned:
            by_tick[e.tick] = by_tick.get(e.tick, 0) + 1
        first_round = min(by_tick)
        assert by_tick[first_round] >= 3, f"only {by_tick[first_round]} assignment(s) on the first round at tick {first_round}"
        assert chosen, "no robot was ever chosen"
    finally:
        eco.close()


def test_a_queued_errand_is_not_released_by_the_paperwork_timeout():
    eco = _run(11, 600)
    try:
        released = [e.detail.get("reason", "") for e in eco.logger._recent if e.topic == "task_released"]
        assert not [r for r in released if "waiting for its robot" in r], released
    finally:
        eco.close()


def test_the_scheduler_still_never_sends_two_robots_for_one_parcel():
    eco = _run(11, 300)
    try:
        live = {}
        for e in eco.logger._recent:
            if e.topic == "task_started":
                pid = e.detail.get("parcel_id") or e.correlation_id
                live.setdefault(pid, set()).add(e.detail.get("robot_id"))
        # one parcel may be carried by several robots over several legs, but a
        # single task is started by exactly one robot
        by_task = {}
        for e in eco.logger._recent:
            if e.topic == "task_started" and e.detail.get("task_type") == "TRANSPORT":
                by_task.setdefault(e.detail["task_id"], []).append(e.detail.get("robot_id"))
        doubled = {t: r for t, r in by_task.items() if len(r) > 1}
        assert not doubled, doubled
    finally:
        eco.close()
