"""
A proposed action, checked before the facility acts on it.

An agent decides; the gate says whether the decision may be carried out. The
separation is the point. Without it there is nowhere to stand between "the
model said DISPATCH" and a parcel moving, and every guard has to be written
into every rule -- which means, in practice, into the deterministic rules
only, leaving the model path unguarded precisely where it matters.

Three questions, asked in order, stopping at the first refusal:

    schema    Is this an answer to the question that was asked? An answer off
              the option list, or no answer at all.
    policy    Is this agent allowed to answer that way? Two things live here:
              which decisions belong to which agent, and the supervisor's
              standing orders -- the ceilings in `world.policy`, which an
              agent may reason about but may not exceed.
    state     Is it still true? Facts are gathered, a tick passes, messages
              are delivered, and the floor moves. A charge point free when
              the question was asked can be occupied by the time the answer
              arrives.

Kept apart because they fail differently. Off-list answers are a model
problem; refused-by-policy is an authority problem; stale-state is a
concurrency problem that grows with load. Collapsing them into one "invalid"
verdict would hide exactly the signal a stress experiment is looking for.

What the gate is not: it is not a second decision-maker. It never improves an
answer, never picks between permitted options, and has no opinion about which
of two lawful choices is wiser. When it refuses, the agent's own deterministic
rule answers instead, and the refusal is logged. That is what keeps the
reasoning free to be interesting -- the model may propose anything within its
authority, because nothing it proposes can put the facility into a state the
supervisor forbade or the floor cannot support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence

from ..environment.zones import Zone

#: Which agent owns which decision. An expert deciding something that is not
#: its own is the coordination failure this table exists to catch -- and it is
#: a table rather than an assertion in each agent so that the whole authority
#: map can be read, and logged, in one place.
AUTHORITY: Dict[str, str] = {
    "release_work": "PLANNER",
    "accept_parcel": "INTAKE",
    "classify_destination": "SORTING",
    "choose_next_task": "SCHEDULING",
    "choose_robot": "SCHEDULING",
    "resolve_block": "ROUTING",
    "battery_sufficient": "RESOURCE",
    "allocate_charge_point": "RESOURCE",
    "accept_into_storage": "RESOURCE",
    "release_parcel": "DISPATCH",
}


@dataclass(frozen=True)
class Proposal:
    """What an agent wants to do, before anybody has agreed to it."""

    kind: str
    agent_id: str
    choice: Any
    options: Sequence[Any] = ()
    facts: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    source: str = "deterministic"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "agent_id": self.agent_id,
                "choice": str(self.choice), "source": self.source,
                "reason": self.reason}


@dataclass(frozen=True)
class Verdict:
    """Permitted, or refused with the stage and the reason."""

    ok: bool
    stage: str = "ok"            # "schema" | "policy" | "state" | "ok"
    violation: str = ""

    def as_dict(self) -> dict:
        return {"ok": self.ok, "stage": self.stage, "violation": self.violation}


PERMITTED = Verdict(True)


class PolicyGate:
    """
    Validates proposals against the supervisor's orders and the current floor.

    Holds a reference to the world and reads it; it writes nothing, anywhere.
    A component that can refuse an action and also change the thing it is
    refusing about is not a check.
    """

    def __init__(self, world) -> None:
        self.world = world
        self.checked = 0
        self.refused = 0
        #: Refusals by stage, for the run summary. The shape of this dict over
        #: a stressed run is the measurement the gate exists to make possible.
        self.by_stage: Dict[str, int] = {"schema": 0, "policy": 0, "state": 0}

    # ------------------------------------------------------------------ api
    def check(self, proposal: Proposal) -> Verdict:
        self.checked += 1
        for stage in (self._schema, self._policy, self._state):
            verdict = stage(proposal)
            if not verdict.ok:
                self.refused += 1
                self.by_stage[verdict.stage] = self.by_stage.get(verdict.stage, 0) + 1
                return verdict
        return PERMITTED

    def stats(self) -> dict:
        return {"checked": self.checked, "refused": self.refused,
                "by_stage": dict(self.by_stage)}

    # --------------------------------------------------------------- schema
    def _schema(self, proposal: Proposal) -> Verdict:
        options = list(proposal.options or ())
        if not options:
            # A free-form question. Nothing to validate the shape against, and
            # inventing a constraint here would be the gate deciding.
            return PERMITTED
        if proposal.choice is None:
            return Verdict(False, "schema", "no answer given")
        if proposal.choice not in options:
            return Verdict(False, "schema",
                           f"{proposal.choice!r} is not one of "
                           f"{[str(o) for o in options]}")
        return PERMITTED

    # --------------------------------------------------------------- policy
    def _policy(self, proposal: Proposal) -> Verdict:
        owner = AUTHORITY.get(proposal.kind)
        if owner is not None and proposal.agent_id != owner:
            return Verdict(False, "policy",
                           f"{proposal.agent_id} may not decide "
                           f"{proposal.kind!r}; that belongs to {owner}")

        policy = self.world.policy
        choice = proposal.choice
        facts = proposal.facts or {}

        # The supervisor's ceilings. An agent may reason about how close to one
        # it is; it may not decide that today is an exception.
        if proposal.kind == "accept_into_storage" and choice == "ACCEPT":
            load = _number(facts.get("load"))
            if load is not None and load > policy.max_storage_load:
                return Verdict(False, "policy",
                               f"shelves at {load:.0%}, above the "
                               f"{policy.max_storage_load:.0%} ceiling")

        if proposal.kind == "release_work":
            count = _number(choice)
            headroom = _number(facts.get("headroom"))
            if count is not None and headroom is not None and count > headroom:
                return Verdict(False, "policy",
                               f"releasing {count:.0f} with headroom "
                               f"{headroom:.0f}")

        if proposal.kind == "classify_destination" \
                and choice == Zone.TEMPORARY_STORAGE.value \
                and not policy.store_normal_parcels \
                and str(facts.get("priority", "")) == "NORMAL":
            return Verdict(False, "policy",
                           "the supervisor has turned off storing NORMAL parcels")

        return PERMITTED

    # ---------------------------------------------------------------- state
    def _state(self, proposal: Proposal) -> Verdict:
        env = getattr(self.world, "env", None)
        if env is None:
            return PERMITTED
        choice = proposal.choice

        if proposal.kind == "allocate_charge_point" and choice not in (None, "WAIT"):
            free = {s.station_id for s in env.free_stations()}
            if str(choice) not in free:
                return Verdict(False, "state",
                               f"{choice} is no longer free")

        if proposal.kind == "classify_destination" \
                and choice == Zone.TEMPORARY_STORAGE.value:
            storage = getattr(env, "storage", None)
            if storage is not None and storage.free <= 0:
                return Verdict(False, "state", "no shelf left")

        if proposal.kind == "choose_robot" and choice is not None:
            robot = self.world.fleet.get(str(choice))
            if robot is None:
                return Verdict(False, "state", f"{choice} is not in the fleet")
            if not robot.is_available:
                return Verdict(False, "state",
                               f"{choice} is {robot.status.value} now")

        return PERMITTED


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
