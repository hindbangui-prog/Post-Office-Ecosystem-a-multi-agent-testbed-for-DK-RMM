"""
The collapse criterion: did the facility stop doing its job, and when?

A stressed run is judged against the control run of the same seed, tick by
tick, on facility quantities only: parcels dispatched (what left on vans) and
the backlog (parcels inside the building). DK-RMM's reading of the same run
is recorded beside the verdict and plays no part in it.

The parameters, with their defaults (`COLLAPSE`):

    evaluated_from          400   ticks before are never degraded
    window                  100   throughput = parcels dispatched in the
                                  trailing window (t - window, t]
    throughput_fraction     0.5   throughput degraded: run < fraction x control
    throughput_evaluable_min  2   and the control dispatched at least this
                                  many in its window (otherwise nothing can
                                  be said about throughput on that tick)
    backlog_margin            5   backlog degraded: run > control + margin
    slope_window            200   and the run's backlog over the trailing
                                  slope window has not fallen (slope >= 0)
    persist_ticks           300   collapse: throughput and backlog both
                                  degraded on every tick of a 300-tick run

Outcome: `COLLAPSED` (the first tick of the first such run, and whether it
held to the end), `DEGRADED` (degraded ticks but no run long enough), or
`STABLE`. `critical_stop_tick` is the first evaluated tick on which the run
dispatched nothing in the trailing 400 ticks while the control dispatched
something: a facility that has stopped, as opposed to one that has slowed.

Pure functions over the rows `measure.Collector` writes to `series.csv`
(each a dict with at least `tick`, `dispatched`, `backlog`). Rows are
matched by tick; a tick the control has no row for is skipped, and a skipped
tick breaks a run of consecutive degraded ticks, because it was not shown to
be degraded.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import Any, Dict, List, Optional, Sequence

COLLAPSE: Dict[str, Any] = {
    "evaluated_from": 400,
    "window": 100,
    "throughput_fraction": 0.5,
    "throughput_evaluable_min": 2,
    "backlog_margin": 5,
    "slope_window": 200,
    "persist_ticks": 300,
}

#: The trailing window of the critical-stop test, in ticks.
CRITICAL_STOP_WINDOW = 400

COLLAPSED = "COLLAPSED"
DEGRADED = "DEGRADED"
STABLE = "STABLE"


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
        self._prefix = [0]
        for n in self.dispatched:
            self._prefix.append(self._prefix[-1] + n)

    def __contains__(self, tick: int) -> bool:
        return tick in self.rows

    def dispatched_in(self, tick: int, window: int) -> int:
        """Parcels dispatched on the ticks in (tick - window, tick]."""
        lo = bisect_right(self.ticks, tick - window)
        hi = bisect_right(self.ticks, tick)
        return self._prefix[hi] - self._prefix[lo]

    def backlog_at(self, tick: int) -> int:
        return int(self.rows[tick].get("backlog", 0) or 0)

    def backlog_at_or_after(self, tick: int) -> Optional[int]:
        """The backlog on the first row at or after `tick`, if there is one."""
        index = bisect_left(self.ticks, tick)
        if index >= len(self.ticks):
            return None
        return self.backlog[index]


def flags(run_rows: Sequence[Dict[str, Any]], control_rows: Sequence[Dict[str, Any]],
          params: Dict[str, Any] = COLLAPSE) -> List[Dict[str, Any]]:
    """
    The per-tick flags, one row per evaluated tick of the run.

    Each row: `tick`, `run_throughput`, `control_throughput`, `run_backlog`,
    `control_backlog`, `backlog_slope`, `through_degraded`, `backlog_degraded`,
    `degraded`. Ticks before `evaluated_from` are included with every flag
    false; ticks the control has no row for are left out.
    """
    p = {**COLLAPSE, **(params or {})}
    run, control = _Series(run_rows), _Series(control_rows)
    window = int(p["window"])
    slope_window = int(p["slope_window"])
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
        evaluated = tick >= int(p["evaluated_from"])
        through = (evaluated and ctl_tp >= int(p["throughput_evaluable_min"])
                   and run_tp < float(p["throughput_fraction"]) * ctl_tp)
        backlog = (evaluated and run_bl > ctl_bl + int(p["backlog_margin"])
                   and slope >= 0)
        out.append({
            "tick": tick,
            "run_throughput": run_tp, "control_throughput": ctl_tp,
            "run_backlog": run_bl, "control_backlog": ctl_bl,
            "backlog_slope": slope,
            "through_degraded": bool(through),
            "backlog_degraded": bool(backlog),
            "degraded": bool(through and backlog),
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


def _held_to_end(rows: List[Dict[str, Any]], key: str, since: int) -> bool:
    """Whether `key` holds on every evaluated tick from `since` to the last."""
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
    `collapse_tick`, `held_to_end`, `critical_stop_tick`, `first_degraded_tick`,
    the counts of ticks each flag held on, `evaluated_ticks`,
    `simulation_end_tick` and the parameters used. Pure: reads the rows and
    nothing else.
    """
    p = {**COLLAPSE, **(params or {})}
    rows = flags(run_rows, control_rows, p)
    evaluated_from = int(p["evaluated_from"])
    persist = int(p["persist_ticks"])

    collapse_tick = _first_run(rows, "degraded", persist, evaluated_from)
    held = _held_to_end(rows, "degraded", collapse_tick) if collapse_tick is not None else False

    run, control = _Series(run_rows), _Series(control_rows)
    critical_stop: Optional[int] = None
    for row in rows:
        tick = row["tick"]
        if tick < evaluated_from:
            continue
        if (run.dispatched_in(tick, CRITICAL_STOP_WINDOW) == 0
                and control.dispatched_in(tick, CRITICAL_STOP_WINDOW) > 0):
            critical_stop = tick
            break

    degraded_ticks = [row["tick"] for row in rows if row["degraded"]]
    if collapse_tick is not None:
        outcome = COLLAPSED
    elif degraded_ticks:
        outcome = DEGRADED
    else:
        outcome = STABLE
    return {
        "outcome": outcome,
        "collapse_tick": collapse_tick,
        "held_to_end": bool(held),
        "critical_stop_tick": critical_stop,
        "first_degraded_tick": degraded_ticks[0] if degraded_ticks else None,
        "degraded_ticks": len(degraded_ticks),
        "through_degraded_ticks": sum(1 for row in rows if row["through_degraded"]),
        "backlog_degraded_ticks": sum(1 for row in rows if row["backlog_degraded"]),
        "evaluated_ticks": sum(1 for row in rows if row["tick"] >= evaluated_from),
        "simulation_end_tick": run.ticks[-1] if run.ticks else None,
        "control_end_tick": control.ticks[-1] if control.ticks else None,
        "params": p,
    }
