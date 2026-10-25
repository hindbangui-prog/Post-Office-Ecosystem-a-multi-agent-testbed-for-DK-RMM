"""
The sorting agent: decides what a parcel is and where it goes next.

It owns three sub-agents, and its job is to ask them in the right order, weigh
what they report, and write the answer onto the parcel:

    planner --CLASSIFY--> sorting
                          sorting --> SUB-BARCODE      (what does the address say?)
                          sorting --> SUB-PRIORITY     (what was claimed, and
                                                        how busy is the dock?)
                          sorting             judges   how urgent
                          sorting --> SUB-DESTINATION  (how full are the shelves?)
                          sorting             judges   where next
                          sorting --> planner          (done: EXPRESS, DISPATCH)

Three round trips, and that is on purpose: a supervisor of a real facility
would not get an answer instantly either, and a system that pretends
coordination is free is a system where coordination can never be the thing that
fails.

The sub-agents measure and the sorting agent decides. That split used to run
the other way -- SUB-PRIORITY graded the parcel and SUB-DESTINATION chose its
zone, and this agent relayed two answers it had no part in -- which put both
judgements one level below the agent whose whole responsibility is a parcel's
identity. Now the tools report facts and this agent is the only thing that both
decides and writes the record.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..communication.directory import AgentKind
from ..communication.events import EventCategory
from ..communication.message import Message, MessageType
from ..environment.parcels import ParcelPriority, ParcelStatus
from ..environment.zones import Zone
from ..tasks.task import TaskStatus, TaskType
from .base import BaseAgent
from .brain import Answer
from .deferral import Deferral, is_pending
from .reasoning import REASONS, Trigger
from .subagents.sorting_subagents import make_barcode

#: The service code to print when the grade has moved away from what the
#: sender asked for -- the facility labels what it will actually do.
SERVICE_FOR = {ParcelPriority.URGENT: "URG", ParcelPriority.EXPRESS: "EXP",
               ParcelPriority.NORMAL: "STD"}

#: And back again: what the timetable calls the service written on a label.
SERVICE_GRADE = {"URG": "URGENT", "EXP": "EXPRESS", "STD": "NORMAL"}


class SortingAgent(BaseAgent):
    """Classifies parcels, by asking the two specialists that know how."""

    kind = AgentKind.EXPERT

    BARCODE = "SUB-BARCODE"
    PRIORITY = "SUB-PRIORITY"
    DESTINATION = "SUB-DESTINATION"

    def __init__(self, agent_id: str = "SORTING", parent_id: str = "PLANNER",
                 **kw) -> None:
        super().__init__(agent_id, "sorting", parent_id=parent_id, **kw)
        self._waiting: Dict[str, Dict[str, Any]] = {}   # request id -> context
        self._jobs: Dict[str, Dict[str, Any]] = {}      # parcel id -> progress
        self.classified = 0

    # ----------------------------------------------------------------- rules
    def install_triggers(self) -> None:
        """
        When the next leg of a parcel's journey is not obvious.

        Routine is a graded parcel and a facility with room: shelves well
        below the ceiling, the standing policy applying, nothing unusual about
        the parcel. Storage or dispatch is then a rule about what class of
        parcel waits, and it has one right answer.

        It stops having one when the two considerations pull apart -- a paid
        parcel that the standing policy would put on a shelf, shelves close
        enough to full that putting anything else there may cost more than it
        saves, or no shelf at all, which makes "storage" an answer the floor
        cannot honour whatever the policy says.
        """

        def shelves_tight(facts):
            load = float(facts.get("storage_load", 0.0) or 0.0)
            ceiling = float(facts.get("max_storage_load", 0.9) or 0.9)
            if load >= ceiling - 0.15:
                return Trigger(REASONS.CONTENTION,
                               f"shelves at {load:.0%} of a {ceiling:.0%} ceiling")
            return None

        def no_shelf(facts):
            if int(facts.get("storage_free", 0) or 0) <= 0:
                return Trigger(REASONS.ENVIRONMENT, "no shelf free")
            return None

        def paid_parcel(facts):
            # A parcel somebody paid to have hurried, facing a decision whose
            # standing answer is to put it down and leave it there.
            if str(facts.get("priority", "NORMAL")) != "NORMAL" \
                    and facts.get("storage_policy", True):
                # The rule's first branch is "URGENT or EXPRESS -> DISPATCH":
                # the tension this names is one the rule already settles, so
                # where rule coverage is authoritative the rule answers it.
                covered = (self._rule_covered()
                           if str(facts.get("priority")) in ("URGENT", "EXPRESS")
                           else None)
                return Trigger(REASONS.CONFLICT,
                               f"{facts.get('priority')} parcel, and the policy "
                               f"is to store", rule_sufficient=covered)
            return None

        self.triggers.register("classify_destination", no_shelf)
        self.triggers.register("classify_destination", shelves_tight)
        self.triggers.register("classify_destination", paid_parcel)

    def install_rules(self) -> None:
        """
        The judgement this agent makes, and the fallback under any model.

        There used to be two. The other decided what grade to give a parcel,
        weighing the customer's claim against how busy the dock was -- and a
        service class is sold rather than assigned, so there was nothing there
        to weigh. It is now read off the label and written down.

        Where a parcel goes next is a real decision: the shelves are finite,
        they fill, and holding a parcel costs something whichever way it goes.
        """
        rules = self.rules()
        if rules is None:
            return

        def route(question) -> Answer:
            """Hold it on a shelf, or send it straight to the door."""
            facts = question.facts
            priority = str(facts.get("priority", "NORMAL"))
            load = float(facts.get("storage_load", 0.0) or 0.0)
            free = int(facts.get("storage_free", 99) or 0)
            size = str(facts.get("size", "SMALL")).upper()
            may_store = bool(facts.get("storage_policy", True))
            if priority in ("URGENT", "EXPRESS"):
                return Answer(Zone.DISPATCH.value,
                              "urgent and express parcels do not wait on a shelf")
            if not may_store or load >= float(facts.get("max_storage_load", 0.9)):
                return Answer(Zone.DISPATCH.value,
                              f"storage at {load:.0%}; sending it straight out")
            # The ratio is not the whole story: two shelves left is two shelves
            # left whether the area holds twenty or two hundred, and the last
            # few are worth keeping for parcels that have nowhere else to be.
            if free <= 2:
                return Answer(Zone.DISPATCH.value,
                              f"only {free} shelves left; not worth taking one")
            if size == "LARGE" and free <= 5:
                return Answer(Zone.DISPATCH.value,
                              f"a LARGE parcel with {free} shelves left")
            return Answer(Zone.TEMPORARY_STORAGE.value,
                          "standard parcel, shelves have room")

        rules.register("classify_destination", route)

    # --------------------------------------------------------------- inbound
    def handle(self, message: Message) -> None:
        if message.message_type is MessageType.TASK_ASSIGNMENT:
            self._begin(message)
        elif message.message_type is MessageType.SUBTASK_RESULT:
            self._sub_result(message)

    def _begin(self, message: Message) -> None:
        parcel_id = message.content.get("parcel_id", "")
        task_id = message.content.get("task_id", "")
        parcel = self.world.env.parcels.get(parcel_id)
        if parcel is None:
            self.reply(message, MessageType.TASK_REJECTED,
                       {"task_id": task_id, "reason": "no such parcel"})
            return

        task = self.world.tasks.get(task_id)
        if task is not None and task.status is TaskStatus.CREATED:
            task.assign(self.agent_id, self.tick, self.agent_id)
            task.start(self.tick, self.agent_id)
            self.world.tasks.record_transition(task, self.tick, "task_started",
                                               actor=self.agent_id)

        self._jobs[parcel_id] = {"task_id": task_id, "stage": "scan",
                                 "asked_by": message.sender}
        self.reply(message, MessageType.TASK_ACCEPTED,
                   {"task_id": task_id, "parcel_id": parcel_id})

        if parcel.priority_set:
            # Graded on an earlier leg. A parcel coming back from a shelf faces
            # a genuinely new destination question and the same old grade, so
            # only the open decision is asked again.
            self._jobs[parcel_id]["stage"] = "destination"
            self._ask(self.DESTINATION, parcel_id,
                      {"parcel_id": parcel_id, "priority": parcel.priority.value})
            return

        # Scanning and reading: the address in, a route and a service out.
        self._ask(self.BARCODE, parcel_id, {"parcel_id": parcel_id})

    def _ask(self, sub_agent: str, parcel_id: str,
             content: Dict[str, Any]) -> None:
        sent = self.send(sub_agent, MessageType.SUBTASK_REQUEST, content,
                         correlation_id=parcel_id)
        if sent is not None:
            self._waiting[sent.message_id] = {"parcel_id": parcel_id,
                                              "sub_agent": sub_agent}

    # --------------------------------------------------------- sub-agent work
    def _sub_result(self, message: Message) -> None:
        context = self._waiting.pop(message.in_reply_to or "", None)
        if context is None:
            return
        parcel_id = context["parcel_id"]
        job = self._jobs.get(parcel_id)
        parcel = self.world.env.parcels.get(parcel_id)
        if job is None or parcel is None:
            return

        content = message.content
        operation = content.get("operation", "")

        if operation == "scan":
            if not content.get("ok"):
                # The gate could read enough of the address to accept this
                # parcel and the scanner cannot. A real outcome, not an error:
                # the parcel goes back to the sender, and the reason is on the
                # record.
                self._return_to_sender(
                    parcel_id, content.get("reason", "will not scan"))
                return
            parcel.route_label = content.get("route", "")
            parcel.record(self.tick, self.agent_id, "address_read",
                          route=parcel.route_label,
                          service=content.get("service", ""))
            # The machine read is the better one. If the gate priced this
            # parcel on a service it could not quite make out, the promise is
            # re-made now on what the line actually says.
            self.reprice(parcel, content.get("service", ""))
            job["stage"] = "priority"
            job["service"] = content.get("service", "STD")
            self._ask(self.PRIORITY, parcel_id,
                      {"parcel_id": parcel_id,
                       "service": content.get("service", "STD"),
                       "route": parcel.route_label})
            return

        if operation == "classify_priority":
            if content.get("ok"):
                # What the customer paid for, written down rather than judged.
                # This used to be a decision that could demote an urgent parcel
                # to express when the dock was backed up -- three of them on a
                # busy day -- which is not a grading call but a refund nobody
                # issued. A carrier that finds an urgent parcel awkward still
                # owes the urgent departure; the awkwardness is its own problem
                # and shows up where it belongs, as a promise missed.
                parcel.priority = ParcelPriority(
                    str(content.get("claimed", "NORMAL")))
                parcel.priority_set = True
                parcel.record(self.tick, self.agent_id, "priority_set",
                              priority=parcel.priority.value,
                              service=content.get("service", ""),
                              reason="the service on the label",
                              reported_by=message.sender, source="label")
            job["stage"] = "destination"
            self._ask(self.DESTINATION, parcel_id,
                      {"parcel_id": parcel_id, "priority": parcel.priority.value})

        elif operation == "classify_destination":
            if not content.get("ok"):
                self._give_up(parcel_id, content.get("reason", "cannot classify"))
                return
            settled = content.get("settled", "")
            if settled:
                # A leg with one possible answer. Nothing to decide, and
                # putting it through `decide` would spend a model call to
                # confirm that everything is sorted before anything else.
                parcel.destination = Zone(settled)
                parcel.route_via = (Zone(content["via"]) if content.get("via")
                                    else None)
                self._classified(parcel_id, message, content, "rule")
                return
            answer = self.decide(
                "classify_destination",
                f"Parcel {parcel_id} has been sorted. Should it wait in "
                "temporary storage or go straight to dispatch?",
                options=(Zone.TEMPORARY_STORAGE.value, Zone.DISPATCH.value),
                correlation_id=parcel_id,
                priority=content.get("priority", parcel.priority.value),
                size=content.get("size", ""),
                storage_load=content.get("storage_load", 0.0),
                storage_free=content.get("storage_free", 0),
                storage_policy=content.get("storage_policy", True),
                max_storage_load=content.get("max_storage_load", 0.9),
                deferral=self._destination_deferral(parcel_id, message,
                                                    content),
            )
            if is_pending(answer):
                # The parcel stays where it is, classified as far as its grade
                # and no further, until the model has said shelf or door.
                return
            self._destination_chosen(parcel_id, message, content, answer)

    def _destination_chosen(self, parcel_id: str, message: Message,
                            content: Dict[str, Any], answer: Answer) -> None:
        parcel = self.world.env.parcels[parcel_id]
        parcel.destination = Zone(answer.choice)
        self._classified(parcel_id, message,
                         {**content, "reason": answer.reason}, answer.source)

    def _destination_deferral(self, parcel_id: str, message: Message,
                              content: Dict[str, Any]) -> Deferral:
        """
        Finishing a `classify_destination` the model answers after the tick.

        Still applicable while the parcel is on this agent's books and on the
        floor where it was asked about. A late answer that would put it on a
        shelf when none is left is caught by the gate, not here.
        """
        parcel = self.world.env.parcels.get(parcel_id)
        zone = parcel.current_zone if parcel is not None else None

        def still_valid(answer: Answer) -> str:
            now = self.world.env.parcels.get(parcel_id)
            if now is None or parcel_id not in self._jobs:
                return f"{parcel_id} is no longer being sorted"
            if now.current_zone is not zone:
                return f"{parcel_id} has moved since the question was asked"
            return ""

        def reevaluate(why: str) -> None:
            now = self.world.env.parcels.get(parcel_id)
            if now is None or parcel_id not in self._jobs:
                return
            self._ask(self.DESTINATION, parcel_id,
                      {"parcel_id": parcel_id, "priority": now.priority.value})

        return Deferral(key=parcel_id,
                        apply=lambda answer: self._destination_chosen(
                            parcel_id, message, content, answer),
                        still_valid=still_valid, reevaluate=reevaluate)

    def _classified(self, parcel_id: str, message: Message,
                    content: Dict[str, Any], source: str) -> None:
        """Barcode, status, and the report up: the destination is settled."""
        parcel = self.world.env.parcels[parcel_id]
        job = self._jobs.get(parcel_id, {})
        # Applying the barcode. The step the facility is named for, and it
        # happens here because a barcode encodes where the parcel is going
        # -- so it cannot be printed until that is decided. A parcel
        # carrying one has been read, graded and routed by this building.
        if parcel.route_label and not parcel.barcode:
            parcel.barcode = make_barcode(
                parcel.route_label,
                job.get("service") or SERVICE_FOR[parcel.priority],
                parcel.parcel_id.split("-")[-1])
            parcel.record(self.tick, self.agent_id, "barcode_applied",
                          barcode=parcel.barcode)
        parcel.set_status(ParcelStatus.CLASSIFIED, self.tick, self.agent_id,
                          destination=parcel.destination.value,
                          reason=content.get("reason", ""),
                          reported_by=message.sender, source=source)
        self._finish(parcel_id, message)

    # ------------------------------------------------------------- the promise
    def reprice(self, parcel, service: str, tick: Optional[int] = None) -> bool:
        """
        Re-make the promise on the service the scanner actually read.

        The gate reads the label the way a person does and promises on that.
        The scanner reads it properly, and when the two disagree the better
        read wins: a parcel the clerk could not price is not left on the
        standard departure for the rest of its life, and one the clerk read as
        express does not keep an express promise if the line says otherwise.

        Only ever revised to what the label says, never to what is convenient.
        A facility that could quietly move its own deadlines would have no
        deadlines, and the lateness figure would measure nothing.
        """
        board = getattr(self.world.env, "departures", None)
        if board is None or not parcel.route_label or not service:
            return False
        grade = SERVICE_GRADE.get(str(service).upper())
        if grade is None:
            return False
        booked = parcel.timestamps.get("received", tick if tick is not None
                                       else self.tick)
        revised = board.promise_for(grade, booked, parcel.route_label)
        if revised == parcel.due_by:
            return False
        was, parcel.due_by = parcel.due_by, revised
        parcel.record(tick if tick is not None else self.tick, self.agent_id,
                      "promise_revised", was=was, now=revised, service=service,
                      grade=grade)
        self.world.logger.emit(
            EventCategory.PARCEL, "promise_revised",
            tick=tick if tick is not None else self.tick, actor=self.agent_id,
            correlation_id=parcel.parcel_id, parcel_id=parcel.parcel_id,
            was=was, now=revised, service=service)
        return True

    # -------------------------------------------------------------- outbound
    def _finish(self, parcel_id: str, last: Message) -> None:
        job = self._jobs.pop(parcel_id, {})
        parcel = self.world.env.parcels[parcel_id]
        task = self.world.tasks.get(job.get("task_id", ""))
        if task is not None and task.is_open:
            task.complete(self.tick, self.agent_id,
                          destination=parcel.destination.value,
                          priority=parcel.priority.value)
            self.world.tasks.record_transition(task, self.tick, "task_completed",
                                               actor=self.agent_id)
        self.classified += 1
        self.world.logger.emit(
            EventCategory.PARCEL, "parcel_classified", tick=self.tick,
            actor=self.agent_id, correlation_id=parcel_id,
            parcel_id=parcel_id, priority=parcel.priority.value,
            destination=parcel.destination.value if parcel.destination else None,
            route=parcel.route_label,
        )
        self.send(self.parent_id, MessageType.TASK_COMPLETED,
                  {"task_id": job.get("task_id"), "parcel_id": parcel_id,
                   "priority": parcel.priority.value,
                   "destination": parcel.destination.value,
                   "route": parcel.route_label},
                  correlation_id=parcel_id,
                  text=(f"{parcel_id} is {parcel.priority.value}, bound for "
                        f"{parcel.destination.value} ({parcel.route_label})."))

    def _return_to_sender(self, parcel_id: str, reason: str) -> None:
        """
        The parcel was accepted and cannot be sorted. It leaves, going back.

        The promise goes with it. A facility that could not read the address
        never had a chance to meet the departure it sold, and leaving the
        deadline in place would score the parcel late forever against a service
        nobody could have performed -- which is noise in the one figure that is
        supposed to mean something.
        """
        parcel = self.world.env.parcels.get(parcel_id)
        if parcel is not None:
            parcel.due_by = None
            parcel.set_status(ParcelStatus.RETURNED, self.tick, self.agent_id,
                              reason=reason)
            self.world.logger.emit(
                EventCategory.PARCEL, "parcel_returned", tick=self.tick,
                actor=self.agent_id, correlation_id=parcel_id,
                parcel_id=parcel_id, reason=reason)
            self.world.env.remove_parcel(parcel_id, dispatched=False,
                                         returned=True)
        self._give_up(parcel_id, reason)

    def _give_up(self, parcel_id: str, reason: str) -> None:
        job = self._jobs.pop(parcel_id, {})
        task = self.world.tasks.get(job.get("task_id", ""))
        if task is not None and task.is_open:
            task.fail(self.tick, self.agent_id, reason=reason)
            self.world.tasks.record_transition(task, self.tick, "task_failed",
                                               actor=self.agent_id, reason=reason)
        self.send(self.parent_id, MessageType.TASK_FAILED,
                  {"task_id": job.get("task_id"), "parcel_id": parcel_id,
                   "reason": reason},
                  correlation_id=parcel_id,
                  text=f"Cannot classify {parcel_id}: {reason}")

    # ----------------------------------------------------------------- state
    def state(self) -> Dict[str, Any]:
        return {
            "classified": self.classified,
            "in_progress": {k: v["stage"] for k, v in sorted(self._jobs.items())},
            "awaiting_subagents": len(self._waiting),
            "subagents": [self.BARCODE, self.PRIORITY,
                          self.DESTINATION],
        }
