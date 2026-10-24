"""
Identifiers that are readable in a log and identical between two runs.

No UUIDs anywhere in the simulation: a run that cannot be diffed against its
own repeat is not much use for an experiment, and `P-0007` tells you more at a
glance than a hex string ever will.
"""

from __future__ import annotations

from typing import Dict


class IdFactory:
    """Monotonic, per-prefix counters. `reset()` puts a run back to zero."""

    __slots__ = ("_counters", "_width")

    def __init__(self, width: int = 4) -> None:
        self._counters: Dict[str, int] = {}
        self._width = width

    def next(self, prefix: str) -> str:
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}-{n:0{self._width}d}"

    def issued(self, prefix: str) -> int:
        return self._counters.get(prefix, 0)

    def reset(self) -> None:
        self._counters.clear()
