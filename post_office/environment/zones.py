"""
The five functional areas of the facility, and the rectangles they occupy.

A zone is a named region plus the cells that belong to it. Keeping the mapping
here -- rather than scattering `if x < 5` tests through the agents -- means the
floor plan can be redrawn in `config/` without a single agent changing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterator, List, Optional, Sequence

from .grid import Position


class Zone(str, Enum):
    """Where in the post office something is."""

    INTAKE = "INTAKE"                       # parcels arrive here
    SORTING = "SORTING"                     # they are classified and grouped
    TEMPORARY_STORAGE = "TEMPORARY_STORAGE"  # they wait here for their van
    DISPATCH = "DISPATCH"                   # they leave from here
    CHARGING = "CHARGING"                   # robots, not parcels


@dataclass(frozen=True, slots=True)
class Rect:
    """An inclusive rectangle of cells."""

    x0: int
    y0: int
    x1: int
    y1: int

    def __contains__(self, p: Position) -> bool:
        return self.x0 <= p.x <= self.x1 and self.y0 <= p.y <= self.y1

    def cells(self) -> Iterator[Position]:
        for y in range(self.y0, self.y1 + 1):
            for x in range(self.x0, self.x1 + 1):
                yield Position(x, y)

    @property
    def centre(self) -> Position:
        return Position((self.x0 + self.x1) // 2, (self.y0 + self.y1) // 2)

    def as_dict(self) -> dict:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}

    @staticmethod
    def of(value) -> "Rect":
        if isinstance(value, Rect):
            return value
        if isinstance(value, dict):
            return Rect(int(value["x0"]), int(value["y0"]),
                        int(value["x1"]), int(value["y1"]))
        a, b, c, d = value
        return Rect(int(a), int(b), int(c), int(d))


class ZoneMap:
    """Which zone each cell belongs to, and where each zone is."""

    def __init__(self, rects: Dict[Zone, Rect]) -> None:
        self._rects: Dict[Zone, Rect] = dict(rects)
        self._index: Dict[Position, Zone] = {}
        for zone, rect in self._rects.items():
            for cell in rect.cells():
                self._index[cell] = zone

    def __getitem__(self, zone: Zone) -> Rect:
        return self._rects[zone]

    def __contains__(self, zone: Zone) -> bool:
        return zone in self._rects

    def zones(self) -> List[Zone]:
        return list(self._rects)

    def zone_at(self, p) -> Optional[Zone]:
        return self._index.get(Position.of(p))

    def cells_of(self, zone: Zone) -> List[Position]:
        return sorted(self._rects[zone].cells())

    def anchor(self, zone: Zone) -> Position:
        """One canonical cell per zone: where a robot goes when told 'DISPATCH'."""
        return self._rects[zone].centre

    def as_dict(self) -> dict:
        return {z.value: r.as_dict() for z, r in self._rects.items()}
