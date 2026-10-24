"""
Seeded randomness that survives a change of experiment.

A single shared generator is reproducible only until the moment you add a robot
or reorder the agents -- from then on every later draw shifts, and two runs that
should have been comparable are not. So each named participant draws from its
own stream, derived from the run seed and its own identifier by hashing. Adding
R6 changes nothing about what R3 draws.

Taken from the mas-ecosystems framework, where the same argument applies.
"""

from __future__ import annotations

import hashlib
import random
from typing import Dict


def mix(seed: int, label: str) -> int:
    """Derive an independent sub-seed from a run seed and a name."""
    digest = hashlib.sha256(f"{seed}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


class SeededRNG:
    """A run seed, and one `random.Random` per named participant."""

    __slots__ = ("seed", "world", "_streams")

    def __init__(self, seed: int = 0) -> None:
        self.seed = int(seed)
        self.world = random.Random(mix(self.seed, "__world__"))
        self._streams: Dict[str, random.Random] = {}

    def stream(self, label: str) -> random.Random:
        """The generator belonging to `label`, created on first use."""
        rng = self._streams.get(label)
        if rng is None:
            rng = random.Random(mix(self.seed, label))
            self._streams[label] = rng
        return rng

    def labels(self) -> list:
        return sorted(self._streams)
