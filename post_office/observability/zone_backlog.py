"""
Where the unfinished parcels are, tick by tick, and how many came and went.

One row per tick, read from the building after the tick has been stepped. It
reads only; nothing in the run depends on it.

    tick            the tick just completed (0 is the building as built)
    intake          parcels on the floor whose `current_zone` is INTAKE
    sorting         ... SORTING
    storage         ... TEMPORARY_STORAGE
    dispatch        ... DISPATCH (parcels bagged or already loaded on a van
                    that has not left are still here: they are inside)
    carried         parcels on a robot (no position)
    other           parcels on the floor in any other zone (expected 0)
    total           every parcel inside the building, `len(env.parcels)`;
                    each parcel is counted in exactly one of the six columns
                    above, so they always sum to `total`
    loaded_on_van   of `dispatch`, those already loaded on a van that has not
                    left (a part of `dispatch`, not added to the sum)
    arrivals        parcels the dock accepted this tick (`generator.created`)
    dock_refusals   arrivals the dock turned away this tick (`generator.refused`)
    completions     parcels that left on a van this tick (`env.dispatched_count`)
    returned        parcels accepted and then returned unread (`env.returned_count`)
    gate_refused    parcels refused after arrival (`env.refused_count`)
    reconciled      `total` equals the previous row's `total` plus arrivals
                    minus completions, returned and gate_refused (None on
                    tick 0, which has no previous row)
    unfinished_tasks  tasks not COMPLETED, FAILED or CANCELLED

The initial parcels seeded on the dock before tick 1 are the tick-0 row's
`total`, not arrivals (the convention of `stress/measure.Collector`).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional

ZONE_COLUMNS = ["intake", "sorting", "storage", "dispatch", "carried", "other"]
FLOW_COLUMNS = ["arrivals", "dock_refusals", "completions", "returned", "gate_refused"]
COLUMNS = (["tick"] + ZONE_COLUMNS + ["total", "loaded_on_van"] + FLOW_COLUMNS
           + ["reconciled", "unfinished_tasks"])

_ZONE_KEY = {"INTAKE": "intake", "SORTING": "sorting",
             "TEMPORARY_STORAGE": "storage", "DISPATCH": "dispatch"}

_FINISHED = ("COMPLETED", "FAILED", "CANCELLED")


def _counters(eco: Any) -> Dict[str, int]:
    env, gen = eco.env, eco.generator
    return {"arrivals": int(gen.created),
            "dock_refusals": int(getattr(gen, "refused", 0) or 0),
            "completions": int(getattr(env, "dispatched_count", 0) or 0),
            "returned": int(getattr(env, "returned_count", 0) or 0),
            "gate_refused": int(getattr(env, "refused_count", 0) or 0)}


def zone_counts(eco: Any) -> Dict[str, int]:
    """The six zone columns, `total` and `loaded_on_van`, as the building stands now."""
    out = {key: 0 for key in ZONE_COLUMNS}
    loaded = 0
    parcels = list(eco.env.parcels.values())
    for parcel in parcels:
        if getattr(parcel, "position", None) is None:
            out["carried"] += 1
            continue
        zone = getattr(parcel, "current_zone", None)
        key = _ZONE_KEY.get(str(getattr(zone, "value", zone)), "other")
        out[key] += 1
        if key == "dispatch" and getattr(parcel, "loaded_on", None):
            loaded += 1
    out["total"] = len(parcels)
    out["loaded_on_van"] = loaded
    return out


class ZoneSeries:
    """The rows of one run, appended by `sample()` once per completed tick."""

    def __init__(self, eco: Any, keep: int = 50000) -> None:
        self.eco = eco
        self.keep = int(keep)
        self.rows: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self._seen = _counters(eco)
        first = {"tick": int(eco.world.tick), **zone_counts(eco),
                 **{key: 0 for key in FLOW_COLUMNS}, "reconciled": None,
                 "unfinished_tasks": self._unfinished()}
        self.rows.append(first)

    def _unfinished(self) -> Optional[int]:
        try:
            counts = self.eco.world.tasks.counts()
            return sum(int(n) for status, n in counts.items() if status not in _FINISHED)
        except Exception:
            return None

    def sample(self) -> Optional[Dict[str, Any]]:
        """Append the row of the tick just completed (once per tick) and return it."""
        try:
            tick = int(self.eco.world.tick)
            if self.rows and self.rows[-1]["tick"] == tick:
                return self.rows[-1]
            now = _counters(self.eco)
            flows = {key: now[key] - self._seen[key] for key in FLOW_COLUMNS}
            self._seen = now
            row: Dict[str, Any] = {"tick": tick, **zone_counts(self.eco), **flows}
            previous = self.rows[-1]["total"] if self.rows else None
            row["reconciled"] = (None if previous is None else
                                 row["total"] == previous + flows["arrivals"]
                                 - flows["completions"] - flows["returned"]
                                 - flows["gate_refused"])
            row["unfinished_tasks"] = self._unfinished()
            self.rows.append(row)
            if len(self.rows) > self.keep:
                del self.rows[: len(self.rows) - self.keep]
            return row
        except Exception as exc:                 # the run never depends on this
            self.errors.append(f"{type(exc).__name__}: {exc}")
            return None

    def since(self, after: int = -1, limit: int = 5000) -> List[Dict[str, Any]]:
        """Rows with `tick > after`, oldest first, at most `limit` (the newest)."""
        rows = [row for row in self.rows if row["tick"] > after]
        return rows[-int(limit):] if limit else rows

    def write(self, path: Any) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            for row in self.rows:
                writer.writerow({key: ("" if row.get(key) is None else row.get(key))
                                 for key in COLUMNS})


__all__ = ["COLUMNS", "FLOW_COLUMNS", "ZONE_COLUMNS", "ZoneSeries", "zone_counts"]
