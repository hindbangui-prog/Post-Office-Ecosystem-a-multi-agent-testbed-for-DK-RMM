"""
Every task the system has ever created, and the queries the agents ask of it.

The registry is a record, not an authority. It does not decide who gets what --
that is the planner's and the scheduler's job -- it just remembers, and answers
questions in a defined order so that two runs with the same seed pick the same
task off the queue.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional

from ..core.ids import IdFactory
from ..environment.parcels import ParcelPriority
from ..environment.zones import Zone
from .task import Task, TaskStatus, TaskType, TERMINAL_STATUSES


class TaskRegistry:
    """Tasks by id, plus the orderings the rest of the system needs."""

    def __init__(self, ids: Optional[IdFactory] = None,
                 event_sink: Optional[Callable[..., None]] = None) -> None:
        self._tasks: Dict[str, Task] = {}
        self._live: List[str] = []       # ids that were open when last compacted
        self._finished: Dict[str, int] = {}   # terminal status -> how many
        self._ids = ids or IdFactory()
        self._sink = event_sink

    def set_event_sink(self, sink: Optional[Callable[..., None]]) -> None:
        self._sink = sink

    def _emit(self, topic: str, task: Task, tick: int, **detail) -> None:
        if self._sink is not None:
            self._sink(topic=topic, tick=tick, task_id=task.task_id,
                       task_type=task.task_type.value,
                       status=task.status.value,
                       correlation_id=task.correlation_id, **detail)

    # ---------------------------------------------------------------- create
    def create(self, task_type: TaskType, tick: int, created_by: str,
               parcel_id: Optional[str] = None,
               source: Optional[Zone] = None,
               destination: Optional[Zone] = None,
               priority: ParcelPriority = ParcelPriority.NORMAL,
               depends_on: Optional[Iterable[str]] = None,
               due_by: Optional[int] = None,
               **detail) -> Task:
        task = Task(
            task_id=self._ids.next("T"),
            task_type=task_type,
            parcel_id=parcel_id,
            source=source,
            destination=destination,
            priority=priority,
            created_by=created_by,
            created_tick=tick,
            due_by=due_by,
            depends_on=list(depends_on or ()),
            detail=dict(detail),
        )
        self._tasks[task.task_id] = task
        self._live.append(task.task_id)
        self._emit("task_created", task, tick, created_by=created_by,
                   parcel_id=parcel_id,
                   destination=destination.value if destination else None,
                   priority=priority.value)
        return task

    def adopt(self, task: Task) -> Task:
        """Put an externally built task (an API request, a test) under management."""
        self._tasks[task.task_id] = task
        if task.task_id not in self._live:
            self._live.append(task.task_id)
        return task

    def _open_tasks(self) -> List[Task]:
        """
        The still-open tasks, with the finished ones dropped from the index.

        Tasks are never deleted -- the record of a run has to be complete -- but
        scanning every task ever created, several times a tick, makes a long run
        quadratic: measurably, a run slowed by three times over twelve thousand
        ticks purely from re-sorting its own history. The live index costs one
        list rebuild per call and keeps every query proportional to the work
        actually outstanding.
        """
        live, out = [], []
        for task_id in self._live:
            task = self._tasks.get(task_id)
            if task is None:
                continue
            if task.is_open:
                live.append(task_id)
                out.append(task)
            else:
                key = task.status.value
                self._finished[key] = self._finished.get(key, 0) + 1
        self._live = live
        return out

    # ----------------------------------------------------------------- reads
    def __contains__(self, task_id: str) -> bool:
        return task_id in self._tasks

    def __len__(self) -> int:
        return len(self._tasks)

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def all(self) -> List[Task]:
        return [self._tasks[k] for k in sorted(self._tasks)]

    def open_tasks(self) -> List[Task]:
        return sorted(self._open_tasks(), key=lambda t: t.sort_key)

    def unassigned(self, task_type: Optional[TaskType] = None) -> List[Task]:
        """The queue, in the order everyone agrees on."""
        return sorted(
            (t for t in self._open_tasks()
             if t.is_unassigned and (task_type is None or t.task_type is task_type)),
            key=lambda t: t.sort_key,
        )

    def for_parcel(self, parcel_id: str) -> List[Task]:
        return sorted((t for t in self._tasks.values() if t.parcel_id == parcel_id),
                      key=lambda t: (t.created_tick, t.task_id))

    def for_robot(self, robot_id: str, open_only: bool = True) -> List[Task]:
        return sorted(
            (t for t in self._tasks.values()
             if t.assigned_robot == robot_id and (t.is_open or not open_only)),
            key=lambda t: (t.created_tick, t.task_id),
        )

    def for_agent(self, agent_id: str, open_only: bool = True) -> List[Task]:
        return sorted(
            (t for t in self._tasks.values()
             if t.assigned_agent == agent_id and (t.is_open or not open_only)),
            key=lambda t: t.sort_key,
        )

    def blocked(self) -> List[Task]:
        """Tasks whose dependencies are not all finished yet."""
        out = []
        for task in self.open_tasks():
            if any(self._unfinished(d) for d in task.depends_on):
                out.append(task)
        return out

    def ready(self) -> List[Task]:
        """Unassigned tasks whose dependencies are all satisfied."""
        return [t for t in self.unassigned()
                if not any(self._unfinished(d) for d in t.depends_on)]

    def _unfinished(self, task_id: str) -> bool:
        dep = self._tasks.get(task_id)
        return dep is None or dep.status is not TaskStatus.COMPLETED

    # --------------------------------------------------------------- reports
    def counts(self) -> Dict[str, int]:
        """
        How many tasks are in each state.

        Counted from the live index plus a running tally of the ones that have
        finished, rather than by walking every task ever created -- this is
        asked for once per tick by the snapshot, and a full scan there is what
        turns a long run quadratic.
        """
        out = {s.value: 0 for s in TaskStatus}
        out.update(self._finished)
        for task in self._open_tasks():
            out[task.status.value] += 1
        return out

    @property
    def open_count(self) -> int:
        return len(self._open_tasks())

    def record_transition(self, task: Task, tick: int, topic: str,
                          **detail) -> None:
        """Announce a transition the caller has already made on the task."""
        self._emit(topic, task, tick, **detail)

    def as_dict(self) -> dict:
        return {
            "total": len(self._tasks),
            "counts": self.counts(),
            "tasks": [t.summary() for t in self.all()],
        }
