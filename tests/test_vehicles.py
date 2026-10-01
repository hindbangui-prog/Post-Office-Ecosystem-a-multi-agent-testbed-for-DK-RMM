"""
Outbound vans, cut-off times, and the first thing in this model that can go
wrong for a parcel.

Until now a dispatched parcel simply ceased to exist: the departure gate deleted
it from the building and that was departure. A real sortation hub is organised
the other way round -- every sort decision exists to get a parcel onto a
particular truck before that truck's cut-off, and the cut-offs are what the
whole shift is arranged around. Without them nothing in the simulation could
ever be *late*, so URGENT changed the order of a queue and nothing else.

So there are vans now. One per route stands at the bay, it leaves on a
schedule, and the gate loads parcels onto it. A parcel's promise is derived
from that schedule rather than invented: the service its customer paid for buys
it a place on the next departure, or the second, or the fourth. Missing that
departure is a fact about the run, counted and attributable.
"""

from __future__ import annotations

import pytest

from post_office.environment import ParcelStatus, Zone
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=3, run_id="vans")
    made.start()
    yield made
    made.close()


def run(eco, ticks):
    for _ in range(ticks):
        eco.step()
    return eco


# ------------------------------------------------------------ the departures
def test_a_van_stands_at_the_bay_for_every_route():
    from post_office.environment.vehicles import DepartureBoard

    board = DepartureBoard(routes=("BRNO", "PLZEN"), interval=100, capacity=6)
    board.open(tick=0)
    for route in ("BRNO", "PLZEN"):
        van = board.at_bay(route)
        assert van is not None and van.route == route
        # Each route leaves on its own slot inside the interval rather than on
        # the interval itself: the six routes are staggered so that something
        # leaves the yard regularly, instead of everything leaving at once.
        assert 0 < van.departs_at <= 100, (
            f"{route} leaves at {van.departs_at}, outside the first interval")
        assert van.free == 6
    assert (board.at_bay("BRNO").departs_at
            != board.at_bay("PLZEN").departs_at), "the routes share a slot"


def test_a_van_leaves_on_time_and_the_next_one_takes_its_place():
    from post_office.environment.vehicles import DepartureBoard

    board = DepartureBoard(routes=("BRNO",), interval=100, capacity=6)
    board.open(tick=0)
    first = board.at_bay("BRNO")

    assert board.advance(50) == [], "nothing leaves before its time"
    departed = board.advance(100)

    assert departed == [first]
    assert first.departed_at == 100
    second = board.at_bay("BRNO")
    assert second is not None and second is not first
    assert second.departs_at == 200


def test_a_full_van_takes_no_more():
    from post_office.environment.vehicles import DepartureBoard

    board = DepartureBoard(routes=("BRNO",), interval=100, capacity=3)
    board.open(tick=0)
    van = board.at_bay("BRNO")

    assert van.load("P-0001", units=2) is True
    assert van.free == 1
    assert van.load("P-0002", units=2) is False, "it does not fit"
    assert van.load("P-0003", units=1) is True
    assert van.free == 0 and van.loaded == ["P-0001", "P-0003"]


def test_the_board_can_say_when_the_nth_departure_for_a_route_is():
    """What a promise is made of: a place on a departure, not a duration."""
    from post_office.environment.vehicles import DepartureBoard

    board = DepartureBoard(routes=("BRNO",), interval=100, capacity=6)
    board.open(tick=0)
    assert board.nth_departure_after("BRNO", tick=0, nth=1) == 100
    assert board.nth_departure_after("BRNO", tick=0, nth=2) == 200
    # Just after a departure the next one is a whole interval away, which is
    # exactly the trouble a parcel that missed its van is in.
    assert board.nth_departure_after("BRNO", tick=101, nth=1) == 200


# --------------------------------------------------------------- the promise
def test_a_parcel_is_promised_a_departure_when_the_facility_accepts_it(eco):
    """
    Derived, not invented. The service the customer paid for buys a place on
    the next departure for their route, or the second, or the fourth -- so the
    promise stays coherent whatever the van interval is set to.
    """
    run(eco, 60)
    promised = [p for p in eco.env.all_parcels().values()
                if p.due_by is not None]
    assert promised, "a 60-tick run accepts something"
    for parcel in promised:
        assert parcel.due_by > (parcel.timestamps.get("received") or 0)
        assert parcel.due_by in eco.env.departures.departures_for(parcel.route_label
                                                                 or "BRNO", 12) \
            or parcel.route_label == ""


def test_the_more_a_customer_paid_the_sooner_the_promise(eco):
    from post_office.environment.vehicles import PROMISED_DEPARTURE

    assert PROMISED_DEPARTURE["URGENT"] < PROMISED_DEPARTURE["EXPRESS"]
    assert PROMISED_DEPARTURE["EXPRESS"] < PROMISED_DEPARTURE["NORMAL"]


# ------------------------------------------------------------- the departure
def test_nothing_leaves_the_building_except_on_a_van(eco):
    """
    The change that makes a cut-off mean anything. The gate used to delete a
    parcel; now it loads one, and the van leaving is what takes it away.
    """
    run(eco, 900)
    assert eco.env.dispatched_count > 0, "a 900-tick run gets something out"
    for parcel in eco.env.departed.values():
        if parcel.status is ParcelStatus.DISPATCHED:
            assert parcel.loaded_on, f"{parcel.parcel_id} left with no van"


def test_a_parcel_that_misses_its_promise_is_counted_late(eco):
    run(eco, 900)
    summary = eco.summary()
    assert "parcels_late" in summary
    late = [p for p in eco.env.all_parcels().values() if p.is_late]
    assert summary["parcels_late"] == len(late)
    for parcel in late:
        assert parcel.due_by is not None


def test_a_parcel_loaded_before_the_cut_off_is_not_late(eco):
    run(eco, 900)
    out = [p for p in eco.env.departed.values()
           if p.status is ParcelStatus.DISPATCHED and p.due_by is not None]
    assert out
    for parcel in out:
        left = parcel.timestamps.get("dispatched")
        assert (left > parcel.due_by) == parcel.is_late, parcel.parcel_id


def test_the_gate_reports_what_it_loaded_and_what_it_could_not(eco):
    run(eco, 900)
    gate = eco.experts["DISPATCH"]
    assert gate.loaded > 0
    assert gate.loaded == sum(len(v.loaded) for v in eco.env.departures.all_vans())
    # Holding is now a fact about a van rather than a timer.
    assert isinstance(gate.held, int)


def test_the_clock_says_what_a_tick_is():
    """
    A model whose time has no unit cannot be checked against anything. One line
    of arithmetic is the difference between "a median dwell of 400" and "a
    median dwell of about seven minutes", and only the second can be wrong.
    """
    from post_office.config import settings

    assert settings.SECONDS_PER_TICK == 1.0
    assert settings.ticks_to_seconds(120) == 120.0
    assert "second" in settings.__doc__.lower()


def test_the_promise_is_met_when_the_facility_copes_and_broken_when_it_does_not():
    """
    A deadline nothing can ever miss is decoration, and one everything misses
    is noise. This pins the shape: the baseline keeps every promise it makes,
    and a facility whose fleet cannot keep up starts breaking them.

    The stress is a starved fleet rather than a flooded dock, and the reason is
    worth recording. Flooding the dock does *not* break promises -- the intake
    gate refuses parcels it has no room to work, so the facility sheds load and
    keeps every promise it made about what it did accept, which is what a real
    hub does when it stops taking intake to protect its service levels. Take
    the robots away instead and there is nothing to shed with: the work is
    already accepted, the promises are already made, and they break.
    """
    from post_office.config.settings import config
    from tests.presets import busy_config

    healthy = build(seed=1, run_id="healthy", config=config("default"))
    healthy.start()
    for _ in range(6000):
        healthy.step()
    assert healthy.summary()["parcels_dispatched"] > 50
    assert healthy.summary()["parcels_late"] == 0, \
        "a facility inside its capacity keeps its promises"
    healthy.close()

    flooded = build(seed=1, run_id="flooded",
                    config=busy_config(arrival_interval=10.0,
                                       initial_parcels=18))
    flooded.start()
    for _ in range(6000):
        flooded.step()
    assert flooded.summary()["parcels_refused"] > 0, \
        "a flooded dock is refused rather than silently absorbed"
    flooded.close()

    # One robot, not two. Two used to be enough to break promises because the
    # fleet lost most of its day to charging -- every robot shuttling to a plug
    # every forty ticks at half battery. Now that a charge is something a robot
    # does when it is actually low, and mostly while parked, two robots keep up
    # with a busy day: the starvation has to be real to bite.
    starved = build(seed=1, run_id="starved",
                    config=busy_config(robot_homes={"R1": (13, 13)}))
    starved.start()
    for _ in range(6000):
        starved.step()
    missed = [p for p in starved.env.all_parcels().values()
              if p.late_at(starved.world.tick)]
    assert missed, "a fleet that cannot keep up misses departures"
    assert starved.summary()["parcels_late"] == len(missed)
    starved.close()


def test_a_promise_allows_for_the_handling_it_takes_to_keep_it():
    """
    A cut-off in this trade is an induction deadline, not the moment the doors
    shut. Promising a parcel handed over one tick before a van leaves that it
    will be on that van would measure the promise rather than the facility --
    every such parcel would be late however well the place ran.
    """
    from post_office.environment.vehicles import HANDLING_ALLOWANCE, DepartureBoard

    board = DepartureBoard(routes=("BRNO",), interval=600, capacity=20)
    board.open(tick=0)
    # Accepted one tick before a departure: promised the one after it, not the
    # one it could never have been got onto.
    promised = board.promise_for("URGENT", tick=599, route="BRNO")
    assert promised > 600
    assert promised - 599 > HANDLING_ALLOWANCE - board.interval
