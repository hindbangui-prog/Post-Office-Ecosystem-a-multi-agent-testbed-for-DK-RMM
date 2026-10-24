"""
The dispatch agent: the facility's back door.

The mirror of intake, and it was missing for the same reason. A robot set a
parcel down in the dispatch zone, the scheduler turned it into DISPATCHED and
removed it from the building in the same tick, and that was the whole of
departure. Nothing handed anything over, and -- more to the point -- there was
no moment at which a parcel existed at the door, so there was nothing anybody
could decide about it.

Now a delivered parcel waits, and leaving happens in the two steps a real
facility performs:

    planner --RELEASE--> dispatch
                         dispatch --> SUB-MANIFEST   (book it out)
                         dispatch                    (send it now? or hold it)
                         dispatch --> SUB-PACKING    (into the bag for its route)
                         dispatch                    (hand the bag to the van)
                         dispatch --> planner        (gone, or still waiting)

Packing and bagging is the grouping: parcels sharing an origin -- this building
-- a destination and a mail class go into one receptacle, so the next hub
receives a labelled bag rather than a van floor to re-sort. Handover is the
bag going onto the outbound van. The gate used to load loose parcels one at a
time, which meant the last step of a sorting process was not in the model at
all and a van was a bucket of unrelated parcels going roughly the same way.

Manifesting and packing are both clerical: is the parcel complete, does it have
a route, which bag does it belong in. Whether it goes *now* is the judgement --
an urgent parcel alone is worth sending on its own, a standard one may be worth
holding while others for the same route catch up, and the cost of being wrong
is either a wasted trip or a missed deadline. There is no formula for that,
which is why this agent has a brain.

Holding is bounded by the rule underneath: a parcel that has waited long
enough goes regardless of what anything else thinks, so nothing can be held
forever by a model having a bad day.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..communication.directory import AgentKind
from ..communication.events import EventCategory
from ..communication.message import Message, MessageType
from ..environment.parcels import ParcelStatus
from ..tasks.task import TaskStatus
from .base import BaseAgent
from .brain import Answer
from .deferral import Deferral, is_pending
from .reasoning import REASONS, Trigger

#: Closed, like every other decision here, so a reply that is neither is a
#: fallback rather than a third outcome nothing downstream understands.
OUTCOMES = ("RELEASE", "HOLD")

#: How long a parcel may be held before it goes anyway. The ceiling on the
#: judgement rather than the judgement itself: without it a model that answered
#: HOLD every time would quietly stop the facility dispatching anything, and
#: the run would look like a throughput collapse rather than a bad decision.
MAX_HOLD_TICKS = 25

#: How close to a departure a bag is handed over regardless of how full it is,
#: by the class of post inside it.
#:
#: The induction moment: a bag still being filled at the cut-off is a bag that
#: misses the van, so the room stops filling it and puts it on board.
#:
#: One number per class, because consolidation is a saving standard post can
#: afford and priority post cannot. There are few urgent parcels and they
#: rarely share a destination, so an urgent bag holds about one parcel and
#: never fills -- and while this was a single number it therefore waited for
#: the cut-off exactly like a bag of standard post. Urgent came out of the back
#: door *slower* than standard, which is the opposite of what was sold. A
#: priority receptacle holding one parcel is a complete receptacle: the thing
#: the customer paid for is that it leaves, not that it travels in company.
#:
#: Urgent's lead is longer than any interval, which is how "the moment there is
#: a van" is said in the same units as the others.
HANDOVER_LEAD = {
    "URGENT": 10 ** 9,   # immediately: whatever van is at the bay takes it
    "EXPRESS": 240,      # consolidates a little, still goes well before the cut-off
    "NORMAL": 60,        # the cut-off, as before
}


class DispatchAgent(BaseAgent):
    """Releases parcels from the facility, or holds them a little longer."""

    kind = AgentKind.EXPERT

    MANIFEST = "SUB-MANIFEST"
    PACKING = "SUB-PACKING"

    def __init__(self, agent_id: str = "DISPATCH", parent_id: str = "PLANNER",
                 **kw) -> None:
        super().__init__(agent_id, "dispatch", parent_id=parent_id, **kw)
        self._waiting: Dict[str, Dict[str, Any]] = {}   # request id -> context
        self._asked: set = set()                        # parcels being judged
        self.released = 0
        self.held = 0
        #: Parcels put into a bag. The first of the two steps out.
        self.packed = 0
        #: Bags handed to a van. The second, and the one that is a handover.
        self.handed_over = 0
        #: Parcels actually put on a van, via their bag. `released` is the
        #: gate's decision; this is what fitted.
        self.loaded = 0
        #: What went out, in order. The facility's record of its own day.
        self.manifest: List[Dict[str, Any]] = []
        #: Why each released parcel was released, held between the judgement
        #: and the clerk coming back with a bag for it.
        self._release_reason: Dict[str, str] = {}

    # ----------------------------------------------------------------- rules
    def install_triggers(self) -> None:
        """
        When loading a van stops being a rule about mail class.

        Routine is a van with room, a promise comfortably ahead of the
        cut-off, and nothing else contending for the space. Load it or hold it
        for company, per the standing rule, and be done.

        Three things make it a judgement. A van with less room than the
        parcels waiting for it is a choice about which ones travel. A promise
        that falls due before the next departure is a choice between breaking
        it and sending a van half empty. And a parcel already past its promise
        is not a scheduling question at all -- it is a question about what to
        do for a customer who has already been let down, which is exactly the
        sort of thing there is no good rule for.
        """

        def past_the_promise(facts):
            left = facts.get("ticks_to_deadline")
            if left is not None and float(left) < 0:
                return Trigger(REASONS.DEADLINE,
                               f"{abs(float(left)):.0f} ticks late already")
            return None

        def promise_before_departure(facts):
            left = facts.get("ticks_to_deadline")
            until = facts.get("ticks_to_departure")
            if left is None or until is None:
                return None
            if float(left) < float(until):
                return Trigger(REASONS.CONFLICT,
                               f"due in {float(left):.0f}, van goes in "
                               f"{float(until):.0f}")
            return None

        def van_too_small(facts):
            free = facts.get("van_free_units")
            waiting = facts.get("same_route_waiting")
            if free is None or waiting is None:
                return None
            if float(waiting) > float(free):
                return Trigger(REASONS.CONTENTION,
                               f"{float(waiting):.0f} waiting for "
                               f"{float(free):.0f} units of space")
            return None

        self.triggers.register("release_parcel", past_the_promise)
        self.triggers.register("release_parcel", promise_before_departure)
        self.triggers.register("release_parcel", van_too_small)

    def install_rules(self) -> None:
        """
        Send it, unless it is standard and has company coming.

        The deterministic answer and the fallback under any model: hold a
        NORMAL parcel briefly when others are already waiting for the same
        route, and send anything urgent, anything alone, and anything that has
        waited long enough.
        """
        rules = self.rules()
        if rules is None:
            return

        def judge(question):
            from .brain import Answer

            facts = question.facts
            deadline = facts.get("ticks_to_deadline")
            to_departure = int(facts.get("ticks_to_departure", 0) or 0)
            free = facts.get("van_free_units")

            # A van without room for *this* parcel cannot take it, however
            # good the reasons. Size matters: a van with two units left has
            # room for a small parcel and none for a large one.
            units = {"SMALL": 1, "MEDIUM": 2, "LARGE": 3}.get(
                str(facts.get("size", "SMALL")).upper(), 1)
            if free is not None and int(free) < units:
                return Answer("HOLD", f"this van has {free} units left and the "
                                      f"parcel needs {units}")

            # The promise beats every other consideration. Holding a parcel
            # that would miss its departure, because two others happen to be
            # going the same way, is a promise broken for a saving nobody
            # asked for -- and this rule used to do exactly that, because it
            # was handed the deadline and never read it.
            if deadline is not None and int(deadline) <= to_departure:
                return Answer("RELEASE", "it misses its promise otherwise")

            if int(facts.get("waiting_ticks", 0)) >= MAX_HOLD_TICKS:
                return Answer("RELEASE", "it has waited long enough")
            if facts.get("priority") in ("URGENT", "EXPRESS"):
                return Answer("RELEASE", "urgent parcels do not wait")
            if int(facts.get("same_route_waiting", 0)) >= 2:
                return Answer("HOLD", "others are going the same way")
            return Answer("RELEASE", "nothing to wait for")

        rules.register("release_parcel", judge)

    # --------------------------------------------------------------- inbound
    def handle(self, message: Message) -> None:
        if message.message_type is MessageType.SUBTASK_RESULT:
            self._sub_result(message)

    # ------------------------------------------------------------- unprompted
    def tick_work(self) -> None:
        """
        Look at the back door.

        Unlike sorting, this agent is not driven by an assignment: a parcel
        arrives at the door because a robot put it there, and nobody tells the
        gate. So it watches, the way the resource agent watches batteries.
        """
        if self.world is None:
            return
        # The bags first: a van about to leave takes whatever is ready before
        # any new parcel is considered, so nothing misses a departure it was
        # packed in time for.
        self._hand_over_ready()
        for parcel in self._at_the_door():
            if parcel.parcel_id in self._asked:
                continue
            self._asked.add(parcel.parcel_id)
            self._ask(parcel.parcel_id)

    def _at_the_door(self):
        """
        Waiting to be dealt with.

        A parcel already in a bag is not: packing is the moment it stops being
        loose at the door and becomes part of an outbound batch, and asking the
        clerk about it again would put it in a second bag.
        """
        return [p for p in self.world.env.parcels.values()
                if p.status is ParcelStatus.AWAITING_DISPATCH
                and not p.loaded_on and not p.bagged_in]

    def _ask(self, parcel_id: str, sub_agent: str = "") -> None:
        sent = self.send(sub_agent or self.MANIFEST,
                         MessageType.SUBTASK_REQUEST,
                         {"parcel_id": parcel_id}, correlation_id=parcel_id)
        if sent is not None:
            self._waiting[sent.message_id] = {"parcel_id": parcel_id}
        else:
            self._asked.discard(parcel_id)

    def _sub_result(self, message: Message) -> None:
        context = self._waiting.pop(message.in_reply_to or "", None)
        if context is None:
            return
        content = message.content
        parcel_id = content.get("parcel_id", "")
        parcel = self.world.env.parcels.get(parcel_id)
        operation = content.get("operation", "")

        if operation == "pack":
            self._asked.discard(parcel_id)
            self._packed(parcel_id, content)
            return

        self._asked.discard(parcel_id)
        if parcel is None or operation != "manifest":
            return
        if parcel.status is not ParcelStatus.AWAITING_DISPATCH:
            return

        route = content.get("route", "")
        if not content.get("ok", False):
            # No route on it. Sending it nowhere is worse than keeping it, so
            # it stays at the door and the planner is told why.
            self.held += 1
            self.send(self.parent_id, MessageType.TASK_FAILED,
                      {"parcel_id": parcel_id,
                       "reason": content.get("reason", "not ready to go")},
                      correlation_id=parcel_id,
                      text=f"{parcel_id} cannot be released: "
                           f"{content.get('reason', '')}")
            return

        waiting = int(content.get("waiting_ticks", 0))
        board = self.world.env.departures
        van = board.at_bay(route) if board is not None else None
        if van is None:
            # Nothing going that way is standing at the bay. Not a judgement --
            # there is nothing to load onto.
            self.held += 1
            return

        answer = self.decide(
            "release_parcel",
            f"Parcel {parcel_id} is at the dispatch door for {route}. The van "
            f"there leaves at tick {van.departs_at}. Load it, or hold it for "
            "the next one?",
            options=OUTCOMES,
            correlation_id=parcel_id,
            priority=content.get("priority", "NORMAL"),
            route=route,
            size=content.get("size", ""),
            waiting_ticks=waiting,
            same_route_waiting=self._same_route(route, parcel_id),
            # The two facts that make this a judgement rather than a timer:
            # how long until this van goes, and how long until the parcel is
            # late. Holding past the second is a promise broken on purpose.
            ticks_to_departure=max(0, van.departs_at - self.tick),
            ticks_to_deadline=(None if parcel.due_by is None
                               else parcel.due_by - self.tick),
            van_free_units=van.free,
            deferral=self._release_deferral(parcel_id, route, waiting, van),
        )
        if is_pending(answer):
            # Held at the door, which is what the gate does with a parcel it
            # has not decided about, and kept off the list of parcels to ask
            # about again until the model has answered.
            self._asked.add(parcel_id)
            return
        self._release_or_hold(parcel_id, route, waiting, van, answer)

    def _release_or_hold(self, parcel_id: str, route: str, waiting: int, van,
                         answer: Answer) -> None:
        """Carry out a `release_parcel` answer."""
        parcel = self.world.env.parcels[parcel_id]
        if str(answer.choice).upper() == "HOLD" and waiting < MAX_HOLD_TICKS:
            self.held += 1
            parcel.record(self.tick, self.agent_id, "held",
                          reason=answer.reason, waiting_ticks=waiting,
                          vehicle=van.vehicle_id)
            return
        self._release(parcel_id, route, answer.reason)

    def _release_deferral(self, parcel_id: str, route: str, waiting: int,
                          van) -> Deferral:
        """
        Finishing a `release_parcel` the model answers after the tick.

        The question was about one parcel and one van. If the parcel has been
        bagged or moved, or that van has left the bay, the answer is about a
        departure that is no longer on offer; the parcel goes back on the list
        and is asked about afresh.
        """
        def still_valid(answer: Answer) -> str:
            parcel = self.world.env.parcels.get(parcel_id)
            if parcel is None or parcel.status is not ParcelStatus.AWAITING_DISPATCH \
                    or parcel.bagged_in or parcel.loaded_on:
                return f"{parcel_id} is no longer loose at the door"
            board = self.world.env.departures
            now = board.at_bay(route) if board is not None else None
            if now is None or now.vehicle_id != van.vehicle_id:
                return f"{van.vehicle_id} has left the {route} bay"
            return ""

        def settle(answer: Answer) -> None:
            self._asked.discard(parcel_id)
            self._release_or_hold(parcel_id, route, waiting, van, answer)

        return Deferral(key=parcel_id, apply=settle,
                        still_valid=still_valid,
                        reevaluate=lambda why: self._asked.discard(parcel_id))

    # ------------------------------------------------ packing and bagging
    def _release(self, parcel_id: str, route: str, reason: str) -> None:
        """
        The gate has decided the parcel goes. Pack it.

        Releasing is no longer the same act as loading. The parcel goes into
        the bag for its destination and class, and the bag goes to a van when
        it is full or when its van is nearly away -- which is the order a real
        facility works in, and the reason a driver receives sorted receptacles
        rather than a heap.
        """
        self.released += 1
        self._release_reason[parcel_id] = reason
        self._asked.add(parcel_id)
        self._ask(parcel_id, self.PACKING)

    def _packed(self, parcel_id: str, content: Dict[str, Any]) -> None:
        """The clerk has bagged it. Decide whether the bag goes now."""
        parcel = self.world.env.parcels.get(parcel_id)
        reason = self._release_reason.pop(parcel_id, "")
        if parcel is None:
            return
        if not content.get("ok"):
            # Nothing to pack it into. It stays at the door, which is better
            # than a parcel in no bag being counted as on its way.
            self.held += 1
            self.released = max(0, self.released - 1)
            parcel.record(self.tick, self.agent_id, "not_packed",
                          reason=content.get("reason", "no bag for it"))
            return

        bag_id = str(content.get("receptacle", ""))
        parcel.bagged_in = bag_id
        self.packed += 1
        self.world.logger.emit(EventCategory.PARCEL, "parcel_packed",
                               tick=self.tick, actor=self.agent_id,
                               correlation_id=parcel_id, parcel_id=parcel_id,
                               receptacle=bag_id,
                               route=content.get("route", ""),
                               mail_class=content.get("mail_class", ""),
                               reason=reason)
        self._hand_over_ready(str(content.get("route", "")))

    def _hand_over_ready(self, route: str = "") -> None:
        """
        Put on the van every bag that is ready to go, for one route or all.

        Two things make a bag ready and neither is a judgement: it is full, or
        its van is near enough away. The gate already decided that the parcels
        inside are going; when the receptacle physically moves is a matter of
        the timetable and of what was paid for -- "near enough" is a different
        number for urgent post than for standard, and that is the whole of the
        difference the back door makes between them.
        """
        env = self.world.env
        room, board = env.bags, env.departures
        if room is None or board is None:
            return
        routes = [route] if route else list(
            {b.route for b in room.open_bags()}
            | {b.route for b in room.waiting()})
        for one in routes:
            van = board.at_bay(one)
            if van is None:
                continue
            until = van.departs_at - self.tick
            for bag in list(room.open_bags()):
                if bag.route != one:
                    continue
                lead = HANDOVER_LEAD.get(bag.mail_class, HANDOVER_LEAD["NORMAL"])
                if bag.is_full or until <= lead:
                    room.seal(bag, self.tick)
            for bag in room.waiting(one):
                self._hand_over(bag, van)

    def _hand_over(self, bag, van) -> None:
        """
        The handover: one sealed bag onto one van, whole or not at all.

        Half a bag on this van and half on the next is the thing bagging exists
        to prevent, so a bag that will not fit waits for the next van rather
        than being split across two.
        """
        if bag.loaded_on or van.has_gone or bag.units > van.free:
            return
        env = self.world.env
        for parcel_id in bag.parcel_ids:
            parcel = env.parcels.get(parcel_id)
            units = parcel.size.units if parcel is not None else 1
            if not van.load(parcel_id, units):
                return
            if parcel is not None:
                parcel.loaded_on = van.vehicle_id
                parcel.record(self.tick, self.agent_id, "loaded",
                              vehicle=van.vehicle_id, receptacle=bag.receptacle_id,
                              departs_at=van.departs_at)
            self.loaded += 1
            self.manifest.append({"parcel_id": parcel_id, "route": bag.route,
                                  "tick": self.tick, "vehicle": van.vehicle_id,
                                  "receptacle": bag.receptacle_id,
                                  "departs_at": van.departs_at,
                                  "priority": bag.mail_class})
        bag.loaded_on = van.vehicle_id
        self.handed_over += 1
        self.world.logger.emit(EventCategory.PARCEL, "bag_handed_over",
                               tick=self.tick, actor=self.agent_id,
                               correlation_id=bag.receptacle_id,
                               receptacle=bag.receptacle_id, route=bag.route,
                               mail_class=bag.mail_class,
                               parcels=bag.count, units=bag.units,
                               vehicle=van.vehicle_id,
                               departs_at=van.departs_at)
        self.send(self.parent_id, MessageType.TASK_COMPLETED,
                  {"receptacle": bag.receptacle_id, "route": bag.route,
                   "vehicle": van.vehicle_id, "parcels": bag.count},
                  correlation_id=bag.receptacle_id,
                  text=(f"{bag.receptacle_id} ({bag.count} for {bag.route}, "
                        f"{bag.mail_class}) handed to {van.vehicle_id}, "
                        f"leaving at {van.departs_at}"))

    def _same_route(self, route: str, except_id: str) -> int:
        return sum(1 for p in self._at_the_door()
                   if p.parcel_id != except_id and p.route_label == route)

    # ---------------------------------------------------------------- report
    def state(self) -> Dict[str, Any]:
        room = self.world.env.bags if self.world is not None else None
        return {
            "released": self.released,
            "packed": self.packed,
            "handed_over": self.handed_over,
            "loaded": self.loaded,
            "held": self.held,
            "at_the_door": sorted(p.parcel_id for p in self._at_the_door())
            if self.world is not None else [],
            "bags": room.summary() if room is not None else {},
            "awaiting_subagents": len(self._waiting),
            "subagents": [self.MANIFEST, self.PACKING],
        }
