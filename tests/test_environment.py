"""
Phase 1: the floor plan, the parcels and the tasks.

These tests are about the properties the rest of the system leans on -- paths
are reproducible, capacity actually runs out, an illegal task transition raises
-- rather than about particular coordinates, so redrawing the building does not
break them.
"""

from __future__ import annotations

import pytest

from post_office.core.ids import IdFactory
from post_office.core.rng import SeededRNG
from post_office.environment import (Grid, Parcel, ParcelPriority, ParcelSize,
                                     ParcelStatus, Position, Rect, Zone,
                                     ZoneMap, build_environment)
from post_office.tasks import (IllegalTransition, TaskRegistry, TaskStatus,
                               TaskType)


# --------------------------------------------------------------------- grid
def test_a_path_avoids_walls_and_is_contiguous():
    grid = Grid(8, 5, obstacles=[Position(3, y) for y in range(0, 4)])
    path = grid.path(Position(0, 0), Position(7, 0))
    assert path is not None
    assert path[0] == Position(0, 0) and path[-1] == Position(7, 0)
    assert all(p not in grid.obstacles for p in path)
    assert all(a.manhattan(b) == 1 for a, b in zip(path, path[1:]))


def test_a_walled_in_goal_has_no_path():
    grid = Grid(5, 5, obstacles=[Position(3, 2), Position(4, 1), Position(4, 3)])
    # (4,2) is boxed in by three walls and the right-hand edge
    assert grid.path(Position(0, 0), Position(4, 2)) is None


def test_the_same_pair_of_cells_always_gives_the_same_path():
    # Reproducibility starts here: a route that wobbles between runs would make
    # every downstream statistic irreproducible.
    a = Grid(12, 9, obstacles=[Position(5, y) for y in range(0, 7)])
    b = Grid(12, 9, obstacles=[Position(5, y) for y in range(0, 7)])
    assert a.path((0, 0), (11, 8)) == b.path((0, 0), (11, 8))


def test_distance_agrees_with_path_length():
    grid = Grid(10, 10)
    assert grid.distance((0, 0), (3, 4)) == 7
    assert len(grid.path((0, 0), (3, 4))) == 8


# --------------------------------------------------------------------- zones
def test_every_cell_of_a_rectangle_reports_its_zone():
    zones = ZoneMap({Zone.INTAKE: Rect(0, 0, 2, 2),
                     Zone.DISPATCH: Rect(5, 5, 6, 6)})
    assert zones.zone_at((1, 1)) is Zone.INTAKE
    assert zones.zone_at((6, 5)) is Zone.DISPATCH
    assert zones.zone_at((4, 4)) is None
    assert len(zones.cells_of(Zone.INTAKE)) == 9


# ------------------------------------------------------------------ facility
def test_the_default_building_connects_every_zone_to_intake():
    env = build_environment()
    intake = env.anchor(Zone.INTAKE)
    for zone in (Zone.SORTING, Zone.TEMPORARY_STORAGE, Zone.DISPATCH,
                 Zone.CHARGING):
        assert env.path(intake, env.anchor(zone)) is not None, zone


def test_the_walls_force_journeys_through_the_doorways():
    # If this ever fails the building has been opened up, and the routing and
    # collision sub-agents have nothing left to do.
    env = build_environment()
    path = env.path(env.anchor(Zone.INTAKE), env.anchor(Zone.DISPATCH))
    crossings = [p for p in path if p.x == 5]
    assert crossings and all(p.y in (6, 7) for p in crossings)


def test_storage_refuses_once_the_shelves_are_full():
    env = build_environment(storage_capacity=2)
    assert env.claim_storage("P-1") is True
    assert env.claim_storage("P-2") is True
    assert env.claim_storage("P-3") is False
    assert env.storage.refusals == 1
    env.release_storage("P-1")
    assert env.claim_storage("P-3") is True


def test_a_charge_point_serves_one_robot_at_a_time():
    env = build_environment(station_cells=[(13, 10)])
    first = env.claim_station("R1")
    assert first is not None
    assert env.claim_station("R2") is None          # refused, not queued
    env.release_station("R1")
    assert env.claim_station("R2") is not None


def test_a_refusal_is_announced_not_swallowed():
    seen = []
    env = build_environment(storage_capacity=1)
    env.set_event_sink(lambda **kw: seen.append(kw["topic"]))
    env.claim_storage("P-1")
    env.claim_storage("P-2")
    assert "storage_refused" in seen


def test_lifting_a_parcel_takes_it_off_the_floor():
    env = build_environment()
    parcel = env.add_parcel(Parcel(parcel_id="P-0001"))
    assert parcel.position is not None
    assert env.lift_parcel("P-0001", "R1") is True
    assert parcel.position is None and parcel.assigned_robot == "R1"
    env.drop_parcel("P-0001", env.anchor(Zone.SORTING))
    assert parcel.current_zone is Zone.SORTING and parcel.assigned_robot is None


# ------------------------------------------------------------------- parcels
def test_a_parcel_keeps_its_own_biography():
    parcel = Parcel(parcel_id="P-0001", priority=ParcelPriority.URGENT,
                    size=ParcelSize.LARGE)
    parcel.set_status(ParcelStatus.REGISTERED, 3, "SUB-BARCODE")
    parcel.set_status(ParcelStatus.CLASSIFIED, 4, "SUB-DESTINATION")
    actors = [h["actor"] for h in parcel.processing_history]
    assert actors == ["SUB-BARCODE", "SUB-DESTINATION"]
    assert parcel.timestamps["registered"] == 3
    assert parcel.size.units == 3
    assert parcel.priority.rank > ParcelPriority.NORMAL.rank


def test_a_parcel_serialises_to_plain_json_types():
    import json
    env = build_environment()
    parcel = env.add_parcel(Parcel(parcel_id="P-0001"))
    parcel.set_status(ParcelStatus.REGISTERED, 1, "SUB-BARCODE")
    json.dumps(parcel.as_dict())     # raises if anything is not serialisable


# --------------------------------------------------------------------- tasks
def test_the_queue_orders_by_priority_then_by_age():
    reg = TaskRegistry(IdFactory())
    reg.create(TaskType.TRANSPORT, 1, "PLANNER", parcel_id="P-1",
               priority=ParcelPriority.NORMAL)
    urgent = reg.create(TaskType.TRANSPORT, 5, "PLANNER", parcel_id="P-2",
                        priority=ParcelPriority.URGENT)
    express = reg.create(TaskType.TRANSPORT, 2, "PLANNER", parcel_id="P-3",
                         priority=ParcelPriority.EXPRESS)
    order = [t.task_id for t in reg.unassigned()]
    assert order[0] == urgent.task_id and order[1] == express.task_id


def test_a_task_cannot_go_backwards_through_its_life():
    reg = TaskRegistry(IdFactory())
    task = reg.create(TaskType.TRANSPORT, 1, "PLANNER", parcel_id="P-1")
    task.assign("SORTING", 2, "PLANNER", robot_id="R1")
    task.start(3, "R1")
    task.complete(4, "R1")
    with pytest.raises(IllegalTransition):
        task.start(5, "R1")


def test_a_released_task_returns_to_the_queue_without_its_robot():
    reg = TaskRegistry(IdFactory())
    task = reg.create(TaskType.TRANSPORT, 1, "PLANNER", parcel_id="P-1")
    task.assign("ROUTING", 2, "PLANNER", robot_id="R1")
    task.release(3, "RESOURCE", reason="robot went to charge")
    assert task.status is TaskStatus.CREATED
    assert task.assigned_robot is None
    assert task in reg.unassigned()


def test_a_task_waits_for_what_it_depends_on():
    reg = TaskRegistry(IdFactory())
    first = reg.create(TaskType.CLASSIFY, 1, "PLANNER", parcel_id="P-1")
    second = reg.create(TaskType.TRANSPORT, 1, "PLANNER", parcel_id="P-1",
                        depends_on=[first.task_id])
    assert second in reg.blocked()
    assert second not in reg.ready()
    first.assign("SORTING", 2, "PLANNER")
    first.start(2, "SORTING")
    first.complete(3, "SORTING")
    assert second in reg.ready()


# ----------------------------------------------------------------------- rng
def test_adding_a_robot_does_not_disturb_the_others():
    # The whole point of per-agent streams: an experiment that adds R6 must not
    # silently change what R3 does.
    before = SeededRNG(11)
    draws_before = {r: before.stream(r).random() for r in ("R1", "R2", "R3")}
    after = SeededRNG(11)
    after.stream("R6").random()
    draws_after = {r: after.stream(r).random() for r in ("R1", "R2", "R3")}
    assert draws_before == draws_after


def test_a_different_seed_gives_different_draws():
    assert SeededRNG(1).stream("R1").random() != SeededRNG(2).stream("R1").random()
