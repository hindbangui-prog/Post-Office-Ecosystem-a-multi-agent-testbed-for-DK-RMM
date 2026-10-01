"""
The two specialists that work for the routing agent.

    SUB-ROUTE       finds paths across the floor
    SUB-COLLISION   decides what to do when the way ahead is occupied

The split follows a real difference. Path finding is geometry and has one right
answer; what to do about another robot standing in a doorway is a judgement --
wait, and the doorway probably clears; go round, and you certainly arrive, but
later, and you may meet the same robot at the other end. That second decision
is a `decide()` call, and it is one of the more interesting places to put a
language model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...communication.message import Message
from ...environment.grid import Position
from ..base import SubAgent
from ..brain import Answer, Question


class RoutePlanningSubAgent(SubAgent):
    """Turns two cells into a list of cells. No judgement, and none wanted."""

    def __init__(self, parent_id: str, agent_id: str = "SUB-ROUTE", **kw):
        super().__init__(agent_id, "route planning", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        content = message.content
        operation = content.get("operation", "plan_route")
        env = self.world.env

        if operation == "plan_transport":
            # Both legs at once: a robot is given its whole errand up front, so
            # it never has to stop half way and ask for the rest.
            start = Position.of(content["start"])
            pickup = Position.of(content["pickup"])
            dropoff = Position.of(content["dropoff"])
            to_pickup = env.path(start, pickup)
            # An errand that goes by way of a waypoint -- an urgent parcel
            # through the sorting hall -- has its carrying leg in two parts,
            # so the robot can be told where the first one ends.
            via = Position.of(content["via"]) if content.get("via") else None
            if via is not None:
                to_dropoff = env.path(pickup, via)
                after_via = env.path(via, dropoff)
            else:
                to_dropoff = env.path(pickup, dropoff)
                after_via = []
            ok = (to_pickup is not None and to_dropoff is not None
                  and after_via is not None)
            extra = ({"via": via.as_dict(),
                      "after_via": [p.as_dict() for p in (after_via or [])]}
                     if via is not None else {})
            return {
                "operation": operation,
                "ok": ok,
                "robot_id": content.get("robot_id"),
                "task_id": content.get("task_id"),
                "to_pickup": [p.as_dict() for p in (to_pickup or [])],
                "to_dropoff": [p.as_dict() for p in (to_dropoff or [])],
                **extra,
                "length": (len(to_pickup or []) + len(to_dropoff or [])
                           + len(after_via or [])),
                "reason": "" if ok else "no path across the floor",
                "_text": (f"Route for {content.get('robot_id')}: "
                          f"{len(to_pickup or [])} cells to the parcel, "
                          f"{len(to_dropoff or [])} on to the drop."),
            }

        start = Position.of(content["start"])
        goal = Position.of(content["goal"])
        path = env.path(start, goal)
        return {
            "operation": operation,
            "ok": path is not None,
            "robot_id": content.get("robot_id"),
            "task_id": content.get("task_id"),
            "route": [p.as_dict() for p in (path or [])],
            "length": len(path or []),
            "reason": "" if path else "unreachable",
            "_text": f"Route {start} -> {goal}: {len(path or [])} cells.",
        }


class CollisionAvoidanceSubAgent(SubAgent):
    """
    Works out what a robot that has stopped could do about it, and what each
    way out would cost. ROUTING chooses between them.

    Four moves are possible and each is sometimes right, which is what makes
    the choice a judgement rather than a rule -- and why it belongs to the
    agent responsible for the floor rather than to this one, whose work is
    measuring it:

        WAIT      hold position; the obstruction is probably passing through
        REROUTE   recompute the path treating the occupied cells as walls
        YIELD     step out of the doorway entirely and ask for a fresh route

    YIELD exists because the building's doorways are two cells wide at their
    widest, and two robots
    meeting head-on in one of those cannot both wait and cannot both go round.
    Without it the facility deadlocks: every robot polite, every robot
    stationary, the whole floor stopped.

    Priority over a contested cell goes to the robot with the lower id, which is
    arbitrary but total and deterministic -- an arbitrary tie-break that is
    written down beats a fair one that depends on iteration order. But priority
    is a courtesy, not a right: a robot that has been stuck for `IMPATIENCE`
    ticks steps aside whatever its id, because the robot in front of it is
    plainly not about to move and waiting politely for ever is how a fleet dies
    one robot at a time.

    There is also a block routing cannot solve: the cell the robot is trying to
    reach is the cell somebody else is standing on. No route and no sidestep
    helps, so the answer is ABANDON -- the scheduler is told, the errand goes
    back in the queue, and it is tried again later from wherever things have
    moved to.

    A detour is only offered when one exists and is not absurdly longer than
    waiting, so the brain is never asked to choose an option that does not
    exist.
    """

    #: How much longer a detour may be before waiting is obviously better.
    DETOUR_TOLERANCE = 8

    #: After this many ticks stuck, a robot stops deferring to anybody.
    IMPATIENCE = 6

    #: And after this many, an errand whose destination is occupied is given
    #: back to the scheduler. Set well above IMPATIENCE on purpose: a robot
    #: standing on a drop cell has usually just put a parcel down and is about
    #: to leave, and abandoning errands over a two-tick pause would cancel most
    #: of the work in the building.
    PATIENCE_WITH_OCCUPIED_GOAL = 12

    def __init__(self, parent_id: str, agent_id: str = "SUB-COLLISION", **kw):
        super().__init__(agent_id, "collision avoidance", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        content = message.content
        robot_id = content.get("robot_id", "")
        env = self.world.env
        robot = self.world.fleet.get(robot_id)
        if robot is None:
            return {"operation": "resolve_block", "ok": False,
                    "reason": f"no robot {robot_id}"}

        goal = Position.of(content["goal"]) if content.get("goal") else robot.destination
        if goal is None:
            return {"operation": "resolve_block", "robot_id": robot_id,
                    "ok": False, "reason": "robot has nowhere to be"}

        detour = self._detour(env, robot, goal)
        direct = env.distance(robot.current_position, goal)
        detour_extra = (len(detour) - 1 - direct) if detour and direct is not None else None
        if detour_extra is not None and detour_extra > self.DETOUR_TOLERANCE:
            detour, detour_extra = None, None

        blocked_by = content.get("blocked_by", "")
        blocked_for = int(content.get("ticks_blocked", 1))
        side = self._side_step(env, robot, goal)
        # The way onward is planned around the other robots, not through them.
        # A resume route computed on the empty floor walks straight back into
        # whoever was blocking, and the pair spend the rest of the run stepping
        # aside for each other -- politely, repeatedly, and at half a percent of
        # battery per step.
        resume = None
        if side is not None:
            resume = self._around(env, robot, side, goal) or env.path(side, goal)

        # Whoever is standing on the destination cannot be routed around, and a
        # robot waiting for them to move may wait for the rest of the run.
        occupant_of_goal = env.occupied_by_robot(goal, excluding=robot_id)

        may_yield = (side is not None and resume is not None
                     and bool(blocked_by)
                     and (robot_id > blocked_by or blocked_for >= self.IMPATIENCE))

        # A robot that has finished its errand and stopped in a corridor is not
        # going to move on its own, and no amount of waiting or rerouting gets
        # past it -- in a building with doorways this narrow there is frequently no
        # way round. So it is asked to move. This is the only place in the
        # system where one robot's problem is solved by moving another, and it
        # goes through the routing agent and a message, not by reaching in.
        blocker = self.world.fleet.get(blocked_by) if blocked_by else None
        push_to = None
        if blocker is not None and blocker.status.value in ("IDLE", "WAITING") \
                and blocked_for >= 2:
            push_to = self._side_step(env, blocker, robot.current_position)

        options = ["WAIT"]
        if detour:
            options.append("REROUTE")
        if may_yield:
            options.append("YIELD")
        if push_to is not None:
            options.append("PUSH")
        if occupant_of_goal is not None \
                and blocked_for >= self.PATIENCE_WITH_OCCUPIED_GOAL:
            options = ["ABANDON"] + options

        return {
            "operation": "resolve_block",
            "robot_id": robot_id,
            "ok": True,
            # What ROUTING may choose between. Only moves that exist: a detour
            # is offered when there is one, yielding when there is somewhere to
            # yield to, so the agent above is never asked to pick something
            # that cannot be done.
            "options": list(options),
            # What each of them would cost, which is what the choice turns on.
            "blocked_by": blocked_by or "?",
            "ticks_blocked": blocked_for,
            "direct_distance": direct,
            "detour_extra": detour_extra,
            "battery": round(robot.battery_level, 1),
            # And the geometry behind each move, worked out here because
            # measuring the floor is this agent's whole purpose. ROUTING picks
            # one and sends it; it does not compute paths.
            "route": [p.as_dict() for p in (detour or [])],
            "yield_to": side.as_dict() if side else None,
            "hold": self._backoff(robot_id),
            "push_robot": blocked_by or None,
            "push_to": push_to.as_dict() if push_to else None,
            "resume_route": [p.as_dict() for p in resume] if resume else [],
            "goal": goal.as_dict(),
            "task_id": robot.current_task,
            "occupant_of_goal": occupant_of_goal,
            "_text": (f"{robot_id} blocked by {blocked_by or 'something'} for "
                      f"{blocked_for} tick(s); can " + ", ".join(options)),
        }

    def _backoff(self, robot_id: str) -> int:
        """
        How long to stand still after stepping aside, in ticks.

        Jittered, from the robot's own seeded stream. Without the jitter two
        robots that meet head-on step aside together, set off again together,
        and meet again one cell further on -- the synchronisation is an artefact
        of the scheduler rather than anything about the building, and it is the
        single most expensive thing that can happen to a fleet's batteries.
        """
        return 1 + self.world.rng.stream(f"backoff:{robot_id}").randrange(0, 3)

    @staticmethod
    def _around(env, robot, start, goal) -> Optional[List[Position]]:
        """A path from `start` to `goal` treating the other robots as walls."""
        from ...environment.grid import Grid

        occupied = {p for rid, p in env.robot_positions().items()
                    if rid != robot.robot_id}
        occupied.discard(start)
        if goal in occupied:
            return None
        scratch = Grid(env.grid.width, env.grid.height,
                       set(env.grid.obstacles) | occupied)
        return scratch.path(start, goal)

    @staticmethod
    def _side_step(env, robot, goal) -> Optional[Position]:
        """
        A free neighbouring cell to get out of the way into.

        Preference is for the cell that moves *away* from the goal, because
        stepping towards it usually means stepping into the same queue one cell
        further along. Ties break on coordinates, so the choice is the same on
        every run.
        """
        candidates = []
        for cell in robot.current_position.neighbours():
            if not env.is_free(cell):
                continue
            if env.occupied_by_robot(cell, excluding=robot.robot_id):
                continue
            candidates.append((-cell.manhattan(goal), cell.x, cell.y, cell))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][3]

    @staticmethod
    def _detour(env, robot, goal) -> Optional[List[Position]]:
        """
        A path that treats the other robots as walls.

        Built on a throwaway copy of the grid, because turning a robot into a
        permanent obstacle would slowly brick the building.
        """
        from ...environment.grid import Grid

        occupied = {p for rid, p in env.robot_positions().items()
                    if rid != robot.robot_id}
        occupied.discard(robot.current_position)
        if goal in occupied:
            # Somebody is standing on the destination. Pretending otherwise
            # produces a "detour" that walks straight through them, which the
            # robot then reports as blocked, for ever.
            return None
        if not occupied:
            return None
        scratch = Grid(env.grid.width, env.grid.height,
                       set(env.grid.obstacles) | occupied)
        return scratch.path(robot.current_position, goal)
