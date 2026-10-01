"""
The fleet: the robots as a group, and the questions the expert agents ask of it.

Every query here returns a deterministically ordered result. "The nearest free
robot" has to mean the same robot on two runs of the same seed, so ties break
on robot id rather than on whatever order a dictionary happened to iterate in.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

from ..environment.facility import PostOfficeEnvironment
from ..environment.grid import Position
from ..environment.layout import DEFAULT_ROBOT_HOME
from .robot import Robot, RobotState


class Fleet:
    """All the robots, with the orderings the rest of the system relies on."""

    def __init__(self, robots: Iterable[Robot] = ()) -> None:
        self._robots: Dict[str, Robot] = {r.robot_id: r for r in robots}

    # ------------------------------------------------------------ membership
    def add(self, robot: Robot) -> Robot:
        self._robots[robot.robot_id] = robot
        return robot

    def __getitem__(self, robot_id: str) -> Robot:
        return self._robots[robot_id]

    def __contains__(self, robot_id: str) -> bool:
        return robot_id in self._robots

    def __len__(self) -> int:
        return len(self._robots)

    def get(self, robot_id: str) -> Optional[Robot]:
        return self._robots.get(robot_id)

    def all(self) -> List[Robot]:
        return [self._robots[k] for k in sorted(self._robots)]

    def ids(self) -> List[str]:
        return sorted(self._robots)

    # --------------------------------------------------------------- queries
    def available(self) -> List[Robot]:
        return [r for r in self.all() if r.is_available]

    def in_state(self, state: RobotState) -> List[Robot]:
        return [r for r in self.all() if r.status is state]

    def needing_charge(self) -> List[Robot]:
        """Flattest first -- whoever is closest to stopping gets the plug."""
        return sorted((r for r in self.all() if r.needs_charge),
                      key=lambda r: (r.battery_level, r.robot_id))

    def nearest_available(self, env: PostOfficeEnvironment,
                          target: Position) -> Optional[Robot]:
        """
        The free robot with the shortest real path to `target`.

        Real path, not straight-line distance: with three walls in the building
        the nearest robot as the crow flies is regularly the slowest one, and a
        scheduler that cannot tell the difference will look incompetent in the
        demonstration for a reason that has nothing to do with scheduling.
        """
        best: Optional[Robot] = None
        best_key = None
        for robot in self.available():
            distance = env.distance(robot.current_position, target)
            if distance is None:
                continue
            key = (distance, -robot.battery_level, robot.robot_id)
            if best_key is None or key < best_key:
                best, best_key = robot, key
        return best

    # --------------------------------------------------------------- reports
    def battery_summary(self) -> Dict[str, float]:
        levels = [r.battery_level for r in self.all()]
        if not levels:
            return {"min": 0.0, "mean": 0.0, "max": 0.0}
        return {
            "min": round(min(levels), 2),
            "mean": round(sum(levels) / len(levels), 2),
            "max": round(max(levels), 2),
        }

    def status_counts(self) -> Dict[str, int]:
        counts = {s.value: 0 for s in RobotState}
        for robot in self.all():
            counts[robot.status.value] += 1
        return counts

    def as_dict(self) -> dict:
        return {
            "count": len(self._robots),
            "status_counts": self.status_counts(),
            "battery": self.battery_summary(),
            "robots": [r.as_dict() for r in self.all()],
        }


def build_fleet(env: PostOfficeEnvironment,
                homes: Optional[Dict[str, Position]] = None,
                speed: int = 1, load_capacity: int = 3,
                low_battery: float = 25.0) -> Fleet:
    """Create the fleet and put it on the floor. Five robots by default."""
    homes = homes or DEFAULT_ROBOT_HOME
    fleet = Fleet()
    for robot_id in sorted(homes):
        position = Position.of(homes[robot_id])
        if not env.is_free(position):
            raise ValueError(f"{robot_id} starts inside a wall at {position}")
        robot = Robot(robot_id=robot_id, current_position=position,
                      current_zone=env.zone_at(position), speed=speed,
                      load_capacity=load_capacity, low_battery=low_battery)
        fleet.add(robot)
        env.place_robot(robot_id, position)
    return fleet
