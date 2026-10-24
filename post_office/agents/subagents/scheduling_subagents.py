"""
The two specialists that work for the scheduling agent.

    SUB-QUEUE      puts the pending work in the order it should be done
    SUB-DEADLINE   notices the jobs that have been waiting too long

They exist as separate agents because they pull in opposite directions, and
that tension is the interesting part. The queue wants throughput and will
happily serve urgent parcels for ever; the deadline monitor exists to notice
the standard parcel at the back that has now been there ninety ticks. A system
with only one of the two either starves its slow work or ignores its fast work.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...communication.message import Message
from ...tasks.task import TaskStatus
from ..base import SubAgent
from ..brain import Answer, Question


class QueueManagementSubAgent(SubAgent):
    """Orders the ready work, and says why the order is what it is."""

    def __init__(self, parent_id: str, agent_id: str = "SUB-QUEUE", **kw):
        super().__init__(agent_id, "queue management", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        content = message.content
        promoted = set(content.get("promoted", ()))
        # Work the scheduler already has a robot going to. Several assignment
        # conversations can be open at once now, and without this every one of
        # them would be shown the same head of the queue and answer the same
        # way -- which is how two robots end up sent for one parcel.
        exclude = set(content.get("exclude", ()))
        ready = [t for t in self.world.tasks.ready()
                 if t.task_id not in exclude]

        # A promoted task jumps the queue without its stored priority changing:
        # the deadline monitor's opinion is advice to the scheduler, not a
        # rewrite of what the sorting agent decided.
        # `sort_key` is deadline first now, so this is earliest-deadline-first
        # with the monitor's promotions ahead of everything.
        ordered: List = sorted(
            ready,
            key=lambda t: (0 if t.task_id in promoted else 1, t.sort_key),
        )
        if not ordered:
            return {"operation": "next_task", "ok": True, "task_id": None,
                    "queue_length": 0, "candidates": [], "slack": {},
                    "_text": "Nothing ready."}

        shortlist = ordered[:8]
        return {
            "operation": "next_task",
            "ok": True,
            "queue_length": len(ordered),
            "queue": [t.task_id for t in ordered[:10]],
            # The shortlist SCHEDULING chooses from, in the order this agent
            # would take them, and what the choice turns on: how long each has
            # before the promise made to its parcel breaks. Ordering the work
            # is bookkeeping; deciding which promise to serve first is not.
            "candidates": [t.task_id for t in shortlist],
            "slack": {t.task_id: t.slack_at(self.tick)
                      for t in shortlist if t.slack_at(self.tick) is not None},
            "promoted": sorted(promoted & {t.task_id for t in shortlist}),
            "_text": (f"{len(ordered)} ready; shortlist "
                      f"{', '.join(t.task_id for t in shortlist)}."),
        }


class DeadlineMonitorSubAgent(SubAgent):
    """
    Finds work that is ageing badly.

    Reports rather than acts. It has no authority to reorder anything -- it
    hands its list to the scheduling agent, which decides what to do with it.
    """

    #: How long a task with no promise may sit unstarted before it is worth
    #: mentioning. Only a fallback now: a task whose parcel was accepted by the
    #: intake gate carries the departure it was promised, and that is what this
    #: agent measures. The constants remain for the work that has none --
    #: nothing should be invisible merely because nobody sold it a deadline.
    PATIENCE = {2: 15, 1: 30, 0: 60}      # by priority rank: urgent, express, normal

    #: Slack at which a promise is close enough to be worth reporting. Twice
    #: the coordination latency of a single leg, so a job flagged here can still
    #: be started, routed, approved and carried before its van goes.
    AT_RISK = 120

    def __init__(self, parent_id: str, agent_id: str = "SUB-DEADLINE", **kw):
        super().__init__(agent_id, "deadline monitoring", parent_id, **kw)

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        tick = self.tick
        overdue: List[Dict[str, Any]] = []
        for task in self.world.tasks.open_tasks():
            if task.status is not TaskStatus.CREATED:
                continue
            waited = tick - task.created_tick
            slack = task.slack_at(tick)

            if slack is not None:
                # Against the promise the facility made, not against an
                # invented timer. Two parcels promised departures an hour apart
                # used to be indistinguishable here if they shared a priority.
                if slack > self.AT_RISK:
                    continue
                over_by = max(0, -slack)
            else:
                patience = self.PATIENCE.get(task.priority.rank, 60)
                if waited < patience:
                    continue
                over_by = waited - patience

            overdue.append({
                "task_id": task.task_id,
                "parcel_id": task.parcel_id,
                "priority": task.priority.value,
                "waited": waited,
                "due_by": task.due_by,
                "slack": slack,
                "over_by": over_by,
            })
        # Least slack first: the one nearest to breaking, whatever it paid.
        overdue.sort(key=lambda d: (d["slack"] if d["slack"] is not None
                                    else 10 ** 9, -d["over_by"], d["task_id"]))
        worst = overdue[0]["task_id"] if overdue else None
        return {
            "operation": "overdue_report", "ok": True,
            "overdue": overdue[:12], "count": len(overdue), "worst": worst,
            "_text": (f"{len(overdue)} tasks at risk of missing a departure"
                      + (f", worst {worst} with {overdue[0]['slack']} ticks "
                         f"of slack." if overdue else ".")),
        }
