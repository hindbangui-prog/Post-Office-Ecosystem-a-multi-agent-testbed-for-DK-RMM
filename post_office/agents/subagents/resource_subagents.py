"""
The three specialists that work for the resource agent.

    SUB-BATTERY    is there enough charge left in this robot for this errand?
    SUB-CHARGING   which charge point, and is there one at all?
    SUB-STORAGE    how full are the shelves, and should we keep filling them?

Between them they own everything in the facility that can run out. The resource
agent asks them; it does not second-guess them, and no other expert may reach
past it to them -- the bus refuses that, and writes the refusal down.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ...communication.message import Message
from ...robots.robot import HANDLING_COST, MOVE_COST
from ..base import SubAgent
from ..brain import Answer, Question


class BatteryManagementSubAgent(SubAgent):
    """
    Judges whether a robot can finish a job before it runs flat.

    The estimate is deliberately explicit -- cells to travel, cost per cell,
    two handling operations, plus a reserve -- so that when a robot does strand
    itself the log says which of those numbers was wrong.
    """

    #: How much longer a real journey is than the empty-floor route. Measured
    #: from baseline runs: with five robots and the narrow doorways between
    #: zones, a
    #: journey costs the best part of twice its planned length once blocking,
    #: yielding and rerouting are counted. Estimating with the planned length is
    #: how a robot is approved for an errand it cannot finish.
    CONGESTION = 1.8

    def __init__(self, parent_id: str, agent_id: str = "SUB-BATTERY", **kw):
        super().__init__(agent_id, "battery management", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        content = message.content
        robot_id = content.get("robot_id", "")
        robot = self.world.fleet.get(robot_id)
        if robot is None:
            return {"operation": "battery_check", "robot_id": robot_id,
                    "ok": False, "reason": "no such robot"}

        cells = float(content.get("route_length", 0))
        # The route length is the distance with the floor empty. Real journeys
        # are longer: robots are rerouted round each other, step aside in
        # doorways and occasionally go back on themselves. `CONGESTION` above is
        # what the baseline run actually costs -- most of twice the planned
        # length, not the quarter again this comment used to claim -- and
        # under-estimating here is what strands a robot half way to a charge
        # point.
        estimate = cells * MOVE_COST * self.CONGESTION + 2 * HANDLING_COST
        level = round(robot.battery_level, 1)
        reserve = self.world.policy.reserve_battery
        return {
            "operation": "battery_check",
            "robot_id": robot_id,
            "ok": True,
            # The estimate and nothing else. What to do about it -- send it,
            # charge it first, refuse the errand -- is RESOURCE's call, because
            # it is a trade against the work waiting rather than a sum.
            "battery": level,
            "route_length": cells,
            "estimated_cost": round(estimate, 1),
            "left_after": round(level - estimate, 1),
            "reserve": reserve,
            "_text": (f"{robot_id} has {level:.0f}% and the errand costs about "
                      f"{estimate:.0f}% (reserve {reserve:.0f}%)."),
        }


class ChargingStationSubAgent(SubAgent):
    """
    Allocates charge points, and says plainly when there are none.

    There are four points and five robots, which is not an oversight: a
    resource that never runs out never teaches you anything about the system
    that depends on it.
    """

    def __init__(self, parent_id: str, agent_id: str = "SUB-CHARGING", **kw):
        super().__init__(agent_id, "charging station management", parent_id, **kw)

    def _errand(self, robot) -> Optional[Dict[str, Any]]:
        """
        What the robot is in the middle of, in the terms the contest needs:
        the class the sender paid for, and how long the promise has left.

        A lookup, not a judgement. `carrying` was already reported and was
        already useless on its own -- a parcel id tells you a robot is busy
        and nothing about whether it is busy with something urgent.
        """
        parcel = self.world.env.parcels.get(robot.carrying or "")
        if parcel is None:
            return None
        return {
            "parcel_id": parcel.parcel_id,
            "class": parcel.priority.value,
            "ticks_to_deadline": (None if parcel.due_by is None
                                  else parcel.due_by - self.world.tick),
        }

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        content = message.content
        operation = content.get("operation", "request_station")
        env = self.world.env

        if operation == "station_report":
            return {
                "operation": operation, "ok": True,
                "stations": [s.as_dict() for s in
                             sorted(env.stations.values(),
                                    key=lambda s: s.station_id)],
                "free": len(env.free_stations()),
                "_text": f"{len(env.free_stations())} of {len(env.stations)} "
                         f"charge points free.",
            }

        robot_id = content.get("robot_id", "")
        robot = self.world.fleet.get(robot_id)
        if robot is None:
            return {"operation": operation, "ok": False,
                    "reason": "no such robot"}

        free = env.free_stations()
        if not free:
            # Not a failure of this sub-agent -- a fact about the facility. It
            # is reported and logged rather than retried silently.
            return {"operation": operation, "robot_id": robot_id, "ok": False,
                    "reason": "every charge point is occupied",
                    "waiting": len(self.world.fleet.needing_charge()),
                    "_text": f"No charge point for {robot_id}: all "
                             f"{len(env.stations)} are busy."}

        # Every free point this robot could actually reach, with the walk to
        # it. Measuring the floor is this agent's work; four points and five
        # robots means somebody goes without, and who that is is a trade-off
        # RESOURCE makes.
        reachable = []
        for station in sorted(free, key=lambda s: s.station_id):
            distance = env.distance(robot.current_position, station.position)
            if distance is None:
                continue
            reachable.append({"station_id": station.station_id,
                              "position": station.position.as_dict(),
                              "distance": distance,
                              "rate": getattr(station, "rate", None)})
        if not reachable:
            return {"operation": operation, "robot_id": robot_id, "ok": False,
                    "reason": "no charge point is reachable from there"}

        # Who else is queueing for the same points, and what each of them is in
        # the middle of. Without this the allocation cannot be a trade-off at
        # all -- it was a nearest-point lookup that could not tell a robot
        # carrying an urgent parcel from an idle one.
        rivals = {}
        for other in self.world.fleet.needing_charge():
            if other.robot_id == robot_id:
                continue
            rivals[other.robot_id] = {
                "battery": round(other.battery_level, 1),
                "carrying": other.carrying or "",
                "errand": self._errand(other),
                "status": other.status.value,
            }
        return {
            "operation": operation,
            "robot_id": robot_id,
            "ok": True,
            "stations": reachable,
            "free": len(free),
            "points": len(env.stations),
            "battery": round(robot.battery_level, 1),
            "carrying": robot.carrying or "",
            "errand": self._errand(robot),
            "rivals": rivals,
            "_text": (f"{len(reachable)} point(s) reachable for {robot_id} "
                      f"at {robot.battery_level:.0f}%"
                      + (f", {len(rivals)} other(s) also want one." if rivals
                         else ".")),
        }


class StorageMonitoringSubAgent(SubAgent):
    """
    Watches the shelves.

    Answers two different questions: "how full is it" (a fact) and "should we
    keep sending parcels there" (a judgement, because the right answer depends
    on how much is still coming through the door).
    """

    def __init__(self, parent_id: str, agent_id: str = "SUB-STORAGE", **kw):
        super().__init__(agent_id, "storage monitoring", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        content = message.content
        env = self.world.env
        operation = content.get("operation", "storage_report")

        if operation == "storage_report":
            return {"operation": operation, "ok": True, **env.storage.as_dict(),
                    "_text": f"Storage {env.storage.used}/{env.storage.capacity}."}

        if operation == "claim_storage":
            parcel_id = content.get("parcel_id", "")
            granted = env.claim_storage(parcel_id)
            return {"operation": operation, "parcel_id": parcel_id,
                    "ok": granted, "free": env.storage.free,
                    "reason": "" if granted else "shelves full",
                    "_text": (f"Shelf {'reserved' if granted else 'refused'} "
                              f"for {parcel_id}.")}

        if operation == "release_storage":
            parcel_id = content.get("parcel_id", "")
            env.release_storage(parcel_id)
            return {"operation": operation, "parcel_id": parcel_id, "ok": True,
                    "free": env.storage.free}

        from ...environment.zones import Zone
        return {
            "operation": "accept_into_storage",
            "ok": True,
            # How full the shelves are and what is still coming: facts. Whether
            # to keep filling them is a judgement about the rest of the day,
            # and RESOURCE makes it.
            "load": round(env.storage.load, 3),
            "used": env.storage.used,
            "capacity": env.storage.capacity,
            "free": env.storage.free,
            "max_load": self.world.policy.max_storage_load,
            "parcels_inbound": len(env.parcels_in(Zone.INTAKE)),
            "_text": (f"Shelves {env.storage.used}/{env.storage.capacity} "
                      f"({env.storage.load:.0%}), "
                      f"{len(env.parcels_in(Zone.INTAKE))} still inbound."),
        }
