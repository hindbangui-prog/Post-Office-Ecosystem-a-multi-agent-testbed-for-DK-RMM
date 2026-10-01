"""
Phase 2: the robots.

A robot is tested here against a bare environment with no agents at all, which
is the clearest evidence that it does not secretly depend on one.
"""

from __future__ import annotations

from post_office.environment import (Grid, Parcel, ParcelSize, Position, Rect,
                                     Zone, ZoneMap, build_environment)
from post_office.environment.facility import PostOfficeEnvironment
from post_office.robots import Robot, RobotState, build_fleet


def open_environment(width=10, height=6):
    """A featureless room, so a test is about the robot and not about walls."""
    zones = ZoneMap({Zone.INTAKE: Rect(0, 0, 1, height - 1),
                     Zone.SORTING: Rect(4, 0, 5, height - 1),
                     Zone.DISPATCH: Rect(width - 2, 0, width - 1, height - 1),
                     Zone.TEMPORARY_STORAGE: Rect(2, 0, 3, 1),
                     Zone.CHARGING: Rect(2, height - 2, 3, height - 1)})
    return PostOfficeEnvironment(Grid(width, height), zones)


def transport(env, robot, parcel_id, pickup, dropoff, tick=0, zone=None):
    robot.assign_transport(
        tick, task_id="T-0001", parcel_id=parcel_id,
        pickup=pickup, dropoff=dropoff,
        route_to_pickup=env.path(robot.current_position, pickup),
        route_to_dropoff=env.path(pickup, dropoff),
        destination_zone=zone,
    )


def run(env, robot, ticks, start=1):
    out = []
    for t in range(start, start + ticks):
        out.extend(robot.step(env, t))
    return out


# ------------------------------------------------------------------ the fleet
def test_the_default_fleet_is_five_robots_on_free_cells():
    env = build_environment()
    fleet = build_fleet(env)
    assert len(fleet) == 5
    assert fleet.ids() == ["R1", "R2", "R3", "R4", "R5"]
    for robot in fleet.all():
        assert env.is_free(robot.current_position)
        assert robot.status is RobotState.IDLE


def test_every_state_in_the_spec_exists():
    names = {s.value for s in RobotState}
    assert {"IDLE", "MOVING", "PICKING", "DELIVERING", "CHARGING",
            "WAITING", "BLOCKED"} <= names


# ------------------------------------------------------------- a whole errand
def test_a_robot_fetches_a_parcel_and_delivers_it():
    env = open_environment()
    robot = Robot("R1", Position(0, 0))
    env.place_robot("R1", robot.current_position)
    pickup, dropoff = Position(3, 0), Position(9, 5)
    env.add_parcel(Parcel(parcel_id="P-0001"), at=pickup)

    transport(env, robot, "P-0001", pickup, dropoff, zone=Zone.DISPATCH)
    reports = run(env, robot, 40)

    kinds = [r["report"] for r in reports]
    assert "arrived_at_pickup" in kinds
    assert "picked" in kinds
    assert "delivered" in kinds
    assert robot.status is RobotState.IDLE
    assert robot.current_position == dropoff
    assert robot.carrying is None and robot.load == 0
    assert env.parcels["P-0001"].position == dropoff
    assert env.parcels["P-0001"].current_zone is Zone.DISPATCH


def test_carrying_a_parcel_costs_battery():
    env = open_environment()
    robot = Robot("R1", Position(0, 0))
    env.place_robot("R1", robot.current_position)
    env.add_parcel(Parcel(parcel_id="P-0001", size=ParcelSize.LARGE),
                   at=Position(3, 0))
    transport(env, robot, "P-0001", Position(3, 0), Position(9, 5))
    run(env, robot, 40)
    assert robot.battery_level < 100.0


def test_a_robot_reports_being_blocked_rather_than_walking_through_another():
    env = open_environment()
    a = Robot("R1", Position(0, 0))
    b = Robot("R2", Position(1, 0))
    env.place_robot("R1", a.current_position)
    env.place_robot("R2", b.current_position)
    env.add_parcel(Parcel(parcel_id="P-0001"), at=Position(5, 0))

    transport(env, a, "P-0001", Position(5, 0), Position(9, 0))
    reports = run(env, a, 1)

    assert any(r["report"] == "blocked" for r in reports)
    assert a.status is RobotState.BLOCKED
    assert a.current_position == Position(0, 0)          # it did not pass through


def test_a_reroute_unblocks_a_robot():
    env = open_environment()
    a = Robot("R1", Position(0, 0))
    env.place_robot("R1", a.current_position)
    env.place_robot("R2", Position(1, 0))
    env.add_parcel(Parcel(parcel_id="P-0001"), at=Position(5, 0))
    transport(env, a, "P-0001", Position(5, 0), Position(9, 0))
    run(env, a, 1)
    assert a.status is RobotState.BLOCKED

    detour = [Position(0, 0), Position(0, 1), Position(1, 1), Position(2, 1),
              Position(3, 1), Position(4, 1), Position(5, 1), Position(5, 0)]
    a.set_route(2, detour)
    run(env, a, 12, start=2)
    assert a.status is not RobotState.BLOCKED
    assert a.carrying == "P-0001" or env.parcels["P-0001"].position == Position(9, 0)


# --------------------------------------------------------------------- charge
def test_a_flat_robot_asks_for_a_charge_exactly_once():
    env = open_environment()
    robot = Robot("R1", Position(0, 0), battery_level=20.0)
    env.place_robot("R1", robot.current_position)
    reports = run(env, robot, 5)
    assert sum(1 for r in reports if r["report"] == "battery_low") == 1


def test_charging_fills_the_battery_and_frees_the_point():
    env = build_environment()
    station = env.free_stations()[0]
    robot = Robot("R1", Position.of(station.position), battery_level=20.0)
    env.place_robot("R1", robot.current_position)
    robot.assign_charge(1, "T-0001", station.position, [station.position])
    # Sixty ticks, not twenty. A charge point delivers 1.2% a tick now, so a
    # committed charge from the low line back to working order takes about
    # fifty -- long enough that the robot is genuinely out of service, which is
    # the whole point. It used to be 8% a tick: a full battery in fourteen
    # seconds, which cost less than the walk to the plug.
    run(env, robot, 60)
    assert robot.battery_level >= robot.resume_battery
    assert robot.status is RobotState.IDLE
    assert env.station_of("R1") is None                  # gave the point back


def test_a_robot_that_cannot_get_a_point_waits_rather_than_pretending():
    env = build_environment(station_cells=[(13, 10)])
    station = env.free_stations()[0]
    env.claim_station("R9")                              # somebody else has it
    robot = Robot("R1", Position.of(station.position), battery_level=10.0)
    env.place_robot("R1", robot.current_position)
    robot.assign_charge(1, "T-0001", station.position, [station.position])
    reports = run(env, robot, 2)
    assert any(r["report"] == "charging_unavailable" for r in reports)
    assert robot.status is RobotState.WAITING


# ---------------------------------------------------------------- scheduling
def test_the_nearest_free_robot_accounts_for_the_walls():
    env = build_environment()
    fleet = build_fleet(env)
    target = env.anchor(Zone.DISPATCH)
    nearest = fleet.nearest_available(env, target)
    by_path = min(fleet.available(),
                  key=lambda r: env.distance(r.current_position, target))
    assert nearest.robot_id == by_path.robot_id


def test_a_busy_robot_is_not_offered_more_work():
    env = open_environment()
    robot = Robot("R1", Position(0, 0))
    env.place_robot("R1", robot.current_position)
    env.add_parcel(Parcel(parcel_id="P-0001"), at=Position(5, 0))
    assert robot.is_available
    transport(env, robot, "P-0001", Position(5, 0), Position(9, 0))
    assert not robot.is_available


def test_a_robot_serialises_to_plain_json_types():
    import json
    env = build_environment()
    fleet = build_fleet(env)
    json.dumps(fleet.as_dict())
