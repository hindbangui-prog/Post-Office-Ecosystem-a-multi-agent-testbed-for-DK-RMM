"""
Giving a robot its next errand before it has finished the current one.

The gap this closes, traced through the code rather than guessed at: a robot
sets its parcel down, reports `delivered`, and only then does anything start
happening on its behalf. The scheduler releases its reservation, notices a
free robot on its next tick, asks the queue clerk what is next, asks who
should take it, asks routing for a path and resource for clearance, and
finally sends the command. Six ticks, every errand, with the robot standing
on the spot for all of them -- measured as 49% of all the time the fleet
spends idle.

So the errand is arranged while the robot is still walking the last few cells
of the one before it, and handed over the moment it is genuinely free.

What must not happen is the queued errand running early. A robot that has been
given its next job while still carrying the last one has two parcels as far as
the task registry is concerned, which is exactly the confusion the one-parcel
model exists to avoid. The queued errand is therefore inert: it is arranged,
validated and parked, and nothing commands the robot until it is idle,
empty-handed and still fit to do it.

And "still fit" is checked again at the moment of handover, not assumed from
when it was arranged. Several ticks pass in between, during which the battery
drains, the parcel may have been moved by somebody else, a shelf may have
filled and the task may have been released by the stale sweep. A clearance
granted against conditions that have since changed is not a clearance.
"""

from __future__ import annotations

import pytest

from tests.presets import busy_config
from post_office.simulation import build


@pytest.fixture
def busy():
    made = build(seed=1, run_id="queued", config=busy_config())
    made.start()
    yield made
    made.close()


def run(eco, ticks):
    for _ in range(ticks):
        eco.step()
    return eco


def queued_jobs(scheduler):
    return {task_id: job for task_id, job in scheduler._dispatch.items()
            if job.get("queued")}


# ------------------------------------------------------- errands get queued
def test_an_errand_is_arranged_before_the_robot_is_free(busy):
    """
    The point of the whole thing. Somewhere in a busy run there is a robot on
    its last few cells with its next job already routed and cleared.
    """
    scheduler = busy.experts["SCHEDULING"]
    seen = 0
    for _ in range(600):
        busy.step()
        seen = max(seen, len(queued_jobs(scheduler)))

    assert seen > 0, "no errand was ever queued behind a working robot"


def test_a_queued_errand_belongs_to_a_robot_that_is_still_working(busy):
    """
    Queued means "next", not "spare". An errand parked against an idle robot
    is an errand that should simply have been given to it.

    Robots step after the experts within a tick, so a robot can finish its
    delivery moments after the scheduler has already run. That leaves a
    one-tick window where an errand is parked against a robot that is free --
    harmless, because a parked errand is inert, but it means the invariant is
    "handed over promptly", not "never observed".

    An errand whose route or clearance has not arrived is a different case
    again: the robot is free and the paperwork is not finished. Holding it is
    deliberate, so only a `READY` errand is held to the two-tick rule.
    """
    scheduler = busy.experts["SCHEDULING"]
    waiting_since = {}
    for _ in range(600):
        busy.step()
        still = set()
        for task_id, job in queued_jobs(scheduler).items():
            robot = busy.fleet.get(job["robot_id"])
            assert robot is not None
            if not robot.is_available or job.get("prep") != "READY":
                continue
            still.add(task_id)
            waiting_since[task_id] = waiting_since.get(task_id, 0) + 1
            assert waiting_since[task_id] <= 2, (
                f"{task_id} has been parked against the free "
                f"{robot.robot_id} for {waiting_since[task_id]} ticks")
        for task_id in list(waiting_since):
            if task_id not in still:
                waiting_since.pop(task_id)


# ------------------------------------------- and do not run before their time
def test_a_queued_errand_never_commands_a_robot_that_is_still_carrying(busy):
    """
    The failure that would break the one-parcel model: a robot told to collect
    its next parcel while the last one is still on board.
    """
    scheduler = busy.experts["SCHEDULING"]
    for _ in range(600):
        busy.step()
        for task_id, job in scheduler._dispatch.items():
            if job.get("queued"):
                continue                      # inert by definition
            robot = busy.fleet.get(job["robot_id"])
            if robot is None or robot.carrying is None:
                continue
            # A live errand whose robot carries something must be carrying
            # that errand's own parcel, never another one.
            assert robot.carrying == job["parcel_id"], (
                f"{robot.robot_id} is carrying {robot.carrying} on {task_id}")


def test_no_robot_ever_holds_two_live_errands(busy):
    scheduler = busy.experts["SCHEDULING"]
    for _ in range(600):
        busy.step()
        live = [job["robot_id"] for job in scheduler._dispatch.values()
                if not job.get("queued")]
        assert len(live) == len(set(live)), f"a robot has two live errands: {live}"


def test_a_robot_has_at_most_one_errand_waiting_for_it(busy):
    scheduler = busy.experts["SCHEDULING"]
    for _ in range(600):
        busy.step()
        waiting = [job["robot_id"] for job in queued_jobs(scheduler).values()]
        assert len(waiting) == len(set(waiting)), f"two queued for one: {waiting}"


# ----------------------------------------------- revalidated at the handover
def test_a_queued_errand_is_checked_again_before_it_is_carried_out(busy):
    """
    Not merely dequeued. The handover re-runs the conditions, because several
    ticks have passed since they were true: the parcel is looked for where the
    errand expects it, and the robot's charge is measured against what the
    errand was cleared for rather than what it had then.
    """
    scheduler = busy.experts["SCHEDULING"]
    run(busy, 400)

    task_id, job = next(iter(queued_jobs(scheduler).items()), (None, None))
    if job is None:
        pytest.skip("nothing queued at this tick")

    robot = busy.fleet.get(job["robot_id"])
    # The parcel is spirited away between the arranging and the handover.
    busy.env.parcels.pop(job["parcel_id"], None)

    assert not scheduler.handover_ready(task_id), \
        "a queued errand whose parcel has gone is still considered executable"


def test_an_errand_that_cannot_be_handed_over_goes_back_in_the_queue(busy):
    scheduler = busy.experts["SCHEDULING"]
    run(busy, 400)

    task_id, job = next(iter(queued_jobs(scheduler).items()), (None, None))
    if job is None:
        pytest.skip("nothing queued at this tick")
    busy.env.parcels.pop(job["parcel_id"], None)

    run(busy, 40)
    assert task_id not in scheduler._dispatch, "the dead errand is still held"


def test_a_prepared_route_that_has_gone_stale_is_planned_again(busy):
    """
    The path was planned from the cell the robot was walking towards, several
    ticks before it arrived. A wall put up in between makes it a description
    of a building that no longer exists -- and the answer is to ask routing
    again, not to walk it anyway and not to throw the errand away.
    """
    scheduler = busy.experts["SCHEDULING"]
    task_id = job = None
    for _ in range(600):
        busy.step()
        task_id, job = next(((t, j) for t, j in queued_jobs(scheduler).items()
                             if j.get("to_pickup")), (None, None))
        if job is not None:
            break
    if job is None:
        pytest.skip("no errand was routed while parked")

    robot = busy.fleet.get(job["robot_id"])
    busy.env.grid.add_obstacle(job["to_pickup"][len(job["to_pickup"]) // 2])
    assert not scheduler._route_is_fresh(job, robot), \
        "a route through a wall is still considered fresh"
    assert not scheduler.handover_ready(task_id), \
        "a stale route would have been walked"

    scheduler._replan_queued(task_id)
    again = scheduler._dispatch.get(task_id)
    assert again is not None, "the errand was thrown away rather than replanned"
    assert not again.get("routed")
    assert again.get("prep") in ("QUEUED", "VALIDATED")
    assert scheduler._queued.get(robot.robot_id) == task_id, \
        "the errand lost its place behind its robot"


# ------------------------------------- one current errand, one prepared one
def test_a_queued_errand_always_sits_behind_a_live_one(busy):
    """
    The pairing the whole model rests on: a parked errand belongs to a robot
    that is running an errand of its own. A robot with a parked errand and
    nothing live is a robot that should simply have been given the work.
    """
    scheduler = busy.experts["SCHEDULING"]
    for _ in range(600):
        busy.step()
        live = {job["robot_id"] for job in scheduler._dispatch.values()
                if not job.get("queued")}
        for task_id, job in queued_jobs(scheduler).items():
            robot = busy.fleet.get(job["robot_id"])
            if robot is not None and robot.is_available:
                continue               # the one-tick handover window
            assert job["robot_id"] in live, (
                f"{task_id} is parked behind {job['robot_id']}, "
                "which has no errand of its own")


def test_the_robot_does_not_move_before_promotion(busy):
    """
    A prepared errand is paperwork. Until it is promoted the robot must not be
    walking its route, holding its task or carrying its parcel -- the
    simulator stays the source of truth for where the robot is.
    """
    scheduler = busy.experts["SCHEDULING"]
    for _ in range(600):
        busy.step()
        for task_id, job in queued_jobs(scheduler).items():
            robot = busy.fleet.get(job["robot_id"])
            if robot is None:
                continue
            assert robot.current_task != task_id, (
                f"{robot.robot_id} is already on the parked {task_id}")
            assert robot.carrying != job["parcel_id"], (
                f"{robot.robot_id} has collected {job['parcel_id']} early")


def test_routing_is_prepared_but_the_route_is_not_walked(busy):
    """
    Routing may plan ahead. The plan lives on the parked errand, not in the
    robot: while the plan sits there the robot is still walking towards its
    own drop, on its own task.
    """
    scheduler = busy.experts["SCHEDULING"]
    seen = 0
    for _ in range(600):
        busy.step()
        for task_id, job in queued_jobs(scheduler).items():
            if not job.get("routed"):
                continue
            robot = busy.fleet.get(job["robot_id"])
            if robot is None or not robot.on_final_leg:
                continue
            seen += 1
            assert job.get("to_pickup"), "a routed errand with no route"
            live = next((j for t, j in scheduler._dispatch.items()
                         if j.get("robot_id") == robot.robot_id
                         and not j.get("queued")), None)
            assert live is not None
            assert robot.current_task != task_id
            assert robot.destination == live["dropoff"], (
                f"{robot.robot_id} is not walking its own errand")
    assert seen, "no parked errand was ever routed ahead of time"


def test_a_queued_errand_is_never_commanded_without_clearance(busy):
    """
    Preparing ahead must not become a way round RESOURCE. Nothing reaches the
    floor uncleared, queued or not.
    """
    scheduler = busy.experts["SCHEDULING"]
    for _ in range(600):
        busy.step()
        for task_id, job in scheduler._dispatch.items():
            if job.get("stage") != "under way":
                continue
            assert job.get("cleared"), f"{task_id} is running uncleared"


def test_an_aborted_current_errand_does_not_release_the_queued_one_unchecked(busy):
    """
    Losing the errand a robot is on frees the robot, which is exactly the
    condition the handover waits for. It must still go through the same
    checks rather than being let straight out.
    """
    scheduler = busy.experts["SCHEDULING"]
    run(busy, 400)

    task_id, job = next(iter(queued_jobs(scheduler).items()), (None, None))
    if job is None:
        pytest.skip("nothing queued at this tick")
    robot_id = job["robot_id"]

    live = next((t for t, j in scheduler._dispatch.items()
                 if j.get("robot_id") == robot_id and not j.get("queued")), None)
    if live is None:
        pytest.skip("no live errand to abort")

    # The parcel the queued errand expects disappears at the same moment.
    busy.env.parcels.pop(job["parcel_id"], None)
    scheduler._abandon(live, "aborted by the test")

    busy.step()
    robot = busy.fleet.get(robot_id)
    assert robot.current_task != task_id, (
        "the queued errand was executed without revalidation")


def test_existing_single_parcel_behaviour_is_unchanged(busy):
    """
    Nothing here may quietly turn into batching: one parcel, one task, one
    robot, still.
    """
    for _ in range(600):
        busy.step()
        for robot in busy.fleet.all():
            assert robot.carrying is None or isinstance(robot.carrying, str)
            assert robot.load <= robot.load_capacity


# ------------------------------------------------------------ and measured
def test_the_assignment_log_records_every_stage(busy):
    scheduler = busy.experts["SCHEDULING"]
    run(busy, 400)

    commanded = [r for r in scheduler.assignments.all()
                 if r.command_tick is not None]
    assert commanded, "nothing was commanded in 400 ticks"

    for record in commanded:
        assert record.robot_id
        assert record.next_assignment_selected_tick is not None
        if record.queued_tick is not None:
            assert record.promoted_tick is not None
            assert record.promoted_tick >= record.queued_tick

    report = scheduler.assignments.report()
    assert report["average_idle_ticks"] is not None
    assert report["percent_with_queued_successor"] > 0


# --------------------------------------------------------- and it is faster
def test_the_fleet_stands_still_less_than_it_did(busy):
    """
    Measured before this change, over 900 ticks of the busy preset: idle 26%,
    of which 49% was a robot between errands waiting to be given the next one.
    """
    from collections import Counter

    states = Counter()
    for _ in range(600):
        busy.step()
        for robot in busy.fleet.all():
            states[robot.status.value] += 1

    total = sum(states.values())
    assert states["IDLE"] / total < 0.24, (
        f"idle is {states['IDLE'] / total:.0%}, no better than before")
