"""
The collapse criterion: did the facility stop doing its job, and when?

A stressed run is judged against the control run of the same seed, tick by
tick, on facility quantities only: parcels dispatched (what left on vans),
the backlog (parcels inside the building) and the dock refusals (arrivals
turned away because the intake dock was full). DK-RMM's reading of the same
run is recorded beside the verdict and plays no part in it.

The parameters, with their defaults (`COLLAPSE`):

    evaluated_from          400   ticks before are never degraded
    window                  250   throughput = parcels dispatched in the
                                  trailing window (t - window, t]. One van
                                  interval, so every control window spans a
                                  departure of every open route.
    throughput_fraction     0.5   throughput degraded: run < fraction x control
    throughput_evaluable_min  2   and the control dispatched at least this
                                  many in its window (otherwise nothing can
                                  be said about throughput on that tick)
    backlog_margin            5   backlog degraded: run > control + margin
    slope_window            200   and either the run's backlog over the
                                  trailing slope window has not fallen
                                  (slope >= 0) ...
    refused_window          200   ... or the run refused more arrivals at the
                                  dock in the trailing refused window than
                                  the control did (the dock is saturated: the
                                  backlog cannot grow because nothing more
                                  gets in)
    persist_ticks           300   collapse: throughput and backlog both
                                  degraded on every tick of a 300-tick run
    critical_stop_window    400   critical stop: the run dispatched nothing
                                  in this trailing window while the control
                                  dispatched something

Two collapse paths:

    sustained_degradation   `degraded` (throughput and backlog degraded)
                            holds on `persist_ticks` consecutive evaluated
                            ticks
    critical_stop           `critical_stop` holds from its first tick to
                            the end of the run

Outcome: `COLLAPSED` when either path fires (`collapse_criterion` names the
paths that fired, `collapse_tick` is the earliest of their ticks),
`DEGRADED` (degraded ticks but no run long enough and no critical stop held
to the end), or `STABLE`. A critical stop that did not hold to the end is
reported (`critical_stop_tick`, `critical_stop_held_to_end`) but is not a
collapse.

Evaluability: a throughput flag needs the control to have dispatched at
least `throughput_evaluable_min` in its window, and a critical-stop flag
needs the control to have dispatched something in its window. `classify`
counts, per flag, the evaluated ticks on which that was not so, so a reader
sees how much of the run could not be judged.

Pure functions over the rows `measure.Collector` writes to `series.csv`
(each a dict with at least `tick`, `dispatched`, `backlog`; `arrival_refused`
is read as 0 when absent). Rows are matched by tick; a tick the control has
no row for is skipped, and a skipped tick breaks a run of consecutive
degraded ticks, because it was not shown to be degraded.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import Any, Dict, List, Optional, Sequence

COLLAPSE: Dict[str, Any] = {
    "evaluated_from": 400,
    "window": 250,
    "throughput_fraction": 0.5,
    "throughput_evaluable_min": 2,
    "backlog_margin": 5,
    "slope_window": 200,
    "refused_window": 200,
    "persist_ticks": 300,
    "critical_stop_window": 400,
}

#: The trailing window of the critical-stop test, in ticks (the default).
CRITICAL_STOP_WINDOW = COLLAPSE["critical_stop_window"]

COLLAPSED = "COLLAPSED"
DEGRADED = "DEGRADED"
STABLE = "STABLE"

SUSTAINED_DEGRADATION = "sustained_degradation"
CRITICAL_STOP = "critical_stop"


class _Series:
    """One run's rows indexed by tick, with prefix sums for window queries."""

    def __init__(self, rows: Sequence[Dict[str, Any]]) -> None:
        by_tick: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            by_tick[int(row["tick"])] = row
        self.ticks: List[int] = sorted(by_tick)
        self.rows = by_tick
        self.dispatched = [int(by_tick[t].get("dispatched", 0) or 0) for t in self.ticks]
        self.backlog = [int(by_tick[t].get("backlog", 0) or 0) for t in self.ticks]
        self.refused = [int(by_tick[t].get("arrival_refused", 0) or 0) for t in self.ticks]
        self._prefix = _prefix(self.dispatched)
        self._prefix_refused = _prefix(self.refused)

    def __contains__(self, tick: int) -> bool:
        return tick in self.rows

    def _window(self, prefix: List[int], tick: int, window: int) -> int:
        lo = bisect_right(self.ticks, tick - window)
        hi = bisect_right(self.ticks, tick)
        return prefix[hi] - prefix[lo]

    def dispatched_in(self, tick: int, window: int) -> int:
        """Parcels dispatched on the ticks in (tick - window, tick]."""
        return self._window(self._prefix, tick, window)

    def refused_in(self, tick: int, window: int) -> int:
        """Arrivals refused at the dock on the ticks in (tick - window, tick]."""
        return self._window(self._prefix_refused, tick, window)

    def backlog_at(self, tick: int) -> int:
        return int(self.rows[tick].get("backlog", 0) or 0)

    def backlog_at_or_after(self, tick: int) -> Optional[int]:
        """The backlog on the first row at or after `tick`, if there is one."""
        index = bisect_left(self.ticks, tick)
        if index >= len(self.ticks):
            return None
        return self.backlog[index]


def _prefix(values: Sequence[int]) -> List[int]:
    out = [0]
    for n in values:
        out.append(out[-1] + n)
    return out


def flags(run_rows: Sequence[Dict[str, Any]], control_rows: Sequence[Dict[str, Any]],
          params: Dict[str, Any] = COLLAPSE) -> List[Dict[str, Any]]:
    """
    The per-tick flags, one row per tick of the run the control also has.

    Each row: `tick`, `evaluated`, `run_throughput`, `control_throughput`,
    `through_evaluable`, `through_degraded`, `run_backlog`, `control_backlog`,
    `backlog_slope`, `run_refused`, `control_refused`, `backlog_degraded`,
    `degraded`, `critical_stop_evaluable`, `critical_stop`. Ticks before
    `evaluated_from` are included with every flag false; ticks the control
    has no row for are left out.
    """
    p = {**COLLAPSE, **(params or {})}
    run, control = _Series(run_rows), _Series(control_rows)
    window = int(p["window"])
    slope_window = int(p["slope_window"])
    refused_window = int(p["refused_window"])
    stop_window = int(p["critical_stop_window"])
    evaluable_min = int(p["throughput_evaluable_min"])
    out: List[Dict[str, Any]] = []
    for tick in run.ticks:
        if tick not in control:
            continue
        run_tp = run.dispatched_in(tick, window)
        ctl_tp = control.dispatched_in(tick, window)
        run_bl = run.backlog_at(tick)
        ctl_bl = control.backlog_at(tick)
        earlier = run.backlog_at_or_after(tick - slope_window)
        slope = run_bl - (earlier if earlier is not None else run_bl)
        run_refused = run.refused_in(tick, refused_window)
        ctl_refused = control.refused_in(tick, refused_window)
        evaluated = tick >= int(p["evaluated_from"])
        through_evaluable = evaluated and ctl_tp >= evaluable_min
        through = through_evaluable and run_tp < float(p["throughput_fraction"]) * ctl_tp
        backlog = (evaluated and run_bl > ctl_bl + int(p["backlog_margin"])
                   and (slope >= 0 or run_refused > ctl_refused))
        ctl_stop_tp = control.dispatched_in(tick, stop_window)
        stop_evaluable = evaluated and ctl_stop_tp > 0
        stop = stop_evaluable and run.dispatched_in(tick, stop_window) == 0
        out.append({
            "tick": tick,
            "evaluated": bool(evaluated),
            "run_throughput": run_tp, "control_throughput": ctl_tp,
            "through_evaluable": bool(through_evaluable),
            "through_degraded": bool(through),
            "run_backlog": run_bl, "control_backlog": ctl_bl,
            "backlog_slope": slope,
            "run_refused": run_refused, "control_refused": ctl_refused,
            "backlog_degraded": bool(backlog),
            "degraded": bool(through and backlog),
            "critical_stop_evaluable": bool(stop_evaluable),
            "critical_stop": bool(stop),
        })
    return out


def _first_run(rows: List[Dict[str, Any]], key: str, length: int,
               start: int) -> Optional[int]:
    """
    The first tick t >= start from which `key` holds on `length` consecutive
    ticks (t, t + 1, ..., t + length - 1, every one present and flagged).
    """
    run_start: Optional[int] = None
    previous: Optional[int] = None
    for row in rows:
        tick = row["tick"]
        if tick < start:
            continue
        consecutive = previous is not None and tick == previous + 1
        if not row[key]:
            run_start = None
        elif run_start is None or not consecutive:
            run_start = tick
        previous = tick
        if run_start is not None and tick - run_start + 1 >= length:
            return run_start
    return None


def _first_tick(rows: List[Dict[str, Any]], key: str, start: int) -> Optional[int]:
    """The first tick t >= start on which `key` holds."""
    for row in rows:
        if row["tick"] >= start and row[key]:
            return row["tick"]
    return None


def _held_to_end(rows: List[Dict[str, Any]], key: str, since: int) -> bool:
    """Whether `key` holds on every tick from `since` to the last, with no gap."""
    tail = [row for row in rows if row["tick"] >= since]
    if not tail:
        return False
    for earlier, later in zip(tail, tail[1:]):
        if later["tick"] != earlier["tick"] + 1:
            return False
    return all(row[key] for row in tail)


def classify(run_rows: Sequence[Dict[str, Any]], control_rows: Sequence[Dict[str, Any]],
             params: Dict[str, Any] = COLLAPSE) -> Dict[str, Any]:
    """
    The verdict on `run_rows` against `control_rows` (same seed).

    Returns a dictionary with `outcome` (COLLAPSED / DEGRADED / STABLE),
    `collapse_tick`, `collapse_criterion` (the paths that fired, earliest
    first; None when none did), `held_to_end` (for the path that set
    `collapse_tick`), the two paths' own ticks and held-to-end flags,
    `first_degraded_tick`, the counts of ticks each flag held on, the counts
    of evaluated ticks each flag could not be evaluated on, `evaluated_ticks`,
    `simulation_end_tick` and the parameters used. Pure: reads the rows and
    nothing else.
    """
    p = {**COLLAPSE, **(params or {})}
    rows = flags(run_rows, control_rows, p)
    evaluated_from = int(p["evaluated_from"])
    persist = int(p["persist_ticks"])

    degradation_tick = _first_run(rows, "degraded", persist, evaluated_from)
    degradation_held = (_held_to_end(rows, "degraded", degradation_tick)
                        if degradation_tick is not None else False)

    critical_stop = _first_tick(rows, "critical_stop", evaluated_from)
    critical_stop_held = (_held_to_end(rows, "critical_stop", critical_stop)
                          if critical_stop is not None else False)

    fired: List[tuple] = []
    if degradation_tick is not None:
        fired.append((degradation_tick, SUSTAINED_DEGRADATION, degradation_held))
    if critical_stop is not None and critical_stop_held:
        fired.append((critical_stop, CRITICAL_STOP, True))
    fired.sort(key=lambda item: item[0])

    degraded_ticks = [row["tick"] for row in rows if row["degraded"]]
    if fired:
        outcome = COLLAPSED
        collapse_tick: Optional[int] = fired[0][0]
        criterion: Optional[List[str]] = [name for _, name, _ in fired]
        held = bool(fired[0][2])
    else:
        collapse_tick, criterion, held = None, None, False
        outcome = DEGRADED if degraded_ticks else STABLE

    evaluated = [row for row in rows if row["evaluated"]]
    run, control = _Series(run_rows), _Series(control_rows)
    return {
        "outcome": outcome,
        "collapse_tick": collapse_tick,
        "collapse_criterion": criterion,
        "held_to_end": held,
        "degradation_tick": degradation_tick,
        "degradation_held_to_end": bool(degradation_held),
        "critical_stop_tick": critical_stop,
        "critical_stop_held_to_end": bool(critical_stop_held),
        "first_degraded_tick": degraded_ticks[0] if degraded_ticks else None,
        "degraded_ticks": len(degraded_ticks),
        "through_degraded_ticks": sum(1 for row in rows if row["through_degraded"]),
        "backlog_degraded_ticks": sum(1 for row in rows if row["backlog_degraded"]),
        "critical_stop_ticks": sum(1 for row in rows if row["critical_stop"]),
        "evaluated_ticks": len(evaluated),
        # Per flag: evaluated ticks on which the flag could not be judged.
        "not_evaluable_ticks": {
            "through_degraded": sum(1 for row in evaluated if not row["through_evaluable"]),
            "backlog_degraded": 0,
            "critical_stop": sum(1 for row in evaluated
                                 if not row["critical_stop_evaluable"]),
        },
        "simulation_end_tick": run.ticks[-1] if run.ticks else None,
        "control_end_tick": control.ticks[-1] if control.ticks else None,
        "params": p,
    }
