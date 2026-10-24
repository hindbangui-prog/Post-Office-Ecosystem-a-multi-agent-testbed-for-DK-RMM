"""
The post office itself: floor plan, zones, docks, shelves and charge points.

This is the physical world and nothing else. It holds no agents, sends no
messages and makes no decisions; it answers questions ("is there a free charge
point?", "how far is DISPATCH from here?") and it accepts changes ("this parcel
is now on that shelf"). Agents act *on* it through the simulation, never by
reaching into it.

Keeping it this way is what makes the environment reusable: the same facility
can be driven by the deterministic agents shipped here, by CrewAI agents, or by
a unit test with no agents at all.

Capacity is real. Charge points and storage shelves are finite, and a request
for one that cannot be granted is refused rather than queued -- a refusal is
the cheapest early signal there is that the facility is under strain, and the
monitoring layer you will attach later will want to see it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

from .grid import Grid, Position
from .parcels import Parcel, ParcelStatus
from .zones import Rect, Zone, ZoneMap


@dataclass
class ChargingStation:
    """One charge point. Occupied by at most one robot at a time."""

    station_id: str
    position: Position
    occupant: Optional[str] = None
    rate: float = 8.0            # battery percent restored per tick
    served: int = 0

    @property
    def free(self) -> bool:
        return self.occupant is None

    def as_dict(self) -> dict:
        return {
            "station_id": self.station_id,
            "position": self.position.as_dict(),
            "occupant": self.occupant,
            "rate": self.rate,
            "served": self.served,
            "free": self.free,
        }


@dataclass
class StorageArea:
    """Temporary storage, with a shelf count that can actually run out."""

    capacity: int
    held: Set[str] = field(default_factory=set)
    refusals: int = 0

    @property
    def used(self) -> int:
        return len(self.held)

    @property
    def free(self) -> int:
        return max(0, self.capacity - self.used)

    @property
    def load(self) -> float:
        return self.used / self.capacity if self.capacity else 1.0

    def as_dict(self) -> dict:
        return {"capacity": self.capacity, "used": self.used, "free": self.free,
                "load": round(self.load, 4), "refusals": self.refusals,
                "held": sorted(self.held)}


class PostOfficeEnvironment:
    """The building, its contents and its finite capacities."""

    def __init__(self, grid: Grid, zones: ZoneMap,
                 charging_stations: Sequence[ChargingStation] = (),
                 storage_capacity: int = 24,
                 event_sink: Optional[Callable[..., None]] = None) -> None:
        self.grid = grid
        self.zones = zones
        self.stations: Dict[str, ChargingStation] = {
            s.station_id: s for s in charging_stations
        }
        self.storage = StorageArea(capacity=storage_capacity)
        self.parcels: Dict[str, Parcel] = {}       # still in the building
        self.departed: Dict[str, Parcel] = {}      # gone, but not forgotten
        #: Structured requests from agents for the facility to intervene
        #: physically -- fetching a robot that has run flat, today. Agents
        #: append; only the simulation engine acts on them, and it may refuse.
        #: The queue lives on the environment rather than on an agent because
        #: it is a fact about the floor, not about whoever noticed.
        self.recovery_requests: List[Any] = []
        self.dispatched_count: int = 0
        #: The outbound timetable. Set by `build_environment`, because a
        #: facility without departures is one whose parcels can never be late.
        self.departures = None
        #: The bag room: the receptacles parcels are grouped into before they
        #: are handed to a van. Set by the layout, for the same reason the
        #: timetable is -- a bag is part of the building, not of an agent.
        self.bags = None
        #: Parcels the intake gate would not take. Kept apart from the
        #: dispatched total on purpose: "we handled 400 and turned 9 away" and
        #: "we handled 409" are different sentences about the same day.
        self.refused_count: int = 0
        #: Parcels the facility accepted and then could not work: the address
        #: passed the clerk's glance and defeated the scanner. Counted apart
        #: from refusals because it is a different failure -- the facility took
        #: this one on -- and apart from dispatches because it never left for
        #: where it was going.
        self.returned_count: int = 0
        self.dwell_total: int = 0
        self._robot_positions: Dict[str, Position] = {}
        self._sink = event_sink
        self.tick: int = 0

    # ---------------------------------------------------------------- events
    def _emit(self, topic: str, **detail) -> None:
        """Announce a change in the world. Silent if nobody is listening."""
        if self._sink is not None:
            self._sink(topic=topic, tick=self.tick, **detail)

    def set_event_sink(self, sink: Optional[Callable[..., None]]) -> None:
        self._sink = sink

    # ------------------------------------------------------------- geography
    def zone_at(self, p) -> Optional[Zone]:
        return self.zones.zone_at(p)

    def anchor(self, zone: Zone) -> Position:
        return self.zones.anchor(zone)

    def free_cell_in(self, zone: Zone, near=None) -> Position:
        """
        Somewhere in that zone to put a parcel down.

        A zone is an area, not a point, and it matters that the code treats it
        as one. Sending every delivery to a single anchor cell turns each zone
        into a one-lane queue: robots pile up behind whoever is unloading,
        block each other, and the facility looks congested for a reason that is
        an artefact of the model rather than anything about the building.

        Cells already holding a parcel or a robot are skipped, and the rest are
        ordered by distance from `near` with coordinates breaking ties, so the
        choice is the same on every run of a seed.
        """
        taken = {p.position for p in self.parcels.values() if p.position is not None}
        taken |= set(self._robot_positions.values())
        anchor = self.zones.anchor(zone)
        reference = Position.of(near) if near is not None else anchor

        best, best_key = None, None
        for cell in self.zones.cells_of(zone):
            if not self.grid.is_free(cell) or cell in taken:
                continue
            key = (cell.manhattan(reference), cell.x, cell.y)
            if best_key is None or key < best_key:
                best, best_key = cell, key
        return best if best is not None else anchor

    def path(self, start, goal) -> Optional[List[Position]]:
        return self.grid.path(start, goal)

    def distance(self, start, goal) -> Optional[int]:
        return self.grid.distance(start, goal)

    def is_free(self, p) -> bool:
        return self.grid.is_free(Position.of(p))

    # ------------------------------------------------------------- occupancy
    def place_robot(self, robot_id: str, p) -> None:
        self._robot_positions[robot_id] = Position.of(p)

    def robot_positions(self) -> Dict[str, Position]:
        return dict(self._robot_positions)

    def occupied_by_robot(self, p, excluding: str = "") -> Optional[str]:
        """Which other robot is standing on that cell, if any."""
        p = Position.of(p)
        for rid, pos in sorted(self._robot_positions.items()):
            if rid != excluding and pos == p:
                return rid
        return None

    # --------------------------------------------------------------- parcels
    def add_parcel(self, parcel: Parcel, at: Optional[Position] = None) -> Parcel:
        """A parcel appears on the floor, normally on the intake dock."""
        where = Position.of(at) if at is not None else self.anchor(parcel.origin)
        parcel.position = where
        parcel.current_zone = self.zone_at(where) or parcel.origin
        self.parcels[parcel.parcel_id] = parcel
        self._emit("parcel_arrived", parcel_id=parcel.parcel_id,
                   position=where.as_dict(), zone=parcel.current_zone.value,
                   priority=parcel.priority.value, size=parcel.size.value)
        return parcel

    def parcels_at(self, p) -> List[Parcel]:
        p = Position.of(p)
        return [x for x in self.parcels.values() if x.position == p]

    def parcels_in(self, zone: Zone) -> List[Parcel]:
        return [x for x in self.parcels.values()
                if x.position is not None and x.current_zone is zone]

    def lift_parcel(self, parcel_id: str, robot_id: str) -> bool:
        """Take a parcel off the floor and onto a robot."""
        parcel = self.parcels.get(parcel_id)
        if parcel is None or parcel.position is None:
            return False
        origin = parcel.position
        if parcel.current_zone is Zone.TEMPORARY_STORAGE:
            self.release_storage(parcel_id)
        parcel.position = None
        parcel.assigned_robot = robot_id
        self._emit("parcel_lifted", parcel_id=parcel_id, robot_id=robot_id,
                   position=origin.as_dict())
        return True

    def drop_parcel(self, parcel_id: str, at) -> bool:
        """Put a parcel down. The caller has already checked it may."""
        parcel = self.parcels.get(parcel_id)
        if parcel is None:
            return False
        where = Position.of(at)
        parcel.position = where
        parcel.current_zone = self.zone_at(where) or parcel.current_zone
        parcel.assigned_robot = None
        self._emit("parcel_dropped", parcel_id=parcel_id,
                   position=where.as_dict(), zone=parcel.current_zone.value)
        return True

    def remove_parcel(self, parcel_id: str, dispatched: bool = True,
                      returned: bool = False) -> Optional[Parcel]:
        """
        A parcel leaves the building. It stays in the record, not on the floor.

        `dispatched` is what it left as. True is the front-to-back journey
        finishing and counts towards the dispatched total and the dwell mean.
        False is a parcel the intake gate turned away: it also leaves, and it
        also stays in the record, but counting a refusal as a dispatch would
        put a parcel the facility never accepted into the figure for parcels it
        delivered, and give it a dwell time for work it never had done.

        `returned` is the third way out and is counted apart from both. A
        parcel the door accepted and the scanner could not read was neither
        refused nor delivered: the facility took it on and could not do the
        work, which is a different failure from declining the parcel at all,
        and a facility that returns twenty parcels a day has a reading problem
        rather than a busy dock.

        Moved out of `parcels` and into `departed` rather than merely marked,
        because the planner and the generator scan the parcels still inside on
        every single tick. Leaving ten thousand finished parcels in that
        dictionary makes a long run slower and slower for no reason at all, and
        `all_parcels()` still returns everything for anyone who wants the
        complete record.
        """
        parcel = self.parcels.pop(parcel_id, None)
        if parcel is None:
            return self.departed.get(parcel_id)
        self.release_storage(parcel_id)
        parcel.position = None
        parcel.assigned_robot = None
        self.departed[parcel_id] = parcel
        if dispatched:
            self.dispatched_count += 1
            if parcel.dwell is not None:
                self.dwell_total += parcel.dwell
            self._emit("parcel_departed", parcel_id=parcel_id,
                       dwell=parcel.dwell)
        elif returned:
            self.returned_count += 1
            self._emit("parcel_returned", parcel_id=parcel_id)
        else:
            self.refused_count += 1
            self._emit("parcel_refused", parcel_id=parcel_id)
        return parcel

    def parcel(self, parcel_id: str) -> Optional[Parcel]:
        """By id, whether it is still inside or long gone."""
        return self.parcels.get(parcel_id) or self.departed.get(parcel_id)

    def all_parcels(self) -> Dict[str, Parcel]:
        """Everything the facility has ever handled."""
        return {**self.departed, **self.parcels}

    @property
    def mean_dwell(self) -> Optional[float]:
        if not self.dispatched_count:
            return None
        return round(self.dwell_total / self.dispatched_count, 2)

    # --------------------------------------------------------------- storage
    def claim_storage(self, parcel_id: str) -> bool:
        """
        Reserve one shelf. False when the shelves are full, and the refusal is
        counted and announced rather than swallowed.
        """
        if parcel_id in self.storage.held:
            return True
        if self.storage.free <= 0:
            self.storage.refusals += 1
            self._emit("storage_refused", parcel_id=parcel_id,
                       capacity=self.storage.capacity, used=self.storage.used)
            return False
        self.storage.held.add(parcel_id)
        self._emit("storage_claimed", parcel_id=parcel_id,
                   used=self.storage.used, capacity=self.storage.capacity)
        return True

    def release_storage(self, parcel_id: str) -> None:
        if parcel_id in self.storage.held:
            self.storage.held.discard(parcel_id)
            self._emit("storage_released", parcel_id=parcel_id,
                       used=self.storage.used, capacity=self.storage.capacity)

    # -------------------------------------------------------------- charging
    def free_stations(self) -> List[ChargingStation]:
        return [s for s in sorted(self.stations.values(),
                                  key=lambda s: s.station_id) if s.free]

    def station_at(self, p) -> Optional[ChargingStation]:
        """The charge point on that cell, if there is one."""
        p = Position.of(p)
        for station in sorted(self.stations.values(), key=lambda s: s.station_id):
            if station.position == p:
                return station
        return None

    def station_of(self, robot_id: str) -> Optional[ChargingStation]:
        for s in sorted(self.stations.values(), key=lambda s: s.station_id):
            if s.occupant == robot_id:
                return s
        return None

    def claim_station(self, robot_id: str,
                      station_id: Optional[str] = None) -> Optional[ChargingStation]:
        """Take a charge point, or be refused because they are all busy."""
        existing = self.station_of(robot_id)
        if existing is not None:
            return existing
        if station_id is not None:
            candidate = self.stations.get(station_id)
            candidates = [candidate] if candidate is not None and candidate.free else []
        else:
            candidates = self.free_stations()
        if not candidates:
            self._emit("charging_refused", robot_id=robot_id,
                       stations=len(self.stations),
                       busy=sum(1 for s in self.stations.values() if not s.free))
            return None
        station = candidates[0]
        station.occupant = robot_id
        station.served += 1
        self._emit("charging_claimed", robot_id=robot_id,
                   station_id=station.station_id,
                   position=station.position.as_dict())
        return station

    def release_station(self, robot_id: str) -> None:
        station = self.station_of(robot_id)
        if station is not None:
            station.occupant = None
            self._emit("charging_released", robot_id=robot_id,
                       station_id=station.station_id)

    # ----------------------------------------------------------------- state
    def as_dict(self) -> dict:
        return {
            "tick": self.tick,
            "grid": self.grid.as_dict(),
            "zones": self.zones.as_dict(),
            "charging_stations": [s.as_dict() for s in
                                  sorted(self.stations.values(),
                                         key=lambda s: s.station_id)],
            "storage": self.storage.as_dict(),
            "parcels_on_floor": sum(1 for p in self.parcels.values()
                                    if p.position is not None),
            "robot_positions": {r: p.as_dict() for r, p in
                                sorted(self._robot_positions.items())},
        }

    def as_text(self) -> str:
        """An ASCII picture of the floor, for the terminal demonstration."""
        marks: Dict[Position, str] = {}
        for zone in self.zones.zones():
            letter = zone.value[0].lower()
            for cell in self.zones.cells_of(zone):
                marks[cell] = letter
        for parcel in self.parcels.values():
            if parcel.position is not None:
                marks[parcel.position] = "p"
        for station in self.stations.values():
            marks[station.position] = "C" if station.free else "c"
        for rid, pos in self._robot_positions.items():
            marks[pos] = rid[-1] if rid[-1].isdigit() else "R"
        return self.grid.as_text(marks)
