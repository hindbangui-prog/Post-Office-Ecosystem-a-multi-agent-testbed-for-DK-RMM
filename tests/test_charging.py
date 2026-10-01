"""
What a robot's battery costs it, and when it goes to the plug.

The old arrangement looked plausible and was not. Measured over three thousand
ticks with five robots:

    68 charge trips              one robot leaving for a plug every 44 ticks
    51% mean battery when sent   sometimes 72%
    12 ticks walking to it
     6 ticks plugged in          51% -> 94%, a full charge in fourteen seconds
    182 cells of range           about two errands

Two separate faults. The trip cost twice what it bought, so every charge was a
net loss of robot time; and the thing sending robots away was not the low
battery line at all -- it was the clearance rule refusing any errand that would
leave a robot under a flat reserve, with the estimate inflated for congestion.
A robot at 73% was told to go and charge before a long job.

What real fleets do instead is top up opportunistically: a robot that is idle
anyway, next to a free point, takes some charge and drops it the moment work
appears. The fleet here is idle 45% of the time, so that converts dead time
into charge rather than spending live time walking. A dedicated trip is what
happens when a robot is genuinely low, and then it is worth the walk.

Two kinds of charging, and the difference between them is what these tests
pin:

    top-up      idle, available, unplugs the instant it is given work
    committed   low, out of service, charges until it can work a stretch again
"""

from __future__ import annotations

import pytest

from post_office.robots.robot import RobotState
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=1, run_id="charging")
    made.start()
    yield made
    made.close()


def run(eco, ticks):
    for _ in range(ticks):
        eco.step()
    return eco


def charge_trips(eco):
    """Every dedicated trip to a plug: when it was ordered, and at what level."""
    trips = []
    for robot in eco.fleet.all():
        for row in robot.task_history:
            if row.get("event") == "charge_assigned":
                trips.append({"robot": robot.robot_id, "tick": row.get("tick"),
                              "level": row.get("level")})
    return trips


# ------------------------------------------------------------------ the range
def test_a_robot_works_a_stretch_rather_than_two_errands(eco):
    """
    A full charge used to be a hundred and eighty cells: two crossings of the
    building and a robot was on its way to a plug. A real one works a shift.
    Scaled to this facility the same way the van timetable is -- what matters
    is that a robot does a useful run of work between charges, not that the
    number matches a datasheet.
    """
    from post_office.robots.robot import MOVE_COST

    cells = 100.0 / MOVE_COST
    errand = 45          # a cross-building pickup and drop, with congestion
    assert cells / errand >= 12, \
        f"a full charge is only {cells / errand:.0f} errands"


def test_being_plugged_in_costs_more_time_than_walking_to_the_plug(eco):
    """
    The arithmetic that made the old model absurd. Twelve ticks of walking for
    six ticks of charge is a trip that loses the facility robot-time however
    the battery looks afterwards, and no dispatcher would make it.
    """
    from post_office.environment.layout import CHARGE_RATE

    # A committed charge takes a robot from its low line back to working order.
    from post_office.robots.robot import COMMIT_BELOW, WORKING_ORDER

    ticks_plugged = (WORKING_ORDER - COMMIT_BELOW) / CHARGE_RATE
    assert ticks_plugged >= 25, \
        f"a committed charge is over in {ticks_plugged:.0f} ticks"


# --------------------------------------------------------------- the trigger
def test_nobody_is_sent_to_a_plug_while_it_still_has_a_shift_in_it(eco):
    """
    The defect the user saw: robots leaving for a charger in the first two
    hundred ticks, at half battery or better, because the clearance rule
    protected a flat reserve rather than the robot's ability to get to a plug.
    """
    run(eco, 3000)
    trips = charge_trips(eco)
    top_ups = sum(1 for robot in eco.fleet.all()
                  for row in robot.task_history
                  if row.get("event") == "top_up_started")

    # Charging has to be happening somehow, but a dedicated trip is no longer
    # the way it usually happens and demanding one would be demanding the
    # defect back. With a faster timetable the fleet is busier and takes its
    # charge opportunistically -- 35 top-ups and 2 arranged trips in this run
    # -- which is exactly what the opportunistic arrangement is for.
    assert trips or top_ups, "nothing charged at all in three thousand ticks"

    too_early = [t for t in trips if (t["level"] or 0) > 45]
    assert not too_early, \
        f"sent to charge with plenty left: {too_early[:4]}"


def test_a_long_errand_is_not_a_reason_to_go_and_charge(eco):
    """
    The rule itself. A robot with enough charge to finish the errand and still
    reach a plug afterwards takes the errand: the reserve protects the walk to
    the charger, not a comfort margin.
    """
    from post_office.agents.brain import Question

    resource = eco.experts["RESOURCE"]
    brain = resource.brain
    rule = getattr(brain, "fallback", brain)._rules["battery_sufficient"]

    def verdict(**facts):
        return rule(Question(kind="battery_sufficient", asked_by="RESOURCE",
                             prompt="?", options=("APPROVE", "CHARGE_FIRST",
                                                  "REFUSE"),
                             facts=facts)).choice

    # Plenty in hand for a long job.
    assert verdict(battery=73, estimated_cost=41, reserve=35) == "APPROVE"
    # It would finish, but with nothing left to reach a plug with.
    assert verdict(battery=20, estimated_cost=18, reserve=35) != "APPROVE"
    # It would not finish at all.
    assert verdict(battery=12, estimated_cost=30, reserve=35) == "REFUSE"


def test_the_fleet_does_not_spend_its_day_walking_to_plugs(eco):
    """
    The whole point, measured end to end rather than rule by rule.
    """
    run(eco, 3000)
    trips = charge_trips(eco)
    assert len(trips) <= 20, \
        f"{len(trips)} dedicated charge trips in 3000 ticks across 5 robots"


# ------------------------------------------------------------- the top-up
def test_an_idle_robot_beside_a_free_plug_tops_up(eco):
    """
    What makes this arrangement work: the fleet is idle for nearly half the
    run, and idle time next to a plug is free charge. A facility that lets a
    robot stand at 60% doing nothing, and then sends it across the building to
    charge an hour later, has wasted both.
    """
    run(eco, 1200)
    topped = [row for robot in eco.fleet.all() for row in robot.task_history
              if row.get("event") == "top_up_started"]
    assert topped, "no robot ever took a free top-up while idle"


def test_a_topping_up_robot_is_still_available_for_work(eco):
    """
    The difference between a top-up and a committed charge. A robot on a
    top-up has not left service: it is standing at a plug with nothing better
    to do, and the moment there is something better it goes.
    """
    run(eco, 600)
    robot = next(r for r in eco.fleet.all())
    robot.battery_level = 70.0
    robot.status = RobotState.CHARGING
    robot._topping_up = True
    robot.current_task = None
    robot.carrying = None
    assert robot.is_available, "a top-up is not a reason to refuse work"

    # And a committed charge is.
    robot._topping_up = False
    assert not robot.is_available


def test_work_unplugs_a_topping_up_robot(eco):
    """
    It goes when it is called, rather than finishing its charge first.
    """
    run(eco, 800)
    unplugged = [row for robot in eco.fleet.all() for row in robot.task_history
                 if row.get("event") == "top_up_ended"]
    assert unplugged, "no top-up was ever cut short by work"
    for row in unplugged:
        assert row.get("reason")


def test_a_top_up_stops_at_the_band_rather_than_filling_the_battery(eco):
    """
    Real fleets keep a pack in a band rather than charging it to full every
    time, and a robot that sits on a plug to the last percent is holding one of
    four points against four other robots for the least useful part of the
    charge.
    """
    from post_office.robots.robot import TOP_UP_CEILING

    assert 70 <= TOP_UP_CEILING <= 90
    run(eco, 1500)
    for robot in eco.fleet.all():
        for row in robot.task_history:
            if row.get("event") == "top_up_ended" and row.get("reason") == "full":
                assert row.get("level", 0) <= TOP_UP_CEILING + 5


def test_the_plugs_are_still_contested(eco):
    """
    Four points and five robots is the constraint the resource agent exists
    for. Opportunistic charging must not quietly remove it by making charging
    so cheap that nobody ever queues.
    """
    run(eco, 3000)
    resource = eco.experts["RESOURCE"]
    allocations = [d for d in resource.decisions
                   if d["kind"] == "allocate_charge_point"]
    assert allocations, "the resource agent never allocated a plug"
