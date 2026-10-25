"""
The scheduled faults of C2-NEAR-SYSTEM-OVERRIDE, applied from outside.

`ScheduledFaults` walks the condition's schedule (`c2near_system_override.
schedule`) and fires each row as its tick comes: the three operational
mechanisms, which act on the facility, and the attack row, which acts on
nothing and only writes down that the campaign is armed. Every row acts
through a seam that already exists, so the ecosystem's own code is untouched:

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
                    arriving. Parcels already on the removed van stay on it
                    (see `_route_closed`): every parcel on a van is in a
                    sealed bag handed over whole, and no existing method
                    unseals a bag or takes a parcel off a van, so they are
                    recorded as stranded and count as backlog to the end.
    charge_loss     the named charge points are removed from `env.stations`,
                    which is the dictionary every reader uses. A robot that
                    was on one of them finds its station gone on its next
                    charging step, reports `charging_interrupted` and waits.
                    An occupied point is removed like a free one, and the
                    occupant is written into the event.
    attack          (condition C2) no operational effect. The System
                    Override campaign is the interception layer's agent
                    hooks, installed when the ecosystem was built and active
                    from its own `start_tick`; this row records at that tick
                    that it is armed: targets, start tick, delivery policy,
                    corpus fingerprint, and whether the campaign is bound.

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


class ScheduledFaults:
    """The scheduled faults of one run (operational and attack arming), applied as their tick comes."""

    def __init__(self, eco: Any, cond: Condition) -> None:
        self.eco = eco
        self.cond = cond
        #: Every row of the condition's schedule, the attack row included.
        self.schedule: List[Dict[str, Any]] = list(spec.schedule(cond))
        #: fault_id -> the detail that was written into its activation event.
        self.applied: Dict[str, Dict[str, Any]] = {}
        #: Routes closed so far, in the order they were closed.
        self.closed_routes: List[str] = []

    # ------------------------------------------------------------- the clock
    def before_tick(self, tick: int) -> List[str]:
        """
        Fire every scheduled row whose tick is `tick`, once each.

        Called by the driver before `eco.step()` for that tick, so the tick's
        arrivals, agents and departures already see the fault. Returns the
        fault ids fired on this call (usually none).
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
            elif mechanism == spec.ATTACK:
                detail = self._attack_armed(row["detail"])
            else:
                raise ValueError(f"unknown scheduled mechanism {mechanism!r}")
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
        """
        Take the route's van off the bay.

        What was already on the van stays on it. The only way a parcel gets
        onto a van is `DISPATCH._hand_over`, one sealed bag at a time, which
        sets `bag.loaded_on`, `parcel.bagged_in` and `parcel.loaded_on`.
        There is no existing method that unseals a bag (`Receptacle.seal` is
        one-way), unbags a parcel, or takes a parcel off a `Vehicle`
        (`Vehicle.load` only adds), and this module adds none. Clearing
        `parcel.loaded_on` alone would leave the bag and the van saying the
        parcel is loaded while the parcel says it is not, so nothing is
        unloaded: the parcels and their bags are recorded as stranded. They
        stay in `env.parcels` with status AWAITING_DISPATCH, `bagged_in` and
        `loaded_on` set, so the gate never asks about them again and they
        count as backlog for the rest of the run.
        """
        env = self.eco.env
        board = env.departures
        van = board._bay.pop(route, None)
        if route not in self.closed_routes:
            self.closed_routes.append(route)
        stranded_parcels: List[str] = []
        stranded_bags: List[str] = []
        if van is not None:
            stranded_parcels = list(van.loaded)
            room = getattr(env, "bags", None)
            if room is not None:
                stranded_bags = sorted(bag.receptacle_id for bag in room.all_bags()
                                       if bag.loaded_on == van.vehicle_id)
        return {
            "route": route,
            "vehicle_removed": van.vehicle_id if van is not None else None,
            "would_have_departed_at": van.departs_at if van is not None else None,
            "parcels_on_van_at_removal": len(van.loaded) if van is not None else 0,
            # Nothing can be unloaded with the methods that exist (see above).
            "parcels_unloaded": [],
            "bags_unloaded": [],
            "parcels_stranded_on_van": stranded_parcels,
            "bags_stranded_on_van": stranded_bags,
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

    def _attack_armed(self, row_detail: Dict[str, Any]) -> Dict[str, Any]:
        """
        The campaign's arming record. Changes nothing: the campaign is the
        interception layer's agent hooks and has been in place since the
        ecosystem was built; from its `start_tick` it delivers on its own.
        """
        campaign = self.campaign()
        return {
            "targets": list(row_detail.get("targets", spec.TARGETS)),
            "start_tick": int(row_detail.get("start_tick", spec.STRESS_START)),
            "delivery": str(row_detail.get("delivery", spec.DELIVERY)),
            "exhaustion": str(row_detail.get("exhaustion", spec.EXHAUSTION)),
            "corpus_fingerprint": str(row_detail.get("corpus_fingerprint", "")),
            "campaign_installed": campaign is not None,
            "campaign_bound": bool(getattr(campaign, "bound", False)),
            "campaign_targets": list(getattr(campaign, "targets", []) or []),
            "campaign_start_tick": getattr(campaign, "start_tick", None),
            "operational_effect": "none",
        }

    # --------------------------------------------------------------- reports
    def campaign(self) -> Any:
        """The System Override campaign installed as the agent hooks, or None."""
        crew = getattr(self.eco, "crew", None)
        interception = getattr(crew, "interception", None)
        agent = getattr(interception, "agent", None)
        return agent if hasattr(agent, "before_prompt") and hasattr(agent, "bound") else None

    def routes_open(self) -> List[str]:
        """The routes with a van at the bay, in timetable order."""
        board = self.eco.env.departures
        return [route for route in board.routes if board.at_bay(route) is not None]

    def stations_available(self) -> List[str]:
        """The charge points still in the facility."""
        return sorted(self.eco.env.stations)

    def faults_applied(self) -> List[Dict[str, Any]]:
        """Every fault fired so far, in activation order, for the measurement file."""
        return [{"fault_id": fault_id, **detail}
                for fault_id, detail in self.applied.items()]


#: The name the first commit used; the class applies the whole schedule, not
#: only its operational rows, so it is `ScheduledFaults` now.
OperationalStress = ScheduledFaults

__all__ = ["OperationalStress", "ScheduledFaults"]
