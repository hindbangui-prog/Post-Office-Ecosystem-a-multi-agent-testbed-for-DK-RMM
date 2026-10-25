"""
The handles every agent needs, gathered in one object.

`World` is not a god object and is not allowed to become one: it holds the
facility, the task registry, the fleet, the seeded generators and the logger,
and it has no behaviour of its own. Agents read from it and call the methods of
the things inside it; what they may not do is reach into another agent through
it, which is why the agents themselves are deliberately absent from this class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..communication.events import EventLogger
from ..environment.facility import PostOfficeEnvironment
from ..robots.fleet import Fleet
from ..tasks.registry import TaskRegistry
from .ids import IdFactory
from .rng import SeededRNG


@dataclass
class Policy:
    """
    The supervisor's standing orders.

    Everything here is something a human supervisor would plausibly set, and
    nothing here is something an agent may change on its own: the supervisor
    writes, everybody else reads. Keeping them in one object means a
    perturbation experiment can change one number at a known tick and see what
    happens, which is the whole reason for separating policy from code.
    """

    max_concurrent_transports: int = 8     # how much work is let onto the floor
    reserve_battery: float = 35.0          # below this, a robot goes to charge
    resume_battery: float = 90.0           # and charges until this
    urgent_first: bool = True              # priority beats age in the queue
    store_normal_parcels: bool = True      # NORMAL parcels go via storage
    status_report_every: int = 20          # planner -> supervisor cadence
    max_storage_load: float = 0.9          # above this, stop routing to storage
    notes: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "max_concurrent_transports": self.max_concurrent_transports,
            "reserve_battery": self.reserve_battery,
            "resume_battery": self.resume_battery,
            "urgent_first": self.urgent_first,
            "store_normal_parcels": self.store_normal_parcels,
            "status_report_every": self.status_report_every,
            "max_storage_load": self.max_storage_load,
            "notes": dict(self.notes),
        }


@dataclass
class World:
    """Shared, non-agent runtime state. Passed to every agent at attach time."""

    env: PostOfficeEnvironment
    tasks: TaskRegistry
    fleet: Fleet
    rng: SeededRNG
    logger: EventLogger
    ids: IdFactory
    policy: Policy = field(default_factory=Policy)
    #: The validator every agent decision passes through before it counts.
    #: Held here rather than on the agents for the same reason `policy` is:
    #: the thing that permits an action must not belong to the thing taking
    #: it. Left None only in unit tests that build an agent by hand.
    gate: Optional[Any] = None
    #: Whether the facility is still idle, for the experts' model calls
    #: (`simulation.activity.ActivityGate`). Installed only in a run with an
    #: expert on the model; None in a rules-only run and in unit tests.
    activity: Optional[Any] = None
    tick: int = 0
    objective: str = ""
    running: bool = False

    def advance(self, tick: int) -> None:
        self.tick = tick
        self.env.tick = tick
