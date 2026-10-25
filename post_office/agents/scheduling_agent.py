"""
The scheduling agent: decides what happens next, and who does it.

This is where the dependencies in the spec become visible as a chain rather
than as a diagram. Getting one parcel moved takes four agents and two
sub-agents, in this order, each step waiting on the last:

    SUB-QUEUE       which job is next?
    SUB-ASSIGNMENT  which free robot should take it?
    ROUTING     a route for that robot -- which asks SUB-ROUTE
    RESOURCE    is there charge for it, and a shelf at the far end?
                -- which asks SUB-BATTERY and SUB-STORAGE
    robot       here is the errand

Each arrow is a message and each message costs a tick, so dispatching a parcel
has a real coordination cost. It could all have been one function call. It is
not, because the point of the prototype is to study what happens when that
chain is under strain, and a chain you cannot see cannot be strained.

A robot picked in step two is reserved until step five resolves, so two jobs
cannot be handed to the same robot while the clearance for the first is still
in flight.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from ..communication.directory import AgentKind
from ..communication.events import EventCategory
from ..communication.message import Message, MessageType
from ..environment.grid import Position
from ..environment.parcels import ParcelStatus
from ..environment.zones import Zone
from ..tasks.task import TaskStatus, TaskType
from .assignment_metrics import AssignmentLog
from .base import BaseAgent
from .brain import Answer
from .deferral import Deferral, is_pending
from .reasoning import REASONS, Trigger

#: The life of a *prepared* errand, before it is anybody's current errand.
#:
#: Four words rather than one boolean, because "queued" was being asked to
#: mean two different things: parked behind a robot, and ready to be carried
#: out. A parked errand whose route has not come back yet is neither, and
#: handing one of those to a robot sends it off with no path and no clearance
#: -- which is exactly what happened before these states existed.
#:
#:   QUEUED     arranged and parked; route and clearance still outstanding
#:   VALIDATED  RESOURCE has cleared it; the route has not arrived
#:   READY      cleared and routed; nothing outstanding but the robot
#:   PROMOTED   the handover checks passed; the command goes out now
#:
#: There is no EXECUTING member: an errand that is executing is an ordinary
#: live dispatch with `stage == "under way"`, and its preparation is over.
QUEUED = "QUEUED"
VALIDATED = "VALIDATED"
READY = "READY"
PROMOTED = "PROMOTED"

#: Which parcel status a delivery into each zone produces.
#:
#: A parcel carried to the dispatch zone is `AWAITING_DISPATCH`, not
#: `DISPATCHED`: the robot's job is finished but the facility's is not, and the
#: departure gate is what decides whether it goes now. Before there was a gate
#: this said `DISPATCHED` and the scheduler removed the parcel from the
#: building on the spot, which made the back door a threshold rather than a
#: door -- nothing could be checked, recorded or held, because the parcel
#: ceased to exist in the same tick it arrived.
ARRIVAL_STATUS = {
    Zone.SORTING: ParcelStatus.SORTED,
    Zone.TEMPORARY_STORAGE: ParcelStatus.STORED,
    Zone.DISPATCH: ParcelStatus.AWAITING_DISPATCH,
}


class SchedulingAgent(BaseAgent):
    """Matches work to robots, and shepherds each job to its end."""

    kind = AgentKind.EXPERT

    QUEUE_SUB = "SUB-QUEUE"
    DEADLINE_SUB = "SUB-DEADLINE"
    ASSIGNMENT = "SUB-ASSIGNMENT"
    ROUTING = "ROUTING"
    RESOURCE = "RESOURCE"

    #: How often to ask the deadline monitor. Every tick would be noise.
    DEADLINE_EVERY = 15

    #: How long a dispatch may sit half-arranged before it is given up.
    #: Routing and clearance together take about nine ticks; anything still
    #: unresolved after thirty has lost a message somewhere, and the robot it
    #: is holding is worth more than the attempt.
    DISPATCH_TIMEOUT = 30

    #: And how long an errand may run before the same conclusion is drawn.
    ERRAND_TIMEOUT = 140

    #: How close to its drop a robot must be before its next errand is
    #: arranged. The chain -- queue, robot, route, clearance, command -- takes
    #: about six ticks, so six cells of remaining walk is the lead that has
    #: the command waiting when the robot lands rather than starting then.
    #: Longer would arrange errands against a future that has more time to
    #: change; shorter would not cover the handshake.
    FINISHING_WITHIN = 6

    #: How long a parked errand may wait for its robot before it is given up.
    #: Generous: the robot is working, and the thing that usually ends this
    #: wait is the delivery it is queued behind.
    QUEUE_PATIENCE = 120

    #: Ticks after the last model decision was out during which the timers
    #: still allow for it (`_model_allowance`): the answer's reply is a
    #: message or two away from here when the model has finished.
    MODEL_ANSWER_TRAVEL = 5

    def __init__(self, agent_id: str = "SCHEDULING", parent_id: str = "PLANNER",
                 **kw) -> None:
        super().__init__(agent_id, "scheduling", parent_id=parent_id, **kw)
        self._waiting: Dict[str, Dict[str, Any]] = {}     # sub request -> context
        self._dispatch: Dict[str, Dict[str, Any]] = {}    # task id -> progress
        self._reserved: Set[str] = set()                  # robots held mid-dispatch
        self._promoted: Set[str] = set()                  # tasks the monitor flagged
        #: The assignment conversations open right now, by the id of the
        #: message that started each one. This was a single boolean, and the
        #: boolean was the throughput ceiling of the whole building: while one
        #: "what should I start next" question was outstanding, nothing else
        #: began -- no route, no clearance, no command to a robot. The chain
        #: takes about eight ticks, so the facility started one errand every
        #: nine however many robots were standing idle. Measured over 900
        #: ticks of the busy preset: work ready and a robot idle on 75% of
        #: them, and 109 ticks between a task being created and being given to
        #: anybody.
        self._asking: Dict[str, int] = {}                 # message id -> tick
        #: Tasks a conversation has picked but which are not yet dispatches.
        #: Without this the concurrency above buys nothing: every open
        #: conversation is shown the same head of the queue, they all name the
        #: same task and the same nearest robot, and every one but the first
        #: aborts at the reservation check -- measured as no change at all in
        #: throughput, which is how this was found.
        self._claiming: Set[str] = set()
        #: A `choose_next_task` the model is deciding, by conversation: the
        #: shortlist it was shown, held in `_claiming` until the answer is
        #: applied or rejected, so another conversation cannot take those tasks
        #: from under it (live runs only; see `_next_task_deferral`).
        self._held: Dict[str, Set[str]] = {}
        #: Robots that already have their *next* errand arranged and parked.
        #: One each, at most: a second would be a robot two jobs deep with
        #: nothing holding the order, and the one-parcel model has no way to
        #: express that.
        self._queued: Dict[str, str] = {}                 # robot id -> task id

        #: When each stage of each errand happened. Not for the simulation's
        #: benefit -- nothing reads it -- but because the claim that preparing
        #: ahead removes idle ticks is a measurable claim, and measuring it
        #: needs the timings of the run that made it.
        self.assignments = AssignmentLog()

        self._home: Dict[str, Any] = {}
        self.dispatched = 0
        self.completed = 0
        self.denials = 0

    # ----------------------------------------------------------------- rules
    def install_triggers(self) -> None:
        """
        When an assignment stops being the obvious one.

        Two decisions, and both are routine in the same circumstance: there is
        only one sensible answer. One task ready, or one robot able to take
        it, and there is nothing to weigh. Keeping an assignment that still
        satisfies its constraints is likewise not a decision.

        They become decisions when several things want the same robot, when
        promises are close enough together that ordering them matters, or when
        nothing is able to take the work at all -- that last one especially,
        because the answer then is about what to do instead, which no ranking
        rule contains.
        """

        def competing_tasks(facts):
            slack = facts.get("slack") or {}
            if len(slack) > 1:
                tightest = sorted(float(v) for v in slack.values())[:2]
                if len(tightest) == 2 and abs(tightest[0] - tightest[1]) < 60:
                    return Trigger(REASONS.CONFLICT,
                                   f"two promises within "
                                   f"{abs(tightest[0] - tightest[1]):.0f} ticks")
            return None

        def already_late(facts):
            slack = facts.get("slack") or {}
            overdue = [k for k, v in slack.items() if float(v) < 0]
            if overdue:
                return Trigger(REASONS.DEADLINE,
                               f"{len(overdue)} task(s) past their promise")
            return None

        def promoted_work(facts):
            if facts.get("promoted"):
                return Trigger(REASONS.REPLAN,
                               f"{len(facts['promoted'])} task(s) promoted")
            return None

        def equally_placed(facts):
            """
            Two able robots within two cells of each other: noted, not escalated.

            This used to say the rule could not separate them, on the belief
            that the rule's tie-break was the walk. It is not: `which_robot`
            ranks able robots by distance, then charge, then robot id when the
            job is urgent, and otherwise by charge among those within six
            cells of the nearest, then robot id -- so a tie on the walk always
            has one answer, the same one every time it is asked. Sending it to the model bought
            nothing but a different robot on each call (seed 1, 1,000 ticks of
            Normal on a stand-in model: 52 model calls, every one of them this
            condition). It stays as recorded pressure (`noted`); the cases the
            rule really cannot decide -- nobody able to finish -- are
            `nobody_able`'s.
            """
            about = facts.get("robots") or {}
            able = list(facts.get("able") or [])
            if len(able) < 2:
                return None
            walks = sorted(float((about.get(r) or {}).get("distance", 10 ** 6)
                                 or 10 ** 6) for r in able)
            if walks[1] - walks[0] <= 2:
                # With no model behind this agent the record is left as it
                # was (insufficient, answered by the rule): rules-only runs,
                # the frozen Phase 7 run among them, log exactly as before.
                return Trigger(REASONS.CONTENTION,
                               f"two robots within {walks[1] - walks[0]:.0f} "
                               f"cells of each other", rule_sufficient=self._has_model())
            return None

        def paid_errand_thin_robot(facts):
            """The nearest able robot is low, and the parcel was paid for."""
            if str(facts.get("priority", "NORMAL")) == "NORMAL":
                return None
            about = facts.get("robots") or {}
            able = list(facts.get("able") or [])
            if not able:
                return None
            nearest = min(able,
                          key=lambda r: float((about.get(r) or {})
                                              .get("distance", 10 ** 6) or 10 ** 6))
            battery = float((about.get(nearest) or {}).get("battery", 100) or 100)
            if battery < 40:
                # Covered by the rule: every robot in `able` has been costed
                # to finish this errand with margin to spare, and the rule
                # already weighs urgency against charge -- nearest for an
                # urgent job, best charged nearby otherwise. A thin battery on
                # a robot that can finish is not a case the rule leaves open.
                return Trigger(REASONS.CONFLICT,
                               f"{facts.get('priority')} errand and the nearest "
                               f"robot is at {battery:.0f}%",
                               rule_sufficient=self._rule_covered())
            return None

        def nobody_able(facts):
            able = facts.get("able") or []
            robots = facts.get("robots") or {}
            if not able and robots:
                # No robot the rule may choose: whatever it answers is not a
                # ranking but a guess, and the question is what to do instead.
                return Trigger(REASONS.CONTENTION,
                               f"{len(robots)} robots, none able", rule_sufficient=False)
            return None

        self.triggers.register("choose_next_task", already_late)
        self.triggers.register("choose_next_task", promoted_work)
        self.triggers.register("choose_next_task", competing_tasks)
        self.triggers.register("choose_robot", nobody_able)
        self.triggers.register("choose_robot", paid_errand_thin_robot)
        self.triggers.register("choose_robot", equally_placed)

    def install_rules(self) -> None:
        """
        The two judgements this agent makes, and the fallback under any model.

        Which job next and which robot takes it: both are choices under
        competing pressures -- a promise about to break against a robot that
        would not survive the errand -- and both used to sit on the clerks that
        merely measure those pressures.
        """
        rules = self.rules()
        if rules is None:
            return

        def next_task(question) -> Answer:
            """
            Earliest deadline first: the job closest to breaking a promise.

            Chosen from the offered tasks on the slack each has left, rather
            than by taking the head of a pre-sorted list -- a decision whose
            only reachable answer is `options[0]` is not one a model could ever
            disagree with, which is the only reason to ask.
            """
            options = list(question.options)
            if not options:
                return Answer(None, "nothing ready")
            slack = question.facts.get("slack") or {}
            # The deadline monitor's flags are advice, and they come first:
            # a job it has flagged is one already in trouble, and choosing
            # among the flagged ones by slack is the same question one level in.
            promoted = [t for t in question.facts.get("promoted") or []
                        if t in options]
            among = promoted or options
            unpromised = 10 ** 9
            best = min(among, key=lambda t: (slack.get(t, unpromised),
                                             options.index(t)))
            left = slack.get(best)
            flagged = " the monitor flagged" if best in promoted else ""
            if left is None:
                return Answer(best, f"nothing is promised; oldest and most "
                                    f"urgent{flagged}")
            return Answer(best, f"{left} ticks of slack left, the least of "
                                f"{len(among)}{flagged or ' ready'}")

        def which_robot(question) -> Answer:
            """
            The nearest robot that can actually finish the errand.

            Distance decides between candidates that can all do the job; a
            robot that would arrive without the charge to complete it is not a
            candidate at all, however near it is.
            """
            options = list(question.options)
            if not options:
                return Answer(None, "no robot free")
            about = question.facts.get("robots") or {}
            able = [r for r in question.facts.get("able") or [] if r in options]

            def nearness(robot_id: str) -> tuple:
                detail = about.get(robot_id) or {}
                return (float(detail.get("distance", 10 ** 6) or 10 ** 6),
                        -float(detail.get("battery", 0) or 0), robot_id)

            if able:
                slack = question.facts.get("slack")
                urgent = (question.facts.get("priority") == "URGENT"
                          or (slack is not None and int(slack) < 200))
                if urgent:
                    best = min(able, key=nearness)
                    detail = about.get(best) or {}
                    return Answer(best, f"{detail.get('distance')} cells away "
                                        f"and this job has little time left")
                # Nothing is pressing, so send the robot with most in hand
                # among those close enough to be sensible. Sending the nearest
                # every time runs one robot flat while another idles at full
                # charge, and the fleet is only as available as its emptiest.
                closest = min(nearness(r)[0] for r in able)
                near_enough = [r for r in able if nearness(r)[0] <= closest + 6]
                def charge(r: str) -> float:
                    return float((about.get(r) or {}).get("battery", 0) or 0)

                # Most charge, then the highest robot id: a total order on
                # figures the assignment clerk measured, so a tie gets the
                # same robot on every call, and the reason says how it was
                # broken.
                best = max(near_enough, key=lambda r: (charge(r), r))
                detail = about.get(best) or {}
                tied = (self._has_model()          # rules-only records stay as they were
                        and sum(1 for r in near_enough if charge(r) == charge(best)) > 1)
                return Answer(best, f"best charged of {len(near_enough)} nearby "
                                    f"at {detail.get('battery')}%, "
                                    f"{detail.get('distance')} cells away"
                                    + ("; tied on charge, broken by robot id"
                                       if tied else ""))

            # Nobody can finish it comfortably. Send the one with the most left
            # rather than the nearest: it gets furthest, and RESOURCE still has
            # a veto before the errand is issued.
            best = max(options,
                       key=lambda r: float((about.get(r) or {}).get("battery", 0)
                                           or 0))
            return Answer(best, "none has the charge to finish comfortably; "
                                "sending the best charged")

        rules.register("choose_next_task", next_task)
        rules.register("choose_robot", which_robot)

    def on_attach(self) -> None:
        # Each robot's parking bay is where it started. Recorded once, here,
        # rather than read from the layout every time -- the fleet is the
        # authority on where its robots belong.
        self._home = {r.robot_id: r.current_position
                      for r in self.world.fleet.all()}

    # --------------------------------------------------------------- inbound
    def handle(self, message: Message) -> None:
        kind = message.message_type
        if kind is MessageType.TASK_ASSIGNMENT:
            self._accept(message)
        elif kind is MessageType.SUBTASK_RESULT:
            self._sub_result(message)
        elif kind is MessageType.ROUTE_RESPONSE:
            self._route_ready(message)
        elif kind is MessageType.RESOURCE_GRANT:
            self._cleared(message)
        elif kind is MessageType.RESOURCE_DENIAL:
            self._refused(message)
        elif kind is MessageType.ALERT:
            if message.content.get("operation") == "recall_robot":
                robot_id = message.content.get("robot_id", "")
                target = next((k for k, v in self._dispatch.items()
                               if v["robot_id"] == robot_id), "")
                if target:
                    self._abandon(target,
                                  message.content.get("reason", "recalled"))
        elif kind is MessageType.TASK_FAILED:
            # Routing has decided an errand cannot be finished as planned.
            task_id = message.content.get("task_id") or ""
            if task_id in self._dispatch:
                self._abandon(task_id, message.content.get("reason", "abandoned"))
        elif kind is MessageType.ROBOT_REPORT:
            self._robot_report(message)

    def _accept(self, message: Message) -> None:
        """The planner has added work. The registry already holds it."""
        task_id = message.content.get("task_id", "")
        self.reply(message, MessageType.TASK_ACCEPTED,
                   {"task_id": task_id, "queue_length": len(self.world.tasks.ready())})

    # ---------------------------------------------------- step 1: pick a job
    #: How often to look for robots loitering somewhere unhelpful.
    PARK_EVERY = 10

    def tick_work(self) -> None:
        self._sweep_stale()

        if self.tick % self.PARK_EVERY == 0:
            self._send_idle_robots_home()

        if self.tick % self.DEADLINE_EVERY == 0:
            asked = self.send(self.DEADLINE_SUB, MessageType.SUBTASK_REQUEST,
                              {"operation": "overdue_report"},
                              correlation_id="deadlines")
            if asked is not None:
                self._waiting[asked.message_id] = {"stage": "deadlines"}

        # A lost reply must not wedge dispatch for the rest of the run with
        # nothing in the log to say why.
        for message_id, asked_at in list(self._asking.items()):
            if self.tick - asked_at > self.DISPATCH_TIMEOUT + self._model_allowance():
                self._asking.pop(message_id, None)
                self.assignments.forget_question(message_id)
                self.world.logger.emit(
                    EventCategory.TASK, "queue_question_timed_out",
                    tick=self.tick, actor=self.agent_id,
                    waited=self.tick - asked_at)

        # Anything parked behind a robot that has since become free is handed
        # over now, before new work is arranged: a robot standing next to its
        # own next errand is the whole thing this exists to prevent.
        self._hand_over_queued()

        headroom = (self.world.policy.max_concurrent_transports
                    - len(self._dispatch))
        free = self._free_robots() + self._finishing_robots()
        # One conversation per robot that could actually take the answer, and
        # no more: a question whose answer has no robot to carry it out is a
        # task reserved against nothing. This is the whole change -- the old
        # ceiling was one, regardless of the fleet.
        room = min(len(free), headroom) - len(self._asking)
        if room <= 0 or not self.world.tasks.ready():
            return

        for _ in range(room):
            sent = self.send(self.QUEUE_SUB, MessageType.SUBTASK_REQUEST,
                             {"operation": "next_task",
                              "promoted": sorted(self._promoted),
                              # Two questions in flight would otherwise come
                              # back naming the same task, and two robots sent
                              # for one parcel is a worse failure than a slow
                              # queue.
                              "exclude": sorted(set(self._dispatch)
                                                | self._claiming)},
                             correlation_id="queue")
            if sent is None:
                break
            self._asking[sent.message_id] = self.tick
            self.assignments.asked(sent.message_id, self.tick)
            self._waiting[sent.message_id] = {"stage": "queue"}

    def assigning(self) -> Dict[str, int]:
        """The assignment conversations open right now. Read by the tests."""
        return dict(self._asking)

    def _sweep_stale(self) -> None:
        """
        Give up on dispatches that have stopped making progress.

        Without this a single lost reply costs the fleet a robot permanently:
        the task sits ASSIGNED, the robot sits in `_reserved` looking idle but
        never offered work, and the facility quietly loses a fifth of its
        capacity with nothing in the log to say so. The sweep turns a silent
        leak into a `task_released` event.
        """
        for task_id, job in list(self._dispatch.items()):
            age = self.tick - int(job.get("since", self.tick))
            stage = job.get("stage", "")
            if stage == "under way":
                robot = self.world.fleet.get(job["robot_id"])
                if robot is not None and robot.current_task != task_id:
                    # Give the report a couple of ticks to arrive: a robot that
                    # has just delivered drops the task before its "delivered"
                    # message lands, and abandoning it here would race the
                    # completion that is already in the post.
                    job["orphan_since"] = job.get("orphan_since", self.tick)
                    if self.tick - job["orphan_since"] >= 3:
                        self._abandon(task_id, "robot is no longer on this errand")
                elif age > self.ERRAND_TIMEOUT + self._model_allowance():
                    self._abandon(task_id, f"errand ran {age} ticks without ending")
            elif job.get("queued") and stage == "waiting for its robot":
                # Prepared and parked behind a robot that is still finishing
                # its errand. Nothing is lost here -- the route and the
                # clearance are in -- and the wait ends when the robot lands,
                # so `_hand_over_queued` owns it, with `QUEUE_PATIENCE` as the
                # bound. Applying the paperwork timeout here released such
                # errands after 30 ticks whenever the robot was held up in a
                # doorway, sent the parcel back to the queue, and started the
                # whole chain again -- against, as often as not, another
                # robot about to be held up in the same doorway.
                continue
            elif age > self.DISPATCH_TIMEOUT + self._model_allowance():
                self._abandon(task_id, f"no answer in {age} ticks at stage {stage}")

    def _has_model(self) -> bool:
        """Whether a model sits behind this agent (its brain is not just its rules)."""
        rules = self.rules()
        return rules is not None and self.brain is not rules

    def _model_allowance(self) -> int:
        """
        Extra ticks a stage may take while model decisions do not stop the clock.

        The timeouts above were measured on a clock that stood still while a
        model thought, so a clearance or a route that went to a model still
        came back in a few ticks. On the live clock it takes as long as the
        model does -- up to `llm_deadline_ticks`, after which the rule answers
        -- and giving the dispatch up before then threw away a valid answer
        purely because time had passed. Only while a model decision is out
        somewhere on the floor (or was, a few ticks ago, while its answer is
        still on its way here): with no model thinking, a lost message is
        caught as quickly as ever -- which a collapse scenario that drops
        messages depends on.
        """
        if not self.async_decisions or self.llm_deadline_ticks <= 0:
            return 0
        busy = getattr(self.world, "model_busy_tick", None)
        if busy is None or self.tick - int(busy) > self.MODEL_ANSWER_TRAVEL:
            return 0
        return self.llm_deadline_ticks

    def _send_idle_robots_home(self) -> None:
        """
        Idle robots go back to their bay.

        "Return to the available pool" in the spec is a real movement, not a
        flag. A robot that stops where it finished is an obstacle wherever that
        was, and the whole fleet slowly silts up the doorways it depends on.
        Parking is the lowest-priority thing in the system: it is offered only
        to robots with no errand, and any errand cancels it.
        """
        if self.world.tasks.ready():
            return                      # there is work; parking can wait
        for robot in self.world.fleet.all():
            if robot.robot_id in self._reserved or robot.current_task is not None:
                continue
            if robot.status.value != "IDLE" or robot.carrying is not None:
                continue
            home = self._home.get(robot.robot_id)
            if home is None or robot.current_position == home:
                continue
            route = self.world.env.path(robot.current_position, home)
            if route is None or len(route) <= 1:
                continue
            self.send(robot.robot_id, MessageType.ROBOT_COMMAND,
                      {"operation": "park", "home": home.as_dict(),
                       "route": [p.as_dict() for p in route]},
                      correlation_id=robot.robot_id,
                      text=f"{robot.robot_id}: nothing doing, go and wait at {home}.")

    def _free_robots(self) -> List:
        return [r for r in self.world.fleet.available()
                if r.robot_id not in self._reserved
                and r.robot_id not in self._queued]

    # --------------------------------------- the errand waiting behind an errand
    def _finishing_robots(self) -> List:
        """
        Robots close enough to the end of an errand to be given the next one.

        Not "nearly idle" as a guess, and not a count of ticks: the robot is
        asked. `on_final_leg` is the robot's own account of what it is doing
        -- carrying, walking the leg that ends at the drop -- and
        `route_remaining` is its own count of the cells left, which stays
        honest while it is blocked, yielding or held, where a straight-line
        distance from the scheduler's copy of the dropoff does not.

        `FINISHING_WITHIN` remains, and remains a distance: it is the lead
        the handshake needs, not an inference about what the robot is doing.
        """
        out = []
        for job in self._dispatch.values():
            if job.get("queued") or job.get("stage") != "under way":
                continue
            robot_id = job["robot_id"]
            if robot_id in self._queued:
                continue                       # already has its next errand
            robot = self.world.fleet.get(robot_id)
            if robot is None or not robot.on_final_leg:
                continue                       # not yet on the homeward leg
            if robot.route_remaining <= self.FINISHING_WITHIN:
                out.append(robot)
        return out

    # ------------------------------------------------- preparation and promotion
    def _prepared(self, job: Dict[str, Any]) -> None:
        """Move a parked errand along as its route and clearance arrive."""
        if not job.get("queued"):
            return
        if job.get("routed") and job.get("cleared"):
            job["prep"] = READY
        elif job.get("cleared"):
            job["prep"] = VALIDATED
        else:
            job["prep"] = QUEUED

    def _route_is_fresh(self, job: Dict[str, Any], robot) -> bool:
        """
        Whether the path planned for a parked errand still describes the walk.

        It was planned from the cell the robot was walking towards, several
        ticks before it got there, so two things can have gone stale: the
        robot may not be standing where the route starts -- its errand was
        abandoned, it was diverted, it yielded and stopped short -- and a cell
        on the way may have become a wall. Either makes the route a
        description of a building that no longer exists, and walking it would
        put the robot somewhere nobody expects.
        """
        legs = (list(job.get("to_pickup") or []) + list(job.get("to_dropoff") or [])
                + list(job.get("after_via") or []))
        if not legs:
            return False
        first = Position.of(legs[0])
        if first != robot.current_position:
            return False
        grid = self.world.env
        return all(grid.is_free(Position.of(cell)) for cell in legs)

    def _conditions_hold(self, task_id: str) -> bool:
        """
        Whether the facts the errand was arranged against are still facts.

        Everything is checked again rather than trusted, because several ticks
        have passed: the robot has to be genuinely free, the parcel has to
        still be where the errand expects it and still be waiting to move, the
        task has to still be open, and the charge has to still cover what the
        clearance was granted for. A clearance measured against conditions
        that have since changed is not a clearance.
        """
        job = self._dispatch.get(task_id)
        if job is None or not job.get("queued"):
            return False

        robot = self.world.fleet.get(job["robot_id"])
        if robot is None or not robot.is_available:
            return False                       # still working, or unfit

        parcel = self.world.env.parcels.get(job["parcel_id"])
        if parcel is None or parcel.position is None:
            return False                       # gone, or on somebody else
        if parcel.position != job["pickup"]:
            return False                       # moved since this was arranged

        task = self.world.tasks.get(task_id)
        if task is None or not task.is_open:
            return False

        # The battery is the condition most likely to have moved: the robot
        # has been walking since the clearance was granted.
        needed = float(job.get("estimated_cost", 0.0) or 0.0)
        return robot.battery_level - needed > 0.0

    def handover_ready(self, task_id: str) -> bool:
        """
        Whether a parked errand may now be carried out -- all three parts.

        The conditions still hold, the preparation actually finished, and the
        route still describes the floor. The middle one is not a formality: a
        parked errand whose robot comes free early is a `READY`-looking
        candidate with no path and no clearance, and handing it over sends a
        robot off with neither. The state is what stops that.
        """
        job = self._dispatch.get(task_id)
        if job is None or job.get("prep") != READY:
            return False
        if not self._conditions_hold(task_id):
            return False
        robot = self.world.fleet.get(job["robot_id"])
        return robot is not None and self._route_is_fresh(job, robot)

    def _replan_queued(self, task_id: str) -> None:
        """
        Ask routing again for an errand whose prepared path has gone stale.

        Re-routed, never forced: executing a path that no longer starts where
        the robot is standing is the one thing the revalidation exists to
        prevent. The errand keeps its clearance and its place behind the
        robot; only the walk is planned again, and by ROUTING, because the
        scheduler planning its own paths would be the same bypass in a
        different coat.
        """
        job = self._dispatch.get(task_id)
        robot = self.world.fleet.get(job["robot_id"]) if job else None
        parcel = self.world.env.parcels.get(job["parcel_id"]) if job else None
        if job is None or robot is None or parcel is None \
                or parcel.position is None:
            self._abandon(task_id, "nothing left to re-route")
            return

        job["routed"] = False
        job["to_pickup"] = []
        job["to_dropoff"] = []
        job["after_via"] = []
        job["prep"] = VALIDATED if job.get("cleared") else QUEUED
        job["stage"] = "re-routing"
        self.world.logger.emit(
            EventCategory.TASK, "queued_errand_rerouted", tick=self.tick,
            actor=self.agent_id, target=robot.robot_id, task_id=task_id)
        self.send(self.ROUTING, MessageType.ROUTE_REQUEST,
                  {"operation": "plan_transport", "task_id": task_id,
                   "robot_id": robot.robot_id,
                   "start": robot.current_position.as_dict(),
                   "pickup": parcel.position.as_dict(),
                   "dropoff": job["dropoff"].as_dict(),
                   **self._via_request(job)},
                  correlation_id=parcel.parcel_id,
                  text=(f"The path prepared for {robot.robot_id} on {task_id} "
                        f"no longer starts where it is standing."))

    def _hand_over_queued(self) -> None:
        """Carry out, re-plan, or give up on every errand parked behind a robot."""
        for robot_id, task_id in list(self._queued.items()):
            job = self._dispatch.get(task_id)
            if job is None:
                self._queued.pop(robot_id, None)
                continue
            robot = self.world.fleet.get(robot_id)
            waited = self.tick - job.get("since", self.tick)
            if robot is not None and not robot.is_available:
                if waited > self.QUEUE_PATIENCE + self._model_allowance():
                    self._abandon(task_id, "waited too long behind its robot")
                continue

            if not self._conditions_hold(task_id):
                # Arranged against a floor that has moved. The parcel still
                # needs carrying, so the task goes back rather than failing.
                self._queued.pop(robot_id, None)
                self._abandon(task_id, "conditions changed before handover")
                continue
            if job.get("prep") != READY:
                # The robot is free before the paperwork is. Holding it is
                # still cheaper than starting the chain from nothing, and the
                # patience timeout bounds the wait.
                if waited > self.QUEUE_PATIENCE + self._model_allowance():
                    self._abandon(task_id, "preparation never finished")
                continue
            if robot is not None and not self._route_is_fresh(job, robot):
                self._replan_queued(task_id)
                continue

            self._queued.pop(robot_id, None)
            job["queued"] = False
            job["prep"] = PROMOTED
            self._reserved.add(robot_id)
            self.assignments.promoted(task_id, self.tick)
            self.world.logger.emit(
                EventCategory.TASK, "errand_handed_over", tick=self.tick,
                actor=self.agent_id, target=robot_id, task_id=task_id,
                waited=waited)
            self._command(task_id)

    # ------------------------------------------------------- sub-agent replies
    def _sub_result(self, message: Message) -> None:
        context = self._waiting.pop(message.in_reply_to or "", None)
        if context is None:
            return
        content = message.content
        operation = content.get("operation", "")

        if operation == "next_task":
            self._asking.pop(message.in_reply_to or "", None)
            # Whatever the clerk shortlisted, anything already being dispatched
            # is off the table -- the exclusion travels with the question, but
            # a task can enter dispatch while the question is in flight.
            candidates = [str(t) for t in content.get("candidates", ())
                          if str(t) not in self._dispatch
                          and str(t) not in self._claiming]
            if not candidates:
                return
            # The clerk ordered the ready work and measured the slack on each
            # job; which promise to serve first is this agent's call.
            asked = message.in_reply_to or ""
            answer = self.decide(
                "choose_next_task",
                "Which of the ready tasks should be started next?",
                options=tuple(candidates),
                correlation_id=content.get("correlation_id", ""),
                slack=content.get("slack") or {},
                promoted=content.get("promoted") or [],
                deferral=self._next_task_deferral(asked, candidates),
            )
            if is_pending(answer):
                # The model is weighing these promises: the shortlist is held
                # so another conversation does not dispatch one of them under
                # it -- except urgent work, which stays where any conversation
                # can reach it, so an urgent parcel never waits on a model.
                held = {t for t in candidates if not self._urgent(t)}
                self._held[asked] = held
                self._claiming |= held
                return
            self._next_task_chosen(asked, candidates, answer)
            return

        if operation == "choose_robot":
            task_id = context.get("task_id") or content.get("task_id") or ""
            candidates = [str(r) for r in content.get("candidates", ())]
            if not content.get("ok") or not task_id or not candidates:
                return
            answer = self.decide(
                "choose_robot",
                f"Which robot should take the errand for "
                f"{context.get('parcel_id') or task_id}?",
                options=tuple(candidates),
                correlation_id=context.get("correlation_id", "") or task_id,
                robots=content.get("robots") or {},
                able=content.get("able") or [],
                priority=content.get("priority", "NORMAL"),
                slack=content.get("slack"),
                deferral=self._robot_deferral(task_id, context, content,
                                              candidates),
            )
            if is_pending(answer):
                # The task stays claimed and unassigned: no robot is reserved
                # for it and every robot carries on with what it has.
                return
            self._robot_answer(task_id, context, content, candidates, answer)
            return

        if operation == "overdue_report":
            self._promoted = {row["task_id"] for row in content.get("overdue", ())}
            if content.get("count"):
                self.world.logger.emit(
                    EventCategory.TASK, "overdue", tick=self.tick,
                    actor=self.DEADLINE_SUB, target=self.agent_id,
                    count=content["count"], worst=content.get("worst"))

    # ------------------------------------------ decisions that wait on a model
    def _next_task_chosen(self, asked: str, candidates: List[str],
                          answer: Answer) -> None:
        """Claim the task a `choose_next_task` answer names, and dispatch it."""
        task_id = answer.choice if answer.choice in candidates else candidates[0]
        self._release_held(asked, keep=task_id)
        self.assignments.selected(asked, task_id, self.tick)
        # Claimed from here until it is either a dispatch or abandoned, so
        # the conversations still open are shown a different task.
        self._claiming.add(task_id)
        self._start_dispatch(task_id)

    def _release_held(self, asked: str, keep: str = "") -> None:
        """Give back the shortlist a model decision was holding, all but `keep`."""
        self._claiming -= self._held.pop(asked, set()) - {keep}

    def _urgent(self, task_id: str) -> bool:
        task = self.world.tasks.get(task_id)
        return task is not None and task.priority.value == "URGENT"

    def _next_task_deferral(self, asked: str, candidates: List[str]) -> Deferral:
        """
        Finishing a `choose_next_task` the model answers after the tick.

        While it is pending its shortlist is held (`_held`), urgent tasks
        excepted, and no room is held: the other conversations carry on with
        the rest of the queue, and once this agent's requests to its model are
        all taken the rule answers them. Holding a slot per pending question
        was tried and is wrong -- with three questions out and three robots
        free, a model that is slow to answer stopped all dispatch. Holding the
        tasks is not: without it the next conversation was shown the same
        shortlist, the rule dispatched the same task, and every model answer
        arrived to find it gone.

        The answer applies whenever the task it names is still ready and not
        taken by anything else -- however long the model took. Otherwise the
        shortlist is given back and the next question to the queue, rules
        first, is the re-evaluation.
        """
        def still_valid(answer: Answer) -> str:
            task_id = answer.choice if answer.choice in candidates else candidates[0]
            task = self.world.tasks.get(str(task_id))
            if task is None or not task.is_unassigned:
                return f"{task_id} is no longer waiting"
            ours = self._held.get(asked, set())
            if task_id in self._dispatch or (task_id in self._claiming
                                              and task_id not in ours):
                return f"{task_id} was taken while the model was deciding"
            return ""

        # Keyed by the conversation, not by the shortlist: two conversations
        # shown the same shortlist are two robots' worth of work, and one of
        # them waiting on the model must not hold the other back.
        return Deferral(key=asked or "|".join(sorted(candidates)),
                        apply=lambda answer: self._next_task_chosen(
                            asked, candidates, answer),
                        still_valid=still_valid,
                        reevaluate=lambda why: self._release_held(asked))

    def _robot_deferral(self, task_id: str, context: Dict[str, Any],
                        content: Dict[str, Any],
                        candidates: List[str]) -> Deferral:
        """
        Finishing a `choose_robot` the model answers after the tick.

        The one answer that must never be applied late is a robot that is no
        longer free: by then it may be carrying somebody else's parcel. So a
        late answer is used only while the task is still this agent's to
        assign and the robot it names can still take it; otherwise the robot
        question is asked again from the robots free now, rules first.
        """
        def still_valid(answer: Answer) -> str:
            task = self.world.tasks.get(task_id)
            if task is None or not task.is_unassigned:
                return f"{task_id} is no longer waiting for a robot"
            if task_id not in self._claiming:
                return f"{task_id} was released while the model was deciding"
            robot_id = str(answer.choice)
            if robot_id not in candidates:
                return ""              # off the list; the gate will say so
            if not self._takeable(robot_id):
                return f"{robot_id} is no longer free"
            return ""

        def reevaluate(why: str) -> None:
            task = self.world.tasks.get(task_id)
            if (task is None or not task.is_unassigned
                    or task_id not in self._claiming):
                self._claiming.discard(task_id)
                return
            self._start_dispatch(task_id)

        return Deferral(key=task_id,
                        apply=lambda answer: self._robot_answer(
                            task_id, context, content, candidates, answer),
                        still_valid=still_valid, reevaluate=reevaluate)

    def _robot_answer(self, task_id: str, context: Dict[str, Any],
                      content: Dict[str, Any], candidates: List[str],
                      answer: Answer) -> None:
        """Assign the robot a `choose_robot` answer names, or choose again."""
        robot_id = (answer.choice if answer.choice in candidates
                    else min(candidates))
        # Several of these conversations are in flight at once, and they
        # were all shown the same free robots -- so at the start of a
        # shift every one of them names the same nearest robot, and only
        # the first reservation sticks. Before this, the rest gave up
        # here and began again next tick with a fresh question to the
        # queue clerk and another to this one: one errand handed out
        # every two ticks while five robots stood idle beside six ready
        # jobs, and the supervisor raising the ceiling to no effect. Now a
        # conversation whose robot was taken while it was asking chooses
        # again from the candidates still free, this tick, and only gives
        # up when none is left.
        remaining = list(candidates)
        while remaining:
            if self._takeable(robot_id):
                self._robot_chosen(task_id, robot_id)
                return
            # Every robot already taken is off the list, not just this one:
            # conversations opened in the same tick share one snapshot of the
            # free robots, and dropping them one at a time re-asked the same
            # task once per taken robot (T-0035: R5, R4, R3, R2, R1 in one
            # tick, a fresh decision each).
            # (With a model behind the agent only: a rules-only run, whose
            # re-decisions cost nothing, logs exactly as it always has.)
            remaining = [r for r in remaining
                         if r != robot_id and (not self._has_model() or self._takeable(r))]
            if not remaining:
                break
            narrowed = {**content,
                        "robots": {k: v for k, v in (content.get("robots") or {}).items()
                                   if k in remaining},
                        "able": [r for r in (content.get("able") or [])
                                 if r in remaining]}
            answer = self.decide(
                "choose_robot",
                f"Which robot should take the errand for "
                f"{context.get('parcel_id') or task_id}? ({robot_id} was "
                f"taken while we were asking)",
                options=tuple(remaining),
                correlation_id=context.get("correlation_id", "") or task_id,
                robots=narrowed["robots"],
                able=narrowed["able"],
                priority=content.get("priority", "NORMAL"),
                slack=content.get("slack"),
                deferral=self._robot_deferral(task_id, context, narrowed,
                                              list(remaining)),
            )
            if is_pending(answer):
                return             # still claimed; the model has it
            robot_id = (answer.choice if answer.choice in remaining
                        else min(remaining))
        self._claiming.discard(task_id)    # every candidate was taken

    # ------------------------------------------- step 2: choose a robot, ask
    def _start_dispatch(self, task_id: str) -> None:
        task = self.world.tasks.get(task_id)
        if task is None or not task.is_unassigned:
            return
        parcel = self.world.env.parcels.get(task.parcel_id or "")
        if parcel is None or parcel.position is None:
            task.fail(self.tick, self.agent_id, reason="parcel is not on the floor")
            self.world.tasks.record_transition(task, self.tick, "task_failed",
                                               actor=self.agent_id)
            return

        # Who goes is a judgement, so it is asked rather than sorted. The rest
        # of this errand is set up in `_robot_chosen` when the answer comes
        # back -- one more tick of latency, and the same shape as every other
        # decision this agent delegates.
        # Robots that are free, and robots about to be: an errand arranged
        # for one that is finishing is what gives the chain time to complete
        # before the robot actually lands.
        free = self._free_robots() + self._finishing_robots()
        if not free:
            self._claiming.discard(task_id)   # nobody to take it; unclaim
            return                     # try again next tick; the task stays ready

        env = self.world.env
        candidates = []
        for robot in free:
            # From where each will be when it starts: a finishing robot is
            # measured from its drop, not from the corridor it is crossing.
            here = robot.current_position
            job = next((j for j in self._dispatch.values()
                        if j.get("robot_id") == robot.robot_id
                        and not j.get("queued")), None)
            if job is not None:
                here = job["dropoff"]
            distance = env.distance(here, parcel.position)
            if distance is None:
                continue
            candidates.append({"robot_id": robot.robot_id,
                               "distance": distance,
                               "battery": round(robot.battery_level, 1),
                               "carrying": robot.carrying or ""})
        if not candidates:
            return

        destination = task.destination or parcel.destination or Zone.SORTING
        dropoff = env.free_cell_in(destination, near=parcel.position)
        via = self._via_cell(task, parcel)
        if via is None:
            errand = env.distance(parcel.position, dropoff)
        else:
            legs = (env.distance(parcel.position, via), env.distance(via, dropoff))
            errand = None if None in legs else sum(legs)
        sent = self.send(self.ASSIGNMENT, MessageType.SUBTASK_REQUEST,
                         {"operation": "choose_robot", "task_id": task_id,
                          "parcel_id": parcel.parcel_id,
                          "robots": candidates,
                          "errand_cells": errand or 0,
                          "priority": task.priority.value,
                          "slack": task.slack_at(self.tick)},
                         correlation_id=parcel.parcel_id,
                         text=f"Who should collect {parcel.parcel_id}?")
        if sent is not None:
            self._waiting[sent.message_id] = {"task_id": task_id,
                                              "sub_agent": self.ASSIGNMENT}

    def _takeable(self, robot_id: str) -> bool:
        """Whether this robot can still be given an errand right now."""
        robot = self.world.fleet.get(robot_id)
        if robot is None:
            return False
        if robot in self._free_robots() and robot_id not in self._reserved:
            return True
        return robot in self._finishing_robots() and robot_id not in self._queued

    def _robot_chosen(self, task_id: str, robot_id: str) -> None:
        """The errand, now that somebody has said who is taking it."""
        task = self.world.tasks.get(task_id)
        if task is None or not task.is_unassigned:
            return
        parcel = self.world.env.parcels.get(task.parcel_id or "")
        robot = self.world.fleet.get(robot_id)
        if parcel is None or parcel.position is None or robot is None:
            return
        finishing = robot in self._finishing_robots()
        if not finishing and (robot_id in self._reserved
                              or robot not in self._free_robots()):
            self._claiming.discard(task_id)
            return                     # taken while we were asking
        if finishing and robot_id in self._queued:
            self._claiming.discard(task_id)
            return                     # it already has one waiting

        destination = task.destination or parcel.destination or Zone.SORTING
        dropoff = self.world.env.free_cell_in(destination, near=parcel.position)

        task.assign(self.agent_id, self.tick, self.agent_id,
                    robot_id=robot.robot_id)
        self.world.tasks.record_transition(task, self.tick, "task_assigned",
                                           actor=self.agent_id,
                                           robot_id=robot.robot_id)
        # A robot still finishing is not reserved -- it is already reserved
        # against the errand it is on -- and its next one is parked instead.
        if not finishing:
            self._reserved.add(robot.robot_id)
        else:
            self._queued[robot.robot_id] = task_id
        self._claiming.discard(task_id)        # it is a dispatch now
        self.assignments.assigned(task_id, robot.robot_id, self.tick,
                                  queued=finishing)
        self._dispatch[task_id] = {
            "queued": finishing,
            "prep": QUEUED if finishing else None,
            "robot_id": robot.robot_id, "parcel_id": parcel.parcel_id,
            "destination": destination.value, "stage": "routing",
            "pickup": parcel.position, "dropoff": dropoff,
            "via": self._via_cell(task, parcel),
            "since": self.tick,
        }

        # Where the robot will be standing when it starts, which for a queued
        # errand is the drop it is still walking to. Routing from where it
        # happens to be mid-walk would plan the journey from a cell it is
        # about to leave.
        start = robot.current_position
        if finishing:
            current = next((j for j in self._dispatch.values()
                            if j.get("robot_id") == robot.robot_id
                            and not j.get("queued")), None)
            if current is not None:
                start = current["dropoff"]
        self.send(self.ROUTING, MessageType.ROUTE_REQUEST,
                  {"operation": "plan_transport", "task_id": task_id,
                   "robot_id": robot.robot_id,
                   "start": start.as_dict(),
                   "pickup": parcel.position.as_dict(),
                   "dropoff": dropoff.as_dict(),
                   **self._via_request(self._dispatch[task_id])},
                  correlation_id=parcel.parcel_id,
                  text=(f"Route {robot.robot_id} to collect "
                        f"{parcel.parcel_id} for {destination.value}."))

        # And the clearance at the same time, not after the route comes back.
        #
        # These were sequential because clearance needs a distance for the
        # battery estimate, and the route is where the distance came from. But
        # the battery clerk multiplies whatever it is given by 1.8 for
        # congestion -- so it was never using the route as a route, only as a
        # length, and the grid distance is the same number before the
        # inflation. Waiting for the exact figure cost a robot that had
        # already been chosen two more ticks of standing still, every errand.
        #
        # Measured over 900 ticks of the busy preset: of all the time robots
        # spent idle, 24% was waiting on clearance and 24% on routing -- half
        # of it spent holding still while the paperwork for its own errand
        # went round the houses.
        self._ask_clearance(task_id, robot, parcel, destination,
                            self._estimated_length(robot, parcel, dropoff,
                                                   self._dispatch[task_id].get("via")))

    def _via_cell(self, task, parcel) -> Optional[Position]:
        """
        The cell an errand must pass through, when its task names a zone.

        An urgent parcel leaving intake goes by way of the sorting hall; the
        cell is the nearest walkable one in that hall to where the parcel is,
        chosen the same way a drop cell is.
        """
        zone = (task.detail or {}).get("via") if task is not None else None
        if not zone:
            return None
        try:
            return self.world.env.free_cell_in(Zone(zone), near=parcel.position)
        except Exception:
            return None

    @staticmethod
    def _via_request(job: Dict[str, Any]) -> Dict[str, Any]:
        via = job.get("via")
        return {"via": via.as_dict()} if via is not None else {}

    def _nearest_free(self, target: Position):
        """
        The nearest free robot by real path length, reservations excluded.

        Re-implemented rather than delegated to `Fleet.nearest_available`
        because this agent must also exclude the robots it is part way through
        committing -- the fleet has no idea those exist.
        """
        env = self.world.env
        best, best_key = None, None
        for robot in self._free_robots():
            distance = env.distance(robot.current_position, target)
            if distance is None:
                continue
            key = (distance, -robot.battery_level, robot.robot_id)
            if best_key is None or key < best_key:
                best, best_key = robot, key
        return best

    # --------------------------------- step 4: the route and the clearance
    def _estimated_length(self, robot, parcel, dropoff, via=None) -> int:
        """
        How far this errand is, before anybody has planned it.

        Grid distance to the parcel plus grid distance on to the drop. The
        same number the route would report on an empty floor, and the battery
        clerk inflates it for congestion either way.
        """
        env = self.world.env
        if via is None:
            legs = (env.distance(robot.current_position, parcel.position),
                    env.distance(parcel.position, dropoff))
        else:
            legs = (env.distance(robot.current_position, parcel.position),
                    env.distance(parcel.position, via),
                    env.distance(via, dropoff))
        return sum(leg for leg in legs if leg is not None)

    def _ask_clearance(self, task_id, robot, parcel, destination,
                       length: int) -> None:
        self.send(self.RESOURCE, MessageType.RESOURCE_REQUEST,
                  {"task_id": task_id, "robot_id": robot.robot_id,
                   "parcel_id": parcel.parcel_id,
                   "destination": destination.value
                   if hasattr(destination, "value") else str(destination),
                   "route_length": length},
                  correlation_id=parcel.parcel_id,
                  text=(f"Clearance for {robot.robot_id} on {task_id}: "
                        f"about {length} cells to "
                        f"{getattr(destination, 'value', destination)}."))

    def _route_ready(self, message: Message) -> None:
        content = message.content
        task_id = content.get("task_id", "")
        job = self._dispatch.get(task_id)
        if job is None:
            return
        if not content.get("ok"):
            self._abandon(task_id, "no route across the floor")
            return

        job["to_pickup"] = content.get("to_pickup", [])
        job["to_dropoff"] = content.get("to_dropoff", [])
        job["after_via"] = content.get("after_via", [])
        job["routed"] = True
        # The clearance went out with the route request. Whichever answer
        # arrives second sends the robot; neither is useful alone, because a
        # cleared errand with no route cannot be walked and a routed errand
        # without clearance has not been permitted.
        self._prepared(job)
        if job.get("cleared") and not job.get("queued"):
            self._command(task_id)
        elif job.get("cleared"):
            job["stage"] = "waiting for its robot"
            job["since"] = self.tick
        else:
            job["stage"] = "clearance"
            job["since"] = self.tick

    # --------------------------------------------- step 5: command the robot
    def _cleared(self, message: Message) -> None:
        task_id = message.content.get("task_id", "")
        job = self._dispatch.get(task_id)
        if job is None:
            return
        job["cleared"] = True
        # What the clearance was granted against, kept so the handover can
        # measure the robot's charge against the same number rather than
        # assuming nothing has moved since.
        job["estimated_cost"] = message.content.get("estimated_cost", 0.0)
        self._prepared(job)
        if not job.get("routed"):
            job["stage"] = "routing"
            job["since"] = self.tick
            return
        if job.get("queued"):
            job["stage"] = "waiting for its robot"
            job["since"] = self.tick
            return
        self._command(task_id)

    def _command(self, task_id: str) -> None:
        """Both answers are in: send the robot."""
        job = self._dispatch.get(task_id)
        task = self.world.tasks.get(task_id)
        if job is None or task is None:
            return
        if job.get("queued"):
            # Belt and braces. Every path into here already checks, but a
            # queued errand commanded early is a robot sent for a second
            # parcel while the first is still on board, and that is the one
            # failure this whole arrangement must not have.
            return

        task.route = (list(job.get("to_pickup", [])) + list(job.get("to_dropoff", []))
                      + list(job.get("after_via", []))[1:])
        if task.status is TaskStatus.ASSIGNED:
            task.start(self.tick, self.agent_id, robot=job["robot_id"])
            self.world.tasks.record_transition(task, self.tick, "task_started",
                                               actor=self.agent_id,
                                               robot_id=job["robot_id"])
        job["stage"] = "under way"
        job["prep"] = None                     # its preparation is over
        job["since"] = self.tick
        self.dispatched += 1
        self.assignments.commanded(task_id, job["robot_id"], self.tick)

        parcel = self.world.env.parcels.get(job["parcel_id"])
        if parcel is not None and parcel.status is ParcelStatus.CLASSIFIED:
            parcel.set_status(ParcelStatus.AWAITING_PICKUP, self.tick,
                              self.agent_id, robot=job["robot_id"])

        self.send(job["robot_id"], MessageType.ROBOT_COMMAND,
                  {"operation": "transport", "task_id": task_id,
                   "parcel_id": job["parcel_id"],
                   "pickup": job["pickup"].as_dict(),
                   "dropoff": job["dropoff"].as_dict(),
                   "destination_zone": job["destination"],
                   "to_pickup": job.get("to_pickup", []),
                   "to_dropoff": job.get("to_dropoff", []),
                   **({"via": job["via"].as_dict(),
                       "after_via": job.get("after_via", [])}
                      if job.get("via") is not None else {})},
                  correlation_id=job["parcel_id"],
                  text=(f"{job['robot_id']}: collect {job['parcel_id']} and "
                        f"take it to {job['destination']}."))

    def _refused(self, message: Message) -> None:
        task_id = message.content.get("task_id", "")
        self.denials += 1
        self._abandon(task_id, message.content.get("reason", "refused"),
                      cause=message.content.get("cause", ""))

    def _abandon(self, task_id: str, reason: str, cause: str = "") -> None:
        """
        Put a job back rather than failing it, and tell the robot it is off it.

        The parcel still needs moving; only this attempt is over. Failing it
        would quietly lose the parcel, which is the worst kind of bug to have
        in a simulation you intend to draw conclusions from.

        Telling the robot matters as much as releasing the task. A robot left
        holding a task nobody is tracking any more is a robot that never
        becomes available again, is never offered work, and -- because the
        resource agent will not divert a robot that is on an errand -- is never
        sent to charge either. One missing message and the fleet shrinks by one
        for the rest of the run.
        """
        job = self._dispatch.pop(task_id, None)
        self._claiming.discard(task_id)
        self.assignments.retired(task_id, self.tick)
        robot_id = job["robot_id"] if job else None
        if job is not None:
            if self._queued.get(job["robot_id"]) == task_id:
                self._queued.pop(job["robot_id"], None)
            else:
                # Only the live errand holds the reservation; a parked one
                # never had it, and discarding it here would free a robot
                # that is still carrying something.
                self._reserved.discard(job["robot_id"])
        task = self.world.tasks.get(task_id)
        if task is not None and task.is_open:
            robot_id = robot_id or task.assigned_robot
            task.release(self.tick, self.agent_id, reason=reason)
            self.world.tasks.record_transition(task, self.tick, "task_released",
                                               actor=self.agent_id,
                                               reason=reason, cause=cause)
        if job is not None and job.get("destination") == Zone.TEMPORARY_STORAGE.value:
            # The shelf was reserved when this attempt was cleared. Give it back,
            # or the storage area loses a slot every time an attempt is dropped.
            self.send(self.RESOURCE, MessageType.RESOURCE_REQUEST,
                      {"operation": "release_storage",
                       "parcel_id": job.get("parcel_id"), "task_id": task_id},
                      correlation_id=job.get("parcel_id", ""),
                      text=f"{task_id} abandoned; the shelf is free again.")
        if robot_id and self.world.fleet.get(robot_id) is not None:
            robot = self.world.fleet[robot_id]
            if robot.current_task == task_id:
                self.send(robot_id, MessageType.ROBOT_COMMAND,
                          {"operation": "abort", "task_id": task_id,
                           "reason": reason},
                          correlation_id=job.get("parcel_id", "") if job else "",
                          text=f"{robot_id}: stand down from {task_id} ({reason}).")

    # --------------------------------------------------------- robot reports
    def _robot_report(self, message: Message) -> None:
        content = message.content
        report = content.get("report", "")
        robot_id = content.get("robot_id", message.sender)
        task_id = content.get("task_id") or ""

        if report == "picked":
            parcel = self.world.env.parcels.get(content.get("parcel_id", ""))
            if parcel is not None:
                parcel.set_status(ParcelStatus.IN_TRANSIT, self.tick, robot_id,
                                  robot=robot_id)
            return

        if report == "delivered":
            self._delivered(message)
            return

        if report == "passed_via":
            # An urgent parcel has been carried through the sorting hall. That
            # is its visit there: noted on the parcel, and the waypoint is
            # spent, so an errand abandoned after this point goes straight on.
            parcel = self.world.env.parcels.get(content.get("parcel_id") or "")
            if parcel is not None:
                parcel.record(self.tick, robot_id, "passed_through",
                              zone=content.get("zone"), at=content.get("at"))
                parcel.route_via = None
            self.world.logger.emit(
                EventCategory.PARCEL, "parcel_passed_through", tick=self.tick,
                actor=robot_id, correlation_id=content.get("parcel_id") or "",
                parcel_id=content.get("parcel_id"), zone=content.get("zone"),
                task_id=task_id)
            return

        if report == "aborted":
            # The parcel is back on the floor. Put its record back to where it
            # was before the errand, so the planner offers it again rather than
            # leaving it marked as travelling on a robot that is not carrying it.
            parcel = self.world.env.parcels.get(content.get("parcel_id") or "")
            if parcel is not None and parcel.position is not None:
                parcel.set_status(ParcelStatus.CLASSIFIED, self.tick,
                                  self.agent_id,
                                  note="errand abandoned", robot=robot_id)
            if task_id:
                self._abandon(task_id, content.get("reason", "aborted"))
            return

        if report in ("pick_failed", "battery_empty"):
            # Only errands this agent is shepherding. A flat robot on its way to
            # a charge point is the resource agent's business, and cancelling
            # that errand would take away the one thing that could revive it.
            target = task_id if task_id in self._dispatch else next(
                (k for k, v in self._dispatch.items() if v["robot_id"] == robot_id),
                "")
            if target:
                self._abandon(target, content.get("reason", report))
            return

    def _delivered(self, message: Message) -> None:
        content = message.content
        robot_id = content.get("robot_id", message.sender)
        task_id = content.get("task_id", "")
        parcel_id = content.get("parcel_id", "")

        job = self._dispatch.pop(task_id, None)
        if job is not None:
            self._reserved.discard(job["robot_id"])
        else:
            self._reserved.discard(robot_id)

        env = self.world.env
        parcel = env.parcels.get(parcel_id)
        task = self.world.tasks.get(task_id)
        zone = parcel.current_zone if parcel is not None else None
        status = ARRIVAL_STATUS.get(zone)

        if parcel is not None and status is not None:
            parcel.set_status(status, self.tick, self.agent_id, zone=zone.value)
            # Removing it is the dispatch gate's to do, once it has released
            # it. The scheduler's responsibility ends when the robot puts the
            # parcel down.

        if task is not None and task.is_open:
            # The task may have been released a tick ago by the stale sweep, in
            # which case it is back in the queue and this delivery is the
            # authority on what really happened -- so it is put back into
            # progress before being completed rather than crashing the run.
            if not task.can(TaskStatus.COMPLETED):
                task.assign(self.agent_id, self.tick, self.agent_id,
                            robot_id=robot_id)
                task.start(self.tick, self.agent_id, late=True)
            task.complete(self.tick, self.agent_id, robot=robot_id,
                          zone=zone.value if zone else None)
            self.world.tasks.record_transition(task, self.tick, "task_completed",
                                               actor=self.agent_id,
                                               robot_id=robot_id)
        self.completed += 1
        self.assignments.completed(task_id, robot_id, self.tick)

        self.send(self.parent_id, MessageType.TASK_COMPLETED,
                  {"task_id": task_id, "parcel_id": parcel_id,
                   "robot_id": robot_id,
                   "zone": zone.value if zone else None,
                   "status": status.value if status else None},
                  correlation_id=parcel_id,
                  text=(f"{robot_id} delivered {parcel_id} to "
                        f"{zone.value if zone else 'nowhere'}."))

    # ----------------------------------------------------------------- state
    def state(self) -> Dict[str, Any]:
        return {
            "dispatched": self.dispatched,
            "completed": self.completed,
            "denials": self.denials,
            "in_flight": {k: v["stage"] for k, v in sorted(self._dispatch.items())},
            "prepared": {k: v["prep"] for k, v in sorted(self._dispatch.items())
                         if v.get("prep")},
            "assignment_timing": self.assignments.report(),
            "reserved_robots": sorted(self._reserved),
            "promoted_tasks": sorted(self._promoted),
            "ready_queue": len(self.world.tasks.ready()) if self.world else 0,
            "subagents": [self.QUEUE_SUB, self.DEADLINE_SUB],
        }
