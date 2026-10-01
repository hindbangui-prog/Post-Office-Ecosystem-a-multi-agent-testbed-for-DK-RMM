"""
How many errands the facility can have starting at once, and how fast a van
comes for what they carry.

Two bottlenecks, found by measuring a busy run rather than by reading the
code, and both of them invisible in the summary line.

*The scheduler started one errand at a time.* Asking its queue clerk "what
next" set a single flag, and while that question was outstanding nothing else
began -- not the route request, not the clearance, not the command to a robot.
The whole chain measured eight ticks, so the building started about one errand
every nine ticks however many robots were standing idle. The consequence, over
900 ticks of the busy preset: work was ready and at least one robot was idle
on 75% of ticks, idle spells ran a median of 14 ticks, and a task waited 109
ticks between being created and being given to anybody.

*Every van left at the same moment.* Six routes, one 600-tick cut-off, so the
timetable had a single beat. An urgent parcel was loaded four ticks after
reaching the door and then sat on a stationary van for another 473, while an
ordinary parcel was loaded late onto a van leaving in sixty. Being urgent made
a parcel later, which is the exact opposite of what the class is sold as.

These tests pin the two properties that fix implies: the scheduler can hold
more than one assignment in flight, and an urgent parcel gets out of the
building faster than an ordinary one.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import pytest

from tests.presets import busy_config
from post_office.environment.vehicles import (DEFAULT_INTERVAL,
                                              HANDLING_ALLOWANCE,
                                              DepartureBoard)
from post_office.simulation import build


def run(eco, ticks):
    for _ in range(ticks):
        eco.step()
    return eco


@pytest.fixture
def busy():
    made = build(seed=1, run_id="throughput", config=busy_config())
    made.start()
    yield made
    made.close()


# ------------------------------------------------------- the van timetable
def test_the_routes_do_not_all_leave_on_the_same_tick():
    """
    The defect this started from. One beat for the whole building means the
    only thing that decides when a parcel leaves is which side of the beat it
    arrived on -- and the dispatch agent's judgement about who goes first
    cannot matter, because everything goes at once.
    """
    board = DepartureBoard(["A", "B", "C", "D", "E", "F"])
    board.open(0)
    times = {route: board.at_bay(route).departs_at for route in board.routes}

    assert len(set(times.values())) == len(board.routes), (
        f"routes share departures: {times}")


def test_the_departures_are_spread_evenly_across_the_interval():
    board = DepartureBoard(["A", "B", "C", "D", "E", "F"])
    board.open(0)
    times = sorted(v.departs_at for v in
                   (board.at_bay(r) for r in board.routes))
    gaps = [b - a for a, b in zip(times, times[1:])]

    # Within a tick of even: six routes do not divide a 250-tick interval, so
    # the slots land 41 and 42 apart rather than all the same.
    nominal = DEFAULT_INTERVAL / len(board.routes)
    assert all(abs(gap - nominal) <= 1 for gap in gaps), f"uneven: {times}"


def test_a_route_keeps_its_own_offset_on_the_next_van():
    """A timetable, not a one-off shuffle: the same route keeps its slot."""
    board = DepartureBoard(["A", "B", "C"])
    board.open(0)
    first = board.at_bay("B").departs_at
    board.advance(first)                    # its van goes; the next one comes up
    second = board.at_bay("B").departs_at

    assert second - first == DEFAULT_INTERVAL
    assert first % DEFAULT_INTERVAL == second % DEFAULT_INTERVAL


def test_the_handling_allowance_fits_inside_the_interval():
    """
    The allowance is how long before a departure the facility stops promising
    it. Larger than the interval and no parcel can ever be promised the next
    van, which quietly turns every promise into a later one.
    """
    assert HANDLING_ALLOWANCE < DEFAULT_INTERVAL


# ------------------------------------------------- urgent is actually fast
def door_to_gone(eco):
    """Per class: ticks from reaching the dispatch door to leaving the site."""
    out = defaultdict(list)
    parcels = list(eco.env.departed.values()) + list(eco.env.parcels.values())
    for parcel in parcels:
        stamps = parcel.timestamps
        if "awaiting_dispatch" in stamps and "dispatched" in stamps:
            out[parcel.priority.value].append(
                stamps["dispatched"] - stamps["awaiting_dispatch"])
    return out


def test_an_urgent_parcel_leaves_sooner_than_an_ordinary_one(busy):
    """
    The inversion, pinned. Urgent measured 477 ticks from door to gone against
    NORMAL's 71 -- loaded in four ticks onto a van that would not move for
    another 473.

    Measured on the whole journey, dock to departure, rather than on the wait
    at the door alone. The door wait is the time to the route's next van, so
    a parcel that reaches the door *earlier* waits *longer* there -- the
    door-wait medians inverted on three of five busy seeds with the old
    scheduler too, and passed on this seed by the timetable. The property
    that priority handling actually moves is how long the parcel is in the
    building; the loading fault the test was written for is guarded by the
    one-timetable-cycle bound below.
    """
    run(busy, 900)
    dwell = defaultdict(list)
    for parcel in busy.env.departed.values():
        if parcel.dwell is not None:
            dwell[parcel.priority.value].append(parcel.dwell)
    for mail_class in ("URGENT", "NORMAL"):
        if not dwell.get(mail_class):
            pytest.skip(f"no {mail_class} parcel got out in this run")

    urgent = sorted(dwell["URGENT"])[len(dwell["URGENT"]) // 2]
    normal = sorted(dwell["NORMAL"])[len(dwell["NORMAL"]) // 2]

    assert urgent <= normal, (
        f"urgent is in the building {urgent} ticks, normal {normal}")


def test_nothing_waits_at_the_door_for_more_than_one_timetable_cycle(busy):
    """
    Whatever else happens, a parcel at the door has missed at most one van.
    A wait longer than the interval means it was passed over, not unlucky.
    """
    run(busy, 900)
    waits = door_to_gone(busy)
    for mail_class in ("URGENT", "EXPRESS"):
        for waited in waits.get(mail_class, []):
            assert waited <= DEFAULT_INTERVAL + HANDLING_ALLOWANCE, (
                f"a {mail_class} parcel waited {waited} at the door")


# ------------------------------------------------- the scheduler's throughput
def test_the_scheduler_can_have_several_assignments_in_flight(busy):
    """
    The bottleneck itself. With five robots and a queue that never emptied,
    the old scheduler never had more than one assignment conversation open at
    a time.
    """
    scheduler = busy.experts["SCHEDULING"]
    most = 0
    for _ in range(400):
        busy.step()
        most = max(most, len(scheduler.assigning()))

    assert most > 1, "the scheduler still starts one errand at a time"


def test_the_fleet_spends_more_of_its_time_moving_than_standing_still(busy):
    """
    What somebody watching the floor actually sees.

    Measured over 900 ticks of the busy preset, before and after: idle fell
    from 33% to 26% and moving rose from 23% to 28%, so the largest single
    thing the fleet does is now travelling rather than waiting. Asserted as an
    ordering rather than a threshold because the exact split moves with the
    seed and the arrival rate; the ordering is the property.

    Not asserted here, because it is not yet true: work is still ready with
    some robot idle on roughly three quarters of ticks. About a third of what
    idle time remains is a robot that has been given an errand and is waiting
    for its route, which is the next thing to overlap.
    """
    states = Counter()
    for _ in range(600):
        busy.step()
        for robot in busy.fleet.all():
            states[robot.status.value] += 1

    moving = states["MOVING"] + states["DELIVERING"]
    assert moving > states["IDLE"], (
        f"moving {moving}, idle {states['IDLE']}: the fleet is still mostly "
        f"standing still")


def test_two_robots_are_never_sent_to_the_same_parcel(busy):
    """
    The hazard the change introduces. Several queue questions in flight can
    each come back naming the same task, and two robots dispatched to one
    parcel is a worse failure than a slow queue.
    """
    scheduler = busy.experts["SCHEDULING"]
    run(busy, 600)

    parcels = [job.get("parcel_id") for job in scheduler._dispatch.values()
               if job.get("parcel_id")]
    assert len(parcels) == len(set(parcels)), f"duplicated errand: {parcels}"
