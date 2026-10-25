"""
The planner: turns an objective into work, and keeps the supervisor informed.

It watches the floor rather than being told what is on it. Each tick it looks
for parcels in a state that implies something still has to happen to them, and
creates the task that moves each one along:

    ARRIVED                 -> CLASSIFY, handed to the sorting agent
    CLASSIFIED              -> TRANSPORT to wherever sorting decided
    SORTED or STORED        -> CLASSIFY again; the next leg is a fresh decision

Reclassifying after every leg is deliberate. A parcel that has just been sorted
faces a genuinely new question -- shelf or dispatch -- and the answer depends on
how full the shelves are *now*, not on what was true when it came through the
door. A plan fixed at arrival would be a plan that is wrong by the time it runs.

The planner has one judgement of its own: how much work to release onto the
floor this tick. That is the lever the supervisor's policy actually pulls, and
it is the obvious place to put a language model -- which is why it goes through
`decide()` even though today's rule is four lines. Everything else here is
bookkeeping, and bookkeeping does not get a model.

`PlannerAgent` is deterministic in this version. Swapping in a `CrewBrain`
changes how much work it releases and nothing else about the interface, which
is the whole point of the seam.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from ..communication.directory import AgentKind
from ..communication.events import EventCategory
from ..communication.message import Message, MessageType
from ..environment.parcels import Parcel, ParcelStatus
from ..environment.zones import Zone
from ..tasks.task import TaskStatus, TaskType
from .base import BaseAgent
from .brain import Answer, Question
from .deferral import Deferral, is_pending
from .reasoning import REASONS, Trigger

#: Which parcel states mean "this parcel needs to be looked at again".
#:
#: `ARRIVED` is no longer among them. A parcel that has just landed on the dock
#: has not been received yet, and sending it to be classified before the
#: facility has agreed to take it is how the old build ended up sorting parcels
#: it would later discover it could not read. It goes to the intake gate
#: instead, and comes back as REGISTERED -- or not at all.
NEEDS_CLASSIFICATION = (ParcelStatus.REGISTERED, ParcelStatus.SORTED,
                        ParcelStatus.STORED)

#: And the one that means "nobody has received this yet".
NEEDS_RECEIVING = (ParcelStatus.ARRIVED,)


class PlannerAgent(BaseAgent):
    """Decomposes the objective into tasks and hands them to the experts."""

    kind = AgentKind.PLANNER

    INTAKE = "INTAKE"
    SORTING = "SORTING"
    SCHEDULING = "SCHEDULING"
    DISPATCH = "DISPATCH"

    def __init__(self, agent_id: str = "PLANNER", parent_id: str = "SUPERVISOR",
                 **kw) -> None:
        super().__init__(agent_id, "planner", parent_id=parent_id, **kw)
        self._classifying: Set[str] = set()     # parcels with a CLASSIFY out
        self._transporting: Set[str] = set()    # parcels with a TRANSPORT out
        self.objective: str = ""
        self.approved: bool = False
        self.tasks_created = 0
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.released_history: List[int] = []
        #: The size of the backlog the last plan was made for, or None when
        #: there is no jam. Read by the reasoning trigger below.
        self._planned_for: Optional[float] = None

    # ----------------------------------------------------------------- rules
    def install_triggers(self) -> None:
        """
        When releasing work stops being arithmetic.

        Routine is a floor with room on it: fewer parcels waiting than the
        ceiling allows onto it, robots free to carry them, shelves not close
        to full. Then how many to release is a subtraction and a model adds
        nothing to it.

        It stops being a subtraction when the floor cannot absorb what is
        waiting. Then releasing more work is a trade against everything else
        happening -- which errands are already open, how much is promised
        soon, whether the robots that would carry it are about to want
        charging -- and that is a plan rather than a sum.
        """

        #: How much the backlog has to move before a jam counts as a new jam.
        #: Without this the planner reasons about the same congestion once a
        #: tick for as long as it lasts -- 386 times in a 400-tick flood, when
        #: it was measured -- which is the per-tick model call the whole
        #: arrangement exists to avoid. A plan made for a queue of forty is
        #: still the plan for a queue of forty-one.
        MATERIAL_CHANGE = 4

        def contention(facts):
            waiting = float(facts.get("waiting", 0) or 0)
            headroom = float(facts.get("headroom", 0) or 0)
            if waiting <= headroom:
                self._planned_for = None      # the jam cleared; forget it
                return None
            before = self._planned_for
            if before is not None and abs(waiting - before) < MATERIAL_CHANGE:
                # The same jam it already made a plan for. The rule carries
                # that plan out; reasoning again would cost a call to answer a
                # question nothing has changed about.
                return None
            self._planned_for = waiting
            return Trigger(REASONS.CONTENTION,
                           f"{waiting:.0f} waiting, headroom {headroom:.0f}"
                           + (f" (was {before:.0f})" if before is not None else ""))

        def no_robots(facts):
            if float(facts.get("free_robots", 0) or 0) <= 0 \
                    and float(facts.get("waiting", 0) or 0) > 0:
                return Trigger(REASONS.CONTENTION, "work waiting, no robot free")
            return None

        def shelves_filling(facts):
            load = float(facts.get("storage_load", 0.0) or 0.0)
            ceiling = (self.world.policy.max_storage_load
                       if self.world is not None else 0.9)
            if load >= ceiling - 0.1:
                return Trigger(REASONS.ENVIRONMENT, f"storage at {load:.0%}")
            return None

        self.triggers.register("release_work", contention)
        self.triggers.register("release_work", no_robots)
        self.triggers.register("release_work", shelves_filling)

    def install_rules(self) -> None:
        rules = self.rules()
        if rules is None:
            return

        def release(question: Question) -> Answer:
            """
            How many new transport jobs to let onto the floor this tick.

            Held below the supervisor's ceiling and below the number of robots
            that could actually start one: releasing work nobody can begin only
            lengthens the queue and makes every later decision harder.
            """
            facts = question.facts
            headroom = int(facts.get("headroom", 0))
            free_robots = int(facts.get("free_robots", 0))
            waiting = int(facts.get("waiting", 0))
            load = float(facts.get("storage_load", 0.0) or 0.0)
            n = max(0, min(headroom, free_robots, waiting, 3))
            # Shelves nearly full means much of this work will be refused at
            # the far end and carried back. Releasing it anyway spends robots
            # on errands the resource agent is about to decline.
            if load >= 0.9 and n > 1:
                return Answer(1, f"shelves at {load:.0%}; releasing one at a "
                                 "time until they drain")
            return Answer(n, f"{headroom} under the ceiling, {free_robots} robots "
                             f"free, {waiting} parcels waiting, shelves "
                             f"{load:.0%}")

        rules.register("release_work", release)

    # --------------------------------------------------------------- inbound
    def handle(self, message: Message) -> None:
        kind = message.message_type

        if kind is MessageType.OBJECTIVE:
            self.objective = message.content.get("objective", "")
            self.world.objective = self.objective
            self._propose_plan()

        elif kind is MessageType.POLICY:
            # The supervisor writes policy; the planner only reads it. Applying
            # it here rather than letting agents read the message means there
            # is exactly one copy of the current policy in the system.
            for field, value in message.content.items():
                if hasattr(self.world.policy, field):
                    setattr(self.world.policy, field, value)
            self.world.logger.emit(EventCategory.SUPERVISOR, "policy_applied",
                                   tick=self.tick, actor=self.agent_id,
                                   **message.content)

        elif kind is MessageType.PLAN_APPROVAL:
            self.approved = True
            self.world.logger.emit(EventCategory.SUPERVISOR, "plan_approved",
                                   tick=self.tick, actor=message.sender,
                                   target=self.agent_id,
                                   note=message.content.get("note", ""))

        elif kind is MessageType.PLAN_REJECTION:
            self.approved = False
            self.world.logger.emit(EventCategory.SUPERVISOR, "plan_rejected",
                                   tick=self.tick, actor=message.sender,
                                   target=self.agent_id,
                                   reason=message.content.get("reason", ""))

        elif kind is MessageType.STATUS_REQUEST:
            self._report_status(to=message.sender)

        elif kind is MessageType.TASK_COMPLETED:
            self._task_done(message, failed=False)

        elif kind is MessageType.TASK_FAILED:
            self._task_done(message, failed=True)

        elif kind is MessageType.TASK_REJECTED:
            parcel_id = message.content.get("parcel_id", "")
            self._classifying.discard(parcel_id)
            self._transporting.discard(parcel_id)

    def _task_done(self, message: Message, failed: bool) -> None:
        parcel_id = message.content.get("parcel_id", "")
        self._classifying.discard(parcel_id)
        self._transporting.discard(parcel_id)
        if failed:
            self.tasks_failed += 1
        else:
            self.tasks_completed += 1

    # ------------------------------------------------------------- the plan
    def _propose_plan(self) -> None:
        """
        The standing plan: which expert owns which stage of a parcel's life.

        It is proposed to the supervisor rather than assumed, because the
        supervisor's right to modify it is part of the spec and because a plan
        that was never approved is a useful thing to be able to see in a log.
        """
        plan = {
            "objective": self.objective,
            "stages": [
                # Both of intake's clerks. The plan listed only the second,
                # so the stage that reads the label was missing from the
                # facility's own description of itself.
                {"stage": "receive", "owner": self.INTAKE,
                 "subagents": ["SUB-VALIDATION", "SUB-REGISTRATION"]},
                {"stage": "classify", "owner": self.SORTING,
                 "subagents": ["SUB-BARCODE", "SUB-PRIORITY", "SUB-DESTINATION"]},
                {"stage": "transport", "owner": self.SCHEDULING,
                 "subagents": ["SUB-QUEUE", "SUB-DEADLINE", "SUB-ASSIGNMENT"],
                 "consults": ["ROUTING", "RESOURCE"]},
                {"stage": "route", "owner": "ROUTING",
                 "subagents": ["SUB-ROUTE", "SUB-COLLISION"]},
                {"stage": "resources", "owner": "RESOURCE",
                 "subagents": ["SUB-BATTERY", "SUB-CHARGING", "SUB-STORAGE"]},
                {"stage": "release", "owner": self.DISPATCH,
                 "subagents": ["SUB-MANIFEST", "SUB-PACKING"]},
            ],
            "itinerary": "INTAKE -> SORTING -> (TEMPORARY_STORAGE) -> DISPATCH",
        }
        # Counted from the plan rather than written into the sentence. It said
        # "twelve sub-agents" while the plan below it listed fifteen, which is
        # what a prose count of a structure that grows always ends up doing.
        experts = len(plan["stages"])
        helpers = sum(len(stage["subagents"]) for stage in plan["stages"])
        self.send(self.parent_id, MessageType.PLAN_PROPOSAL, plan,
                  correlation_id="plan",
                  text=f"{experts} experts, {helpers} sub-agents, parcels "
                       f"received at the dock, sorted, and released from "
                       f"dispatch.")

    # ------------------------------------------------------------ every tick
    def tick_work(self) -> None:
        if not self.world.running:
            return

        self._issue_receipts()
        self._issue_classifications()
        self._issue_transports()

        if self.world.policy.status_report_every and \
                self.tick % self.world.policy.status_report_every == 0:
            self._report_status(to=self.parent_id)

    def _issue_receipts(self) -> None:
        """
        Every parcel on the dock is offered to the intake gate.

        Before classification, deliberately: until the facility has agreed to
        take a parcel there is nothing to classify, and a parcel it turns away
        should cost one round trip rather than four.
        """
        for parcel in self._parcels_needing_receiving():
            task = self.world.tasks.create(
                TaskType.CLASSIFY, self.tick, self.agent_id,
                parcel_id=parcel.parcel_id, source=parcel.current_zone,
                priority=parcel.priority, due_by=parcel.due_by,
                stage="receive")
            self.tasks_created += 1
            self._classifying.add(parcel.parcel_id)
            self.send(self.INTAKE, MessageType.TASK_ASSIGNMENT,
                      {"task_id": task.task_id, "parcel_id": parcel.parcel_id,
                       "zone": parcel.current_zone.value},
                      correlation_id=parcel.parcel_id,
                      text=f"Receive {parcel.parcel_id}, on the dock.")

    def _issue_classifications(self) -> None:
        """Every parcel that needs a decision gets one. No rationing here."""
        for parcel in self._parcels_needing_classification():
            task = self.world.tasks.create(
                TaskType.CLASSIFY, self.tick, self.agent_id,
                parcel_id=parcel.parcel_id, source=parcel.current_zone,
                priority=parcel.priority, due_by=parcel.due_by)
            self.tasks_created += 1
            self._classifying.add(parcel.parcel_id)
            self.send(self.SORTING, MessageType.TASK_ASSIGNMENT,
                      {"task_id": task.task_id, "parcel_id": parcel.parcel_id,
                       "zone": parcel.current_zone.value},
                      correlation_id=parcel.parcel_id,
                      text=f"Classify {parcel.parcel_id}, now in "
                           f"{parcel.current_zone.value}.")

    def _issue_transports(self) -> None:
        """
        Release moving work, up to what the floor can actually absorb.

        This is the planner's one real decision, and it is asked of the brain.
        """
        candidates = self._parcels_ready_to_move()
        if not candidates:
            return

        open_transports = sum(
            1 for t in self.world.tasks.open_tasks()
            if t.task_type is TaskType.TRANSPORT)
        headroom = max(0, self.world.policy.max_concurrent_transports - open_transports)
        free_robots = len(self.world.fleet.available())

        answer = self.decide(
            "release_work",
            "How many more parcels should be released for transport this tick?",
            options=tuple(range(0, 4)),
            correlation_id="plan",
            waiting=len(candidates),
            headroom=headroom,
            free_robots=free_robots,
            open_transports=open_transports,
            ceiling=self.world.policy.max_concurrent_transports,
            storage_load=round(self.world.env.storage.load, 3),
            deferral=self._release_deferral(),
        )
        if is_pending(answer):
            # Nothing new is released while the model is deciding how much
            # to release; the work already on the floor carries on.
            return
        self._release(candidates, answer)

    def _release_deferral(self) -> Deferral:
        """
        Finishing a `release_work` the model answers after the tick.

        The answer is a number, applied to the parcels ready to move when it
        arrives -- not the ones that were ready when it was asked -- and only
        while it still fits under the ceiling as it stands now.
        """
        def still_valid(answer: Answer) -> str:
            try:
                count = max(0, int(answer.choice))
            except (TypeError, ValueError):
                return ""
            open_transports = sum(
                1 for t in self.world.tasks.open_tasks()
                if t.task_type is TaskType.TRANSPORT)
            headroom = max(0, self.world.policy.max_concurrent_transports
                           - open_transports)
            if count > headroom:
                return f"{count} no longer fits: {headroom} under the ceiling"
            return ""

        return Deferral(key="release_work",
                        apply=lambda answer: self._release(
                            self._parcels_ready_to_move(), answer),
                        still_valid=still_valid)

    def _release(self, candidates, answer: Answer) -> None:
        """Create the transports a `release_work` answer allows for."""
        try:
            count = max(0, int(answer.choice))
        except (TypeError, ValueError):
            count = 0
        count = min(count, len(candidates))
        self.released_history.append(count)
        if len(self.released_history) > 200:
            del self.released_history[:100]

        for parcel in candidates[:count]:
            destination = parcel.destination or Zone.SORTING
            # A waypoint the parcel was routed by -- the sorting hall, for an
            # urgent parcel leaving intake -- travels with the errand.
            via = ({"via": parcel.route_via.value}
                   if getattr(parcel, "route_via", None) is not None else {})
            task = self.world.tasks.create(
                TaskType.TRANSPORT, self.tick, self.agent_id,
                parcel_id=parcel.parcel_id, source=parcel.current_zone,
                destination=destination, priority=parcel.priority,
                due_by=parcel.due_by, **via)
            self.tasks_created += 1
            self._transporting.add(parcel.parcel_id)
            self.send(self.SCHEDULING, MessageType.TASK_ASSIGNMENT,
                      {"task_id": task.task_id, "parcel_id": parcel.parcel_id,
                       "source": parcel.current_zone.value,
                       "destination": destination.value,
                       "priority": parcel.priority.value},
                      correlation_id=parcel.parcel_id,
                      text=(f"Move {parcel.parcel_id} ({parcel.priority.value}) "
                            f"from {parcel.current_zone.value} to "
                            f"{destination.value}."))

    # ------------------------------------------------------------- observing
    def _parcels_needing_receiving(self) -> List[Parcel]:
        out = []
        for parcel in self.world.env.parcels.values():
            if parcel.parcel_id in self._classifying:
                continue
            if parcel.position is None:
                continue
            if parcel.status in NEEDS_RECEIVING:
                out.append(parcel)
        out.sort(key=lambda p: (p.timestamps.get("arrived", 0), p.parcel_id))
        return out

    def _parcels_needing_classification(self) -> List[Parcel]:
        out = []
        for parcel in self.world.env.parcels.values():
            if parcel.parcel_id in self._classifying:
                continue
            if parcel.position is None:           # on a robot, or gone
                continue
            if parcel.status in NEEDS_CLASSIFICATION:
                out.append(parcel)
        out.sort(key=lambda p: (-p.priority.rank,
                                p.timestamps.get("arrived", 0), p.parcel_id))
        return out

    def _parcels_ready_to_move(self) -> List[Parcel]:
        out = []
        for parcel in self.world.env.parcels.values():
            if parcel.parcel_id in self._transporting:
                continue
            if parcel.position is None or parcel.destination is None:
                continue
            if parcel.status is not ParcelStatus.CLASSIFIED:
                continue
            if parcel.destination is parcel.current_zone:
                continue
            out.append(parcel)
        out.sort(key=lambda p: (-p.priority.rank,
                                p.timestamps.get("arrived", 0), p.parcel_id))
        return out

    # --------------------------------------------------------------- upwards
    def _report_status(self, to: str) -> None:
        env = self.world.env
        counts = self.world.tasks.counts()
        on_floor = [p for p in env.parcels.values() if p.position is not None]

        report = {
            "tick": self.tick,
            "objective": self.objective,
            "parcels_on_floor": len(on_floor),
            "parcels_dispatched": env.dispatched_count,
            "mean_dwell": env.mean_dwell,
            "tasks": counts,
            "open_tasks": len(self.world.tasks.open_tasks()),
            "ready_tasks": len(self.world.tasks.ready()),
            "blocked_tasks": len(self.world.tasks.blocked()),
            "robots": self.world.fleet.status_counts(),
            "battery": self.world.fleet.battery_summary(),
            "storage_load": round(env.storage.load, 3),
            "storage_refusals": env.storage.refusals,
        }
        self.send(to, MessageType.STATUS_REPORT, report, correlation_id="status",
                  text=(f"{len(on_floor)} parcels on the floor, "
                        f"{env.dispatched_count} dispatched, "
                        f"{report['open_tasks']} tasks open, storage at "
                        f"{env.storage.load:.0%}."))

    # ----------------------------------------------------------------- state
    def state(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "plan_approved": self.approved,
            "tasks_created": self.tasks_created,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "classifying": sorted(self._classifying),
            "transporting": sorted(self._transporting),
            "recent_releases": self.released_history[-15:],
            "experts": [self.INTAKE, self.SORTING, self.SCHEDULING, "ROUTING",
                        "RESOURCE", self.DISPATCH],
        }
