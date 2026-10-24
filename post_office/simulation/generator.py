"""
Parcels arriving at the intake dock.

Arrivals are the one thing in this system that genuinely comes from outside, so
they are modelled as a Poisson-ish process on a dedicated random stream. The
stream matters: putting arrivals on the same generator as anything else would
mean that changing a robot's behaviour changed when parcels turned up, and a
comparison between two configurations would no longer be a comparison of the
thing you varied.

The dock is finite. Each parcel needs a free cell in the intake zone, and when
there is none the arrival is refused and recorded rather than stacked
invisibly. A dock that can hold infinitely many parcels is a dock that never
tells you the facility is falling behind.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..communication.events import EventCategory, EventLogger
from ..core.ids import IdFactory
from ..core.rng import SeededRNG
from ..agents.subagents.sorting_subagents import make_address, smudge
from ..environment.facility import PostOfficeEnvironment
from ..environment.grid import Position
from ..environment.parcels import Parcel, ParcelSize
from ..environment.zones import Zone

#: Relative frequency of each size. Most post is small.
SIZE_WEIGHTS = ((ParcelSize.SMALL, 0.6), (ParcelSize.MEDIUM, 0.3),
                (ParcelSize.LARGE, 0.1))

#: How often a parcel turns up with an address that will not read.
#:
#: Not decoration. The intake gate's whole job is to decide whether the
#: facility takes a parcel on what it can work out from the label, and until
#: the world produced a bad one that decision had exactly one outcome: the
#: generator printed a perfect barcode every time, so the refusal branch was
#: unreachable and the gate was a formality. A few percent is the order a real
#: facility sees -- torn, smudged, printed badly, put on upside down.
UNREADABLE_RATE = 0.04

#: Of those, how many are bad enough that a person at the dock cannot read them
#: either. The rest pass the gate's glance and defeat the scanner a stage later,
#: which is the more interesting failure: the facility accepted a parcel it
#: then could not sort.
HEAVY_SHARE = 0.4

#: And how often one turns up addressed somewhere this facility does not go.
#: Mis-sorted upstream, or simply the wrong label on the box.
OFF_NETWORK_RATE = 0.015

#: Where those wrongly-addressed parcels claim to be going. Real places, none
#: of them on this facility's route list, so the gate has to notice rather than
#: pattern-match on something that looks obviously fake.
OFF_NETWORK = ("KOSICE", "WROCLAW", "LINZ", "DRESDEN", "GYOR")


class ParcelGenerator:
    """Puts new parcels on the intake dock, on its own random stream."""

    def __init__(self, env: PostOfficeEnvironment, rng: SeededRNG,
                 ids: IdFactory, logger: EventLogger,
                 mean_interval: float = 40.0,
                 initial: int = 8,
                 max_on_dock: int = 20) -> None:
        self.env = env
        self.rng = rng
        self.ids = ids
        self.logger = logger
        self.mean_interval = float(mean_interval)
        self.initial = int(initial)
        self.max_on_dock = int(max_on_dock)
        self.created = 0
        self.refused = 0
        self._stream = rng.stream("__arrivals__")
        #: A stream of its own, so whether a parcel's label is damaged does not
        #: depend on how many parcels arrived before it -- and so turning the
        #: damage off leaves every arrival time exactly where it was.
        self._labels = rng.stream("__labels__")
        self.damaged = 0
        self.misaddressed = 0

    # --------------------------------------------------------------- address
    def _address_for(self, parcel_id: str, seed: int) -> str:
        """
        The label on the box, which is occasionally not a good one.

        The facility learns nothing about a parcel except through this string,
        so it is the only place a parcel can arrive wrong. Two ways for it to
        be wrong, and they are different problems: a label that will not read
        at all, and one that reads perfectly and names somewhere this facility
        does not serve. The first is a scanning failure; the second is a
        mis-sort further up the network, and only the gate can catch it.
        """
        roll = self._labels.random()

        if roll < UNREADABLE_RATE:
            self.damaged += 1
            heavy = (roll / UNREADABLE_RATE) < HEAVY_SHARE
            return smudge(make_address(parcel_id, seed), heavy=heavy)

        if roll < UNREADABLE_RATE + OFF_NETWORK_RATE:
            self.misaddressed += 1
            elsewhere = OFF_NETWORK[int(roll * 10 ** 6) % len(OFF_NETWORK)]
            return make_address(parcel_id, seed, city=elsewhere)

        return make_address(parcel_id, seed)

    # ----------------------------------------------------------------- cells
    def _free_dock_cell(self) -> Optional[Position]:
        """
        A free intake cell, scanned in a fixed order.

        Fixed order rather than random choice so that two runs of one seed put
        the same parcel on the same cell even if an earlier run drew a
        different number of random values.
        """
        taken = {p.position for p in self.env.parcels.values()
                 if p.position is not None}
        for cell in self.env.zones.cells_of(Zone.INTAKE):
            if cell not in taken and self.env.is_free(cell):
                return cell
        return None

    # -------------------------------------------------------------- arrivals
    def _make_parcel(self, tick: int, seed: int) -> Optional[Parcel]:
        cell = self._free_dock_cell()
        on_dock = len(self.env.parcels_in(Zone.INTAKE))
        if cell is None or on_dock >= self.max_on_dock:
            self.refused += 1
            self.logger.emit(EventCategory.PARCEL, "arrival_refused", tick=tick,
                             actor="INTAKE_DOCK",
                             reason="dock full", on_dock=on_dock,
                             refused_total=self.refused)
            return None

        parcel_id = self.ids.next("P")
        roll = self._stream.random()
        size = SIZE_WEIGHTS[-1][0]
        cumulative = 0.0
        for candidate, weight in SIZE_WEIGHTS:
            cumulative += weight
            if roll <= cumulative:
                size = candidate
                break

        parcel = Parcel(parcel_id=parcel_id, origin=Zone.INTAKE, size=size,
                        address=self._address_for(parcel_id, seed))
        parcel.stamp("arrived", tick)
        parcel.record(tick, "INTAKE_DOCK", "arrived", cell=cell.as_dict())
        self.env.add_parcel(parcel, at=cell)
        self.created += 1
        return parcel

    def seed_dock(self, tick: int, seed: int) -> List[Parcel]:
        """The parcels already waiting when the shift starts."""
        return [p for p in (self._make_parcel(tick, seed)
                            for _ in range(self.initial)) if p is not None]

    def step(self, tick: int, seed: int) -> List[Parcel]:
        """
        Zero or more arrivals this tick.

        A geometric wait between arrivals, which is the discrete-time Poisson
        process -- memoryless, so a quiet stretch does not make the next parcel
        any more likely, and clusters happen on their own rather than being
        scripted.
        """
        if self.mean_interval <= 0:
            return []
        out = []
        if self._stream.random() < 1.0 / self.mean_interval:
            parcel = self._make_parcel(tick, seed)
            if parcel is not None:
                out.append(parcel)
        return out

    # ----------------------------------------------------------------- state
    def as_dict(self) -> dict:
        return {
            "created": self.created,
            "refused": self.refused,
            "mean_interval": self.mean_interval,
            "max_on_dock": self.max_on_dock,
            "on_dock": len(self.env.parcels_in(Zone.INTAKE)),
        }
