"""
The intake agent: the facility's front door.

Before this existed there was no front door at all. A parcel appeared on the
dock already barcoded, the planner noticed it was ARRIVED, and the next thing
that happened to it was sorting reading a label the simulation had printed
itself. Nothing ever received anything, which meant the facility could not
decline a parcel, could not record when it took responsibility for one, and
discovered an unreadable label three round trips into classification.

So intake does two things -- validation and registration -- and the judgement
sits between them, which is the point:

    planner --RECEIVE--> intake
                         intake --> SUB-VALIDATION     (can this be read? do we
                                                        go there?)
                         intake                        (accept it? or not)
                         intake --> SUB-REGISTRATION   (book it in)
                         intake --> planner            (received, or refused)

Both halves are clerical: look at the parcel and say what you found, then note
the time the facility took it on. Deciding whether the facility takes it at all
is not -- it weighs what the validator found against how busy the dock is, and
there is no formula for it. That decision is why this agent has a brain, and it
is the first expert other than the planner to make one of its own.

The order matters and it used to be the wrong way round. Registering is
booking an item into the postal system; doing that before the gate has decided
meant every refused parcel left the building carrying a receipt for a delivery
nobody was going to perform.

A refused parcel leaves. It keeps its record and its reason, it is counted
apart from the parcels that were dispatched, and nothing further happens to it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..communication.directory import AgentKind
from ..communication.events import EventCategory
from ..communication.message import Message, MessageType
from ..environment.parcels import ParcelStatus
from ..tasks.task import TaskStatus, TaskType
from .base import BaseAgent
from .brain import Answer
from .deferral import Deferral, is_pending
from .reasoning import REASONS, Trigger

#: What the gate may answer. Closed, like every other decision in this project,
#: so a model's reply is validated against it and an unusable one falls back to
#: the rule rather than inventing a third outcome.
OUTCOMES = ("ACCEPT", "REFUSE")


class IntakeAgent(BaseAgent):
    """Receives parcels, and decides which ones the facility will take."""

    kind = AgentKind.EXPERT

    VALIDATION = "SUB-VALIDATION"
    REGISTRATION = "SUB-REGISTRATION"

    def __init__(self, agent_id: str = "INTAKE", parent_id: str = "PLANNER",
                 **kw) -> None:
        super().__init__(agent_id, "intake", parent_id=parent_id, **kw)
        self._waiting: Dict[str, Dict[str, Any]] = {}   # request id -> context
        self._jobs: Dict[str, Dict[str, Any]] = {}      # parcel id -> progress
        # Named `accepted`, not `received`: `BaseAgent` already counts inbound
        # messages in `self.received`, and shadowing it made this gate report
        # three receipts per parcel -- its own message traffic wearing the name
        # of its work.
        self.accepted = 0
        self.refused = 0

    # ----------------------------------------------------------------- rules
    def install_triggers(self) -> None:
        """
        When taking a parcel in stops being a formality.

        Routine is a label that can be read, naming a town on the network,
        with a service on it. The clerk glances, stamps it, and the parcel is
        in the system -- which is what happens to the overwhelming majority of
        them, and there is nothing in it for a model to improve.

        What is left is where the interesting judgement has always been. An
        illegible label, a blank destination, a town the facility does not
        serve: each of those is a parcel somebody has to decide about, and
        each of them wants the context around it -- what else is on the dock,
        how much of the label survived, whether the route could be guessed --
        rather than a rule.
        """

        def unreadable(facts):
            if not facts.get("legible", False):
                return Trigger(REASONS.AMBIGUITY, "the label cannot be read")
            return None

        def no_destination(facts):
            if not str(facts.get("declared_route", "") or "").strip():
                return Trigger(REASONS.AMBIGUITY, "no destination on the label")
            return None

        def off_network(facts):
            # Read from the declared route rather than carried as its own
            # fact: the rule already decides membership this way, and two
            # facts that must agree are a third thing to keep in step.
            from .subagents.sorting_subagents import ROUTES

            route = str(facts.get("declared_route", "") or "").strip()
            if route and route not in ROUTES:
                return Trigger(REASONS.CONFLICT,
                               f"{route} is not a route this facility serves")
            return None

        def dock_backing_up(facts):
            waiting = float(facts.get("parcels_on_dock", 0) or 0)
            if waiting >= 12:
                return Trigger(REASONS.CONTENTION,
                               f"{waiting:.0f} parcels on the dock")
            return None

        self.triggers.register("accept_parcel", unreadable)
        self.triggers.register("accept_parcel", no_destination)
        self.triggers.register("accept_parcel", off_network)
        self.triggers.register("accept_parcel", dock_backing_up)

    def install_rules(self) -> None:
        """
        The deterministic answer, and the fallback under any model.

        Turn a parcel away when its label cannot be read, and take it
        otherwise. Deliberately narrow: a facility that refuses parcels for
        subtler reasons is exactly the judgement a model is here to make, and a
        rule that guessed at those would make the comparison meaningless.
        """
        rules = self.rules()
        if rules is None:
            return

        def judge(question):
            """
            What the gate makes of the information the parcel arrived with.

            It used to read one fact of the five it was given -- whether the
            label scanned -- and the generator never prints an unreadable one,
            so in a normal run this decision had exactly one outcome and the
            other four facts were decoration. A gate that cannot decline
            anything is not a gate.
            """
            from .brain import Answer
            from .subagents.sorting_subagents import ROUTES

            facts = question.facts
            if not facts.get("legible", True):
                return Answer("REFUSE", "the label will not read")

            route = str(facts.get("declared_route", "") or "")
            if route and route not in ROUTES:
                return Answer("REFUSE", f"{route} is not a route this facility "
                                        "serves")

            # The dock is finite and the parcels already on it are committed.
            # Taking a bulky one onto a dock that is backed up is how a
            # facility ends up unable to move the parcels it already accepted.
            on_dock = int(facts.get("parcels_on_dock", 0) or 0)
            size = str(facts.get("size", "SMALL")).upper()
            if on_dock >= 18 and size == "LARGE":
                return Answer("REFUSE", f"{on_dock} already on the dock and no "
                                        "room to work a LARGE parcel")

            return Answer("ACCEPT", f"{size.lower()} parcel for "
                                    f"{route or 'an unnamed route'}")

        rules.register("accept_parcel", judge)

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
        if task is not None and task.can(TaskStatus.ASSIGNED):
            task.assign(self.agent_id, self.tick, self.agent_id)
            task.start(self.tick, self.agent_id)

        self._jobs[parcel_id] = {"task_id": task_id,
                                 "asked_by": message.sender}
        self.reply(message, MessageType.TASK_ACCEPTED,
                      {"task_id": task_id, "parcel_id": parcel_id})
        self._ask(self.VALIDATION, parcel_id, {"parcel_id": parcel_id})

    def _ask(self, sub_agent: str, parcel_id: str,
             content: Dict[str, Any]) -> None:
        sent = self.send(sub_agent, MessageType.SUBTASK_REQUEST, content,
                         correlation_id=parcel_id)
        if sent is not None:
            self._waiting[sent.message_id] = {"parcel_id": parcel_id,
                                              "sub_agent": sub_agent}

    def _sub_result(self, message: Message) -> None:
        context = self._waiting.pop(message.in_reply_to or "", None)
        if context is None:
            return
        content = message.content
        parcel_id = content.get("parcel_id", "")
        parcel = self.world.env.parcels.get(parcel_id)
        if parcel is None or parcel_id not in self._jobs:
            return
        operation = content.get("operation", "")

        if operation == "register":
            # The second clerk has booked it in. Everything that makes the
            # acceptance real -- the status, the promise -- is written here,
            # because writing the parcel record is the expert's job and not a
            # sub-agent's.
            job = self._jobs.get(parcel_id, {})
            self._accept(parcel_id, job.get("reason", ""),
                         job.get("town", ""), job.get("service", ""))
            return

        if operation != "validate":
            return

        # What the validator made of the address: what a person at the dock can
        # tell without a scanner. Coarser than the machine read sorting does a
        # stage later, and deliberately so -- a clerk reads round a smudge, and
        # this is only deciding whether the facility takes the parcel at all.
        # The clerk reads, the gate judges: this agent does not read the
        # address a second time.
        answer = self.decide(
            "accept_parcel",
            f"Parcel {parcel_id} has arrived at the dock. Does the facility "
            "take it?",
            options=OUTCOMES,
            correlation_id=parcel_id,
            legible=bool(content.get("legible", False)),
            declared_route=str(content.get("declared_route", "") or ""),
            size=content.get("size", ""),
            parcels_on_dock=len(self.world.env.parcels_in(parcel.current_zone)),
            deferral=self._acceptance_deferral(parcel_id, content),
        )
        if is_pending(answer):
            # The parcel waits on the dock, received but not booked in, until
            # the model has said whether the facility takes it.
            return
        self._accept_or_refuse(parcel_id, content, answer)

    def _acceptance_deferral(self, parcel_id: str,
                             content: Dict[str, Any]) -> Deferral:
        """
        Finishing an `accept_parcel` the model answers after the tick.

        Applicable while the parcel is still on the dock and still this
        agent's job; a parcel that has gone -- or been booked in some other
        way -- has no acceptance left to decide.
        """
        def still_valid(answer: Answer) -> str:
            parcel = self.world.env.parcels.get(parcel_id)
            if parcel is None or parcel_id not in self._jobs:
                return f"{parcel_id} is no longer at intake"
            if parcel.status is not ParcelStatus.ARRIVED:
                return f"{parcel_id} is {parcel.status.value} now"
            return ""

        def reevaluate(why: str) -> None:
            if self.world.env.parcels.get(parcel_id) is not None \
                    and parcel_id in self._jobs:
                self._ask(self.VALIDATION, parcel_id, {"parcel_id": parcel_id})

        return Deferral(key=parcel_id,
                        apply=lambda answer: self._accept_or_refuse(
                            parcel_id, content, answer),
                        still_valid=still_valid, reevaluate=reevaluate)

    def _accept_or_refuse(self, parcel_id: str, content: Dict[str, Any],
                          answer: Answer) -> None:
        """Carry out an `accept_parcel` answer."""
        if str(answer.choice).upper() == "REFUSE":
            self.refuse(parcel_id, answer.reason)
            return

        # Accepted. Now, and only now, is it booked into the postal system.
        job = self._jobs.get(parcel_id)
        if job is not None:
            job["reason"] = answer.reason
            job["town"] = str(content.get("declared_route", "") or "")
            job["service"] = str(content.get("declared_service", "") or "")
        self._ask(self.REGISTRATION, parcel_id, {"parcel_id": parcel_id})

    # --------------------------------------------------------------- outcomes
    def _accept(self, parcel_id: str, reason: str,
                town: str = "", service: str = "") -> None:
        self._town = town
        job = self._jobs.pop(parcel_id, {})
        parcel = self.world.env.parcels.get(parcel_id)
        if parcel is None:
            return
        # The promise, made at the moment the facility takes responsibility.
        # Derived from the timetable rather than invented as a duration: the
        # service the customer paid for buys a place on the next van for their
        # route, or the second, or the fourth. A parcel accepted a second after
        # a van pulled away is promised the one after it, which is exactly the
        # trouble a real hub has to work around.
        # The promise is made on what the gate could read: the town it is for
        # and the service the sender paid for, both written on the same line.
        # The gate used to drop the service and promise everything the standard
        # departure, which meant express and urgent bought nothing at all --
        # and since the task queue is earliest-deadline-first, the grade never
        # reached the scheduler either. A parcel whose service the clerk cannot
        # make out is promised the standard departure until the scanner reads
        # it properly, and sorting revises it then.
        board = getattr(self.world.env, "departures", None)
        route = self._town
        if board is not None and route:
            parcel.due_by = board.promise_for(service or "NORMAL",
                                              self.tick, route)
        parcel.set_status(ParcelStatus.REGISTERED, self.tick, self.agent_id,
                          reason=reason, due_by=parcel.due_by,
                          service=service or "STD",
                          route=parcel.route_label)
        self.accepted += 1
        self.world.logger.emit(EventCategory.PARCEL, "parcel_received",
                               tick=self.tick, actor=self.agent_id,
                               correlation_id=parcel_id, parcel_id=parcel_id,
                               reason=reason)
        self._close(job, parcel_id, ok=True, reason=reason)

    def refuse(self, parcel_id: str, reason: str) -> bool:
        """
        Turn a parcel away. Public, because an operator may do it too.

        Terminal: the parcel leaves the floor with its reason on it and is
        counted apart from the ones that were dispatched, so "we handled four
        hundred and turned nine away" stays a different sentence from "we
        handled four hundred and nine".
        """
        env = self.world.env
        parcel = env.parcels.get(parcel_id)
        if parcel is None:
            return False
        job = self._jobs.pop(parcel_id, {})
        parcel.set_status(ParcelStatus.REFUSED, self.tick, self.agent_id,
                          reason=reason)
        self.refused += 1
        self.world.logger.emit(EventCategory.PARCEL, "parcel_refused",
                               tick=self.tick, actor=self.agent_id,
                               correlation_id=parcel_id, parcel_id=parcel_id,
                               reason=reason)
        env.remove_parcel(parcel_id, dispatched=False)
        self._close(job, parcel_id, ok=False, reason=reason)
        return True

    def _close(self, job: Dict[str, Any], parcel_id: str, ok: bool,
               reason: str) -> None:
        """Finish the task and tell the planner, whichever way it went."""
        task_id = job.get("task_id", "")
        task = self.world.tasks.get(task_id) if task_id else None
        if task is not None and task.is_open:
            if ok:
                task.complete(self.tick, self.agent_id, parcel_id=parcel_id)
            else:
                task.fail(self.tick, self.agent_id, reason=reason)
        target = job.get("asked_by") or self.parent_id
        self.send(target,
                  MessageType.TASK_COMPLETED if ok else MessageType.TASK_FAILED,
                  {"task_id": task_id, "parcel_id": parcel_id,
                   "reason": reason},
                  correlation_id=parcel_id,
                  text=(f"{parcel_id} received" if ok
                        else f"{parcel_id} refused: {reason}"))

    # ---------------------------------------------------------------- report
    def state(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "refused": self.refused,
            "in_progress": sorted(self._jobs),
            "awaiting_subagents": len(self._waiting),
            "subagents": [self.VALIDATION, self.REGISTRATION],
        }
