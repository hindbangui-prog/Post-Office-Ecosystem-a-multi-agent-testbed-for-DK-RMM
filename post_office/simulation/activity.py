"""
Whether the facility is still idle, for the experts' model calls.

At the start of every run the floor has not started work: the five robots are
parked together at their base, and the first wave of errands has not been
handed out. The experts' triggers read that state as hard cases that it is
not. SCHEDULING, for instance, sees every pair of free robots "within 0 or 1
cells of each other" and calls it contention, and the first tasks, created in
the same tick, look like conflicting promises. In a Normal run on the model,
those are the model calls of ticks 17 to 21 (seed 1): about twenty calls
before a single robot has moved.

So, while the facility is idle, a decision whose rule is insufficient does not
call the model, ever. If the rule gave an admissible answer, the rule answers;
if it gave nothing usable (no rule, a rule that raised, an answer off the
options), the decision takes its first admissible option, the default a
`DeterministicBrain` gives a question it has no rule for, with confidence 0.
Everything else about the decision is unchanged: the trigger is evaluated, the
rule is asked first, the policy gate validates, the decision is logged with
its `handling` (`idle_rule` or `idle_no_rule`).

**The transition is read from the floor, not from the clock.** The facility
becomes *active* at the first tick on which a robot holds an errand
(`Robot.current_task` is set): the fleet is executing work the experts
assigned. That is the first point at which the experts' coordination
questions (which robot, which task first, which route) are about a floor in
motion. Two other signals were considered and rejected:

- *Pending parcels.* The dock is seeded before tick 0 (14 parcels on seed 1),
  so by workload alone a run is never idle, yet the floor has not started.
- *Message volume.* The first ticks carry the most messages of the run (the
  intake and registration of the seeded parcels: 213 messages in ticks 0 to
  19 on seed 1), so traffic says "busy" while the fleet is still parked.

The transition is one-way: once active, the facility stays active for the
rest of the run, however quiet it becomes, so model use is never switched off
again and a later quiet spell (or a fault that stops the fleet) is read by the
experts exactly as before.

The gate exists only in a run with at least one expert on the model. In a
rules-only run there is no model call to skip, nothing is installed and
nothing is logged, so those runs, and every result recorded on them, are
unchanged.

Logged events (category `simulation`, actor `SIMULATION`):

- `ecosystem_idle` once, when the gate is installed (tick 0), with the signal
  it waits for;
- `llm_skipped_idle` for every model call skipped, with the agent, decision,
  decision id, the trigger that would have called the model, and
  `answered_by`: `rule` (the rule's admissible answer) or `default_option`
  (the rule gave nothing usable; `rule_error` says why when it raised);
- `ecosystem_active` once, at the transition, with the robot and errand that
  triggered it, the parcels waiting, and how many calls were skipped.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..communication.events import EventCategory

IDLE = "idle"
ACTIVE = "active"

#: The signal, written into the `ecosystem_idle` event so a log says what the
#: run was waiting for.
SIGNAL = "first robot errand (a robot holds a task)"


class ActivityGate:
    """The facility's idle/active state, read once per tick from the fleet."""

    def __init__(self, fleet: Any, env: Any, logger: Any) -> None:
        self.fleet = fleet
        self.env = env
        self.logger = logger
        self.state = IDLE
        self.activated_at: Optional[int] = None
        self.skipped = 0
        self.no_rule = 0
        self.skipped_by_agent: Dict[str, int] = {}

    # ------------------------------------------------------------- reading
    @property
    def idle(self) -> bool:
        return self.state == IDLE

    def announce(self, tick: int) -> None:
        """Log that the run starts idle (called once, when installed)."""
        self.logger.emit(EventCategory.SIMULATION, "ecosystem_idle", tick=tick,
                         actor="SIMULATION", state=IDLE, waiting_for=SIGNAL,
                         parcels_waiting=self._parcels_waiting(),
                         robots=self.fleet.status_counts())

    def observe(self, tick: int) -> None:
        """
        Read the floor at the start of a tick, before any agent steps.

        Every agent in a tick therefore sees the same state, and the robot
        that took the first errand last tick makes the facility active from
        this one.
        """
        if self.state != IDLE:
            return
        busy = next((r for r in self.fleet.all() if r.current_task is not None), None)
        if busy is None:
            return
        self.state = ACTIVE
        self.activated_at = tick
        self.logger.emit(EventCategory.SIMULATION, "ecosystem_active", tick=tick,
                         actor="SIMULATION", state=ACTIVE, signal=SIGNAL,
                         robot=busy.robot_id, task=busy.current_task,
                         parcels_waiting=self._parcels_waiting(),
                         robots=self.fleet.status_counts(),
                         llm_calls_skipped=self.skipped,
                         skipped_by_agent=dict(sorted(self.skipped_by_agent.items())))

    # ------------------------------------------------------------ skipping
    def skip(self, agent_id: str, kind: str, decision_id: str,
             reason: str, detail: str, tick: int, no_rule: bool = False,
             rule_error: str = "") -> None:
        """
        Count and log one model call not made because the facility is idle.

        `no_rule`: the rule gave nothing usable, so the decision takes its
        default option rather than the rule's answer (`rule_error` says why
        when the rule raised).
        """
        self.skipped += 1
        self.skipped_by_agent[agent_id] = self.skipped_by_agent.get(agent_id, 0) + 1
        if no_rule:
            self.no_rule += 1
        extra = {"rule_error": rule_error} if rule_error else {}
        self.logger.emit(EventCategory.SIMULATION, "llm_skipped_idle", tick=tick,
                         actor="SIMULATION", agent=agent_id, decision=kind,
                         call_id=decision_id, trigger=reason, trigger_detail=detail,
                         answered_by="default_option" if no_rule else "rule", **extra)

    def summary(self) -> Dict[str, Any]:
        return {"state": self.state, "activated_at": self.activated_at,
                "signal": SIGNAL, "llm_calls_skipped": self.skipped,
                "skipped_without_rule_answer": self.no_rule,
                "skipped_by_agent": dict(sorted(self.skipped_by_agent.items()))}

    def _parcels_waiting(self) -> int:
        try:
            return len(self.env.parcels)
        except Exception:
            return -1
