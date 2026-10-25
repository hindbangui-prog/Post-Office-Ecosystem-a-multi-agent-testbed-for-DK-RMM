"""
Work, made explicit.

The spec's demand that dependencies not hide inside function calls is really a
demand about this file. A task is a first-class object with an owner, a state
and a written history, so "the scheduling agent is waiting on the resource
agent" is something you can read off the data rather than something you have to
infer from a stack trace.

Every task carries a `correlation_id`. It is the parcel's id for parcel work,
and it is the thread that ties a message from the barcode sub-agent, a plan
from the planner, a route from the routing agent and a robot's delivery report
into one story.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Dict, List, Optional

from ..environment.parcels import ParcelPriority
from ..environment.zones import Zone


class TaskType(str, Enum):
    """What kind of work this is."""

    CLASSIFY = "CLASSIFY"    # read, identify and grade a parcel; no robot needed
    TRANSPORT = "TRANSPORT"  # carry a parcel from one zone to another
    STORE = "STORE"          # put a parcel into temporary storage
    DISPATCH = "DISPATCH"    # hand a parcel to the outbound dock
    CHARGE = "CHARGE"        # take a robot to a charge point


class TaskStatus(str, Enum):
    """The six states in the spec, and nothing else."""

    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


#: A task in one of these is finished with, one way or another.
TERMINAL_STATUSES = frozenset({
    TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED,
})

#: Which transitions are legal. An illegal one is a bug, and raises.
ALLOWED_TRANSITIONS: Dict[TaskStatus, frozenset] = {
    TaskStatus.CREATED: frozenset({TaskStatus.ASSIGNED, TaskStatus.CANCELLED,
                                   TaskStatus.FAILED}),
    TaskStatus.ASSIGNED: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.CREATED,
                                    TaskStatus.CANCELLED, TaskStatus.FAILED}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED,
                                       TaskStatus.CANCELLED,
                                       TaskStatus.CREATED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


class IllegalTransition(RuntimeError):
    """Raised when something tries to move a task backwards through its life."""


@dataclass
class Task:
    """One unit of work, its owner, its state and everything done to it."""

    #: How many history lines one task keeps before the middle is elided.
    MAX_HISTORY: ClassVar[int] = 40

    task_id: str
    task_type: TaskType
    parcel_id: Optional[str] = None
    source: Optional[Zone] = None
    destination: Optional[Zone] = None
    assigned_agent: Optional[str] = None     # the expert or sub-agent that owns it
    assigned_robot: Optional[str] = None     # the robot actually doing it
    priority: ParcelPriority = ParcelPriority.NORMAL
    status: TaskStatus = TaskStatus.CREATED
    created_by: str = ""
    created_tick: int = 0
    #: When the parcel this task is for was promised to leave. Copied from the
    #: parcel at creation rather than looked up: a queue is ordered thousands of
    #: times a run, and an ordering that has to open every parcel to compare two
    #: tasks is an ordering nobody will use.
    due_by: Optional[int] = None
    correlation_id: str = ""
    depends_on: List[str] = field(default_factory=list)
    route: List[Dict[str, int]] = field(default_factory=list)
    detail: Dict[str, object] = field(default_factory=dict)
    history: List[Dict[str, object]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.correlation_id:
            self.correlation_id = self.parcel_id or self.task_id
        if not self.history:
            self.history.append({
                "tick": self.created_tick,
                "actor": self.created_by,
                "status": self.status.value,
                "note": "created",
            })

    # ------------------------------------------------------------ transitions
    def can(self, status: TaskStatus) -> bool:
        """Whether that move is legal from here. Asked before acting on a
        message that may have crossed with something else."""
        return status is self.status or status in ALLOWED_TRANSITIONS[self.status]

    def transition(self, status: TaskStatus, tick: int, actor: str,
                   note: str = "", **detail) -> None:
        """
        Move to a new state, refusing moves that make no sense.

        A silent illegal transition is the kind of bug that shows up three
        phases later as a parcel that never arrives, so this raises instead.
        """
        if status is self.status:
            return
        if status not in ALLOWED_TRANSITIONS[self.status]:
            raise IllegalTransition(
                f"{self.task_id}: {self.status.value} -> {status.value} "
                f"(attempted by {actor or 'someone'})"
            )
        self.status = status
        self.history.append({
            "tick": tick, "actor": actor, "status": status.value,
            "note": note, **detail,
        })
        if len(self.history) > self.MAX_HISTORY:
            # Keep the beginning and the recent past. A task released and
            # re-dispatched forty times is interesting; the thirty-sixth
            # release is not, and an uncapped list is how a long run's memory
            # and its API payloads grow without limit.
            head, tail = self.history[:4], self.history[-(self.MAX_HISTORY - 5):]
            elided = len(self.history) - len(head) - len(tail)
            self.history = head + [{"tick": tick, "actor": "",
                                    "status": self.status.value,
                                    "note": f"... {elided} entries elided"}] + tail

    def assign(self, agent_id: str, tick: int, actor: str,
               robot_id: Optional[str] = None) -> None:
        self.assigned_agent = agent_id
        if robot_id is not None:
            self.assigned_robot = robot_id
        self.transition(TaskStatus.ASSIGNED, tick, actor,
                        note=f"assigned to {agent_id}", robot=robot_id)

    def start(self, tick: int, actor: str, **detail) -> None:
        self.transition(TaskStatus.IN_PROGRESS, tick, actor, note="started",
                        **detail)

    def complete(self, tick: int, actor: str, **detail) -> None:
        self.transition(TaskStatus.COMPLETED, tick, actor, note="completed",
                        **detail)

    def fail(self, tick: int, actor: str, reason: str = "", **detail) -> None:
        self.transition(TaskStatus.FAILED, tick, actor, note=reason or "failed",
                        **detail)

    def cancel(self, tick: int, actor: str, reason: str = "") -> None:
        self.transition(TaskStatus.CANCELLED, tick, actor,
                        note=reason or "cancelled")

    def release(self, tick: int, actor: str, reason: str = "") -> None:
        """
        Hand a task back to the pool -- the robot that had it went flat, or the
        shelf it was bound for filled up. Back to CREATED, not to FAILED: the
        work still needs doing, it just needs doing by somebody else.
        """
        self.assigned_agent = None
        self.assigned_robot = None
        self.transition(TaskStatus.CREATED, tick, actor,
                        note=reason or "released")

    # ----------------------------------------------------------------- state
    @property
    def is_open(self) -> bool:
        return self.status not in TERMINAL_STATUSES

    @property
    def is_unassigned(self) -> bool:
        return self.status is TaskStatus.CREATED

    def slack_at(self, tick: int) -> Optional[int]:
        """Ticks left before the promise is broken. None when nothing was promised."""
        return None if self.due_by is None else self.due_by - int(tick)

    @property
    def sort_key(self):
        """
        The one ordering rule in the system: what is closest to being late,
        then priority, then age.

        Deadline first is not a refinement of priority ordering, it replaces
        it. A facility with cut-offs does not work on the most important parcel
        -- it works on the one about to miss its van, which is frequently a
        standard parcel that has been waiting while urgent ones with an hour of
        slack went ahead of it. Priority survives as the tie-break for work
        with no promise or the same one.

        Defined here so the planner, the scheduler and the API all order the
        queue identically -- three subtly different orderings would be three
        different systems.
        """
        # A task with no promise sorts after every task that has one, rather
        # than before them: absence of a deadline is not urgency.
        return (self.due_by if self.due_by is not None else 10 ** 9,
                -self.priority.rank, self.created_tick, self.task_id)

    def summary(self) -> dict:
        """Without the history. What a list of tasks should carry."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "parcel_id": self.parcel_id,
            "source": self.source.value if self.source else None,
            "destination": self.destination.value if self.destination else None,
            "assigned_agent": self.assigned_agent,
            "assigned_robot": self.assigned_robot,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_by": self.created_by,
            "created_tick": self.created_tick,
            "due_by": self.due_by,
            "correlation_id": self.correlation_id,
            "history_entries": len(self.history),
        }

    def as_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "parcel_id": self.parcel_id,
            "source": self.source.value if self.source else None,
            "destination": self.destination.value if self.destination else None,
            "assigned_agent": self.assigned_agent,
            "assigned_robot": self.assigned_robot,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_by": self.created_by,
            "created_tick": self.created_tick,
            "due_by": self.due_by,
            "correlation_id": self.correlation_id,
            "depends_on": list(self.depends_on),
            "route": [dict(step) for step in self.route],
            "detail": dict(self.detail),
            "history": [dict(h) for h in self.history],
        }
