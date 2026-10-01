"""
What happens to a robot that runs flat in the middle of the floor.

Something has to happen. A robot at zero cannot move, so nothing in the agent
hierarchy can help it; it sits where it stopped, in whatever doorway it
stopped in, for the rest of the run. The facility has to come and get it.

The question is who does the getting. Until now the resource agent did it
itself, in four lines that set the robot's position to a charge point and its
battery to full. That is the agent reaching past every boundary it has:
moving a robot is the simulator's job, and a battery that goes from empty to
full because an agent assigned to it is not a battery.

So the agent now does what an agent can do -- it notices, and it asks. The
request is structured, it is logged, and it may be refused. The simulation
engine decides whether recovery is possible, and when it happens the robot is
moved by the engine and charges from the level it actually had, at the rate
every other robot charges at.

These tests pin the boundary, not the mechanism: the mechanism may well
change, but an agent must never again be the thing that moves a robot.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from post_office.environment.zones import Zone
from post_office.robots.robot import RobotState
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=13, run_id="recovery")
    made.start()
    yield made
    made.close()


def strand(eco, robot=None):
    """
    Flatten a robot out on the floor. The simulator owns this, not an agent.

    Away from the charge points, and only once the fleet has left them: a
    robot parked on a plug that is set to zero simply charges again next tick,
    which is a robot having a quiet morning rather than a robot stranded.
    """
    run(eco, 40)
    if robot is None:
        robot = eco.fleet.all()[0]
    eco.env.release_station(robot.robot_id)
    # Off the plug as well as off the register. The fleet parks on the charge
    # points, and a robot standing on one tops itself up whether or not it has
    # claimed it -- so a robot flattened where it parked is charging again by
    # the next tick.
    out_on_the_floor = eco.env.free_cell_in(Zone.SORTING)
    eco.env.place_robot(robot.robot_id, out_on_the_floor)
    robot.current_position = out_on_the_floor
    robot.current_zone = Zone.SORTING
    robot.battery_level = 0.0
    return robot


def run(eco, ticks):
    for _ in range(ticks):
        eco.step()
    return eco


# ------------------------------------------------------------- the boundary
def test_the_resource_agent_never_writes_to_a_robots_position_or_battery():
    """
    Read as source, because the point is that the code cannot do it, not that
    it happened not to today. Any assignment to a robot's physical state
    inside this agent is the violation.
    """
    from post_office.agents import resource_agent

    tree = ast.parse(inspect.getsource(resource_agent))
    forbidden = {"current_position", "battery_level", "current_zone", "status"}
    offences = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr in forbidden:
                base = target.value
                name = getattr(base, "id", "") or getattr(base, "attr", "")
                if "robot" in str(name).lower():
                    offences.append(f"line {node.lineno}: {name}.{target.attr}")

    assert not offences, "RESOURCE writes physical state: " + "; ".join(offences)


def test_the_resource_agent_does_not_place_robots_on_the_floor():
    from post_office.agents import resource_agent

    source = inspect.getsource(resource_agent)
    assert "place_robot" not in source, "RESOURCE moves a robot directly"


# -------------------------------------------------------------- the request
def test_a_stranded_robot_produces_a_structured_recovery_request(eco):
    robot = strand(eco)
    run(eco, eco.experts["RESOURCE"].RECOVERY_AFTER + 3)

    pending = eco.env.recovery_requests
    mine = [r for r in pending if r.robot_id == robot.robot_id]
    assert mine, "the agent noticed nothing"
    request = mine[0]
    assert request.action == "REQUEST_RECOVERY"
    assert request.robot_id == robot.robot_id
    assert request.requested_by == "RESOURCE"
    assert request.reason, "a request with no rationale"


def test_the_request_alone_changes_nothing_physical(eco):
    """
    Asking is not doing. Between the request and the engine acting on it the
    robot is exactly where it was, with exactly the charge it had.
    """
    robot = strand(eco)
    where = robot.current_position
    run(eco, eco.experts["RESOURCE"].RECOVERY_AFTER + 1)

    assert robot.battery_level == 0.0, "somebody refilled it"
    assert robot.current_position == where, "somebody moved it"


# --------------------------------------------------------------- the engine
def test_the_engine_recovers_the_robot_and_it_charges_normally(eco):
    """
    The engine moves it, and then the ordinary charging rules apply. What it
    must not do is arrive full: a recovered robot charges from where it was,
    at the rate every other robot charges at.
    """
    robot = strand(eco)
    run(eco, eco.experts["RESOURCE"].RECOVERY_AFTER + eco.recovery.DELAY + 2)

    station = eco.env.station_of(robot.robot_id)
    assert station is not None, "it was never recovered"
    assert robot.status is RobotState.CHARGING
    assert robot.battery_level < 100.0, "it arrived with a full battery"


def test_recovery_waits_for_a_free_point_rather_than_inventing_one(eco):
    """Capacity is physical. The engine may not create a charge point."""
    robot = strand(eco)
    # A floor with every point busy, held that way for the whole window. Set
    # on the environment rather than by occupying the points one by one: real
    # robots arrive and leave mid-tick, so points filled between ticks come
    # free again inside the next one.
    eco.env.free_stations = lambda: []

    run(eco, eco.experts["RESOURCE"].RECOVERY_AFTER + eco.recovery.DELAY + 5)

    assert eco.env.station_of(robot.robot_id) is None
    assert robot.battery_level == 0.0, "recovered with nowhere to put it"
    assert [r for r in eco.env.recovery_requests
            if r.robot_id == robot.robot_id], "the request was dropped"


def test_a_robot_that_is_no_longer_stranded_has_its_request_withdrawn(eco):
    """
    Conditions change between asking and acting. A robot that was charged by
    some other means before the crew arrived is not recovered again.
    """
    robot = strand(eco)
    run(eco, eco.experts["RESOURCE"].RECOVERY_AFTER + 2)
    assert any(r.robot_id == robot.robot_id for r in eco.env.recovery_requests)

    robot.battery_level = 55.0                  # the simulator, not an agent
    run(eco, eco.recovery.DELAY + 2)

    assert not [r for r in eco.env.recovery_requests
                if r.robot_id == robot.robot_id]


def test_every_recovery_is_logged_with_who_asked_and_what_happened(eco):
    robot = strand(eco)
    run(eco, eco.experts["RESOURCE"].RECOVERY_AFTER + eco.recovery.DELAY + 3)

    topics = [e.topic for e in eco.logger.recent(limit=400)]
    assert "recovery_requested" in topics
    assert "recovery_completed" in topics
