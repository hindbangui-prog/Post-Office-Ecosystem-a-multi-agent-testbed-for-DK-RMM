"""
The outbound vans, and the cut-off times the whole facility is arranged around.

This is the piece the simulation was missing. A real sortation hub does not sort
parcels because sorting is good; it sorts them to get each one onto a particular
outbound truck before that truck leaves, and the departure times are hard --
they are what the carrier sold. Everything upstream, the sort plan, the staffing,
the order work is released in, exists to serve them.

Without vans a dispatched parcel simply vanished from the building, which meant
nothing in the model could ever be *late*. `URGENT` changed the order of a queue
and then changed nothing else, because there was no outcome for it to change.

So: one van per route stands at the bay, it leaves on a fixed interval, and the
next one takes its place. A parcel's promise is derived from that schedule
rather than invented as a duration -- the service the customer paid for buys a
place on the next departure, the second, or the fourth. That keeps the promise
coherent whatever the interval is set to, and it means a parcel that has just
missed a van is genuinely in trouble, which is the tension a hub runs on.

A van has a capacity in the same size units a robot carries, so a burst of large
parcels for one route fills a van and the rest wait for the next -- which is a
queue with a real cause rather than a timer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

#: Which departure each service class is promised, counted from the moment the
#: facility accepts the parcel. Urgent post is promised the very next van for
#: its route; standard post can wait for the fourth. Derived rather than given
#: in minutes so that changing the van interval changes the promises with it --
#: a promise that does not move when the timetable does is not a promise about
#: this facility.
PROMISED_DEPARTURE: Dict[str, int] = {
    "URGENT": 1,
    "EXPRESS": 2,
    "NORMAL": 4,
}

#: How often a van leaves for each route, in ticks -- ten minutes at one second
#: per tick.
#:
#: Scaled to this facility rather than copied from a real one. A real hub runs
#: two to six cut-offs across an eight-hour shift, but it also moves sixty
#: thousand parcels an hour; this one moves about ninety. Copying the absolute
#: interval into a miniature would mean nothing ever left the building during a
#: run you could watch. What is preserved instead is the relationship that makes
#: a cut-off bite: a parcel waits for its van about as long as it spends being
#: processed, so the timetable is a live constraint without being the only one.
#: Measured, not guessed: at 600 with every route on the same beat, an urgent
#: parcel reached the door at tick 105, was loaded at 109 and left at 600 --
#: 473 ticks sitting on a stationary van, against 60 for an ordinary parcel
#: that was loaded late onto one about to go. A class sold as faster was
#: slower. Staggered across the routes below, this puts a van in the yard
#: every 41 ticks instead of six at once every 600.
#:
#: 250 rather than the 150 first tried: shortening the interval tightens every
#: promise with it, and at 150 a healthy facility broke three of them in a
#: 3000-tick run -- a timetable it could not actually keep. At 250 it keeps
#: all of them and still gets an urgent parcel out of the door in about 117
#: ticks against the 477 it took before.
DEFAULT_INTERVAL = 250

#: How long before a departure the facility stops promising it.
#:
#: A cut-off in this trade is an induction deadline, not the moment the doors
#: shut: a parcel handed over five minutes before a van leaves has not been
#: sorted, carried across the floor and loaded, so no carrier promises it that
#: van. Without this allowance every parcel accepted shortly before a departure
#: would be promised one it could not physically make, and the lateness figure
#: would measure the promise rather than the facility. Set to roughly what a
#: parcel actually takes to reach the door, with room for a busy day: at 180
#: a busy run broke one promise in six thousand ticks, and at 210 it broke
#: one again once the fleet started queueing its next errand and moving more
#: parcels through the same building. 240 holds in both presets. And it
#: must stay under the interval: an allowance longer than the gap between
#: vans means no parcel can ever be promised the next one, which silently
#: turns every promise into a later one.
HANDLING_ALLOWANCE = 240

#: Size units per van, in the units a parcel is measured in (SMALL 1, MEDIUM 2,
#: LARGE 3). Twenty is roughly eleven average parcels: enough that a van is
#: usually not the constraint, few enough that a burst for one route fills it.
DEFAULT_CAPACITY = 20


@dataclass
class Vehicle:
    """One van: where it goes, when it leaves, and what is on it."""

    vehicle_id: str
    route: str
    capacity: int
    departs_at: int
    loaded: List[str] = field(default_factory=list)
    units: int = 0
    departed_at: Optional[int] = None

    @property
    def free(self) -> int:
        return max(0, self.capacity - self.units)

    @property
    def has_gone(self) -> bool:
        return self.departed_at is not None

    def load(self, parcel_id: str, units: int = 1) -> bool:
        """
        Put a parcel on. False when it will not fit, or the van has gone.

        A refusal rather than an exception: a van filling up is an ordinary
        event in a facility, and the gate's job is to hold the parcel for the
        next one rather than to fail.
        """
        if self.has_gone or units > self.free:
            return False
        self.loaded.append(parcel_id)
        self.units += int(units)
        return True

    def as_dict(self) -> Dict[str, object]:
        return {"vehicle_id": self.vehicle_id, "route": self.route,
                "departs_at": self.departs_at, "departed_at": self.departed_at,
                "capacity": self.capacity, "units": self.units,
                "loaded": list(self.loaded)}


class DepartureBoard:
    """
    The timetable, and the van currently at the bay for each route.

    Owned by the facility rather than by an agent, the same way the charge
    points are: a van leaves whether or not anybody managed to load it, and a
    schedule that an agent could quietly move would not be a cut-off.
    """

    def __init__(self, routes: Sequence[str],
                 interval: int = DEFAULT_INTERVAL,
                 capacity: int = DEFAULT_CAPACITY) -> None:
        self.routes = list(routes)
        self.interval = max(1, int(interval))
        self.capacity = max(1, int(capacity))
        self._bay: Dict[str, Vehicle] = {}
        self._gone: List[Vehicle] = []
        self._counter = 0
        self.departures = 0

    # ------------------------------------------------------------- the bay
    def open(self, tick: int = 0) -> None:
        """Put the first van of the run at each bay."""
        for route in self.routes:
            self._bay[route] = self._next_van(route, tick)

    def _next_van(self, route: str, after: int) -> Vehicle:
        self._counter += 1
        return Vehicle(vehicle_id=f"V-{self._counter:04d}", route=route,
                       capacity=self.capacity,
                       departs_at=self._departure_after(after, route))

    def _offset(self, route: str) -> int:
        """
        Where this route sits inside the interval.

        Six routes and a 150-tick interval put departures at 0, 25, 50, 75,
        100 and 125, so something leaves the yard every 25 ticks. Before this
        every route shared one beat, which made the timetable a single
        heartbeat for the whole building: nothing about which parcel or which
        destination could change when anything left, and the dispatch agent's
        judgement about who goes first could not matter, because everything
        went at once.
        """
        try:
            index = self.routes.index(route)
        except ValueError:
            return 0
        return index * self.interval // max(1, len(self.routes))

    def _departure_after(self, tick: int, route: str = "") -> int:
        """The next slot on this route's timetable, strictly after `tick`."""
        offset = self._offset(route)
        slot = (int(tick) - offset) // self.interval * self.interval + offset
        return slot if slot > int(tick) else slot + self.interval

    def at_bay(self, route: str) -> Optional[Vehicle]:
        return self._bay.get(route)

    def all_vans(self) -> List[Vehicle]:
        """Every van this run has had, gone or standing."""
        return list(self._gone) + list(self._bay.values())

    def gone(self) -> List[Vehicle]:
        return list(self._gone)

    # ---------------------------------------------------------- the clock
    def advance(self, tick: int) -> List[Vehicle]:
        """
        Let go any van whose time has come, and bring up its replacement.

        Returns the vans that left, so the caller can take their parcels out of
        the building. It does not touch the parcels itself: this module knows
        about vehicles and timetables, and the facility knows what a parcel is.
        """
        left: List[Vehicle] = []
        for route in self.routes:
            van = self._bay.get(route)
            if van is None or tick < van.departs_at:
                continue
            van.departed_at = int(tick)
            self._gone.append(van)
            self.departures += 1
            left.append(van)
            self._bay[route] = self._next_van(route, tick)
        return left

    # --------------------------------------------------------- the promise
    def nth_departure_after(self, route: str, tick: int, nth: int = 1) -> int:
        """
        When the `nth` van for this route leaves, counting from `tick`.

        This is what a promise is made of. A parcel accepted a second after a
        van pulled away is promised the one after it, not a fraction of an
        interval -- which is why lateness here is about missing a departure
        rather than exceeding a duration.
        """
        first = self._departure_after(tick, route)
        return first + (max(1, int(nth)) - 1) * self.interval

    def departures_for(self, route: str, count: int = 6,
                       tick: int = 0) -> List[int]:
        """The next `count` departure times, for a timetable on a panel."""
        return [self.nth_departure_after(route, tick, n)
                for n in range(1, max(1, int(count)) + 1)]

    def promise_for(self, service_or_priority: str, tick: int,
                    route: str) -> int:
        """The tick by which a parcel of this class has been promised to leave."""
        nth = PROMISED_DEPARTURE.get(str(service_or_priority).upper(),
                                     PROMISED_DEPARTURE["NORMAL"])
        # From the end of the handling allowance, not from now: the carrier
        # promises the first van the parcel could actually be got onto.
        return self.nth_departure_after(route, int(tick) + HANDLING_ALLOWANCE,
                                        nth)

    # ------------------------------------------------------------- report
    def state(self) -> Dict[str, object]:
        return {
            "interval": self.interval,
            "capacity": self.capacity,
            "departures": self.departures,
            "at_bay": {route: van.as_dict()
                       for route, van in sorted(self._bay.items())},
        }
