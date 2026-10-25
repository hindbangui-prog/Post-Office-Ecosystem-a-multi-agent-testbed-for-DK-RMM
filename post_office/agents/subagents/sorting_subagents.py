"""
The three specialists that work for the sorting agent.

None of them changes anything. They read, they judge, and they report back to
their parent, which is the one that writes the conclusion onto the parcel. The
separation matters more than it looks: it means a sub-agent can be replaced by
an LLM, or by a real barcode scanner, without any of them being able to corrupt
the parcel record between them.

    SUB-BARCODE       reads the label and reports what is printed on it
    SUB-DESTINATION   decides where the parcel goes next
    SUB-PRIORITY      decides how much it is allowed to push in
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ...communication.message import Message
from ...core.rng import mix
from ...environment.parcels import ParcelPriority
from ...environment.zones import Zone
from ..base import SubAgent
from ..brain import Answer, Question

#: Where parcels in this facility are bound. Only ever used as a label.
ROUTES = ("BRNO", "OSTRAVA", "PLZEN", "OLOMOUC", "LIBEREC", "HRADEC")

#: What the service field of a barcode can say.
SERVICE_CODES = {"STD": ParcelPriority.NORMAL,
                 "EXP": ParcelPriority.EXPRESS,
                 "URG": ParcelPriority.URGENT}


#: The postcode of each city on the network, for the address line. Cosmetic,
#: but it is what makes an address look like an address rather than a key.
POSTCODES = {"BRNO": "602 00", "OSTRAVA": "702 00", "PLZEN": "301 00",
             "OLOMOUC": "779 00", "LIBEREC": "460 01", "HRADEC": "500 02"}

#: What the sender writes, by service. The facility reads these words rather
#: than a code, because a code is what the facility prints afterwards.
SERVICE_WORDS = {"STD": "standard", "EXP": "express", "URG": "urgent"}


def make_address(parcel_id: str, seed: int, city: Optional[str] = None) -> str:
    """
    What is written on the parcel when it is handed over.

    An address, not a barcode. A parcel arrives at a post office with a city
    and a service written on it, in handwriting or on a label somebody else
    printed; the barcode is what *this* facility applies once it has read that
    and worked out where the parcel is going. The model used to create parcels
    carrying a perfect machine-readable code, which meant the reading step had
    nothing to read and the applying step did not exist.

    Derived from the parcel id by hashing rather than from a running generator,
    so the address on P-0042 is the same in every run of a given seed whatever
    else the run did first.
    """
    h = mix(seed, f"address:{parcel_id}")
    town = city or ROUTES[h % len(ROUTES)]
    roll = (h >> 8) % 100
    service = "URG" if roll < 12 else "EXP" if roll < 35 else "STD"
    postcode = POSTCODES.get(town, "000 00")
    return f"{town.title()} {postcode}, {SERVICE_WORDS[service]}"


#: What a smudged character reads as. Enough to defeat the scanner without
#: making the line obviously synthetic.
SMUDGES = str.maketrans({"o": "0", "O": "0", "B": "8", "a": "@", "e": "^",
                         "i": "1", "l": "1", "S": "5"})


def smudge(address: str, heavy: bool = False) -> str:
    """
    An address that will not read. Damaged, not absent -- there is still ink.

    Severity matters, and it is the whole reason the gate and the scanner are
    two reads. A light smudge takes out one character: a person at the dock
    reads round it and the facility accepts the parcel, and the scanner then
    fails on it a stage later. A heavy one defeats both, and the gate turns the
    parcel away without wasting a sort on it.
    """
    if heavy:
        return address.translate(SMUDGES)
    town, _, rest = address.partition(" ")
    if len(town) < 3:
        return address.translate(SMUDGES)
    # One character of the town, which is enough to beat an exact match.
    at = len(town) // 2
    return town[:at] + "#" + town[at + 1:] + " " + rest


def read_address(address: str) -> Dict[str, Any]:
    """
    The machine read: an address line in, a route and a service out.

    This is the "scanning and reading" step, and it can fail. A smudged or
    badly written line defeats the scanner even though a person at the dock
    could see there was an address there -- which is why the gate's glance and
    this read are two different judgements rather than one done twice.
    """
    text = str(address or "")
    head = text.split(",")[0].strip().upper()
    city = head.split(" ")[0] if head else ""
    route = city if city in ROUTES else ""

    tail = text.split(",")[-1].strip().lower()
    service = ""
    for code, word in SERVICE_WORDS.items():
        if word in tail:
            service = code
            break

    if not route or not service:
        return {"ok": False, "route": route, "service": service,
                "reason": ("the address will not read" if not route
                           else "the service on the address will not read")}
    return {"ok": True, "route": route, "service": service, "reason": ""}


def glance(address: str) -> Dict[str, Any]:
    """
    What a person at the dock can tell without a scanner.

    Deliberately coarser than `read_address`: it recovers the town even from a
    line the machine cannot parse, because a clerk reads around a smudge, and
    it is how the intake gate decides whether the facility takes the parcel at
    all. Two different reads of one address, which is the real arrangement --
    not the same read performed twice.
    """
    text = str(address or "")
    head = text.split(",")[0].strip().upper()
    word = head.split(" ")[0] if head else ""
    # The service the sender paid for, which is written on the same line and
    # which a person can read without a scanner. The gate used to drop it,
    # which meant every parcel was promised the standard departure whatever
    # was on the label -- and express bought nothing at all.
    service = _service_word(text)
    if not word:
        return {"legible": False, "town": "", "on_network": False,
                "service": service}
    # A clerk matches a smudged town against the ones they know.
    for route in ROUTES:
        if word == route or _close_enough(word, route):
            return {"legible": True, "town": route, "on_network": True,
                    "service": service}
    legible = word.isalpha() and len(word) >= 3
    return {"legible": legible, "town": word if legible else "",
            "on_network": False, "service": service}


def _service_word(address: str) -> str:
    """
    The service code a person would read off the label, or "" if they cannot.

    Looser than the scanner's read, like the rest of a clerk's glance: it looks
    for the word anywhere after the comma and tolerates a character of damage,
    because "exp#ess" is still plainly express to somebody holding the parcel.
    """
    tail = str(address or "").split(",")[-1].strip().lower()
    if not tail:
        return ""
    for code, word in SERVICE_WORDS.items():
        if word in tail:
            return code
    for code, word in SERVICE_WORDS.items():
        if len(tail) == len(word) and _close_enough(tail.upper(), word.upper()):
            return code
    return ""


def _close_enough(word: str, route: str) -> bool:
    """One or two characters out, which is what a smudge costs."""
    if len(word) != len(route):
        return False
    wrong = sum(1 for a, b in zip(word, route) if a != b)
    return wrong <= max(1, len(route) // 4)


def make_barcode(route: str, service: str, serial: str) -> str:
    """
    The label this facility prints, once it knows where the parcel is going.

    Applied rather than received: a parcel carrying one of these is a parcel
    this building has read, graded and routed. It encodes the destination,
    which is what a barcode is for.
    """
    return f"PL-{route}-{service}-{serial}"


def parse_barcode(barcode: str) -> Dict[str, str]:
    parts = str(barcode or "").split("-")
    if len(parts) != 4 or parts[0] != "PL":
        return {"valid": False, "route": "", "service": "", "serial": ""}
    return {"valid": True, "route": parts[1], "service": parts[2],
            "serial": parts[3]}


class BarcodeSubAgent(SubAgent):
    """
    Reads the address written on the parcel, and turns it into a route and a
    service the rest of the facility can act on. The "scanning and reading"
    step of a sorting process: what arrives is a town and a postcode, and this
    is what makes it machine-readable.

    It can fail, and that is the point of having it. An address a person at the
    dock could read round may still defeat the scanner, so a parcel the gate
    accepted can turn out to be unsortable -- a second failure point rather
    than a duplicate of the first.
    """

    def __init__(self, parent_id: str, agent_id: str = "SUB-BARCODE", **kw):
        super().__init__(agent_id, "barcode reading", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        parcel_id = message.content.get("parcel_id", "")
        parcel = self.world.env.parcels.get(parcel_id)
        if parcel is None:
            return {"operation": "scan", "parcel_id": parcel_id, "ok": False,
                    "reason": "no such parcel on the floor"}
        read = read_address(parcel.address)
        return {
            "operation": "scan",
            "parcel_id": parcel_id,
            "ok": bool(read["ok"]),
            "address": parcel.address,
            "route": read["route"],
            "service": read["service"],
            "size": parcel.size.value,
            "reason": read["reason"],
            "_text": (f"Read {parcel_id}: {parcel.address!r} -> route "
                      f"{read['route']}, service {read['service']}"
                      if read["ok"] else
                      f"{parcel_id}: {read['reason']} ({parcel.address!r})"),
        }


class DestinationClassificationSubAgent(SubAgent):
    """
    Reports where a parcel could go next, and what the shelves look like.

    From the intake dock there is nothing to weigh -- everything gets looked at
    -- and a parcel coming off a shelf is leaving. The interesting case is the
    one after sorting: hold it in temporary storage, or send it straight out.
    This agent measures what that turns on -- how full the shelves are, how
    many are left, what the policy allows -- and SORTING decides.

    It used to decide itself, which put the judgement one level below the agent
    whose job the parcel's routing is, and left SORTING relaying an answer it
    had no part in.
    """

    def __init__(self, parent_id: str, agent_id: str = "SUB-DESTINATION", **kw):
        super().__init__(agent_id, "destination classification", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        parcel_id = message.content.get("parcel_id", "")
        parcel = self.world.env.parcels.get(parcel_id)
        if parcel is None:
            return {"operation": "classify_destination", "parcel_id": parcel_id,
                    "ok": False, "reason": "no such parcel"}

        current = parcel.current_zone
        # The two legs with only one answer. Reported as settled rather than
        # handed up as a question, because a decision with one option is not a
        # decision and SORTING should not be asked to make it.
        priority = str(message.content.get("priority", parcel.priority.value))
        if current is Zone.INTAKE and getattr(self, "urgent_via_sorting", False) \
                and priority == "URGENT":
            # Urgent post still goes through the sorting hall, but on the
            # same trip: its answer at the sorting stop is already known --
            # URGENT goes to DISPATCH -- so there is nothing to wait there for.
            return {"operation": "classify_destination", "parcel_id": parcel_id,
                    "ok": True, "settled": Zone.DISPATCH.value,
                    "via": Zone.SORTING.value,
                    "reason": "urgent: through the sorting hall and straight on "
                              "to the door",
                    "_text": (f"{parcel_id} is urgent: it goes through SORTING "
                              "to DISPATCH in one trip.")}
        if current is Zone.INTAKE:
            return {"operation": "classify_destination", "parcel_id": parcel_id,
                    "ok": True, "settled": Zone.SORTING.value,
                    "reason": "everything is sorted before anything else",
                    "_text": f"{parcel_id} goes to SORTING first."}
        if current is Zone.TEMPORARY_STORAGE:
            return {"operation": "classify_destination", "parcel_id": parcel_id,
                    "ok": True, "settled": Zone.DISPATCH.value,
                    "reason": "stored parcels leave next",
                    "_text": f"{parcel_id} comes off the shelf for dispatch."}

        policy = self.world.policy
        storage = self.world.env.storage
        return {
            "operation": "classify_destination",
            "parcel_id": parcel_id,
            "ok": True,
            "settled": "",
            "priority": message.content.get("priority", parcel.priority.value),
            "size": parcel.size.value,
            "storage_load": round(storage.load, 3),
            "storage_free": storage.free,
            "storage_policy": policy.store_normal_parcels,
            "max_storage_load": policy.max_storage_load,
            "_text": (f"{parcel_id} is sorted; shelves at "
                      f"{storage.load:.0%} with {storage.free} free."),
        }


class PriorityClassificationSubAgent(SubAgent):
    """
    Reports what the customer claimed and what the dock looks like.

    The service written on the parcel is the customer's claim; what the
    facility actually does about it is a judgement, and it belongs to SORTING.
    A large parcel with an urgent label still has to fit on a robot, and
    whether to honour that claim while ten parcels wait is exactly the kind of
    call this project keeps above the tool layer.
    """

    def __init__(self, parent_id: str, agent_id: str = "SUB-PRIORITY", **kw):
        super().__init__(agent_id, "priority classification", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        parcel_id = message.content.get("parcel_id", "")
        parcel = self.world.env.parcels.get(parcel_id)
        if parcel is None:
            return {"operation": "classify_priority", "parcel_id": parcel_id,
                    "ok": False, "reason": "no such parcel"}

        service = str(message.content.get("service", "STD")).upper()
        claimed = SERVICE_CODES.get(service, ParcelPriority.NORMAL)
        waited = self.tick - parcel.timestamps.get("arrived", self.tick)
        queue = len(self.world.env.parcels_in(Zone.INTAKE))
        return {
            "operation": "classify_priority",
            "parcel_id": parcel_id,
            "ok": True,
            "service": service,
            # What the customer paid for, named in the facility's own terms so
            # the expert does not have to open the service table itself.
            "claimed": claimed.value,
            "size": parcel.size.value,
            "waiting_ticks": max(0, waited),
            "parcels_waiting": queue,
            "_text": (f"{parcel_id} claims {service} ({claimed.value}), "
                      f"{parcel.size.value}, waited {max(0, waited)} ticks "
                      f"with {queue} on the dock."),
        }
