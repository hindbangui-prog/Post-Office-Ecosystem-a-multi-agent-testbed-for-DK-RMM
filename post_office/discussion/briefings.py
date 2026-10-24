"""
What a peer tells the owner: its own view of the floor, taken on its own turn.

Read on the peer's tick (from `DiscussionManager.on_message`), never from a
worker thread, so it is the floor as it is when the peer replies.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

MAX_ITEMS = 8


def _robots(world, keys) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for robot in list(world.fleet.all())[:MAX_ITEMS]:
        row = {
            "battery": round(float(robot.battery_level), 1),
            "status": robot.status.value,
            "zone": robot.current_zone.value if robot.current_zone else "",
            "task": robot.current_task or "",
            "position": str(robot.current_position),
        }
        out[robot.robot_id] = {k: row[k] for k in keys}
    return out


def _transport_tasks(world):
    return [t for t in world.tasks.open_tasks() if t.task_type.value == "TRANSPORT"]


def resource(agent) -> Dict[str, Any]:
    world = agent.world
    storage = dict(agent.state().get("storage", {}))
    storage.pop("held", None)
    return {
        "robots": _robots(world, ("battery", "status", "task")),
        "reserve_battery": world.policy.reserve_battery,
        "charge_points": {sid: (station.occupant or "free")
                          for sid, station in sorted(world.env.stations.items())},
        "charging": dict(sorted(getattr(agent, "_charging", {}).items())[:MAX_ITEMS]),
        "storage": storage,
    }


def scheduling(agent) -> Dict[str, Any]:
    world = agent.world
    parcels = world.env.parcels
    jobs: Dict[str, Dict[str, Any]] = {}
    for task in _transport_tasks(world):
        parcel = parcels.get(task.parcel_id)
        due = getattr(parcel, "due_by", None) if parcel is not None else None
        jobs[task.task_id] = {
            "parcel": task.parcel_id,
            "priority": task.priority.value,
            "status": task.status.value,
            "robot": task.assigned_robot or "",
            "slack": (int(due) - int(world.tick)) if due is not None else None,
        }
        if len(jobs) >= MAX_ITEMS:
            break
    return {
        "transports": jobs,
        "free_robots": [r.robot_id for r in world.fleet.available()],
        "late": sum(1 for j in jobs.values() if j["slack"] is not None and j["slack"] < 0),
    }


def dispatch(agent) -> Dict[str, Any]:
    world = agent.world
    at_bay = world.env.departures.state().get("at_bay", {})
    state = agent.state()
    return {
        "now": int(world.tick),
        "vans": {route: {"departs_at": van.get("departs_at"),
                         "units": van.get("units"),
                         "capacity": van.get("capacity")}
                 for route, van in sorted(at_bay.items())},
        "at_the_door": list(state.get("at_the_door", []))[:MAX_ITEMS],
        "held": state.get("held", 0),
    }


def routing(agent) -> Dict[str, Any]:
    robots = _robots(agent.world, ("position", "status", "task"))
    return {
        "robots": robots,
        "blocked_or_waiting": [rid for rid, r in robots.items()
                               if r["status"] in ("BLOCKED", "WAITING")],
    }


def planner(agent) -> Dict[str, Any]:
    world = agent.world
    by_status: Dict[str, int] = {}
    for parcel in world.env.parcels.values():
        by_status[parcel.status.value] = by_status.get(parcel.status.value, 0) + 1
    return {
        "max_concurrent_transports": world.policy.max_concurrent_transports,
        "open_transports": len(_transport_tasks(world)),
        "free_robots": len(world.fleet.available()),
        "parcels_by_status": dict(sorted(by_status.items())),
    }


def sorting(agent) -> Dict[str, Any]:
    world = agent.world
    storage = world.env.storage
    return {
        "routes": list(world.env.departures.routes),
        "storage_capacity": storage.capacity,
        "storage_held": len(storage.held),
    }


BRIEFINGS: Dict[str, Callable[[Any], Dict[str, Any]]] = {
    "RESOURCE": resource,
    "SCHEDULING": scheduling,
    "DISPATCH": dispatch,
    "ROUTING": routing,
    "PLANNER": planner,
    "SORTING": sorting,
}


def briefing_for(agent) -> Dict[str, Any]:
    """The peer's facts for a reply. Never raises: a discussion must not stop a tick."""
    gather = BRIEFINGS.get(agent.agent_id)
    if gather is None:
        return {"note": f"no briefing for {agent.agent_id}"}
    try:
        return gather(agent)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
