from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

#: Above this many registered agents the declared-edge set is built from the
#: parent/child links only, rather than by asking the directory about every
#: ordered pair. The facility has 28, so the full set is what is used here;
#: the cap keeps the cost quadratic only while quadratic is cheap.
DECLARED_EDGES_FULL_UP_TO = 40


def _read(errors: Dict[str, str], name: str, reader: Callable[[], Any]) -> Any:
    """One guarded read. None, and a note in `errors`, when it is unavailable."""
    try:
        return reader()
    except Exception as exc:  # any failure at all: the field is unreadable
        errors[name] = f"{type(exc).__name__}: {exc}"
        return None


def _ratio(numerator: Optional[float], denominator: Optional[float],
           cap: Optional[float] = None) -> Optional[float]:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    value = float(numerator) / float(denominator)
    if cap is not None:
        value = min(cap, value)
    return max(0.0, value)


def declared_edges(directory: Any) -> Optional[List[Tuple[str, str]]]:
    """
    The declared structure as ordered (sender, receiver) pairs, from the
    agent directory: every parent/child link both ways, plus (while the
    roster is at most DECLARED_EDGES_FULL_UP_TO agents) every pair the
    directory's own `may_send` allows. `may_send` is a pure check with no
    side effect, so asking it is a read. None when the directory cannot be
    read at all.
    """
    try:
        records = list(directory.all())
    except Exception:
        return None
    edges = set()
    for record in records:
        parent = getattr(record, "parent_id", None)
        child = getattr(record, "agent_id", None)
        if parent and child:
            edges.add((str(parent), str(child)))
            edges.add((str(child), str(parent)))
    if len(records) <= DECLARED_EDGES_FULL_UP_TO and hasattr(directory, "may_send"):
        ids = [str(getattr(r, "agent_id", "")) for r in records]
        for a in ids:
            for b in ids:
                if a == b:
                    continue
                try:
                    allowed = directory.may_send(a, b)[0]
                except Exception:
                    allowed = False
                if allowed:
                    edges.add((a, b))
    return sorted(edges)


def snapshot_state(eco: Any) -> Dict[str, Any]:
    """
    Read the facility's present condition. Reads only; never raises.

    Fields (each None when the read failed, with the reason in `errors`):

    - `backlog`: parcels inside the building (`len(eco.env.parcels)`).
    - `by_zone`: those parcels counted by `parcel.current_zone`, with the
      ones on a robot (position None) under "carried". Each parcel once.
    - `unfinished_tasks`: tasks not COMPLETED, FAILED or CANCELLED.
    - `refused_total`: arrivals the dock has turned away so far.
    - `held_now`: messages the bus is holding back right now.
    - `resources`: per category (robots, charge_points, routes, storage,
      dock) the counts it was read from, its utilisation `value` in [0, 1]
      and whether it is `evaluable`.
    - `resource_saturation`: the maximum over the evaluable categories, the
      bottleneck; None when the roster of robots is empty or unreadable.
    - `declared_edges`: the declared structure, see `declared_edges`.
    """
    errors: Dict[str, str] = {}
    out: Dict[str, Any] = {"errors": errors}

    env = _read(errors, "env", lambda: eco.env)
    fleet = _read(errors, "fleet", lambda: eco.fleet)

    # ---------------------------------------------------------- parcels
    parcels = _read(errors, "parcels", lambda: list(env.parcels.values()))
    out["backlog"] = len(parcels) if parcels is not None else None
    by_zone: Optional[Dict[str, int]] = None
    if parcels is not None:
        def count_zones() -> Dict[str, int]:
            zones: Dict[str, int] = {}
            for parcel in parcels:
                if getattr(parcel, "position", None) is None:
                    key = "carried"
                else:
                    zone = getattr(parcel, "current_zone", None)
                    key = str(getattr(zone, "value", zone) or "unknown")
                zones[key] = zones.get(key, 0) + 1
            return zones
        by_zone = _read(errors, "by_zone", count_zones)
    out["by_zone"] = by_zone

    def unfinished() -> int:
        counts = eco.world.tasks.counts()
        return sum(int(n) for status, n in counts.items()
                   if status not in ("COMPLETED", "FAILED", "CANCELLED"))
    out["unfinished_tasks"] = _read(errors, "unfinished_tasks", unfinished)
    out["refused_total"] = _read(errors, "refused_total",
                                 lambda: int(eco.generator.refused))
    out["held_now"] = _read(errors, "held_now", lambda: len(eco.bus._held))

    # -------------------------------------------------------- resources
    resources: Dict[str, Dict[str, Any]] = {}

    # Robots: the fleet's own `is_available` (via `fleet.available()`) says
    # which can be given work; the rest are busy, charging, flat or stuck.
    roster = _read(errors, "robots.roster", lambda: len(fleet))
    available = _read(errors, "robots.available", lambda: len(fleet.available()))
    robots_value = None
    if roster is not None and available is not None and roster > 0:
        robots_value = max(0.0, min(1.0, 1.0 - available / roster))
    resources["robots"] = {"roster": roster, "available": available,
                           "value": robots_value,
                           "evaluable": robots_value is not None}

    # Charge points: occupied over existing. With no points at all the
    # answer depends on whether anybody needs one: 1.0 if so, 0.0 if not.
    points = _read(errors, "charge.points", lambda: len(env.stations))
    occupied = _read(errors, "charge.occupied", lambda: sum(
        1 for s in env.stations.values() if getattr(s, "occupant", None) is not None))
    needing = _read(errors, "charge.needing", lambda: len(fleet.needing_charge()))
    charge_value = None
    if points is not None and occupied is not None:
        if points > 0:
            charge_value = max(0.0, min(1.0, occupied / points))
        elif needing is not None:
            charge_value = 1.0 if needing > 0 else 0.0
    resources["charge_points"] = {"points": points, "occupied": occupied,
                                  "needing": needing, "value": charge_value,
                                  "evaluable": charge_value is not None}

    # Routes: declared routes with no van at the bay. Before `start()` the
    # bay is empty and every route reads closed; with no routes declared the
    # fraction is 0.0 by convention and not evaluable.
    declared = _read(errors, "routes.declared", lambda: len(env.departures.routes))
    open_routes = _read(errors, "routes.open", lambda: sum(
        1 for route in env.departures.routes
        if env.departures._bay.get(route) is not None))
    routes_value = None
    routes_ok = False
    if declared is not None and open_routes is not None:
        if declared > 0:
            routes_value = max(0.0, min(1.0, (declared - open_routes) / declared))
            routes_ok = True
        else:
            routes_value = 0.0
    resources["routes"] = {"declared": declared, "open": open_routes,
                           "value": routes_value, "evaluable": routes_ok}

    # Storage: shelves used over shelves there are.
    used = _read(errors, "storage.used", lambda: int(env.storage.used))
    capacity = _read(errors, "storage.capacity", lambda: int(env.storage.capacity))
    storage_value = _ratio(used, capacity, cap=1.0)
    resources["storage"] = {"used": used, "capacity": capacity,
                            "value": storage_value,
                            "evaluable": storage_value is not None}

    # Dock: parcels on the intake dock over the cap the generator refuses
    # at. "On the dock" is the generator's own reading, `parcels_in(INTAKE)`:
    # a parcel with a position whose current zone is INTAKE, which is what
    # `by_zone["INTAKE"]` counted above (carried parcels are under "carried").
    on_dock = by_zone.get("INTAKE", 0) if by_zone is not None else None
    max_on_dock = _read(errors, "dock.max_on_dock",
                        lambda: int(eco.generator.max_on_dock))
    dock_value = _ratio(on_dock, max_on_dock, cap=1.0)
    resources["dock"] = {"on_dock": on_dock, "max_on_dock": max_on_dock,
                         "value": dock_value,
                         "evaluable": dock_value is not None}

    out["resources"] = resources
    # The bottleneck: the tightest category. Evaluable only when there are
    # robots to speak of, as the design says; a facility with no fleet has
    # no resource picture worth a number.
    if roster is not None and roster > 0:
        values = [c["value"] for c in resources.values()
                  if c["evaluable"] and c["value"] is not None]
        out["resource_saturation"] = max(values) if values else None
    else:
        out["resource_saturation"] = None

    # -------------------------------------------------------- structure
    directory = _read(errors, "directory", lambda: eco.bus.directory)
    out["declared_edges"] = (declared_edges(directory)
                             if directory is not None else None)
    return out
