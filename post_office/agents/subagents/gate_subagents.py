"""
The four clerks at the gates: two take a parcel in, two send it out.

    SUB-VALIDATION    can this be read, and do we even go there
    SUB-REGISTRATION  book it into the postal system
    SUB-MANIFEST      book it out again
    SUB-PACKING       into the bag for its destination and class

All four are deliberately dull, and none of them decides anything -- whether
the facility *accepts* a parcel, and whether one *leaves now*, are judgements,
and they belong to INTAKE and DISPATCH rather than here. That split is the same
one the rest of the project makes: a sub-agent that checks arithmetic or reads
a label is a poor place to spend a model call, and the expert above it is a
good one.

At the front door the two clerks sit either side of that judgement, and the
order is the point. Validation looks at the parcel and reports what it found;
the gate decides; registration books in what the gate kept. Doing it the other
way round -- stamping the parcel as received and deciding afterwards -- meant
every refused parcel left carrying a receipt for a delivery the system was
never going to perform.

Validation reads the address the way a clerk does -- is there something legible
here, is the town one we go to -- and stops there. Turning that address into a
route the machinery can act on is `SUB-BARCODE`'s job a stage later, and it is
a stricter read: the scanner needs the whole line, the clerk only needs enough
to decide whether to take the parcel at all. Two reads of different
strictness, not one read done twice.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ...communication.message import Message
from ..base import SubAgent
from .sorting_subagents import glance


class ValidationSubAgent(SubAgent):
    """
    Looks at a parcel the facility has not yet accepted, and says what it found.

    A check, not a booking: it stamps nothing and changes nothing, because at
    the moment it runs the facility has taken on no responsibility for this
    parcel at all. What it reports -- whether there is a legible address, which
    town it seems to be for, whether that is somewhere this network goes, how
    big the thing is -- is exactly what the gate needs to decide, and no more.
    """

    def __init__(self, parent_id: str, agent_id: str = "SUB-VALIDATION", **kw):
        super().__init__(agent_id, "validation", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        parcel_id = message.content.get("parcel_id", "")
        parcel = self.world.env.parcels.get(parcel_id)
        if parcel is None:
            return {"operation": "validate", "parcel_id": parcel_id,
                    "ok": False, "legible": False,
                    "reason": "no such parcel on the dock"}

        seen = glance(parcel.address)
        legible = bool(seen["legible"])
        # Recorded on the parcel but not stamped: "we looked at it" is a fact
        # about this parcel's day, and the gate's reason will read oddly
        # without it. "Received" is a different claim and is not made here.
        parcel.record(self.tick, self.agent_id, "validated",
                      legible=legible, address=parcel.address,
                      town=seen["town"], on_network=bool(seen["on_network"]))
        return {
            "operation": "validate",
            "parcel_id": parcel_id,
            "ok": legible,
            "legible": legible,
            "address": parcel.address,
            # Reported, not written onto the parcel: the gate wants to know
            # what can be made out so it can judge the parcel, and sorting
            # still does the read that turns an address into a route.
            "declared_route": seen["town"],
            "declared_service": seen.get("service", ""),
            "on_network": bool(seen["on_network"]),
            "size": parcel.size.value,
            "reason": "" if legible else "the label will not read",
            "_text": (f"{parcel_id} looks like it is for {seen['town']}"
                      if legible else
                      f"{parcel_id} arrived with an address that will not read"),
        }


class RegistrationSubAgent(SubAgent):
    """
    Books an accepted parcel into the postal system.

    Asked only after the gate has said yes, which is what makes the stamp mean
    something: `received` is the moment the facility took responsibility, and a
    parcel it turned away never reaches this clerk.
    """

    def __init__(self, parent_id: str, agent_id: str = "SUB-REGISTRATION", **kw):
        super().__init__(agent_id, "registration", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        parcel_id = message.content.get("parcel_id", "")
        parcel = self.world.env.parcels.get(parcel_id)
        if parcel is None:
            return {"operation": "register", "parcel_id": parcel_id,
                    "ok": False, "reason": "no such parcel on the dock"}

        parcel.stamp("received", self.tick)
        parcel.record(self.tick, self.agent_id, "registered",
                      address=parcel.address, size=parcel.size.value)
        return {
            "operation": "register",
            "parcel_id": parcel_id,
            "ok": True,
            "received_at": parcel.timestamps.get("received"),
            "address": parcel.address,
            "size": parcel.size.value,
            "reason": "",
            "_text": f"Registered {parcel_id}, received at tick {self.tick}",
        }


class ManifestSubAgent(SubAgent):
    """Books a parcel out of the facility."""

    def __init__(self, parent_id: str, agent_id: str = "SUB-MANIFEST", **kw):
        super().__init__(agent_id, "manifesting", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        parcel_id = message.content.get("parcel_id", "")
        parcel = self.world.env.parcels.get(parcel_id)
        if parcel is None:
            return {"operation": "manifest", "parcel_id": parcel_id,
                    "ok": False, "reason": "no such parcel at the door"}

        # A parcel with no route has nowhere to be sent, which is the one thing
        # that can be wrong at this end and is worth catching before it leaves
        # rather than after.
        route = parcel.route_label or ""
        waiting = self.tick - (parcel.timestamps.get("awaiting_dispatch")
                               or self.tick)
        return {
            "operation": "manifest",
            "parcel_id": parcel_id,
            "ok": bool(route),
            "route": route,
            "priority": parcel.priority.value,
            "size": parcel.size.value,
            "waiting_ticks": max(0, waiting),
            "reason": "" if route else "no route on the parcel",
            "_text": (f"{parcel_id} is ready for {route}"
                      if route else
                      f"{parcel_id} reached dispatch with no route on it"),
        }


class PackingSubAgent(SubAgent):
    """
    Packs a parcel into a receptacle: the bagging step of a sorting process.

    A bag holds one destination and one mail class, so which bag a parcel goes
    in follows entirely from what is written on it. There is nothing to weigh,
    which is exactly why this is a clerk and not a decision: the judgement at
    this door is whether the parcel goes *now*, and that stays with DISPATCH.

    It reports how full the bag is afterwards, because that is what the gate
    needs to know to decide whether the bag is worth handing over yet.
    """

    def __init__(self, parent_id: str, agent_id: str = "SUB-PACKING", **kw):
        super().__init__(agent_id, "packing", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        parcel_id = message.content.get("parcel_id", "")
        parcel = self.world.env.parcels.get(parcel_id)
        if parcel is None:
            return {"operation": "pack", "parcel_id": parcel_id, "ok": False,
                    "reason": "no such parcel at the door"}

        route = parcel.route_label or ""
        if not route:
            return {"operation": "pack", "parcel_id": parcel_id, "ok": False,
                    "reason": "no route on the parcel, so no bag for it"}

        # Origin is this facility and never varies, which is why it is not a
        # key here: every bag in this room was filled at this door. Destination
        # and class are what actually sort the bags.
        mail_class = parcel.priority.value
        room = self.world.env.bags
        bag = room.open_bag(route, mail_class, self.tick)
        packed = bag.put(parcel_id, parcel.size.units)
        if not packed:
            # The bag filled between the gate asking and this clerk packing.
            # Seal it and start the next one, which is what a person would do.
            room.seal(bag, self.tick)
            bag = room.open_bag(route, mail_class, self.tick)
            packed = bag.put(parcel_id, parcel.size.units)

        if packed:
            parcel.record(self.tick, self.agent_id, "packed",
                          receptacle=bag.receptacle_id, route=route,
                          mail_class=mail_class)
        return {
            "operation": "pack",
            "parcel_id": parcel_id,
            "ok": bool(packed),
            "receptacle": bag.receptacle_id,
            "route": route,
            "mail_class": mail_class,
            "bag_count": bag.count,
            "bag_units": bag.units,
            "bag_free": bag.free,
            "bag_is_full": bag.is_full,
            "reason": "" if packed else "the parcel will not fit any bag",
            "_text": (f"{parcel_id} packed into {bag.receptacle_id} "
                      f"({route}/{mail_class}, {bag.count} inside)"
                      if packed else
                      f"{parcel_id} would not fit a bag for {route}"),
        }
