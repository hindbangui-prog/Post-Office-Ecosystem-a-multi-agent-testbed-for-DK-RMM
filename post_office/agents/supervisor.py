"""
The supervisor: a plain Python component, exactly as the spec asks.

No language model here and no ambition to have one. A supervisor that
improvises is a supervisor whose interventions you cannot separate from the
ecosystem's own behaviour, and this one exists to be the fixed point an
experiment is measured against. It does four things and no more:

  * states the objective and the standing policy, once, at the start;
  * approves or modifies the plan the planner proposes;
  * reads the status reports;
  * adjusts one policy number when a report shows a problem, and says so.

That last one is the only discretion it has, and it is deliberately dull and
legible: if the shelves fill up it stops routing standard parcels into storage;
if the floor is idle while work is queued it lifts the ceiling by one. Every
adjustment is a `POLICY` message and a logged event, so an experiment can point
at the exact tick the rules changed.

It is also the on/off switch. `start()` and `stop()` set `world.running`, which
is what the planner checks before releasing any work, so stopping the system
means the floor drains rather than freezing mid-parcel.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..communication.directory import AgentKind
from ..communication.events import EventCategory
from ..communication.message import Message, MessageType
from ..core.world import Policy
from .base import BaseAgent

DEFAULT_OBJECTIVE = (
    "Receive parcels at intake, identify and grade every one of them, and move "
    "them through sorting to dispatch without letting temporary storage "
    "overflow or the robot fleet run flat."
)


class SupervisorAgent(BaseAgent):
    """The human seat: objective, policy, approval, and the on/off switch."""

    kind = AgentKind.SUPERVISOR

    PLANNER = "PLANNER"

    def __init__(self, agent_id: str = "SUPERVISOR",
                 objective: str = DEFAULT_OBJECTIVE,
                 auto_approve: bool = True, **kw) -> None:
        super().__init__(agent_id, "supervisor", parent_id=None, **kw)
        self.objective = objective
        self.auto_approve = auto_approve
        self.reports: List[Dict[str, Any]] = []
        self.interventions: List[Dict[str, Any]] = []
        #: Whether this supervisor may act on what it reads. True in every
        #: ordinary run; an experiment that wants to see what a disturbance
        #: does to an ungoverned facility turns it off, and the changes it
        #: would have made are recorded below rather than lost.
        self.interventions_enabled = True
        self.declined: List[Dict[str, Any]] = []
        self.plan: Optional[Dict[str, Any]] = None
        self.started_at: Optional[int] = None
        self.stopped_at: Optional[int] = None

    # -------------------------------------------------------------- controls
    def start(self) -> None:
        """Set the objective and the policy going, and let work begin."""
        self.world.running = True
        self.world.objective = self.objective
        self.started_at = self.tick
        self.world.logger.emit(EventCategory.SUPERVISOR, "system_started",
                               tick=self.tick, actor=self.agent_id,
                               objective=self.objective)
        self.send(self.PLANNER, MessageType.OBJECTIVE,
                  {"objective": self.objective}, correlation_id="objective",
                  text=self.objective)
        self.send(self.PLANNER, MessageType.POLICY,
                  self.world.policy.as_dict(), correlation_id="policy",
                  text="Standing policy for this run.")

    def stop(self, reason: str = "supervisor stopped the system") -> None:
        """
        Stop releasing new work. Work already on the floor still finishes: a
        run that freezes mid-parcel leaves a state nobody can interpret.
        """
        self.world.running = False
        self.stopped_at = self.tick
        self.world.logger.emit(EventCategory.SUPERVISOR, "system_stopped",
                               tick=self.tick, actor=self.agent_id,
                               reason=reason)

    def set_policy(self, note: str = "", **fields) -> None:
        """
        Change the standing orders, and tell the planner what changed.

        `interventions_enabled` is how an experiment holds the supervisor
        still. It exists so that a run with a disturbance and no governance can
        be compared with the same run with governance -- the question of what
        the intervention was worth cannot be asked unless there is a run
        without one. Refusals are recorded rather than silent, because a
        supervisor that wanted to act and was held back is a finding.
        """
        if not self.interventions_enabled:
            self.declined.append({"tick": self.tick, "note": note, **fields})
            self.world.logger.emit(
                EventCategory.SUPERVISOR, "intervention_withheld",
                tick=self.tick, actor=self.agent_id, note=note, **fields)
            return
        applied = {}
        for field, value in fields.items():
            if hasattr(self.world.policy, field):
                setattr(self.world.policy, field, value)
                applied[field] = value
        if not applied:
            return
        self.interventions.append({"tick": self.tick, "note": note, **applied})
        self.world.logger.emit(EventCategory.SUPERVISOR, "policy_changed",
                               tick=self.tick, actor=self.agent_id,
                               note=note, **applied)
        self.send(self.PLANNER, MessageType.POLICY, applied,
                  correlation_id="policy", text=note or "Policy updated.")

    # --------------------------------------------------------------- inbound
    def handle(self, message: Message) -> None:
        if message.message_type is MessageType.PLAN_PROPOSAL:
            self._review_plan(message)
        elif message.message_type is MessageType.STATUS_REPORT:
            self._read_report(message)

    def _review_plan(self, message: Message) -> None:
        self.plan = dict(message.content)
        stages = {s.get("owner") for s in self.plan.get("stages", ())}
        missing = {"INTAKE", "SORTING", "SCHEDULING", "ROUTING", "RESOURCE",
                   "DISPATCH"} - stages
        if missing and not self.auto_approve:
            self.reply(message, MessageType.PLAN_REJECTION,
                       {"reason": f"no owner for {sorted(missing)}"},
                       text=f"Plan rejected: nobody owns {sorted(missing)}.")
            return
        self.reply(message, MessageType.PLAN_APPROVAL,
                   {"note": "approved as proposed",
                    "stages": len(self.plan.get("stages", ()))},
                   text="Plan approved. Begin.")

    def _read_report(self, message: Message) -> None:
        report = dict(message.content)
        self.reports.append(report)
        if len(self.reports) > 200:
            del self.reports[:100]
        self._respond_to(report)

    # ------------------------------------------------------------ discretion
    def _respond_to(self, report: Dict[str, Any]) -> None:
        """
        The whole of the supervisor's judgement, written out so it can be read.

        Three rules, each with a threshold and a direction, and at most one
        change per report so that two adjustments never confound each other.
        """
        policy = self.world.policy
        storage_load = float(report.get("storage_load", 0.0) or 0.0)
        refusals = int(report.get("storage_refusals", 0) or 0)
        robots = report.get("robots", {}) or {}
        idle = int(robots.get("IDLE", 0))
        ready = int(report.get("ready_tasks", 0) or 0)
        open_tasks = int(report.get("open_tasks", 0) or 0)

        if storage_load >= 0.85 and policy.store_normal_parcels:
            self.set_policy(
                note=f"storage at {storage_load:.0%}; standard parcels go "
                     f"straight to dispatch from now on",
                store_normal_parcels=False)
            return

        if storage_load <= 0.4 and not policy.store_normal_parcels:
            self.set_policy(
                note=f"storage back down to {storage_load:.0%}; using the "
                     f"shelves again",
                store_normal_parcels=True)
            return

        if idle >= 2 and ready >= 3 and policy.max_concurrent_transports < 16:
            self.set_policy(
                note=f"{idle} robots idle with {ready} jobs ready; raising the "
                     f"ceiling",
                max_concurrent_transports=policy.max_concurrent_transports + 2)
            return

        if open_tasks > policy.max_concurrent_transports * 4 and \
                policy.max_concurrent_transports > 4:
            self.set_policy(
                note=f"{open_tasks} tasks open against a ceiling of "
                     f"{policy.max_concurrent_transports}; pulling it back",
                max_concurrent_transports=policy.max_concurrent_transports - 1)

    def request_status(self) -> None:
        self.send(self.PLANNER, MessageType.STATUS_REQUEST, {},
                  correlation_id="status", text="Status, please.")

    # ----------------------------------------------------------------- state
    def state(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "running": self.world.running if self.world else False,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "plan_stages": len(self.plan.get("stages", ())) if self.plan else 0,
            "reports_received": len(self.reports),
            "interventions": self.interventions[-10:],
            "policy": self.world.policy.as_dict() if self.world else {},
            "last_report": self.reports[-1] if self.reports else None,
        }
