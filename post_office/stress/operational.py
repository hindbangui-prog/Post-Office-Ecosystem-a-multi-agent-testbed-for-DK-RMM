"""
The operational stressors of C2-NEAR-SYSTEM-OVERRIDE, applied from outside.

Three mechanisms, each acting on the facility through a seam that already
exists, so the ecosystem's own code is untouched:

    arrival_surge   `generator.mean_interval` becomes the configured Normal
                    interval divided by ARRIVAL_FACTOR. The baseline is read
                    from the configuration, never from the generator's
                    current value, so the factor is applied once and to the
                    right number.
    route_closed    the van standing at the bay for the route is taken away
                    (`DepartureBoard._bay.pop`) and no replacement is ever
                    brought up. `board.routes` is left alone: the other
                    routes' offsets are computed from it and must not move.
                    The dispatch gate holds a parcel whose route has no van
                    ("nothing to load onto"); parcels for the route keep
                    arriving.
    charge_loss     the named charge points are removed from `env.stations`,
                    which is the dictionary every reader uses. A robot that
                    was on one of them finds its station gone on its next
                    charging step, reports `charging_interrupted` and waits.
                    An occupied point is removed like a free one, and the
                    occupant is written into the event.

Every activation is one `stress_fault_activated` event (category
`simulation`, actor `SIMULATION`) with the mechanism, the fault id and the
before/after detail. Each fault fires once; `before_tick` is idempotent.

There is no removal, undo or restoration path in this class, on purpose:
the experiment holds every fault to the end of the run, and code that could
put things back would be code whose absence from the run has to be proved.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..communication.events import EventCategory
from . import c2near_system_override as spec
from .c2near_system_override import Condition


class OperationalStress:
    """The scheduled operational faults of one run, applied as their tick comes."""

    def __init__(self, eco: Any, cond: Condition) -> None:
        self.eco = eco
        self.cond = cond
        #: The operational rows of the schedule. The attack row (mechanism
        #: `attack`) belongs to the campaign, not to this class.
        self.schedule: List[Dict[str, Any]] = [
            row for row in spec.schedule(cond) if row["mechanism"] != spec.ATTACK]
        #: fault_id -> the detail that was written into its activation event.
        self.applied: Dict[str, Dict[str, Any]] = {}
        #: Routes closed so far, in the order they were closed.
        self.closed_routes: List[str] = []

    # ------------------------------------------------------------- the clock
    def before_tick(self, tick: int) -> List[str]:
        """
        Apply every scheduled fault whose tick is `tick`, once each.

        Called by the driver before `eco.step()` for that tick, so the tick's
        arrivals, agents and departures already see the fault. Returns the
        fault ids applied on this call (usually none).
        """
        fired: List[str] = []
        for row in self.schedule:
            if int(row["tick"]) != int(tick) or row["fault_id"] in self.applied:
                continue
            mechanism = row["mechanism"]
            if mechanism == spec.ARRIVAL_SURGE:
                detail = self._arrival_surge()
            elif mechanism == spec.ROUTE_CLOSED:
                detail = self._route_closed(row["detail"]["route"])
            elif mechanism == spec.CHARGE_LOSS:
                detail = self._charge_loss()
            else:
                raise ValueError(f"unknown operational mechanism {mechanism!r}")
            self.applied[row["fault_id"]] = {"tick": int(tick), "mechanism": mechanism,
                                             **detail}
            self.eco.logger.emit(
                EventCategory.SIMULATION, "stress_fault_activated", tick=int(tick),
                actor="SIMULATION", mechanism=mechanism, fault_id=row["fault_id"],
                experiment=spec.EXPERIMENT, condition=self.cond.id, **detail)
            fired.append(row["fault_id"])
        return fired

    # ------------------------------------------------------------ mechanisms
    def _arrival_surge(self) -> Dict[str, Any]:
        generator = self.eco.generator
        # The configured Normal value, not the generator's current one.
        baseline = float(self.eco.config["arrival_interval"])
        before = float(generator.mean_interval)
        after = baseline / spec.ARRIVAL_FACTOR
        generator.mean_interval = after
        return {
            "interval_baseline": baseline,
            "interval_before": before,
            "interval_after": after,
            "factor": spec.ARRIVAL_FACTOR,
            "arrivals_per_tick_before": 1.0 / before if before > 0 else 0.0,
            "arrivals_per_tick_after": 1.0 / after if after > 0 else 0.0,
        }

    def _route_closed(self, route: str) -> Dict[str, Any]:
        board = self.eco.env.departures
        van = board._bay.pop(route, None)
        if route not in self.closed_routes:
            self.closed_routes.append(route)
        return {
            "route": route,
            "vehicle_removed": van.vehicle_id if van is not None else None,
            "would_have_departed_at": van.departs_at if van is not None else None,
            "parcels_on_van_at_removal": len(van.loaded) if van is not None else 0,
            "routes_open_after": self.routes_open(),
            "routes_closed_after": list(self.closed_routes),
        }

    def _charge_loss(self) -> Dict[str, Any]:
        env = self.eco.env
        before = sorted(env.stations)
        removed: List[str] = []
        occupied: Dict[str, Optional[str]] = {}
        for station_id in spec.CHARGING_REMOVED:
            station = env.stations.pop(station_id, None)
            if station is None:
                continue
            removed.append(station_id)
            occupied[station_id] = station.occupant
        return {
            "stations_before": before,
            "stations_after": sorted(env.stations),
            "removed": removed,
            "occupied_at_removal": occupied,
            "kept": list(spec.CHARGING_KEPT),
        }

    # --------------------------------------------------------------- reports
    def routes_open(self) -> List[str]:
        """The routes with a van at the bay, in timetable order."""
        board = self.eco.env.departures
        return [route for route in board.routes if board.at_bay(route) is not None]

    def stations_available(self) -> List[str]:
        """The charge points still in the facility."""
        return sorted(self.eco.env.stations)

    def faults_applied(self) -> List[Dict[str, Any]]:
        """Every fault applied so far, in activation order, for the measurement file."""
        return [{"fault_id": fault_id, **detail}
                for fault_id, detail in self.applied.items()]
