"""
Robots, as agents rather than as sprites.

A robot here owns its own body: where it is, what it is carrying, how much
charge it has left, and what it is currently trying to do. It advances itself
one tick at a time and tells the rest of the system what happened. What it does
*not* do is decide where to go -- routes come from the routing agent, work comes
from the scheduler, permission to charge comes from the resource agent. That
division is the point: a robot that planned its own routes would make the expert
agents decorative.

Everything a robot does is reported. `step()` returns a list of plain
dictionaries -- arrived, picked, delivered, blocked, battery_low, charged -- and
the layer above turns them into messages and events. The robot itself has never
heard of the message bus, which is what lets it be tested in four lines.

Movement is deterministic. A robot moves up to `speed` cells along the route it
was given; if the next cell is occupied by another robot it stops, goes BLOCKED
and says so, rather than swapping places or passing through. Deadlock is
therefore possible, and is meant to be: it is exactly the sort of thing a
monitoring layer should be able to see coming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from ..environment.facility import PostOfficeEnvironment
from ..environment.grid import Position
from ..environment.zones import Zone


class RobotState(str, Enum):
    """What the robot is doing this tick."""

    IDLE = "IDLE"              # free, waiting for work
    MOVING = "MOVING"          # travelling along a route
    PICKING = "PICKING"        # loading a parcel, takes a tick
    UNLOADING = "UNLOADING"    # setting one down, which takes a tick too
    DELIVERING = "DELIVERING"  # carrying, or unloading at the far end
    CHARGING = "CHARGING"      # plugged in
    WAITING = "WAITING"        # has asked for something and not got it yet
    BLOCKED = "BLOCKED"        # the way ahead is occupied


#: Costs in battery percent per cell, per handling operation, per idle tick.
#:
#: Scaled to this facility rather than copied from a datasheet, the same way
#: the van timetable is. What is preserved is the relationship that makes a
#: battery matter: a robot works a long run of errands and then charges, so
#: charging is an event in the day rather than the shape of it.
#:
#: These used to be 0.55, 0.4 and 0.04, which gave a robot 182 cells of range
#: -- about two crossings of the building. It spent its life shuttling between
#: work and a plug, and the fleet made 68 charge trips in a 3000-tick run. At
#: 0.12 a full charge is roughly 830 cells, or eighteen errands, which is a
#: stretch of work with an end in sight: long enough that nobody charges twice
#: an hour, short enough that the four charge points still get contested.
MOVE_COST = 0.12
HANDLING_COST = 0.1
IDLE_COST = 0.01

#: Below this a robot stops taking work and commits to a charge. It is the
#: point at which what is left is worth keeping for the walk to a plug rather
#: than spending on another errand.
COMMIT_BELOW = 25.0

#: And what a committed charge brings it back to. Not full: the last stretch
#: of a charge is the slowest and the least useful, and a robot sitting on one
#: of four points to gain it is holding it against four others.
WORKING_ORDER = 85.0

#: A top-up stops here. Real fleets keep a pack in a band rather than cycling
#: it to full, and a robot standing at a plug it does not need is a robot in
#: the way of one that does.
TOP_UP_CEILING = 80.0

#: A top-up is only worth starting below this. Above it there is nothing much
#: to gain and the point is better left free.
TOP_UP_BELOW = 70.0


@dataclass
class Robot:
    """One robot: its body, its job, and its memory of both."""

    robot_id: str
    current_position: Position
    current_zone: Optional[Zone] = None
    current_task: Optional[str] = None
    status: RobotState = RobotState.IDLE
    battery_level: float = 100.0
    battery_capacity: float = 100.0
    load: int = 0
    load_capacity: int = 3
    destination: Optional[Position] = None
    speed: int = 1
    carrying: Optional[str] = None            # parcel id
    task_history: List[Dict[str, Any]] = field(default_factory=list)

    # policy thresholds -- per robot, so an experiment can vary one of them
    low_battery: float = COMMIT_BELOW
    resume_battery: float = WORKING_ORDER

    # internals, not part of the published state
    _route: List[Position] = field(default_factory=list, repr=False)
    _leg: str = field(default="", repr=False)   # "to_pickup" | "to_dropoff" | "to_charger"
    _pickup: Optional[Position] = field(default=None, repr=False)
    _dropoff: Optional[Position] = field(default=None, repr=False)
    _parcel: Optional[str] = field(default=None, repr=False)
    _dest_zone: Optional[Zone] = field(default=None, repr=False)
    _pending_dropoff_route: List[Position] = field(default_factory=list, repr=False)
    #: A cell the carrying leg must pass through before the drop, and the walk
    #: from there on. Set for an errand that goes by way of the sorting hall
    #: without stopping in it; None for every other errand. While it is set,
    #: `destination` is that cell, so a replan, a detour or a yield all aim at
    #: it rather than cutting the corner to the drop.
    _via: Optional[Position] = field(default=None, repr=False)
    _after_via_route: List[Position] = field(default_factory=list, repr=False)
    _blocked_for: int = field(default=0, repr=False)
    _charge_requested: bool = field(default=False, repr=False)
    #: Whether the current plug-in is a top-up rather than a committed charge.
    #: A top-up is a robot with nothing better to do standing at a point that
    #: was free anyway; it has not left service and drops the plug the moment
    #: it is given work. A committed charge is a robot that is genuinely low,
    #: and it is out of service until it can work a stretch again.
    _topping_up: bool = field(default=False, repr=False)
    #: Set when a top-up ended somewhere that had no environment to hand; the
    #: next tick gives the point back.
    _release_station: bool = field(default=False, repr=False)
    _yield_to: Optional[Position] = field(default=None, repr=False)
    _yield_route: List[Position] = field(default_factory=list, repr=False)
    _waited: int = field(default=0, repr=False)
    _flat_for: int = field(default=0, repr=False)
    _hold: int = field(default=0, repr=False)

    # ----------------------------------------------------------------- record
    def note(self, tick: int, what: str, **detail) -> None:
        """One line in the robot's own log. Bounded, so a long run stays small."""
        self.task_history.append({"tick": tick, "event": what, **detail})
        if len(self.task_history) > 400:
            del self.task_history[:200]

    # --------------------------------------------------------------- commands
    def assign_transport(self, tick: int, task_id: str, parcel_id: str,
                         pickup: Position, dropoff: Position,
                         route_to_pickup: Sequence[Position],
                         route_to_dropoff: Sequence[Position],
                         destination_zone: Optional[Zone] = None,
                         via: Optional[Position] = None,
                         route_after_via: Sequence[Position] = ()) -> None:
        """
        Take on a transport job. Both legs of the route arrive with it, because
        the routing agent plans routes and the robot does not.

        With `via`, the carrying leg is walked in two parts: `route_to_dropoff`
        ends at `via`, and `route_after_via` goes on from there to the drop.
        The robot passes through without putting the parcel down.
        """
        if self._topping_up:
            # It was standing at a plug with nothing to do. There is something
            # to do now, so it goes -- which is the whole difference between a
            # top-up and a charge. The point itself is given back on the next
            # tick, when `step` has the environment in hand: a robot does not
            # hold a reference to the building it stands in.
            self._topping_up = False
            self._release_station = True
            self.note(tick, "top_up_ended", reason="work",
                      level=round(self.battery_level, 1))
        self.current_task = task_id
        self._parcel = parcel_id
        self._pickup = Position.of(pickup)
        self._dropoff = Position.of(dropoff)
        self._dest_zone = destination_zone
        self._leg = "to_pickup"
        self._route = [Position.of(p) for p in route_to_pickup]
        self._pending_dropoff_route = [Position.of(p) for p in route_to_dropoff]
        self._via = Position.of(via) if via is not None else None
        self._after_via_route = [Position.of(p) for p in route_after_via]
        self.destination = self._pickup
        self.status = RobotState.MOVING
        self._blocked_for = 0
        self.note(tick, "task_assigned", task_id=task_id, parcel_id=parcel_id,
                  pickup=self._pickup.as_dict(), dropoff=self._dropoff.as_dict())

    def assign_charge(self, tick: int, task_id: str, station_position: Position,
                      route: Sequence[Position]) -> None:
        """Go and plug in. Granted by the resource agent, routed by routing."""
        self.current_task = task_id
        self._leg = "to_charger"
        self._route = [Position.of(p) for p in route]
        self.destination = Position.of(station_position)
        self.status = RobotState.MOVING
        self._charge_requested = False
        self._blocked_for = 0
        self._topping_up = False
        self.note(tick, "charge_assigned", task_id=task_id,
                  level=round(self.battery_level, 1),
                  station=self.destination.as_dict())

    def begin_top_up(self, tick: int, env: PostOfficeEnvironment,
                     station_id: str = "") -> bool:
        """
        Take some charge, having nothing better to do.

        Only from a standing start on the point itself: a top-up is worth
        having because the robot was going to stand there anyway, and one that
        walks across the building for it is a dedicated charge wearing the
        wrong name. It stays available throughout.
        """
        if (self.status is not RobotState.IDLE or self.current_task is not None
                or self.carrying is not None
                or self.battery_level >= TOP_UP_BELOW):
            return False
        here = env.station_at(self.current_position)
        if here is None or (station_id and here.station_id != station_id):
            return False
        if env.claim_station(self.robot_id, here.station_id) is None:
            return False
        self.status = RobotState.CHARGING
        self._topping_up = True
        self.note(tick, "top_up_started", station=here.station_id,
                  level=round(self.battery_level, 1))
        return True

    def end_top_up(self, tick: int, env: PostOfficeEnvironment,
                   reason: str = "work") -> bool:
        """Unplug. Called when work arrives, or when the band is reached."""
        if not self._topping_up:
            return False
        env.release_station(self.robot_id)
        self._topping_up = False
        self.status = RobotState.IDLE
        self.note(tick, "top_up_ended", reason=reason,
                  level=round(self.battery_level, 1))
        return True

    def go_home(self, tick: int, home: Position,
                route: Sequence[Position]) -> bool:
        """
        Drift back to the parking bay, having nothing else to do.

        The lowest-priority thing a robot does: it stays available throughout,
        and any errand offered on the way simply overwrites this one.
        """
        if self.status is not RobotState.IDLE or self.current_task is not None:
            return False
        self._leg = "to_home"
        self._route = [Position.of(p) for p in route]
        self.destination = Position.of(home)
        self.status = RobotState.MOVING
        self.note(tick, "going_home", to=self.destination.as_dict())
        return True

    def set_route(self, tick: int, route: Sequence[Position]) -> bool:
        """
        A fresh route, normally from collision avoidance after a block.

        Refused while charging. Collision answers arrive a few ticks after the
        block that provoked them, and by then the robot may have arrived and
        plugged in; a robot that obeyed a stale order would walk off the charge
        point it had just claimed, still holding it, and take that point out of
        service for the rest of the run.
        """
        if self.status is RobotState.CHARGING:
            self.note(tick, "order_ignored", order="set_route", why="charging")
            return False
        self._route = [Position.of(p) for p in route]
        self._blocked_for = 0
        self._yield_to = None
        if self.status in (RobotState.BLOCKED, RobotState.WAITING):
            self.status = (RobotState.DELIVERING if self._leg == "to_dropoff"
                           else RobotState.MOVING)
        self.note(tick, "rerouted", length=len(self._route))
        return True

    def yield_to(self, tick: int, cell: Position,
                 resume: Sequence[Position] = (), hold: int = 0) -> bool:
        """
        Step out of the way, once.

        Two robots meeting head-on in a narrow doorway cannot both wait and
        cannot both go round, because there is no way round -- that is what a
        doorway is. One of them has to give up its cell.

        `resume` is the route onward from the cell it steps into, worked out by
        collision avoidance at the same time as the sidestep. Sending both
        together matters more than it looks: without it the robot has to stop,
        report, and wait four ticks for a fresh route, and in a run with a few
        hundred yields that latency is most of the fleet's working day.
        """
        if self.status in (RobotState.CHARGING, RobotState.IDLE,
                           RobotState.PICKING, RobotState.UNLOADING):
            # Stale: it has arrived, or plugged in, or has no errand left. The
            # block that provoked this order is somebody else's problem now.
            self.note(tick, "order_ignored", order="yield",
                      why=self.status.value.lower())
            return False
        self._yield_to = Position.of(cell)
        self._yield_route = [Position.of(p) for p in resume]
        self._hold = max(0, int(hold))
        self._blocked_for = 0
        self.status = RobotState.MOVING
        self.note(tick, "yielding", to=self._yield_to.as_dict(),
                  resume=len(self._yield_route))
        return True

    def step_aside(self, tick: int, cell: Position) -> bool:
        """
        Move one cell out of the way, having been asked to.

        Distinct from `yield_to`, which a robot does mid-errand. This is for a
        robot that has finished and stopped somewhere inconvenient: it has no
        route and no reason to move, and without this the corridor it happens to
        be standing in is closed until it is given work again -- which, in a
        building whose doorways are two cells wide, can take the rest of the run.
        """
        if self.status in (RobotState.CHARGING, RobotState.PICKING,
                           RobotState.UNLOADING):
            self.note(tick, "order_ignored", order="step_aside",
                      why=self.status.value.lower())
            return False
        self._yield_to = Position.of(cell)
        self._yield_route = []
        self._hold = 0
        self._blocked_for = 0
        if self.status is RobotState.IDLE:
            self.status = RobotState.MOVING
        self.note(tick, "asked_to_move", to=Position.of(cell).as_dict())
        return True

    def abort(self, tick: int, reason: str = "") -> Optional[str]:
        """
        Give up the current job. Returns the parcel id if one was being carried,
        so the caller can decide where to put it down.

        The robot is left genuinely free -- nothing held, nothing loaded. An
        abort that cleared the task but left `carrying` set would produce a
        robot that is idle, unavailable for ever, and recorded as holding a
        parcel that is lying on the floor.
        """
        task_id = self.current_task
        carried = self.carrying
        self.carrying = None
        self.load = 0
        self._stand_down()
        self.note(tick, "aborted", task_id=task_id, reason=reason,
                  carrying=carried)
        return carried

    # ------------------------------------------------------------------ state
    @property
    def battery_fraction(self) -> float:
        return self.battery_level / self.battery_capacity if self.battery_capacity else 0.0

    @property
    def is_available(self) -> bool:
        """
        Free to be given work: no errand, nothing on board, charge to spare.

        A robot on its way back to its parking bay counts as free. Parking is
        housekeeping, not work, and a fleet that had to finish parking before it
        could be useful again would spend its day walking home.
        """
        return (self.current_task is None
                and self.carrying is None
                and self.battery_level > self.low_battery
                and (self.status is RobotState.IDLE
                     or (self.status is RobotState.MOVING
                         and self._leg == "to_home")
                     # Topping up is not being busy. The robot is standing at a
                     # point it did not have to walk far for, gaining charge it
                     # can give back the instant there is work -- and a fleet
                     # that counted a top-up as out of service would idle four
                     # robots to charge batteries that were never low.
                     or (self.status is RobotState.CHARGING
                         and self._topping_up)))

    @property
    def needs_charge(self) -> bool:
        return (self.battery_level <= self.low_battery
                and self.status is not RobotState.CHARGING)

    @property
    def route_remaining(self) -> int:
        remaining = max(0, len(self._route) - 1)
        if self._via is not None and self._leg == "to_dropoff":
            # Still to pass through its waypoint: the walk after it counts.
            remaining += max(0, len(self._after_via_route) - 1)
        return remaining

    @property
    def leg(self) -> str:
        """
        Which leg of an errand the robot is walking, or `""` between errands.

        Read-only, and deliberately so: the leg is the robot's own account of
        what it is doing, and an agent that could set it would be steering the
        machine rather than instructing it. Published because the scheduler
        needs to know when a robot is on its way home without inferring it
        from what it happens to be carrying.
        """
        return self._leg

    @property
    def on_final_leg(self) -> bool:
        """
        Carrying, and walking the leg that ends at the drop.

        This is the state the scheduler waits for before arranging what comes
        next. It is a fact about the robot rather than a guess from a distance
        or a tick count, which matters because a robot that is blocked, held
        or yielding is still on its final leg and still about to be free.
        """
        return self._leg == "to_dropoff"

    # ------------------------------------------------------------------- tick
    def step(self, env: PostOfficeEnvironment, tick: int) -> List[Dict[str, Any]]:
        """
        Advance one tick and report what happened.

        The reports are the robot's only output. Nothing here writes to a task,
        a parcel's status or another agent -- design principle 2, and the reason
        this class can be unit-tested against a bare grid.
        """
        reports: List[Dict[str, Any]] = []
        self.current_zone = env.zone_at(self.current_position)

        # An errand with no leg left is an errand that ended; a robot that
        # still thinks it has one would sit out the rest of the run looking
        # busy. Checked every tick rather than trusted, because this is the
        # invariant whose violation is hardest to spot from outside.
        if not self._leg and self.carrying is None and self._yield_to is None \
                and self.status in (RobotState.IDLE, RobotState.WAITING,
                                    RobotState.BLOCKED, RobotState.MOVING,
                                    RobotState.DELIVERING) \
                and (self.current_task is not None
                     or self.status is not RobotState.IDLE):
            self._stand_down()

        if self._release_station:
            env.release_station(self.robot_id)
            self._release_station = False

        if self.status is RobotState.CHARGING:
            if self._topping_up:
                return self._top_up(env, tick, reports)
            return self._charge(env, tick, reports)

        self._drain(IDLE_COST)

        if self.battery_level <= 0.0:
            # Flat. It cannot move, but it must not go silent: a robot that
            # reports once and then says nothing for the rest of the run is
            # indistinguishable from one that is quietly working, and nobody
            # comes to rescue it.
            self.battery_level = 0.0
            self.status = RobotState.WAITING
            self._flat_for += 1
            if self._flat_for == 1:
                self.note(tick, "battery_empty")
            if self._flat_for == 1 or self._flat_for % 20 == 0:
                reports.append(self._report("battery_empty", tick,
                                            stranded_for=self._flat_for,
                                            task_id=self.current_task))
            return reports
        self._flat_for = 0

        if self.needs_charge and not self._charge_requested and self._leg != "to_charger":
            self._charge_requested = True
            self.note(tick, "battery_low", level=round(self.battery_level, 2))
            reports.append(self._report("battery_low", tick,
                                        level=round(self.battery_level, 2)))

        if self.status is RobotState.IDLE and self._yield_to is None:
            return reports
        if self.status is RobotState.IDLE:
            return self._give_way(env, tick, reports)

        if self.status is RobotState.WAITING and self._hold:
            self._hold -= 1
            if self._hold == 0 and self._route:
                self.status = (RobotState.DELIVERING if self._leg == "to_dropoff"
                               else RobotState.MOVING)
            return reports

        if self.status is RobotState.WAITING:
            # Waiting on somebody else -- a route, a charge point. Say so again
            # every few ticks: a robot that asks once and then waits for ever is
            # indistinguishable from a robot that has crashed.
            self._waited += 1
            if self._leg and self.destination is not None and self._waited % 5 == 0:
                reports.append(self._report("stalled", tick,
                                            waited=self._waited,
                                            goal=self.destination.as_dict()))
            return reports
        self._waited = 0

        if self.status is RobotState.PICKING:
            return self._finish_pick(env, tick, reports)

        if self.status is RobotState.UNLOADING:
            return self._deliver(env, tick, reports)

        # MOVING, DELIVERING or BLOCKED: try to make progress along the route
        return self._travel(env, tick, reports)

    # ---------------------------------------------------------------- travel
    def _travel(self, env, tick, reports):
        if self._yield_to is not None:
            return self._give_way(env, tick, reports)

        moved = 0
        while moved < self.speed:
            if len(self._route) <= 1:
                break
            nxt = self._route[1]
            occupant = env.occupied_by_robot(nxt, excluding=self.robot_id)
            if occupant is not None:
                self.status = RobotState.BLOCKED
                self._blocked_for += 1
                self.note(tick, "blocked", by=occupant, at=nxt.as_dict())
                # Told on the first tick and then every third. A robot that
                # phoned the routing department on every tick it was blocked
                # would fill the communication log with the same sentence and
                # make the round trip slower for everybody, itself included.
                if self._blocked_for == 1 or self._blocked_for % 3 == 0:
                    reports.append(self._report("blocked", tick,
                                                blocked_by=occupant,
                                                at=nxt.as_dict(),
                                                ticks_blocked=self._blocked_for))
                return reports
            if not env.is_free(nxt):
                self.status = RobotState.BLOCKED
                self._blocked_for += 1
                reports.append(self._report("route_invalid", tick,
                                            at=nxt.as_dict()))
                return reports

            self._route.pop(0)
            self.current_position = nxt
            env.place_robot(self.robot_id, nxt)
            self.current_zone = env.zone_at(nxt)
            self._drain(MOVE_COST)
            moved += 1
            self._blocked_for = 0
            if self.battery_level <= 0.0:
                break

        if self._blocked_for == 0 and self.status is RobotState.BLOCKED:
            self.status = RobotState.MOVING

        if moved:
            reports.append(self._report("moved", tick, cells=moved,
                                        remaining=self.route_remaining))

        if len(self._route) <= 1:
            return self._arrive(env, tick, reports)
        return reports

    def _give_way(self, env, tick, reports):
        """
        One sideways step, then stop and ask for a new route.

        The old route started from a cell the robot is no longer on, so it is
        thrown away rather than patched: a route that begins somewhere the
        robot is not is the kind of thing that produces a robot walking through
        a wall three hundred ticks later.
        """
        target = self._yield_to
        self._yield_to = None
        if env.occupied_by_robot(target, excluding=self.robot_id) or not env.is_free(target):
            self.status = RobotState.BLOCKED
            reports.append(self._report("yield_failed", tick,
                                        at=target.as_dict()))
            return reports
        env.release_station(self.robot_id)      # it is leaving; give the plug back
        self.current_position = target
        env.place_robot(self.robot_id, target)
        self.current_zone = env.zone_at(target)
        self._drain(MOVE_COST)

        resume = self._yield_route
        self._yield_route = []
        if resume and resume[0] == target:
            if self._hold:
                # Stand still for a moment before setting off again, so the
                # robot that was in the way gets clear rather than being met
                # again one cell along.
                self.status = RobotState.WAITING
                self._route = list(resume)
                self.note(tick, "holding", ticks=self._hold)
                reports.append(self._report("yielded", tick,
                                            at=target.as_dict(), resumed=True,
                                            holding=self._hold))
                return reports
            # Carry straight on: the way onward came with the order to move.
            self._route = list(resume)
            self.status = (RobotState.DELIVERING if self._leg == "to_dropoff"
                           else RobotState.MOVING)
            self.note(tick, "yielded", at=target.as_dict(), resumed=True)
            reports.append(self._report("yielded", tick, at=target.as_dict(),
                                        resumed=True))
            return reports

        self._route = []
        self.status = RobotState.WAITING
        self.note(tick, "yielded", at=target.as_dict(), resumed=False)
        reports.append(self._report("yielded", tick, at=target.as_dict(),
                                    resumed=False,
                                    goal=self.destination.as_dict()
                                    if self.destination else None))
        return reports

    # ---------------------------------------------------------------- arrival
    def _arrive(self, env, tick, reports):
        # "The route ran out" and "I am where I was sent" are not the same
        # thing. A route replaced mid-errand -- after a block, a yield, a
        # reroute -- can end somewhere else, and a robot that treats running
        # out of cells as arriving will put a parcel down in the wrong zone and
        # report it as delivered. Checked rather than assumed.
        if self.destination is not None and self.current_position != self.destination:
            self._route = []
            self.status = RobotState.WAITING
            self.note(tick, "arrived_nowhere", at=self.current_position.as_dict(),
                      expected=self.destination.as_dict())
            reports.append(self._report("stalled", tick, waited=0,
                                        goal=self.destination.as_dict(),
                                        reason="route ended short of the destination"))
            return reports

        if self._leg == "to_pickup":
            self.status = RobotState.PICKING
            self.note(tick, "at_pickup", parcel_id=self._parcel)
            reports.append(self._report("arrived_at_pickup", tick,
                                        parcel_id=self._parcel))
        elif self._leg == "to_dropoff" and self._via is not None:
            # The waypoint, not the drop: note it and walk on. No stop -- the
            # parcel stays on board and the next move is next tick's.
            passed = self._via
            self._via = None
            self._route = list(self._after_via_route)
            self._after_via_route = []
            self.destination = self._dropoff
            self.status = RobotState.DELIVERING
            self.note(tick, "passed_via", at=passed.as_dict(),
                      parcel_id=self.carrying)
            reports.append(self._report("passed_via", tick,
                                        parcel_id=self.carrying,
                                        at=passed.as_dict(),
                                        zone=(env.zone_at(passed).value
                                              if env.zone_at(passed) else None)))
            if len(self._route) <= 1 and self.current_position == self._dropoff:
                self.status = RobotState.UNLOADING
                self.note(tick, "at_dropoff", parcel_id=self.carrying)
        elif self._leg == "to_dropoff":
            # Setting a parcel down takes a tick, exactly as picking one up
            # does. It used to be free, which made every delivery a tick
            # cheaper than the collection that preceded it -- an asymmetry with
            # nothing behind it, and one that quietly flattered the fleet's
            # throughput. It also means a robot unloading occupies its cell for
            # a tick, which is the truthful version of a busy drop zone.
            self.status = RobotState.UNLOADING
            self.note(tick, "at_dropoff", parcel_id=self.carrying)
            reports.append(self._report("arrived_at_dropoff", tick,
                                        parcel_id=self.carrying))
        elif self._leg == "to_home":
            self.note(tick, "parked", at=self.current_position.as_dict())
            self._stand_down()
            reports.append(self._report("parked", tick))
        elif self._leg == "to_charger":
            # The point it is standing on, not whichever happens to be free.
            # Claiming a different one leaves the robot plugged into a socket
            # on the other side of the building, which every consistency check
            # in the system then reports as a fault.
            here = env.station_at(self.current_position)
            station = env.claim_station(
                self.robot_id, here.station_id if here is not None else None)
            if station is None:
                self.status = RobotState.WAITING
                reports.append(self._report("charging_unavailable", tick))
            else:
                self.status = RobotState.CHARGING
                self._leg = ""
                self.note(tick, "charging_started", station=station.station_id)
                reports.append(self._report("charging_started", tick,
                                            station_id=station.station_id))
        return reports

    def _finish_pick(self, env, tick, reports):
        """A pick takes one whole tick, so a busy dock is genuinely a bottleneck."""
        parcel = env.parcels.get(self._parcel or "")
        if parcel is None or parcel.position != self.current_position:
            self.note(tick, "pick_failed", parcel_id=self._parcel)
            reports.append(self._report("pick_failed", tick,
                                        parcel_id=self._parcel,
                                        reason="parcel not here"))
            self._stand_down()
            return reports

        if self.load + parcel.size.units > self.load_capacity:
            reports.append(self._report("pick_failed", tick,
                                        parcel_id=self._parcel,
                                        reason="over capacity"))
            self._stand_down()
            return reports

        env.lift_parcel(parcel.parcel_id, self.robot_id)
        self.carrying = parcel.parcel_id
        self.load += parcel.size.units
        self._drain(HANDLING_COST)
        self._leg = "to_dropoff"
        self._route = list(self._pending_dropoff_route)
        self.destination = self._via if self._via is not None else self._dropoff
        self.status = RobotState.DELIVERING
        self.note(tick, "picked", parcel_id=parcel.parcel_id)
        reports.append(self._report("picked", tick, parcel_id=parcel.parcel_id))

        # With a waypoint still to pass, a route that has already run out means
        # the waypoint is here; `_arrive` walks on from it next tick.
        if len(self._route) <= 1 and self._via is None:
            self.status = RobotState.UNLOADING
            self.note(tick, "at_dropoff", parcel_id=self.carrying)
        return reports

    def _deliver(self, env, tick, reports):
        parcel_id = self.carrying
        if parcel_id is None:
            self._stand_down()
            return reports
        env.drop_parcel(parcel_id, self.current_position)
        parcel = env.parcels.get(parcel_id)
        self.load = max(0, self.load - (parcel.size.units if parcel else 1))
        self.carrying = None
        self._drain(HANDLING_COST)
        finished = self.current_task
        zone = self._dest_zone.value if self._dest_zone else None
        self.note(tick, "delivered", parcel_id=parcel_id, task_id=finished)
        self._stand_down()
        reports.append(self._report("delivered", tick, parcel_id=parcel_id,
                                    task_id=finished, zone=zone))
        return reports

    # --------------------------------------------------------------- charging
    def _charge(self, env, tick, reports):
        station = env.station_of(self.robot_id)
        if station is None:                      # somebody took it; try again
            self.status = RobotState.WAITING
            reports.append(self._report("charging_interrupted", tick))
            return reports
        before = self.battery_level
        self.battery_level = min(self.battery_capacity,
                                 self.battery_level + station.rate)
        reports.append(self._report("charging", tick,
                                    level=round(self.battery_level, 2),
                                    gained=round(self.battery_level - before, 2)))
        if self.battery_level >= self.resume_battery:
            env.release_station(self.robot_id)
            self._stand_down()
            self._charge_requested = False
            self.note(tick, "charging_finished",
                      level=round(self.battery_level, 2))
            reports.append(self._report("charging_finished", tick,
                                        level=round(self.battery_level, 2),
                                        station_id=station.station_id))
        return reports

    def _top_up(self, env, tick, reports):
        """
        One tick of opportunistic charge.

        Deliberately not `_charge`: this robot is not on a charge errand, it has
        no task id, and it stops at the band rather than at working order. What
        the two share is the arithmetic, and that lives on the station.
        """
        station = env.station_of(self.robot_id)
        if station is None:
            self._topping_up = False
            self._stand_down()
            reports.append(self._report("charging_interrupted", tick))
            return reports
        before = self.battery_level
        self.battery_level = min(self.battery_capacity,
                                 self.battery_level + station.rate)
        reports.append(self._report("topping_up", tick,
                                    level=round(self.battery_level, 2),
                                    gained=round(self.battery_level - before, 2)))
        if self.battery_level >= TOP_UP_CEILING:
            self.end_top_up(tick, env, reason="full")
            reports.append(self._report("top_up_finished", tick,
                                        level=round(self.battery_level, 2),
                                        station_id=station.station_id))
        return reports

    # ---------------------------------------------------------------- helpers
    def _stand_down(self) -> None:
        """
        Back to idle with nothing held.

        Every path that ends an errand goes through here. Half-clearing -- a
        robot left IDLE but still holding a task id -- is how a fleet silently
        shrinks over a long run: the robot looks free in the status counts and
        is never offered work, and nothing in the log says why.
        """
        self.status = RobotState.IDLE
        self.current_task = None
        self.destination = None
        self._route = []
        self._pending_dropoff_route = []
        self._via = None
        self._after_via_route = []
        self._leg = ""
        self._parcel = None
        self._pickup = None
        self._dropoff = None
        self._dest_zone = None
        self._yield_to = None
        self._hold = 0
        self._blocked_for = 0
        self._waited = 0

    def _drain(self, amount: float) -> None:
        self.battery_level = max(0.0, self.battery_level - amount)

    def _report(self, kind: str, tick: int, **detail) -> Dict[str, Any]:
        return {
            "robot_id": self.robot_id,
            "tick": tick,
            "report": kind,
            "status": self.status.value,
            "position": self.current_position.as_dict(),
            "zone": self.current_zone.value if self.current_zone else None,
            "battery": round(self.battery_level, 2),
            "task_id": self.current_task,
            **detail,
        }

    def as_dict(self) -> dict:
        return {
            "robot_id": self.robot_id,
            "current_position": self.current_position.as_dict(),
            "current_zone": self.current_zone.value if self.current_zone else None,
            "current_task": self.current_task,
            "status": self.status.value,
            "battery_level": round(self.battery_level, 2),
            "battery_capacity": self.battery_capacity,
            "load": self.load,
            "load_capacity": self.load_capacity,
            "carrying": self.carrying,
            "destination": self.destination.as_dict() if self.destination else None,
            "speed": self.speed,
            "route_remaining": self.route_remaining,
            "task_history": [dict(h) for h in self.task_history[-25:]],
        }
