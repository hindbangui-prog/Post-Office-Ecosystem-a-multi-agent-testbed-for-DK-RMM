"""
How long a robot stands still between errands, and where the time goes.

The claim this exists to test is a timing claim: that a robot which finishes a
delivery has to wait while the scheduler asks the queue clerk what is next,
asks who should take it, asks routing for a path and resource for clearance,
and only then sends a command. Six steps, six ticks, every errand. Arranging
the next errand while the robot is still walking should remove most of that,
and the only honest way to say whether it does is to measure the same run
twice.

So each errand carries a small record of when each stage happened, and the
robot's own idle stretch is the gap between the tick its last errand finished
and the tick the command for this one went out. Nothing here is an estimate:
every field is stamped by the code that performs the step.

The module holds no opinion about what a good figure is. It reports what
happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, median
from typing import Any, Dict, List, Optional


@dataclass
class ErrandRecord:
    """One errand's journey from "what next" to "delivered"."""

    task_id: str
    robot_id: str = ""
    #: when the scheduler asked the queue clerk for something to start
    next_assignment_requested_tick: Optional[int] = None
    #: when this task came back as the answer
    next_assignment_selected_tick: Optional[int] = None
    #: when it was parked behind a robot still finishing (None if it never was)
    queued_tick: Optional[int] = None
    #: when the handover checks passed and the reservation was taken
    promoted_tick: Optional[int] = None
    #: when the robot was told to go
    command_tick: Optional[int] = None
    #: when the robot reported the parcel down
    errand_completed_tick: Optional[int] = None
    #: command_tick minus the tick this robot's previous errand ended, or None
    #: for a robot's first errand, which has no gap to measure
    robot_idle_ticks_between_errands: Optional[int] = None

    @property
    def prepared_in_advance(self) -> bool:
        return self.queued_tick is not None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "robot_id": self.robot_id,
            "next_assignment_requested_tick": self.next_assignment_requested_tick,
            "next_assignment_selected_tick": self.next_assignment_selected_tick,
            "queued_tick": self.queued_tick,
            "promoted_tick": self.promoted_tick,
            "command_tick": self.command_tick,
            "errand_completed_tick": self.errand_completed_tick,
            "robot_idle_ticks_between_errands":
                self.robot_idle_ticks_between_errands,
        }


class AssignmentLog:
    """
    The scheduler's stopwatch.

    Every method is a stamp, called from the one place in the scheduler that
    performs that step. A task that is abandoned keeps its record: an errand
    that was arranged and then came apart is evidence too, and dropping it
    would flatter the average.
    """

    def __init__(self) -> None:
        #: the attempt currently in progress for each task
        self.records: Dict[str, ErrandRecord] = {}
        #: attempts that ended, whether delivered or abandoned. A task that
        #: came apart and was arranged again is two errands, not one with
        #: confusing timings -- keeping them separate is what stops a
        #: re-dispatch inheriting the first attempt's `queued_tick`.
        self.history: List[ErrandRecord] = []
        self._asked: Dict[str, int] = {}          # message id -> tick
        self._last_done: Dict[str, int] = {}      # robot id -> tick it ended

    def all(self) -> List[ErrandRecord]:
        return self.history + list(self.records.values())

    # ------------------------------------------------------------- stamping
    def asked(self, message_id: str, tick: int) -> None:
        self._asked[message_id] = int(tick)

    def forget_question(self, message_id: str) -> None:
        self._asked.pop(message_id, None)

    def selected(self, message_id: str, task_id: str, tick: int) -> None:
        self.retired(task_id)
        record = self.records.setdefault(task_id, ErrandRecord(task_id))
        record.next_assignment_requested_tick = self._asked.pop(message_id, None)
        record.next_assignment_selected_tick = int(tick)

    def assigned(self, task_id: str, robot_id: str, tick: int,
                 queued: bool) -> None:
        record = self.records.setdefault(task_id, ErrandRecord(task_id))
        record.robot_id = robot_id
        if queued:
            record.queued_tick = int(tick)

    def retired(self, task_id: str, tick: Optional[int] = None) -> None:
        """
        This attempt is over -- delivered, abandoned or superseded.

        An errand that was running and then came apart ends the robot's errand
        just as truly as a delivery does, so it closes the gap too. Without
        this the next errand's idle stretch is measured from the last
        *successful* delivery and reads as a hundred ticks of standing still,
        when the robot spent them walking an errand that was later given up.
        """
        record = self.records.pop(task_id, None)
        if record is None:
            return
        self.history.append(record)
        if (tick is not None and record.robot_id
                and record.command_tick is not None
                and record.errand_completed_tick is None):
            self._last_done[record.robot_id] = int(tick)

    def promoted(self, task_id: str, tick: int) -> None:
        record = self.records.get(task_id)
        if record is not None:
            record.promoted_tick = int(tick)

    def commanded(self, task_id: str, robot_id: str, tick: int) -> None:
        record = self.records.setdefault(task_id, ErrandRecord(task_id))
        record.robot_id = robot_id or record.robot_id
        record.command_tick = int(tick)
        last = self._last_done.get(record.robot_id)
        if last is not None:
            record.robot_idle_ticks_between_errands = max(0, int(tick) - last)

    def completed(self, task_id: str, robot_id: str, tick: int) -> None:
        record = self.records.get(task_id)
        if record is not None:
            record.errand_completed_tick = int(tick)
            robot_id = robot_id or record.robot_id
        if robot_id:
            self._last_done[robot_id] = int(tick)
        self.retired(task_id)

    # -------------------------------------------------------------- reading
    def finished(self) -> List[ErrandRecord]:
        return [r for r in self.all() if r.errand_completed_tick is not None]

    def report(self) -> Dict[str, Any]:
        """
        The four figures, over every errand that actually reached a robot.

        The idle figures are over errands that had a measurable gap -- a
        robot's first errand of the run has nothing before it, and counting it
        as a zero would pull the average down for a reason that has nothing to
        do with scheduling.
        """
        commanded = [r for r in self.all() if r.command_tick is not None]
        gaps = [r.robot_idle_ticks_between_errands for r in commanded
                if r.robot_idle_ticks_between_errands is not None]
        return {
            "errands_commanded": len(commanded),
            "errands_measured": len(gaps),
            "average_idle_ticks": round(mean(gaps), 2) if gaps else None,
            "median_idle_ticks": round(median(gaps), 1) if gaps else None,
            "max_idle_ticks": max(gaps) if gaps else None,
            "percent_with_queued_successor": (
                round(100.0 * sum(1 for r in commanded if r.prepared_in_advance)
                      / len(commanded), 1) if commanded else None),
        }
