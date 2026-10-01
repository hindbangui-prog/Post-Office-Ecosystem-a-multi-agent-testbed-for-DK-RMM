"""
Urgent parcels: intake -> sorting hall -> dispatch door, in one trip.

The sorting stop for an urgent parcel has one answer, fixed by rule: URGENT
goes to DISPATCH. Put down in the hall and collected again, it waited there a
median of 33 ticks for its second errand to be arranged. With
`urgent_via_sorting` (set by the app) the robot that collects it at intake
carries it through a sorting-hall cell and on to the door without stopping.
Express and standard parcels keep their route; experiments keep theirs.
"""

from __future__ import annotations

import pytest

from post_office.config.settings import config, normal_config
from post_office.environment.grid import Position
from post_office.environment.zones import Zone
from post_office.robots.robot import Robot, RobotState
from post_office.simulation import build


def run(cfg, ticks=1500, seed=1):
    eco = build(seed=seed, config=cfg)
    eco.start()
    transports = {}

    def count(event):
        if event.topic == "task_created" and event.detail.get("destination"):
            pid = event.detail.get("parcel_id")
            transports[pid] = transports.get(pid, 0) + 1

    eco.logger.subscribe(count)
    for _ in range(ticks):
        eco.step()
        busy = [t.assigned_robot for t in eco.tasks.open_tasks()
                if t.status.value == "IN_PROGRESS" and t.task_type.value == "TRANSPORT"]
        assert len(busy) == len(set(busy)), "a robot is on two errands"
    return eco, transports


def statuses(parcel):
    return [h.get("previous") for h in parcel.processing_history
            if h["action"] == "status_change"] + [parcel.status.value]


def test_an_urgent_parcel_goes_through_sorting_to_the_door_in_one_trip():
    eco, transports = run(normal_config())
    try:
        urgent = [p for p in eco.env.all_parcels().values()
                  if p.priority.value == "URGENT"
                  and p.status.value in ("AWAITING_DISPATCH", "DISPATCHED")]
        assert urgent, "no urgent parcel reached the door in this run"
        for parcel in urgent:
            assert transports.get(parcel.parcel_id) == 1, \
                f"{parcel.parcel_id} took {transports.get(parcel.parcel_id)} trips"
            passed = [h for h in parcel.processing_history if h["action"] == "passed_through"]
            assert passed and passed[0]["zone"] == Zone.SORTING.value, \
                f"{parcel.parcel_id} never went through the sorting hall"
            assert "SORTED" not in statuses(parcel), "it was put down in the hall"
            assert parcel.route_via is None
        assert eco.summary()["parcels_late"] == 0
    finally:
        eco.close()


def test_express_and_standard_parcels_keep_their_route():
    eco, transports = run(normal_config())
    try:
        others = [p for p in eco.env.all_parcels().values()
                  if p.priority.value in ("EXPRESS", "NORMAL")
                  and p.status.value in ("AWAITING_DISPATCH", "DISPATCHED")]
        assert others
        for parcel in others:
            assert "SORTED" in statuses(parcel), f"{parcel.parcel_id} skipped the hall stop"
            assert transports.get(parcel.parcel_id, 0) >= 2
    finally:
        eco.close()


def test_outside_the_app_urgent_parcels_keep_the_recorded_two_trip_route():
    eco, transports = run(config("default"), ticks=900)
    try:
        assert eco.urgent_via_sorting is False
        urgent = [p for p in eco.env.all_parcels().values()
                  if p.priority.value == "URGENT"
                  and p.status.value in ("AWAITING_DISPATCH", "DISPATCHED")]
        assert urgent
        assert all("SORTED" in statuses(p) for p in urgent)
    finally:
        eco.close()


def test_the_robot_aims_at_the_waypoint_until_it_has_passed_it():
    """
    While the waypoint is still ahead, it is the robot's destination: a
    replan, a detour or a yield all aim at it, so none of them can cut the
    corner and skip the hall. Once passed, the robot walks on to the drop
    without putting the parcel down.
    """
    eco = build(seed=1, config=config("default"))
    try:
        env = eco.env
        robot = eco.fleet.get("R1")
        parcel_cell = env.free_cell_in(Zone.INTAKE)
        via = env.free_cell_in(Zone.SORTING, near=parcel_cell)
        drop = env.free_cell_in(Zone.DISPATCH, near=via)
        from post_office.environment.parcels import Parcel
        parcel = Parcel(parcel_id="P-TEST")
        env.add_parcel(parcel, at=parcel_cell)
        robot.assign_transport(
            0, "T-TEST", "P-TEST", parcel_cell, drop,
            route_to_pickup=env.path(robot.current_position, parcel_cell),
            route_to_dropoff=env.path(parcel_cell, via),
            via=via, route_after_via=env.path(via, drop))
        seen, passed_at, tick = [], None, 0
        while tick < 400 and robot.carrying is None:
            tick += 1
            robot.step(env, tick)
        assert robot.carrying == "P-TEST"
        assert robot.destination == via, "the drop, not the waypoint, is being aimed at"
        full = len(env.path(parcel_cell, via)) - 1 + len(env.path(via, drop)) - 1
        assert robot.route_remaining == full
        while tick < 800 and robot.carrying is not None:
            tick += 1
            for report in robot.step(env, tick):
                seen.append(report.get("report") or report.get("event"))
                if (report.get("report") or report.get("event")) == "passed_via":
                    passed_at = robot.current_position
                    assert robot.carrying == "P-TEST", "it put the parcel down"
                    assert robot.destination == drop
        assert passed_at == via
        assert "delivered" in seen
        assert env.zone_at(robot.current_position) is Zone.DISPATCH
        assert robot.status is RobotState.IDLE
    finally:
        eco.close()
