"""
The resource agent: the only expert allowed to say no.

Everything in the facility that can run out belongs to it -- battery, charge
points, shelf space -- and it owns the three sub-agents that watch them. The
scheduler proposes work; this agent decides whether the facility can actually
afford it, and a denial is a normal outcome rather than an error.

Two flows meet here.

*Clearance.* Scheduling asks "can R3 do this errand and will there be a shelf
at the far end". That is two questions for two different sub-agents, so the
agent holds the request open until both have answered and only then grants or
denies. Partial answers are never acted on -- granting a job because the
battery is fine, before finding out the shelves are full, is exactly how a
parcel ends up carried to a storage area that cannot take it.

*Charging.* Nobody asks for this. The agent watches the fleet itself, and when
a robot passes its reserve it finds it a charge point, asks routing for a way
there, and sends the robot the command. That makes it the one expert with
standing duties as well as an inbox, which is why `tick_work` is doing real
work here and is empty in the sorting agent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from ..communication.directory import AgentKind
from ..communication.events import EventCategory
from ..communication.message import Message, MessageType
from ..environment.recovery import RecoveryRequest
from ..environment.zones import Zone
from ..robots.robot import RobotState
from ..tasks.task import TaskStatus, TaskType
from .base import BaseAgent
from .brain import Answer
from .deferral import Deferral, is_pending
from .reasoning import REASONS, Trigger

#: Where an errand stands in the queue for a scarce resource. Higher is
#: further forward. Nothing is a claim of its own -- an idle robot is behind
#: every robot that is in the middle of something -- and above that the order
#: is the one the sender paid for.
_QUEUE_RANK = {"NORMAL": 1, "EXPRESS": 2, "URGENT": 3}


def _standing(errand: Optional[Dict[str, Any]], carrying: Any = "") -> tuple:
    """
    How strong a claim this robot has, as something two robots can be sorted
    by: the class of what it carries, then how close that promise is to
    breaking. A parcel with no promise recorded is the weakest claim of its
    class, not the strongest -- there is nothing to break.
    """
    if not errand:
        # Laden with something we could not look up still beats idle: the
        # parcel exists whether or not its record does.
        return (1 if carrying else 0, float("-inf"))
    rank = _QUEUE_RANK.get(str(errand.get("class", "")), 1)
    left = errand.get("ticks_to_deadline")
    return (rank, float("-inf") if left is None else -float(left))


def _describe(errand: Optional[Dict[str, Any]]) -> str:
    """The errand in words, for the line written into the log."""
    if not errand:
        return "carrying"
    return f"carrying {errand.get('class', 'a')} {errand.get('parcel_id', '')}".strip()


class ResourceAgent(BaseAgent):
    """Battery, charge points and shelves -- and the authority to refuse."""

    kind = AgentKind.EXPERT

    #: How long a stranded robot waits before the facility comes and gets it.
    #: A robot at zero cannot move, so nothing in the agent hierarchy can help
    #: it: it stays where it stopped, blocking whatever corridor it stopped in,
    #: for the rest of the run. Modelling a recovery crew is a deliberate
    #: simplification, and it is loud in the log -- `robot_recovered` is the
    #: event to count if you want to know how often the facility had to be
    #: rescued from itself.
    RECOVERY_AFTER = 30

    #: How long each stage of a charge arrangement may take before it is
    #: written off. The first two are message round trips and should be quick;
    #: "on the way" is a robot crossing the building through three doorways,
    #: which legitimately takes a long time -- timing that out early is how a
    #: robot ends up shuttling towards a charge point it is never allowed to
    #: reach, burning the charge it was going there to replace.
    STAGE_PATIENCE = {"finding station": 15, "routing": 15,
                      "on the way": 180, "charging": 10 ** 6}

    BATTERY = "SUB-BATTERY"
    CHARGING = "SUB-CHARGING"
    STORAGE = "SUB-STORAGE"
    ROUTING = "ROUTING"

    def __init__(self, agent_id: str = "RESOURCE", parent_id: str = "PLANNER",
                 **kw) -> None:
        super().__init__(agent_id, "resource management", parent_id=parent_id, **kw)
        self._waiting: Dict[str, Dict[str, Any]] = {}     # sub request -> context
        self._clearances: Dict[str, Dict[str, Any]] = {}  # job key -> answers so far
        self._charging: Dict[str, str] = {}               # robot -> stage
        self._charging_since: Dict[str, int] = {}         # robot -> tick
        self._pending_station: Dict[str, Dict[str, Any]] = {}  # robot -> station
        self._charge_task: Dict[str, str] = {}            # robot -> task id
        self._recalled: Dict[str, str] = {}               # robot -> errand recalled
        self._stranded: Dict[str, int] = {}               # robot -> flat since
        #: Robots the facility has already been asked to fetch, so the queue
        #: does not fill with the same request once a tick while the crew is
        #: on its way. Cleared when the robot moves under its own power again.
        self._asked_for: Dict[str, int] = {}
        self.recoveries = 0
        self.granted = 0
        self.denied = 0
        self.charges_arranged = 0
        self.charge_refusals = 0
        #: Opportunistic top-ups begun. Worth counting apart from
        #: `charges_arranged`: one is a robot using time it had spare,
        #: the other is a robot leaving work to go and find a plug.
        self.top_ups = 0

    # ----------------------------------------------------------------- rules
    def install_triggers(self) -> None:
        """
        When a resource question stops being a threshold.

        This agent has the most obviously routine work in the facility.
        Reporting how full the shelves are is a reading. Approving an errand
        for a robot with plenty of charge is a subtraction. Handing a free
        charge point to the only robot that wants one is a lookup. None of
        that is worth a model, and a model consulted about it every time is a
        model whose useful answers are buried.

        The three questions become trade-offs in three circumstances: the
        margin is thin enough that approving and refusing are both defensible;
        more robots want a point than there are points; the shelves are close
        enough to the ceiling that the next parcel accepted is the one that
        costs somebody else a place.
        """

        def marginal_errand(facts):
            level = float(facts.get("battery", 100) or 100)
            cost = float(facts.get("estimated_cost", 0) or 0)
            reserve = float(facts.get("reserve", 25) or 25)
            after = level - cost
            # Comfortably fine, or plainly impossible, are both rules. The
            # band in between is where the judgement is.
            if 0 <= after <= reserve:
                return Trigger(REASONS.CONFLICT,
                               f"{after:.0f}% left after the errand, against a "
                               f"{reserve:.0f}% reserve")
            return None

        def points_contested(facts):
            rivals = facts.get("rivals") or {}
            free = [o for o in (facts.get("stations") or {}) if o != "WAIT"]
            if rivals and len(rivals) + 1 > max(1, len(free)):
                return Trigger(REASONS.CONTENTION,
                               f"{len(rivals) + 1} robots want {len(free)} "
                               f"free point(s)")
            return None

        def laden_rival(facts):
            # Somebody else is carrying a promise and is lower than we are.
            level = float(facts.get("battery", 100) or 100)
            for rival in (facts.get("rivals") or {}).values():
                if rival.get("carrying") \
                        and float(rival.get("battery", 100) or 100) < level:
                    return Trigger(REASONS.CONFLICT,
                                   "a laden robot is lower than this one")
            return None

        def shelves_near_ceiling(facts):
            load = float(facts.get("load", 0.0) or 0.0)
            ceiling = float(facts.get("max_load", 0.9) or 0.9)
            if load >= ceiling - 0.15:
                return Trigger(REASONS.CONTENTION,
                               f"shelves at {load:.0%}, ceiling {ceiling:.0%}")
            return None

        def more_coming(facts):
            if float(facts.get("parcels_inbound", 0) or 0) > 5:
                return Trigger(REASONS.ENVIRONMENT,
                               f"{facts.get('parcels_inbound')} parcels still "
                               f"inbound")
            return None

        self.triggers.register("battery_sufficient", marginal_errand)
        self.triggers.register("allocate_charge_point", points_contested)
        self.triggers.register("allocate_charge_point", laden_rival)
        self.triggers.register("accept_into_storage", shelves_near_ceiling)
        self.triggers.register("accept_into_storage", more_coming)

    def install_rules(self) -> None:
        """
        The three judgements this agent makes, and the fallback under any model.

        All three are trade-offs between things that cannot all be had: a
        robot's charge against the errand waiting, a shelf against the parcels
        still coming through the door, four charge points against five robots.
        The clerks below measure each of those; weighing them is this agent's
        whole reason to exist, and it used to do none of it.
        """
        rules = self.rules()
        if rules is None:
            return

        def battery(question) -> Answer:
            """
            Can this robot finish the errand and still reach a plug after it?

            That is the question, and it used to be a different one: whether the
            robot would still be above a flat comfort reserve afterwards. With
            the estimate inflated for congestion that sent robots to charge at
            seventy percent, in the first two hundred ticks of a run, before
            long jobs they could comfortably have done -- the single thing that
            made the fleet look like it spent its day at the plugs.

            What is actually at stake is stranding. A robot needs enough left
            after the errand to walk to a charge point; beyond that, charge in
            the battery is charge doing nothing.
            """
            from post_office.robots.robot import COMMIT_BELOW

            facts = question.facts
            level = float(facts.get("battery", 0.0) or 0.0)
            needed = float(facts.get("estimated_cost", 0.0) or 0.0)
            # What it takes to reach a plug from anywhere in the building,
            # with a little in hand. Derived from the operator's reserve rather
            # than compared against it: the reserve is the level at which a
            # robot stops taking work, and the walk to a point is a fraction of
            # it. Comparing the post-errand level against the whole reserve is
            # what used to send robots away at seventy percent.
            reserve = float(facts.get("reserve", COMMIT_BELOW) or COMMIT_BELOW)
            to_a_plug = float(facts.get("walk_to_plug") or reserve * 0.4)
            after = level - needed
            if after < 0:
                return Answer("REFUSE",
                              f"{level:.0f}% left and the errand costs about "
                              f"{needed:.0f}%; it would not finish")
            if after < to_a_plug:
                return Answer("CHARGE_FIRST",
                              f"{level:.0f}% would leave {after:.0f}% after the "
                              f"errand, not enough to reach a plug")
            return Answer("APPROVE", f"{level:.0f}% is ample for {needed:.0f}%")

        def shelves(question) -> Answer:
            facts = question.facts
            load = float(facts.get("load", 0.0) or 0.0)
            ceiling = float(facts.get("max_load", 0.9) or 0.9)
            inbound = int(facts.get("parcels_inbound", 0) or 0)
            if load >= ceiling:
                return Answer("REFUSE",
                              f"shelves at {load:.0%}, ceiling {ceiling:.0%}")
            if load > ceiling - 0.15 and inbound > 5:
                return Answer("REFUSE",
                              f"{load:.0%} full with {inbound} parcels still "
                              f"inbound; keep the headroom")
            return Answer("ACCEPT", f"shelves at {load:.0%}")

        def charge_point(question) -> Answer:
            """
            Which of the free points this robot gets, or none at all.

            Four points and five robots, so this is a contest rather than a
            lookup. A robot in the middle of an errand is carrying somebody's
            promise and is worth letting past; one that is merely low and idle
            can wait for the next point to come free. Nearest wins among
            equals, because the walk is charge spent getting to the charge.

            What "somebody's promise" is worth is not the same for every
            parcel. EXPRESS and URGENT are paid for, and a contested plug that
            cannot tell them from an ordinary parcel hands back at the charge
            point what the dispatch queue just granted. So the queue here is
            ordered by the class of the errand, then by how close its promise
            is to breaking.

            Two things this deliberately does not do. It does not interrupt a
            charge already in progress -- allocation is RESOURCE's to make,
            and a robot on a plug is the simulator's business. And class never
            beats charge: a robot nearly flat keeps the point it needs even
            against an urgent rival, because yielding there is how a robot
            strands itself holding somebody else's parcel.
            """
            facts = question.facts
            options = list(question.options)
            if not options:
                return Answer(None, "nothing free")
            stations = facts.get("stations") or {}
            level = float(facts.get("battery", 100) or 100)
            rivals = facts.get("rivals") or {}

            # Somebody else needs it more: lower, and further up the queue than
            # this robot is. Yielding is a real answer here -- taking the last
            # point at 60% while a laden robot sits at 12% is how an errand is
            # abandoned half way across the floor.
            mine = _standing(facts.get("errand"), facts.get("carrying"))
            if "WAIT" in options:
                for rival_id, rival in sorted(rivals.items()):
                    theirs = _standing(rival.get("errand"),
                                       rival.get("carrying"))
                    if theirs <= mine:
                        continue
                    if float(rival.get("battery", 100) or 100) >= level - 10:
                        continue                  # ahead of us, but not short
                    return Answer("WAIT",
                                  f"{rival_id} is at "
                                  f"{float(rival.get('battery', 0)):.0f}% "
                                  f"and {_describe(rival.get('errand'))}; "
                                  f"it needs the point more")

            points = [o for o in options if o != "WAIT"]
            if not points:
                return Answer("WAIT", "no point free to take")
            best = min(points,
                       key=lambda s: (float((stations.get(s) or {})
                                            .get("distance", 10 ** 6) or 10 ** 6),
                                      s))
            walk = (stations.get(best) or {}).get("distance")
            return Answer(best, f"nearest free point, {walk} cells away")

        rules.register("battery_sufficient", battery)
        rules.register("accept_into_storage", shelves)
        rules.register("allocate_charge_point", charge_point)

    # --------------------------------------------------------------- inbound
    def handle(self, message: Message) -> None:
        if message.message_type is MessageType.RESOURCE_REQUEST:
            self._clearance_request(message)
        elif message.message_type is MessageType.SUBTASK_RESULT:
            self._sub_result(message)
        elif message.message_type is MessageType.ROUTE_RESPONSE:
            self._route_for_charge(message)
        elif message.message_type in (MessageType.ROBOT_REPORT,
                                      MessageType.CHARGE_REQUEST):
            self._robot_report(message)

    # ------------------------------------------------------------- clearance
    def _clearance_request(self, message: Message) -> None:
        content = message.content
        if content.get("operation") == "release_storage":
            # An attempt was abandoned after its shelf had been reserved. The
            # shelf goes back, or storage loses a slot every time that happens.
            self.send(self.STORAGE, MessageType.SUBTASK_REQUEST,
                      {"operation": "release_storage",
                       "parcel_id": content.get("parcel_id")},
                      correlation_id=message.correlation_id)
            return

        key = content.get("task_id") or message.message_id
        destination = content.get("destination")
        needs_shelf = destination == Zone.TEMPORARY_STORAGE.value

        self._clearances[key] = {
            "reply_to": message.sender,
            "request_id": message.message_id,
            "correlation_id": message.correlation_id,
            "task_id": content.get("task_id"),
            "parcel_id": content.get("parcel_id"),
            "robot_id": content.get("robot_id"),
            "destination": destination,
            "outstanding": 2 if needs_shelf else 1,
            "battery": None,
            "storage": None if needs_shelf else True,
        }

        self._ask(self.BATTERY, key,
                  {"operation": "battery_check",
                   "robot_id": content.get("robot_id"),
                   "route_length": content.get("route_length", 0),
                   "correlation_id": message.correlation_id},
                  message.correlation_id)
        if needs_shelf:
            self._ask(self.STORAGE, key,
                      {"operation": "claim_storage",
                       "parcel_id": content.get("parcel_id"),
                       "correlation_id": message.correlation_id},
                      message.correlation_id)

    def _ask(self, sub_agent: str, key: str, content: Dict[str, Any],
             correlation_id: str) -> None:
        sent = self.send(sub_agent, MessageType.SUBTASK_REQUEST, content,
                         correlation_id=correlation_id)
        if sent is not None:
            self._waiting[sent.message_id] = {"key": key, "sub_agent": sub_agent}

    def _maybe_answer(self, key: str) -> None:
        job = self._clearances.get(key)
        if job is None or job["outstanding"] > 0:
            return
        self._clearances.pop(key, None)

        battery = job["battery"] or {}
        verdict = battery.get("verdict", "REFUSE")
        shelf_ok = bool(job["storage"])

        if verdict == "APPROVE" and shelf_ok:
            self.granted += 1
            self.send(job["reply_to"], MessageType.RESOURCE_GRANT,
                      {"task_id": job["task_id"], "robot_id": job["robot_id"],
                       "parcel_id": job["parcel_id"],
                       "battery": battery.get("battery"),
                       "estimated_cost": battery.get("estimated_cost")},
                      correlation_id=job["correlation_id"],
                      in_reply_to=job["request_id"],
                      text=f"{job['robot_id']} cleared for {job['task_id']}.")
            return

        self.denied += 1
        if shelf_ok and job["destination"] == Zone.TEMPORARY_STORAGE.value \
                and job.get("parcel_id"):
            # The shelf sub-agent reserved a slot before the battery sub-agent
            # answered. This errand is not happening, so the slot goes back.
            self.send(self.STORAGE, MessageType.SUBTASK_REQUEST,
                      {"operation": "release_storage",
                       "parcel_id": job["parcel_id"]},
                      correlation_id=job["correlation_id"])
        reason = ("shelves full" if not shelf_ok
                  else battery.get("reason", "insufficient charge"))
        self.send(job["reply_to"], MessageType.RESOURCE_DENIAL,
                  {"task_id": job["task_id"], "robot_id": job["robot_id"],
                   "parcel_id": job["parcel_id"], "verdict": verdict,
                   "cause": "storage" if not shelf_ok else "battery",
                   "reason": reason},
                  correlation_id=job["correlation_id"],
                  in_reply_to=job["request_id"],
                  text=f"{job['task_id']} refused: {reason}")

        if verdict == "CHARGE_FIRST" and job["robot_id"]:
            self._arrange_charge(job["robot_id"], job["correlation_id"])

    # ------------------------------------------------------------- sub-agents
    def _sub_result(self, message: Message) -> None:
        context = self._waiting.pop(message.in_reply_to or "", None)
        if context is None:
            return
        content = message.content
        operation = content.get("operation", "")
        key = context["key"]

        if operation == "battery_check":
            job = self._clearances.get(key)
            if job is not None:
                if content.get("ok"):
                    # The clerk costed the errand; whether the robot goes is
                    # this agent's call.
                    answer = self.decide(
                        "battery_sufficient",
                        f"Robot {content.get('robot_id')} has "
                        f"{content.get('battery')}% and is being offered an "
                        f"errand costing about "
                        f"{content.get('estimated_cost')}%. Approve it?",
                        options=("APPROVE", "CHARGE_FIRST", "REFUSE"),
                        correlation_id=context.get("correlation_id", "")
                        or content.get("robot_id", ""),
                        robot=content.get("robot_id", ""),
                        battery=content.get("battery", 0),
                        route_length=content.get("route_length", 0),
                        estimated_cost=content.get("estimated_cost", 0),
                        reserve=content.get("reserve", 25.0),
                        deferral=self._clearance_deferral(key, content),
                    )
                    if is_pending(answer):
                        # The clearance stays open and the scheduler goes on
                        # waiting for it, exactly as it waits for any reply.
                        return
                    self._battery_verdict(key, content, answer)
                    return
                content = {**content, "verdict": "REFUSE"}
                job["battery"] = content
                job["outstanding"] -= 1
                self._maybe_answer(key)
            return

        if operation == "claim_storage":
            job = self._clearances.get(key)
            if job is not None:
                job["storage"] = bool(content.get("ok"))
                job["outstanding"] -= 1
                self._maybe_answer(key)
            return

        if operation == "request_station":
            robot_id = content.get("robot_id", "")
            if not content.get("ok"):
                self.charge_refusals += 1
                self._forget_charge(robot_id, "no charge point was free")
                self.world.logger.emit(
                    EventCategory.RESOURCE, "charge_unavailable", tick=self.tick,
                    actor=self.agent_id, target=robot_id,
                    reason=content.get("reason", ""))
                return
            robot = self.world.fleet.get(robot_id)
            if robot is None:
                return
            # Four points, five robots. The clerk measured the walk to each
            # free point and who else is queueing; which robot gets one, and
            # whether this one stands down for a rival that needs it more, is
            # the trade-off this agent is here to make.
            stations = {s["station_id"]: s for s in content.get("stations", ())}
            if not stations:
                return
            options = sorted(stations) + (["WAIT"] if content.get("rivals")
                                          else [])
            answer = self.decide(
                "allocate_charge_point",
                f"Robot {robot_id} is at {content.get('battery')}% and wants a "
                f"charge point. {content.get('free')} of "
                f"{content.get('points')} are free. Which one, or should it "
                "wait?",
                options=tuple(options),
                correlation_id=robot_id,
                battery=content.get("battery", 0),
                carrying=content.get("carrying", ""),
                errand=content.get("errand"),
                stations=stations,
                rivals=content.get("rivals") or {},
                deferral=self._charge_deferral(robot_id, content, stations,
                                               options),
            )
            if is_pending(answer):
                # The arrangement stays at "finding station": the robot is not
                # sent anywhere until the model has picked a point.
                return
            self._charge_point_chosen(robot_id, content, stations, options,
                                      answer)
            return

        if operation == "accept_into_storage":
            answer = self.decide(
                "accept_into_storage",
                "Should more parcels be routed into temporary storage right "
                "now?",
                options=("ACCEPT", "REFUSE"),
                correlation_id=context.get("correlation_id", ""),
                load=content.get("load", 0.0),
                used=content.get("used", 0),
                capacity=content.get("capacity", 0),
                max_load=content.get("max_load", 0.9),
                parcels_inbound=content.get("parcels_inbound", 0),
                deferral=Deferral(key="storage",
                                  apply=lambda answer: self._storage_verdict(
                                      content, answer)),
            )
            if is_pending(answer):
                return
            self._storage_verdict(content, answer)

    # ------------------------------------------ decisions that wait on a model
    def _battery_verdict(self, key: str, content: Dict[str, Any],
                         answer: Answer) -> None:
        job = self._clearances.get(key)
        if job is None:
            return
        job["battery"] = {**content, "verdict": answer.choice,
                          "reason": answer.reason, "source": answer.source}
        job["outstanding"] -= 1
        self._maybe_answer(key)

    def _clearance_deferral(self, key: str, content: Dict[str, Any]) -> Deferral:
        """
        Finishing a `battery_sufficient` the model answers after the tick.

        Applicable while the clearance is still open and the robot is still
        the one the errand was assigned to. The scheduler gives up on a
        dispatch whose clearance does not come back in time; an answer to a
        dispatch that is gone would clear an errand nobody is running.
        """
        def still_valid(answer: Answer) -> str:
            job = self._clearances.get(key)
            if job is None:
                return "the clearance was closed while the model was deciding"
            task = self.world.tasks.get(job.get("task_id") or "")
            if task is None or task.assigned_robot != job.get("robot_id") \
                    or not task.is_open:
                return f"{job.get('task_id')} is no longer {job.get('robot_id')}'s"
            return ""

        def reevaluate(why: str) -> None:
            job = self._clearances.get(key)
            task = self.world.tasks.get((job or {}).get("task_id") or "")
            if job is None:
                return
            if task is None or task.assigned_robot != job.get("robot_id") \
                    or not task.is_open:
                self._clearances.pop(key, None)     # nobody is waiting on it
                return
            self._ask(self.BATTERY, key,
                      {"operation": "battery_check",
                       "robot_id": job.get("robot_id"),
                       "route_length": content.get("route_length", 0)},
                      job.get("correlation_id", ""))

        return Deferral(key=key,
                        apply=lambda answer: self._battery_verdict(key, content,
                                                                   answer),
                        still_valid=still_valid, reevaluate=reevaluate)

    def _charge_deferral(self, robot_id: str, content: Dict[str, Any],
                         stations: Dict[str, Any], options: List[str]) -> Deferral:
        """
        Finishing an `allocate_charge_point` the model answers after the tick.

        Applicable while this agent is still finding the robot a point and the
        robot is still idle and empty-handed; a point that has been taken in
        the meantime is the gate's to refuse. Otherwise the next time the
        robot needs charge, the arrangement starts again from the floor as it
        is then.
        """
        def still_valid(answer: Answer) -> str:
            if self._charging.get(robot_id) != "finding station":
                return f"{robot_id}'s charge is no longer being arranged"
            robot = self.world.fleet.get(robot_id)
            if robot is None or robot.current_task is not None \
                    or robot.carrying is not None:
                return f"{robot_id} is busy now"
            return ""

        def reevaluate(why: str) -> None:
            if self._charging.get(robot_id) == "finding station":
                self._forget_charge(robot_id, why)

        return Deferral(key=robot_id,
                        apply=lambda answer: self._charge_point_chosen(
                            robot_id, content, stations, options, answer),
                        still_valid=still_valid, reevaluate=reevaluate)

    def _storage_verdict(self, content: Dict[str, Any], answer: Answer) -> None:
        self.world.logger.emit(
            EventCategory.RESOURCE, "storage_policy", tick=self.tick,
            actor=self.agent_id, verdict=answer.choice,
            load=content.get("load"), reason=answer.reason,
            source=answer.source)

    def _charge_point_chosen(self, robot_id: str, content: Dict[str, Any],
                             stations: Dict[str, Any], options: List[str],
                             answer: Answer) -> None:
        """Send a robot to the point an `allocate_charge_point` answer names."""
        robot = self.world.fleet.get(robot_id)
        if robot is None:
            return
        choice = answer.choice if answer.choice in options else sorted(stations)[0]
        if choice == "WAIT":
            self.charge_refusals += 1
            self._forget_charge(robot_id, answer.reason)
            self.world.logger.emit(
                EventCategory.RESOURCE, "charge_deferred", tick=self.tick,
                actor=self.agent_id, target=robot_id,
                reason=answer.reason, source=answer.source)
            return
        station = stations[choice]
        self._charging[robot_id] = "routing"
        self._charging_since[robot_id] = self.tick
        self._pending_station[robot_id] = station
        self.send(self.ROUTING, MessageType.ROUTE_REQUEST,
                  {"operation": "plan_route",
                   "robot_id": robot_id,
                   "start": robot.current_position.as_dict(),
                   "goal": station["position"],
                   "purpose": "charge"},
                  correlation_id=robot_id,
                  text=f"Route {robot_id} to {station['station_id']}.")

    # --------------------------------------------------------------- charging
    def _arrange_charge(self, robot_id: str, correlation_id: str = "") -> None:
        """
        Start getting a robot to a charge point -- but only once it is free.

        A robot half way through an errand is not sent to charge. Diverting it
        would strand the parcel it is carrying and leave the scheduler holding
        a job that will never finish; the robot will be idle within a leg or
        two, and the battery sub-agent already refuses to give it another
        errand in the meantime.
        """
        if self._charging.get(robot_id):
            return
        robot = self.world.fleet.get(robot_id)
        if robot is None or robot.status.value == "CHARGING":
            return
        if robot.current_task is not None or robot.carrying is not None:
            return
        self._charging[robot_id] = "finding station"
        self._charging_since[robot_id] = self.tick
        self._ask(self.CHARGING, f"charge:{robot_id}",
                  {"operation": "request_station", "robot_id": robot_id},
                  correlation_id or robot_id)

    def _recover_stranded(self) -> None:
        """
        Notice robots that have run flat, and ask the facility to fetch them.

        Ask. This method used to do the fetching: it set the robot's position
        to a charge point and its battery to full, which is three things an
        agent may not do -- move a robot, write its physical state, and create
        charge out of nothing. The last one also quietly made stranding free,
        and a fleet that can strand itself at no cost will do it under load,
        which is exactly the behaviour worth being able to see.

        What is left here is what an agent legitimately owns: watching,
        deciding that the facility should intervene, releasing the parcel the
        robot was holding so somebody else can be sent for it, and issuing a
        structured request. Whether the request can be honoured -- whether a
        charge point is free, how long the crew takes -- belongs to the
        simulation engine, which may refuse it.
        """
        for robot in self.world.fleet.all():
            if robot.battery_level > 0.0:
                self._stranded.pop(robot.robot_id, None)
                self._asked_for.pop(robot.robot_id, None)
                continue
            since = self._stranded.setdefault(robot.robot_id, self.tick)
            if self.tick - since < self.RECOVERY_AFTER:
                continue
            if self._asked_for.get(robot.robot_id):
                continue                       # already asked; the crew is coming
            self._forget_charge(robot.robot_id, "stranded")
            # The parcel is the one thing here the agent may still settle. It
            # is on a robot that is not going anywhere, and leaving it there
            # is a promise nobody is keeping; on the floor, the scheduler can
            # send somebody for it.
            carried = robot.abort(self.tick, "stranded")
            if carried:
                self.world.env.drop_parcel(carried, robot.current_position)
            request = RecoveryRequest(
                action="REQUEST_RECOVERY", robot_id=robot.robot_id,
                requested_by=self.agent_id, tick=self.tick,
                # A robot can run flat in a corridor, which belongs to no
                # zone at all -- and a corridor is the worst place for it to
                # stop, so the one case the message most needs to describe is
                # the one that used to crash on `None.value`.
                reason=f"flat for {self.tick - since} ticks in "
                       f"{robot.current_zone.value if robot.current_zone else 'a corridor'}")
            self.world.env.recovery_requests.append(request)
            self._asked_for[robot.robot_id] = self.tick
            self.world.logger.emit(
                EventCategory.RESOURCE, "recovery_requested", tick=self.tick,
                actor=self.agent_id, target=robot.robot_id,
                stranded_for=self.tick - since, parcel_id=carried,
                reason=request.reason, action=request.action)
            self.recoveries += 1

    def _forget_charge(self, robot_id: str, outcome: str = "",
                       **detail) -> None:
        """
        Drop an arrangement, and close the task that went with it.

        Without closing it the task sits ASSIGNED for the rest of the run. A
        dozen of those and the task counts -- which are what a monitor will
        read -- say the facility is busier than it is.
        """
        self._charging.pop(robot_id, None)
        self._charging_since.pop(robot_id, None)
        self._pending_station.pop(robot_id, None)
        task_id = self._charge_task.pop(robot_id, "")
        task = self.world.tasks.get(task_id) if task_id else None
        if task is None or not task.is_open:
            return
        if outcome == "completed":
            if task.status is TaskStatus.ASSIGNED:
                task.start(self.tick, self.agent_id)
            task.complete(self.tick, self.agent_id, **detail)
            self.world.tasks.record_transition(task, self.tick, "task_completed",
                                               actor=self.agent_id)
        else:
            task.cancel(self.tick, self.agent_id,
                        reason=outcome or "charge arrangement dropped")
            self.world.tasks.record_transition(task, self.tick, "task_cancelled",
                                               actor=self.agent_id,
                                               reason=outcome)

    def _route_for_charge(self, message: Message) -> None:
        content = message.content
        robot_id = content.get("robot_id", "")
        station = self._pending_station.pop(robot_id, None)
        if station is None or not content.get("ok"):
            self._forget_charge(robot_id, "no route to a charge point")
            return
        task = self.world.tasks.create(
            TaskType.CHARGE, self.tick, self.agent_id,
            source=None, destination=Zone.CHARGING,
            station_id=station["station_id"], robot_id=robot_id)
        task.assign(self.agent_id, self.tick, self.agent_id, robot_id=robot_id)
        self.charges_arranged += 1
        self._charge_task[robot_id] = task.task_id
        self._charging[robot_id] = "on the way"
        self._charging_since[robot_id] = self.tick
        self.send(robot_id, MessageType.ROBOT_COMMAND,
                  {"operation": "charge", "task_id": task.task_id,
                   "station_id": station["station_id"],
                   "position": station["position"],
                   "route": content.get("route", [])},
                  correlation_id=robot_id,
                  text=f"{robot_id}: go and charge at {station['station_id']}.")

    def _robot_report(self, message: Message) -> None:
        content = message.content
        report = content.get("report", "")
        robot_id = content.get("robot_id", message.sender)

        if report in ("battery_low", "battery_empty"):
            self._arrange_charge(robot_id, message.correlation_id)
        elif report == "charging_started":
            self._charging[robot_id] = "charging"
            self._charging_since[robot_id] = self.tick
        elif report == "charging_finished":
            self._forget_charge(robot_id, "completed", level=content.get("level"))
        elif report == "charging_interrupted":
            self._forget_charge(robot_id, "charging was interrupted")
        elif report == "charging_unavailable":
            self.charge_refusals += 1
            self._forget_charge(robot_id, "no charge point was free")
        elif report == "charge_declined":
            # The robot was still on an errand. Not a failure -- it will be free
            # shortly, and `tick_work` will offer it a point again then.
            self._forget_charge(robot_id, "robot was busy")

        self.world.logger.emit(
            EventCategory.BATTERY, report, tick=self.tick, actor=robot_id,
            target=self.agent_id, correlation_id=message.correlation_id,
            level=content.get("level", content.get("battery")))

    # ------------------------------------------------------------ own duties
    def tick_work(self) -> None:
        # An arrangement that has not become an actual charge within thirty
        # ticks has lost a message. Forget it and start again, rather than
        # leaving a robot marked as "being dealt with" for the rest of the run.
        for robot_id, since in list(self._charging_since.items()):
            robot = self.world.fleet.get(robot_id)
            if robot is None:
                continue
            if robot.status.value == "CHARGING":
                continue
            if self.tick - since > self.STAGE_PATIENCE.get(
                    self._charging.get(robot_id, ""), 30):
                self.world.logger.emit(
                    EventCategory.RESOURCE, "charge_arrangement_expired",
                    tick=self.tick, actor=self.agent_id, target=robot_id,
                    stage=self._charging.get(robot_id, ""), waited=self.tick - since)
                self._forget_charge(robot_id, "arrangement expired")

        # A charge point whose occupant is not standing on it and not charging
        # is a point out of service. Four points and five robots means one lost
        # plug is a quarter of the facility's charging capacity, and a fleet
        # that cannot charge dies quietly over a few thousand ticks.
        for station in sorted(self.world.env.stations.values(),
                              key=lambda s: s.station_id):
            occupant = station.occupant
            if not occupant:
                continue
            robot = self.world.fleet.get(occupant)
            if robot is None or robot.current_position != station.position \
                    or robot.status.value != "CHARGING":
                self.world.env.release_station(occupant)
                self.world.logger.emit(
                    EventCategory.RESOURCE, "charge_point_reclaimed",
                    tick=self.tick, actor=self.agent_id,
                    target=occupant, station_id=station.station_id,
                    robot_status=robot.status.value if robot else "gone")
                self._forget_charge(occupant, "left the charge point")

        self._recover_stranded()

        for robot in self.world.fleet.needing_charge():
            if robot.robot_id in self._charging:
                continue
            if robot.current_task is not None and robot.carrying is None:
                # Under reserve, empty-handed, and still chasing an errand it
                # may not have the charge to finish. Ask the scheduler to take
                # the errand back; a robot that keeps going in this state is
                # how a fleet loses one robot at a time to a flat battery.
                if self._recalled.get(robot.robot_id) != robot.current_task:
                    self._recalled[robot.robot_id] = robot.current_task
                    self.send("SCHEDULING", MessageType.ALERT,
                              {"operation": "recall_robot",
                               "robot_id": robot.robot_id,
                               "task_id": robot.current_task,
                               "battery": round(robot.battery_level, 1),
                               "reason": "below reserve and empty-handed"},
                              correlation_id=robot.robot_id,
                              text=(f"{robot.robot_id} is at "
                                    f"{robot.battery_level:.0f}% -- take its "
                                    f"errand back so it can charge."))
                continue
            self._arrange_charge(robot.robot_id)

        self._offer_top_ups()

        # A periodic look at the shelves, so the storage policy is re-judged as
        # the load changes rather than once at the start of the run.
        if self.tick % 25 == 0:
            self._ask(self.STORAGE, "storage-policy",
                      {"operation": "accept_into_storage"}, "storage")

    # ------------------------------------------------------- opportunistic
    def _offer_top_ups(self) -> None:
        """
        Let an idle robot standing on a free plug take some charge.

        The cheapest charge in the building, and the reason the fleet no longer
        spends its day walking to plugs: a robot parked on a point was going to
        stand there anyway, so the charge costs nothing in travel and it gives
        the plug back the moment it is given work.

        Deliberately not a judgement and deliberately not a trip. There is
        nothing to weigh -- the robot is idle, the point is free and under its
        nose -- and a robot that had to be routed to a point would be making a
        dedicated charge under another name.

        The one thing worth deciding here is who gives way: a robot topping up
        is holding a point that a genuinely low robot may need, and four points
        against five robots means that happens. A topper yields.
        """
        env, fleet = self.world.env, self.world.fleet
        low = [r for r in fleet.needing_charge()
               if not getattr(r, "_topping_up", False)]
        if low and not env.free_stations():
            # Somebody has to give up a plug, and it is the robot that only
            # wanted a top-up: it can work, and the one waiting cannot.
            for robot in fleet.all():
                if not getattr(robot, "_topping_up", False):
                    continue
                robot.end_top_up(self.tick, env, reason="yielded")
                self.world.logger.emit(
                    EventCategory.RESOURCE, "top_up_yielded", tick=self.tick,
                    actor=self.agent_id, target=robot.robot_id,
                    level=round(robot.battery_level, 1),
                    waiting=low[0].robot_id)
                break

        for robot in fleet.all():
            if not robot.begin_top_up(self.tick, env):
                continue
            self.top_ups += 1
            self.world.logger.emit(
                EventCategory.RESOURCE, "top_up_started", tick=self.tick,
                actor=self.agent_id, target=robot.robot_id,
                level=round(robot.battery_level, 1))

    # ----------------------------------------------------------------- state
    def state(self) -> Dict[str, Any]:
        return {
            "granted": self.granted,
            "denied": self.denied,
            "charges_arranged": self.charges_arranged,
            "charge_refusals": self.charge_refusals,
            "recoveries": self.recoveries,
            "open_clearances": len(self._clearances),
            "charging": dict(sorted(self._charging.items())),
            "storage": self.world.env.storage.as_dict() if self.world else {},
            "subagents": [self.BATTERY, self.CHARGING, self.STORAGE],
        }
