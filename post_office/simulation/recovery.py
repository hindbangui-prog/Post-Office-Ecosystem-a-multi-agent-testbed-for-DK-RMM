"""
Getting a flat robot off the floor, as a thing the facility does.

A robot at zero cannot move. It is not broken and it is not idle -- it is
stuck, in whatever corridor it happened to stop in, and every route planned
through that corridor now fails. Something has to come and get it.

That something is not an agent. An agent can notice the robot, decide the
facility should intervene, and ask; what it cannot do is pick the robot up,
because position and charge belong to the simulation. This module is the other
half of that split: it takes the requests agents have made, decides whether
each one can actually be honoured, and carries out the ones that can.

Honouring one is deliberately not instant and deliberately not free:

    delay       a crew has to reach the robot. `DELAY` ticks, during which
                the robot stays exactly where it stopped.
    capacity    the robot is taken to a charge point, and only if one is
                free. No point, no recovery -- the request stays pending and
                is tried again. The facility cannot conjure a plug.
    charge      it arrives with the charge it had, which is none, and fills
                at the ordinary rate like everything else on a plug.

The last is the one that matters most for the numbers. A recovery that
refilled the battery would make stranding free, and a fleet that can strand
itself for free will, under load, do it constantly -- which is precisely the
ecosystem behaviour the simulation is supposed to be able to observe rather
than paper over.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..communication.events import EventCategory
from ..environment.recovery import RecoveryRequest
from ..robots.robot import RobotState


class RecoveryService:
    """
    The simulation engine's answer to recovery requests.

    Owned by the ecosystem and stepped once a tick, after the agents have had
    theirs. It reads `env.recovery_requests`, which is the queue agents append
    to, and is the only thing in the system that acts on them.
    """

    #: How long the crew takes to reach a stranded robot, in ticks. Long
    #: enough to be a real cost -- a robot stranded in a doorway blocks it for
    #: this long -- and short enough that a run is not dominated by it.
    DELAY = 12

    def __init__(self, world) -> None:
        self.world = world
        self.completed = 0
        self.refused = 0
        self.withdrawn = 0

    # ------------------------------------------------------------------ api
    def step(self, tick: int) -> None:
        env = self.world.env
        pending: List[RecoveryRequest] = getattr(env, "recovery_requests", [])
        if not pending:
            return
        keep: List[RecoveryRequest] = []
        for request in pending:
            outcome = self._attempt(request, tick)
            if outcome == "pending":
                keep.append(request)
        env.recovery_requests = keep

    def stats(self) -> Dict[str, int]:
        return {"completed": self.completed, "refused": self.refused,
                "withdrawn": self.withdrawn}

    # ------------------------------------------------------------- internal
    def _attempt(self, request: RecoveryRequest, tick: int) -> str:
        robot = self.world.fleet.get(request.robot_id)
        if robot is None:
            self.withdrawn += 1
            return "gone"

        # Conditions move between the asking and the acting. A robot that is
        # no longer stranded is not recovered: the request is withdrawn, and
        # said to be withdrawn, rather than carried out against a floor that
        # has changed underneath it.
        if robot.battery_level > 0.0:
            self.withdrawn += 1
            self._log("recovery_withdrawn", request, robot,
                      reason="it is under its own power again")
            return "withdrawn"

        if tick - request.tick < self.DELAY:
            return "pending"                     # the crew is still on its way

        station = self._free_station(request.target)
        if station is None:
            # Physical capacity, and the engine may no more invent it than an
            # agent may. The robot stays where it is and the crew tries again.
            request.attempts += 1
            self.refused += 1
            self._log("recovery_deferred", request, robot,
                      reason="no charge point free")
            return "pending"

        env = self.world.env
        # From here down is the simulation moving a robot, which is its own
        # business and nobody else's. It is still a tow rather than a journey:
        # a robot with no charge cannot drive, so the crew carries it, and the
        # cost of that is the delay above and the corridor it blocked.
        env.place_robot(robot.robot_id, station.position)
        robot.current_position = station.position
        robot.current_zone = env.zone_at(station.position)
        env.claim_station(robot.robot_id, station.station_id)
        robot.status = RobotState.CHARGING
        # Not refilled. It charges from empty, at the rate the plug gives it,
        # exactly like a robot that drove itself here.
        robot.note(tick, "recovered", station=station.station_id,
                   requested_by=request.requested_by)
        self.completed += 1
        self._log("recovery_completed", request, robot,
                  station=station.station_id,
                  reason=f"towed to {station.station_id} after "
                         f"{tick - request.tick} ticks")
        return "done"

    def _free_station(self, preferred: str = ""):
        env = self.world.env
        free = sorted(env.free_stations(), key=lambda s: s.station_id)
        if preferred:
            for station in free:
                if station.station_id == preferred:
                    return station
        return free[0] if free else None

    def _log(self, topic: str, request: RecoveryRequest, robot,
             reason: str = "", **detail) -> None:
        self.world.logger.emit(
            EventCategory.RESOURCE, topic, tick=self.world.tick,
            actor="SIMULATION", target=robot.robot_id,
            requested_by=request.requested_by, reason=reason,
            battery=round(robot.battery_level, 1), **detail)
