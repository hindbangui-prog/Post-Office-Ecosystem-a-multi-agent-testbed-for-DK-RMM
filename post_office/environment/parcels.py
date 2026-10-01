"""
Parcels: what the whole facility exists to move.

A parcel carries its own biography. Every hand it passes through appends one
line to `processing_history` and one entry to `timestamps`, so at the end of a
run you can reconstruct exactly which agent touched a parcel, when, and what
they concluded -- without joining anything against the event log. The event log
is the system's memory; this is the parcel's own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from .zones import Zone


class ParcelPriority(str, Enum):
    """How much the parcel is allowed to push in front of the others."""

    NORMAL = "NORMAL"
    EXPRESS = "EXPRESS"
    URGENT = "URGENT"

    @property
    def rank(self) -> int:
        """Higher is more important. Used wherever a queue is ordered."""
        return {"NORMAL": 0, "EXPRESS": 1, "URGENT": 2}[self.value]


class ParcelSize(str, Enum):
    """Bulk. Decides how much of a robot's load a parcel consumes."""

    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"

    @property
    def units(self) -> int:
        return {"SMALL": 1, "MEDIUM": 2, "LARGE": 3}[self.value]


class ParcelStatus(str, Enum):
    """
    Where a parcel is in its life, as distinct from where it is on the floor.

    ARRIVED -> REGISTERED -> CLASSIFIED -> AWAITING_PICKUP -> IN_TRANSIT
    -> then one of STORED / SORTED / AWAITING_DISPATCH, and a stored or sorted
    parcel may be picked up again for its next leg.

    The two ends are gates rather than thresholds. A parcel is REGISTERED
    because the intake gate accepted it, not because somebody read its label in
    passing, and one the facility will not take is REFUSED and goes no further.

    RETURNED is the third ending and the one the model was missing. The door
    reads an address the way a clerk does and the scanner reads it properly, so
    a parcel can pass the door and then defeat the scanner -- and that parcel
    has been accepted, has a promise on it, and cannot be sorted. Without
    somewhere for it to go it stood in the building forever, quietly breaking a
    promise nothing could ever keep. It goes back to the sender instead.
    At the other end AWAITING_DISPATCH is the parcel standing at the back door:
    it has been carried to the dispatch zone and is waiting to be released.
    Without that state there is no moment at which anything can be decided
    about it -- it would become DISPATCHED the instant a robot set it down --
    and a departure gate that cannot hold anything is not a gate.
    """

    ARRIVED = "ARRIVED"                # on the intake dock, nobody has looked
    REGISTERED = "REGISTERED"          # received and booked in by the gate
    CLASSIFIED = "CLASSIFIED"          # destination and priority decided
    AWAITING_PICKUP = "AWAITING_PICKUP"  # a task exists, no robot yet
    IN_TRANSIT = "IN_TRANSIT"          # on a robot
    SORTED = "SORTED"                  # delivered to the sorting area
    STORED = "STORED"                  # delivered to temporary storage
    AWAITING_DISPATCH = "AWAITING_DISPATCH"  # at the back door, not yet released
    DISPATCHED = "DISPATCHED"          # out of the building; terminal
    REFUSED = "REFUSED"                # the facility would not take it; terminal
    RETURNED = "RETURNED"              # taken, then found unworkable; terminal


#: The statuses from which a parcel still needs work doing to it.
#: `AWAITING_DISPATCH` is open: the parcel is in the building and something has
#: still to decide about it. `REFUSED` is not, for the same reason
#: `DISPATCHED` is not -- nothing further will happen to it.
OPEN_STATUSES = frozenset({
    ParcelStatus.ARRIVED, ParcelStatus.REGISTERED, ParcelStatus.CLASSIFIED,
    ParcelStatus.AWAITING_PICKUP, ParcelStatus.IN_TRANSIT,
    ParcelStatus.SORTED, ParcelStatus.STORED, ParcelStatus.AWAITING_DISPATCH,
})


#: How many lines of biography one parcel keeps. A parcel that has been
#: released and re-dispatched thirty times does not need all thirty recorded on
#: itself -- the event log has them, with more context.
MAX_HISTORY = 60


@dataclass
class Parcel:
    """One physical parcel, and everything anyone has ever decided about it."""

    parcel_id: str
    origin: Zone = Zone.INTAKE
    destination: Optional[Zone] = None          # decided by the sorting expert
    priority: ParcelPriority = ParcelPriority.NORMAL
    size: ParcelSize = ParcelSize.SMALL
    status: ParcelStatus = ParcelStatus.ARRIVED
    assigned_robot: Optional[str] = None
    position: Optional["object"] = None          # Position; None while on a robot
    current_zone: Zone = Zone.INTAKE
    #: What is written on the parcel when it is handed over: a town, a
    #: postcode, a service. This is the only thing the facility knows about a
    #: parcel until it reads it.
    address: str = ""
    #: What this facility printed, once it had read the address and decided
    #: where the parcel is going. Empty until then: a parcel carrying a barcode
    #: is one this building has processed.
    barcode: str = ""
    route_label: str = ""                        # the city it is going to
    #: The tick by which this parcel was promised to leave, set by the intake
    #: gate when the facility accepts it. Not a duration: it is a departure on
    #: the timetable, because that is what a carrier actually sells and what a
    #: parcel can actually miss.
    due_by: Optional[int] = None
    #: The receptacle it was packed into at the back door. Empty until the
    #: dispatch gate releases it: a parcel in a bag is committed to the
    #: outbound stream and is no longer standing loose at the door.
    bagged_in: str = ""
    #: The van it left on. Empty until a van takes it, and the only way out of
    #: the building.
    loaded_on: str = ""
    #: Whether the sorting agent has graded this parcel. A parcel coming back
    #: from a shelf for its next leg faces a new destination question and the
    #: same old grade, and this is how sorting knows which of its two questions
    #: is still open. It used to infer that from whether the parcel carried a
    #: route, which stopped working the moment the route was written at the
    #: door instead -- every parcel would have looked already graded.
    priority_set: bool = False
    #: A zone the next errand must pass through on its way to `destination`,
    #: without stopping there. Set for an urgent parcel leaving intake, which
    #: goes through the sorting hall and straight on to the door; None for
    #: every other parcel and every other leg.
    route_via: Optional[Zone] = None
    timestamps: Dict[str, int] = field(default_factory=dict)
    processing_history: List[Dict[str, object]] = field(default_factory=list)

    # ---------------------------------------------------------------- history
    def record(self, tick: int, actor: str, action: str, **detail) -> None:
        """
        Append one line to the parcel's biography.

        `actor` is an agent id, never a function name: the point of this record
        is to answer "who decided that", and a stack trace cannot.
        """
        self.processing_history.append({
            "tick": tick,
            "actor": actor,
            "action": action,
            "status": self.status.value,
            **detail,
        })
        if len(self.processing_history) > MAX_HISTORY:
            head = self.processing_history[:6]
            tail = self.processing_history[-(MAX_HISTORY - 7):]
            elided = len(self.processing_history) - len(head) - len(tail)
            self.processing_history = head + [{
                "tick": tick, "actor": "", "action": "elided",
                "status": self.status.value,
                "note": f"{elided} entries elided"}] + tail

    def stamp(self, name: str, tick: int) -> None:
        """First occurrence wins -- `arrived` should mean the first arrival."""
        self.timestamps.setdefault(name, tick)

    def set_status(self, status: ParcelStatus, tick: int, actor: str,
                   **detail) -> None:
        previous = self.status
        self.status = status
        self.stamp(status.value.lower(), tick)
        self.record(tick, actor, "status_change", previous=previous.value,
                    **detail)

    # ----------------------------------------------------------------- state
    @property
    def is_done(self) -> bool:
        return self.status is ParcelStatus.DISPATCHED

    def late_at(self, tick: int) -> bool:
        """
        Has this parcel missed what it was promised, as of `tick`?

        Two ways to be late and they are the same fact: it left after its
        departure, or it is still here and its departure has gone. A parcel
        with no promise -- one the facility never accepted -- cannot be late.
        """
        if self.due_by is None:
            return False
        left = self.timestamps.get("dispatched")
        if left is not None:
            return left > self.due_by
        return int(tick) > self.due_by

    @property
    def is_late(self) -> bool:
        """Late as judged at the moment it left; open parcels need `late_at`."""
        left = self.timestamps.get("dispatched")
        if self.due_by is None or left is None:
            return False
        return left > self.due_by

    @property
    def dwell(self) -> Optional[int]:
        """Ticks from arrival to dispatch, once it is out of the building."""
        a = self.timestamps.get("arrived")
        d = self.timestamps.get("dispatched")
        return None if a is None or d is None else d - a

    def summary(self) -> dict:
        """Without the biography. What a list of parcels should carry."""
        pos = self.position
        return {
            "parcel_id": self.parcel_id,
            "origin": self.origin.value,
            "destination": self.destination.value if self.destination else None,
            "priority": self.priority.value,
            "size": self.size.value,
            "status": self.status.value,
            "assigned_robot": self.assigned_robot,
            "position": pos.as_dict() if pos is not None else None,
            "current_zone": self.current_zone.value,
            "address": self.address,
            "barcode": self.barcode,
            "route_label": self.route_label,
            "arrived": self.timestamps.get("arrived"),
            "dwell": self.dwell,
            "history_entries": len(self.processing_history),
        }

    def as_dict(self) -> dict:
        pos = self.position
        return {
            "parcel_id": self.parcel_id,
            "origin": self.origin.value,
            "destination": self.destination.value if self.destination else None,
            "priority": self.priority.value,
            "size": self.size.value,
            "status": self.status.value,
            "assigned_robot": self.assigned_robot,
            "position": pos.as_dict() if pos is not None else None,
            "current_zone": self.current_zone.value,
            "barcode": self.barcode,
            "route_label": self.route_label,
            "due_by": self.due_by,
            "bagged_in": self.bagged_in,
            "loaded_on": self.loaded_on,
            "late": self.is_late,
            "timestamps": dict(self.timestamps),
            "processing_history": [dict(h) for h in self.processing_history],
        }
