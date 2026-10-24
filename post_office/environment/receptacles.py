"""
Receptacles: the bags, trays and containers a facility actually hands over.

A sorting hub does not give a driver a pile of parcels. It packs them into a
receptacle holding items that share an origin, a destination and a mail class,
seals it, and hands the receptacle over -- so the next hub down the line
receives one labelled bag for its own area rather than a van floor to re-sort.
That grouping is the point of the whole sort: every step upstream exists to get
a parcel into the right bag before the right van leaves.

The model had no representation of it. The dispatch gate loaded parcels onto a
van one at a time, which meant "batching", the last step of a real sorting
process, happened nowhere, and a van was a bucket of unrelated parcels that
happened to be going the same way.

Two objects, and both are deliberately dumb:

    Receptacle   one bag: what is in it, whether it is full, whether it is sealed
    BagRoom      the open bags, one per (destination, mail class), and the
                 sealed ones waiting to be handed over

Neither decides anything. Which bag a parcel belongs in follows from what is
written on the parcel, and *when* a bag goes is the dispatch gate's judgement.
This module only knows what a bag is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

#: Size units per bag, in the units a parcel is measured in (SMALL 1, MEDIUM 2,
#: LARGE 3). Six is about three or four average parcels: small enough that bags
#: fill and turn over during a run you can watch, large enough that grouping is
#: worth doing rather than one bag per parcel.
DEFAULT_CAPACITY = 6


@dataclass
class Receptacle:
    """One bag: one destination, one mail class, and what is inside it."""

    receptacle_id: str
    route: str
    mail_class: str
    capacity: int = DEFAULT_CAPACITY
    parcel_ids: List[str] = field(default_factory=list)
    units: int = 0
    opened_at: int = 0
    sealed_at: Optional[int] = None
    #: The van it was handed to. Empty until handover, and the only way a bag
    #: leaves the building.
    loaded_on: str = ""

    # ------------------------------------------------------------------ state
    @property
    def count(self) -> int:
        return len(self.parcel_ids)

    @property
    def free(self) -> int:
        return max(0, self.capacity - self.units)

    @property
    def is_sealed(self) -> bool:
        return self.sealed_at is not None

    @property
    def is_full(self) -> bool:
        """
        Full enough that the smallest parcel would not fit.

        Not "exactly at capacity": a bag with one unit left is full as far as a
        medium parcel is concerned, and the thing worth knowing at the gate is
        whether this bag can still take work.
        """
        return self.free <= 0

    def accepts(self, route: str, mail_class: str) -> bool:
        """Whether this bag is the right one for a parcel, and still open."""
        return (not self.is_sealed
                and not self.is_full
                and self.route == route
                and self.mail_class == mail_class)

    # ------------------------------------------------------------- the work
    def put(self, parcel_id: str, units: int = 1) -> bool:
        """
        Pack one parcel. False when it will not fit or the bag is sealed.

        A refusal rather than an exception, for the same reason a full van
        refuses: a bag filling up is the ordinary case, and what happens next
        -- seal this one, open another -- is the room's business.
        """
        if self.is_sealed or int(units) > self.free:
            return False
        self.parcel_ids.append(parcel_id)
        self.units += int(units)
        return True

    def seal(self, tick: int) -> None:
        """Close the bag. Nothing goes in after this."""
        if self.sealed_at is None:
            self.sealed_at = int(tick)

    def as_dict(self) -> Dict[str, object]:
        return {"receptacle_id": self.receptacle_id, "route": self.route,
                "mail_class": self.mail_class, "capacity": self.capacity,
                "units": self.units, "count": self.count,
                "parcel_ids": list(self.parcel_ids),
                "opened_at": self.opened_at, "sealed_at": self.sealed_at,
                "loaded_on": self.loaded_on}


class BagRoom:
    """
    The open bags, and the sealed ones waiting for a van.

    Owned by the facility rather than by the dispatch agent, for the same
    reason the charge points are: a bag is a physical thing standing on the
    floor, and it should still be there if the gate that opened it stops
    answering.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self.capacity = max(1, int(capacity))
        self._open: Dict[Tuple[str, str], Receptacle] = {}
        self.sealed: List[Receptacle] = []
        self._counter = 0

    # ------------------------------------------------------------- the bags
    def open_bag(self, route: str, mail_class: str,
                 tick: int = 0) -> Receptacle:
        """
        The bag a parcel for this destination and class belongs in.

        Opens one if there is none, which is why this is the only way to get a
        bag: two clerks each starting their own bag for Brno standard is the
        failure this room exists to prevent.
        """
        key = (route, mail_class)
        bag = self._open.get(key)
        if bag is not None and bag.accepts(route, mail_class):
            return bag
        if bag is not None:
            # Full but not yet sealed: it stops being the open bag either way.
            self.seal(bag, tick)
        self._counter += 1
        fresh = Receptacle(receptacle_id=f"B-{self._counter:04d}", route=route,
                           mail_class=mail_class, capacity=self.capacity,
                           opened_at=int(tick))
        self._open[key] = fresh
        return fresh

    def seal(self, bag: Receptacle, tick: int = 0) -> Receptacle:
        """Close a bag and stand it aside for the van."""
        bag.seal(tick)
        key = (bag.route, bag.mail_class)
        if self._open.get(key) is bag:
            self._open.pop(key, None)
        if bag not in self.sealed:
            self.sealed.append(bag)
        return bag

    # ------------------------------------------------------------- the view
    def open_bags(self) -> List[Receptacle]:
        return list(self._open.values())

    def waiting(self, route: str = "") -> List[Receptacle]:
        """Sealed bags nobody has handed over yet, for a route or for all."""
        return [b for b in self.sealed
                if not b.loaded_on and (not route or b.route == route)]

    def all_bags(self) -> List[Receptacle]:
        return list(self.sealed) + self.open_bags()

    def summary(self) -> Dict[str, object]:
        return {
            "open": len(self._open),
            "sealed": len(self.sealed),
            "handed_over": sum(1 for b in self.sealed if b.loaded_on),
            "waiting": len(self.waiting()),
        }
