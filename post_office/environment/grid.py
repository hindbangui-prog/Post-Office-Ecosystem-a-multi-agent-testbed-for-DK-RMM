"""
The floor plan: a 2-D grid with walls, and a way across it.

The grid knows about geometry and obstacles and nothing else. It has never
heard of a robot, a parcel or an agent, which is what lets the same floor plan
be reused by a different simulation, and lets the routing sub-agent be tested
without starting an ecosystem.

Paths are 4-connected and found with A*. Ties in the frontier are broken on
`(f, h, x, y)` rather than on insertion order, so the path between two cells is
the same path on every run and on every machine -- a route that wobbles between
runs would make the whole simulation irreproducible for no good reason.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple


@dataclass(frozen=True, slots=True, order=True)
class Position:
    """A cell. Immutable, hashable, and cheap to put in a set."""

    x: int
    y: int

    def __iter__(self) -> Iterator[int]:
        yield self.x
        yield self.y

    def manhattan(self, other: "Position") -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)

    def neighbours(self) -> Tuple["Position", ...]:
        """North, east, south, west -- always in that order, for determinism."""
        return (
            Position(self.x, self.y - 1),
            Position(self.x + 1, self.y),
            Position(self.x, self.y + 1),
            Position(self.x - 1, self.y),
        )

    def as_dict(self) -> Dict[str, int]:
        return {"x": self.x, "y": self.y}

    @staticmethod
    def of(value) -> "Position":
        """Accept a Position, a tuple or a dict -- config files use all three."""
        if isinstance(value, Position):
            return value
        if isinstance(value, dict):
            return Position(int(value["x"]), int(value["y"]))
        x, y = value
        return Position(int(x), int(y))

    def __repr__(self) -> str:      # shows up in every log line; keep it short
        return f"({self.x},{self.y})"


class Grid:
    """A rectangle of cells, some of which are walls."""

    def __init__(self, width: int, height: int,
                 obstacles: Iterable[Position] = ()) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("grid must have positive width and height")
        self.width = int(width)
        self.height = int(height)
        self.obstacles: Set[Position] = {Position.of(o) for o in obstacles}
        self._path_cache: Dict[Tuple[Position, Position], Optional[List[Position]]] = {}

    # ------------------------------------------------------------------ cells
    def in_bounds(self, p: Position) -> bool:
        return 0 <= p.x < self.width and 0 <= p.y < self.height

    def is_free(self, p: Position) -> bool:
        """Free of *walls*. Robots are not walls -- collisions are the routing
        sub-agent's problem, not the floor plan's."""
        return self.in_bounds(p) and p not in self.obstacles

    def add_obstacle(self, p) -> None:
        self.obstacles.add(Position.of(p))
        self._path_cache.clear()

    def cells(self) -> Iterator[Position]:
        for y in range(self.height):
            for x in range(self.width):
                yield Position(x, y)

    # ------------------------------------------------------------------ paths
    def path(self, start, goal) -> Optional[List[Position]]:
        """
        The shortest walkable path from `start` to `goal`, inclusive of both.

        Returns None when the goal is unreachable or walled in. Results are
        cached: the floor plan does not move, and the routing sub-agent asks
        for the same few hundred paths over and over.
        """
        start = Position.of(start)
        goal = Position.of(goal)
        key = (start, goal)
        if key in self._path_cache:
            cached = self._path_cache[key]
            return list(cached) if cached is not None else None

        result = self._astar(start, goal)
        self._path_cache[key] = result
        return list(result) if result is not None else None

    def distance(self, start, goal) -> Optional[int]:
        """Path length in steps, or None if there is no path."""
        p = self.path(start, goal)
        return None if p is None else len(p) - 1

    def _astar(self, start: Position, goal: Position) -> Optional[List[Position]]:
        if not self.is_free(start) or not self.is_free(goal):
            return None
        if start == goal:
            return [start]

        open_heap: List[Tuple[int, int, int, int, Position]] = []
        heapq.heappush(open_heap, (start.manhattan(goal), start.manhattan(goal),
                                   start.x, start.y, start))
        came: Dict[Position, Position] = {}
        best: Dict[Position, int] = {start: 0}
        closed: Set[Position] = set()

        while open_heap:
            _f, _h, _x, _y, current = heapq.heappop(open_heap)
            if current in closed:
                continue
            if current == goal:
                return self._reconstruct(came, current)
            closed.add(current)

            g = best[current] + 1
            for nxt in current.neighbours():
                if not self.is_free(nxt) or nxt in closed:
                    continue
                if g < best.get(nxt, 1 << 30):
                    best[nxt] = g
                    came[nxt] = current
                    h = nxt.manhattan(goal)
                    heapq.heappush(open_heap, (g + h, h, nxt.x, nxt.y, nxt))

        return None

    @staticmethod
    def _reconstruct(came: Dict[Position, Position],
                     end: Position) -> List[Position]:
        path = [end]
        while path[-1] in came:
            path.append(came[path[-1]])
        path.reverse()
        return path

    # ----------------------------------------------------------------- render
    def as_text(self, marks: Optional[Dict[Position, str]] = None) -> str:
        """A quick ASCII picture. For tests and for the terminal, not for a UI."""
        marks = {Position.of(k): v for k, v in (marks or {}).items()}
        rows = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                p = Position(x, y)
                row.append(marks.get(p, "#" if p in self.obstacles else "."))
            rows.append("".join(row))
        return "\n".join(rows)

    def as_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "obstacles": [p.as_dict() for p in sorted(self.obstacles)],
        }
