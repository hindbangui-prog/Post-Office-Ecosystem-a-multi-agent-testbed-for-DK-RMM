"""
Per-tick measurement of a stress run: `series.csv` and `measurement.json`.

The collector sits beside the ecosystem the way DK-RMM does: it subscribes
to the event log for the things only the log can tell it (vans leaving,
consultations opened, campaign messages delivered, the gate's verdict on a
model decision) and reads the facility's own counters after each tick for
the rest (arrivals, backlog, tasks, robots, stations, routes). It writes to
nothing in the run.

One row per tick. The columns, in the order they are written:

    tick
    arrivals                parcels the generator created this tick
    refused                 parcels the facility refused this tick
    dispatched              parcels that left on vans this tick
    backlog                 parcels inside the building after the tick
    tasks_created ... tasks_cancelled   the registry's counts by status
    tasks_ready, tasks_blocked          open tasks whose dependencies are
                                        satisfied / not yet satisfied
    robots_available        IDLE or WAITING, battery above zero, no task and
                            nothing on board (stated here, because the
                            robot's own `is_available` has other conditions)
    robots_charging         status CHARGING
    robots_flat             battery at or below zero
    stations                charge points in the facility
    routes_open             routes with a van at the bay
    dep_<ROUTE>             vans departed on the route, cumulative
    targeted_consultations  `consult_opened` by a targeted expert this tick
    override_delivered      `system_override_delivered` events this tick
    override_responses      `system_override_response` events this tick
    gate_accepted           model decisions of a targeted expert the gate
                            passed this tick (`validation == "ok"`)
    gate_rejected           those it refused
    dkrmm_state             the monitor's current state, if one is attached
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..agents.subagents.sorting_subagents import ROUTES
from ..robots.robot import RobotState
from ..tasks.task import TaskStatus
from . import c2near_system_override as spec
from .c2near_system_override import Condition

TASK_COLUMNS = [f"tasks_{status.value.lower()}" for status in TaskStatus]
ROUTE_COLUMNS = [f"dep_{route}" for route in ROUTES]
COLUMNS = (["tick", "arrivals", "refused", "dispatched", "backlog"]
           + TASK_COLUMNS + ["tasks_ready", "tasks_blocked",
                             "robots_available", "robots_charging", "robots_flat",
                             "stations", "routes_open"]
           + ROUTE_COLUMNS
           + ["targeted_consultations", "override_delivered", "override_responses",
              "gate_accepted", "gate_rejected", "dkrmm_state"])


class Collector:
    """One run's measurement, a row per tick, bounded by the run's length."""

    def __init__(self, eco: Any, cond: Condition, stress: Any,
                 monitor: Optional[Any] = None) -> None:
        self.eco = eco
        self.cond = cond
        self.stress = stress
        self.monitor = monitor
        self.rows: List[Dict[str, Any]] = []
        # From where the counters stand now: the parcels seeded on the dock
        # before the first tick are the initial backlog, not arrivals.
        self.initial_parcels = int(eco.generator.created)
        self._created_seen = self.initial_parcels
        self._refused_seen = int(getattr(eco.env, "refused_count", 0) or 0)
        # Per-tick counters fed by the event stream, reset by `after_step`.
        self._tick: Dict[str, int] = {}
        self._reset_tick()
        # Run totals fed by the event stream.
        self.departures: Dict[str, int] = {route: 0 for route in ROUTES}
        self.parcels_by_route: Dict[str, int] = {route: 0 for route in ROUTES}
        self.decision_status: Dict[str, int] = {}
        self.fault_ticks: Dict[str, int] = {}
        self._unsubscribe = eco.logger.subscribe(self.observe)

    def _reset_tick(self) -> None:
        self._tick = {"dispatched": 0, "targeted_consultations": 0,
                      "override_delivered": 0, "override_responses": 0,
                      "gate_accepted": 0, "gate_rejected": 0}

    def close(self) -> None:
        if self._unsubscribe is not None:
            try:
                self._unsubscribe()
            except Exception:
                pass
            self._unsubscribe = None

    # ------------------------------------------------------------- the log
    def observe(self, event: Any) -> None:
        """One event, as the logger hands it over. Counts; never acts."""
        topic = event.topic
        detail = event.detail or {}
        if topic == "van_departed":
            parcels = int(detail.get("parcels", 0) or 0)
            route = str(detail.get("route") or "")
            self._tick["dispatched"] += parcels
            if route in self.departures:
                self.departures[route] += 1
                self.parcels_by_route[route] += parcels
        elif topic == "consult_opened":
            if event.actor in spec.TARGETS:
                self._tick["targeted_consultations"] += 1
        elif topic == "system_override_delivered":
            self._tick["override_delivered"] += 1
        elif topic == "system_override_response":
            self._tick["override_responses"] += 1
        elif topic == "decision":
            if event.actor in spec.TARGETS and detail.get("mode") == "llm":
                if detail.get("validation") == "ok":
                    self._tick["gate_accepted"] += 1
                else:
                    self._tick["gate_rejected"] += 1
                status = str(detail.get("status") or "")
                self.decision_status[status] = self.decision_status.get(status, 0) + 1
        elif topic == "stress_fault_activated":
            fault_id = str(detail.get("fault_id") or "")
            if fault_id and fault_id not in self.fault_ticks:
                self.fault_ticks[fault_id] = int(event.tick)

    # ----------------------------------------------------------- the tick
    def _robots(self) -> Dict[str, int]:
        available = charging = flat = 0
        for robot in self.eco.fleet.all():
            if robot.battery_level <= 0:
                flat += 1
            if robot.status is RobotState.CHARGING:
                charging += 1
            if (robot.status in (RobotState.IDLE, RobotState.WAITING)
                    and robot.battery_level > 0
                    and robot.current_task is None
                    and robot.carrying is None):
                available += 1
        return {"robots_available": available, "robots_charging": charging,
                "robots_flat": flat}

    def _dkrmm_state(self) -> str:
        if self.monitor is None:
            return ""
        try:
            current = self.monitor.state().get("current")
        except Exception:
            return ""
        return str(current.get("state", "")) if isinstance(current, dict) else ""

    def after_step(self) -> Dict[str, Any]:
        """Append the row for the tick that has just completed, and return it."""
        eco = self.eco
        created = int(eco.generator.created)
        refused = int(getattr(eco.env, "refused_count", 0) or 0)
        counts = eco.tasks.counts()
        row: Dict[str, Any] = {
            "tick": int(eco.world.tick),
            "arrivals": created - self._created_seen,
            "refused": refused - self._refused_seen,
            "dispatched": self._tick["dispatched"],
            "backlog": len(eco.env.parcels),
        }
        for status in TaskStatus:
            row[f"tasks_{status.value.lower()}"] = int(counts.get(status.value, 0))
        row["tasks_ready"] = len(eco.tasks.ready())
        row["tasks_blocked"] = len(eco.tasks.blocked())
        row.update(self._robots())
        row["stations"] = len(eco.env.stations)
        board = eco.env.departures
        row["routes_open"] = sum(1 for route in board.routes
                                 if board.at_bay(route) is not None)
        for route in ROUTES:
            row[f"dep_{route}"] = self.departures[route]
        for key in ("targeted_consultations", "override_delivered",
                    "override_responses", "gate_accepted", "gate_rejected"):
            row[key] = self._tick[key]
        row["dkrmm_state"] = self._dkrmm_state()
        self.rows.append(row)
        self._created_seen = created
        self._refused_seen = refused
        self._reset_tick()
        return row

    # --------------------------------------------------------------- totals
    def totals(self) -> Dict[str, Any]:
        keys = ("arrivals", "refused", "dispatched", "targeted_consultations",
                "override_delivered", "override_responses", "gate_accepted",
                "gate_rejected")
        out: Dict[str, Any] = {key: sum(int(row[key]) for row in self.rows) for key in keys}
        last = self.rows[-1] if self.rows else {}
        out["initial_parcels"] = self.initial_parcels
        out["ticks"] = int(last.get("tick", 0))
        out["backlog_end"] = int(last.get("backlog", 0))
        out["stations_end"] = int(last.get("stations", 0))
        out["routes_open_end"] = int(last.get("routes_open", 0))
        out["backlog_max"] = max((int(row["backlog"]) for row in self.rows), default=0)
        out["decision_status_targeted_llm"] = dict(sorted(self.decision_status.items()))
        return out

    def per_route(self) -> Dict[str, Dict[str, Any]]:
        """Departures, parcels dispatched, closure tick and backlog by route."""
        closed_at: Dict[str, int] = {}
        for fault in self.stress.faults_applied():
            if fault.get("mechanism") == spec.ROUTE_CLOSED:
                closed_at[str(fault.get("route"))] = int(fault["tick"])
        inside: Dict[str, int] = {route: 0 for route in ROUTES}
        for parcel in self.eco.env.parcels.values():
            label = str(getattr(parcel, "route_label", "") or "")
            if label in inside:
                inside[label] += 1
        board = self.eco.env.departures
        return {route: {
            "departures": self.departures[route],
            "parcels_dispatched": self.parcels_by_route[route],
            "closed_at": closed_at.get(route),
            "open_at_end": board.at_bay(route) is not None,
            "backlog_end": inside[route],
        } for route in ROUTES}

    def measurement(self, interrupted: bool = False) -> Dict[str, Any]:
        return {
            "experiment": spec.EXPERIMENT,
            "label": spec.LABEL,
            "condition": self.cond.id,
            "seed": self.eco.seed,
            "run_id": self.eco.run_id,
            "interrupted": bool(interrupted),
            "totals": self.totals(),
            "faults_applied": self.stress.faults_applied(),
            "fault_ticks": dict(self.fault_ticks),
            "per_route": self.per_route(),
            "summary": self.eco.summary(),
            "reasoning": self.eco.reasoning_summary(),
            "dkrmm": self.monitor.state() if self.monitor is not None else None,
        }

    # ---------------------------------------------------------------- files
    def write(self, out_dir: Any, interrupted: bool = False) -> Dict[str, Any]:
        """Write `series.csv` and `measurement.json` under `out_dir`; return the latter."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        with (out / "series.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            for row in self.rows:
                writer.writerow({key: row.get(key, "") for key in COLUMNS})
        measurement = self.measurement(interrupted=interrupted)
        (out / "measurement.json").write_text(
            json.dumps(measurement, indent=1, default=str) + "\n",
            encoding="utf-8", newline="\n")
        return measurement


def read_series(path: Any) -> List[Dict[str, Any]]:
    """Read a `series.csv` back, numbers as ints, for `collapse.classify`."""
    rows: List[Dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            row: Dict[str, Any] = {}
            for key, value in raw.items():
                if key == "dkrmm_state":
                    row[key] = value
                    continue
                try:
                    row[key] = int(value)
                except (TypeError, ValueError):
                    row[key] = value
            rows.append(row)
    return rows
