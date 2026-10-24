"""
The shape of an agent asking the facility to intervene physically.

Lives beside the environment rather than beside the engine that acts on it,
because the queue of outstanding requests is a fact about the floor -- part of
its state, visible to anything reading it -- while carrying one out is the
engine's business. Keeping the shape here also keeps the agents clear of the
simulation package, which imports them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RecoveryRequest:
    """
    An agent asking the facility to intervene. A request, not an instruction.

    Shaped as a structured action rather than a method call so that it can be
    logged, counted, refused and replayed -- and so that the boundary between
    "an agent decided" and "the floor changed" has something concrete at it.
    """

    action: str                  # "REQUEST_RECOVERY"
    robot_id: str
    requested_by: str
    tick: int
    reason: str = ""
    target: str = ""             # a preferred charge point, if the asker has one
    attempts: int = 0

    def as_dict(self) -> dict:
        return {"action": self.action, "robot_id": self.robot_id,
                "requested_by": self.requested_by, "tick": self.tick,
                "reason": self.reason, "target": self.target,
                "attempts": self.attempts}
