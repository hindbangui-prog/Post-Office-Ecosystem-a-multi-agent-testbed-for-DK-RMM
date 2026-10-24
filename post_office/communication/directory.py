"""
Who is who, and who is allowed to talk to whom.

The hierarchy in the spec is only worth having if something enforces it. A
comment saying "sub-agents should not talk to the supervisor" is a comment; a
bus that refuses the message and writes the refusal to the event log is a
property of the system, and one an experiment can measure.

The rules, in one place:

    supervisor  -> planner                          (and nothing else)
    planner     -> supervisor, experts
    expert      -> planner, other experts, own sub-agents, robots
    sub-agent   -> its own parent expert            (and nothing else)
    robot       -> experts

A sub-agent addressing the supervisor, or reaching sideways into another
expert's sub-agent, is refused. That refusal is not an error in the sense of
something being broken -- it is a finding, and it belongs in the log next to
everything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class AgentKind(str, Enum):
    """A participant's place in the hierarchy."""

    SUPERVISOR = "SUPERVISOR"
    PLANNER = "PLANNER"
    EXPERT = "EXPERT"
    SUBAGENT = "SUBAGENT"
    ROBOT = "ROBOT"


#: Which kinds may address which. The parent rule for sub-agents is separate,
#: because it is about identity rather than about kind.
ALLOWED_KINDS: Dict[AgentKind, Set[AgentKind]] = {
    AgentKind.SUPERVISOR: {AgentKind.PLANNER},
    AgentKind.PLANNER: {AgentKind.SUPERVISOR, AgentKind.EXPERT},
    AgentKind.EXPERT: {AgentKind.PLANNER, AgentKind.EXPERT,
                       AgentKind.SUBAGENT, AgentKind.ROBOT},
    AgentKind.SUBAGENT: {AgentKind.EXPERT},
    AgentKind.ROBOT: {AgentKind.EXPERT},
}


@dataclass
class AgentRecord:
    """The directory's entry for one participant."""

    agent_id: str
    kind: AgentKind
    role: str = ""
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    created_tick: int = 0
    active: bool = True

    def as_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "kind": self.kind.value,
            "role": self.role,
            "parent_id": self.parent_id,
            "children": list(self.children),
            "created_tick": self.created_tick,
            "active": self.active,
        }


class Directory:
    """Every participant, its place in the tree, and the routing rules."""

    def __init__(self) -> None:
        self._records: Dict[str, AgentRecord] = {}

    # ------------------------------------------------------------- registry
    def register(self, agent_id: str, kind: AgentKind, role: str = "",
                 parent_id: Optional[str] = None,
                 created_tick: int = 0) -> AgentRecord:
        if kind is AgentKind.SUBAGENT and not parent_id:
            raise ValueError(f"{agent_id}: a sub-agent must have a parent")
        if parent_id is not None and parent_id not in self._records:
            raise ValueError(f"{agent_id}: unknown parent {parent_id!r}")

        record = AgentRecord(agent_id=agent_id, kind=kind, role=role,
                             parent_id=parent_id, created_tick=created_tick)
        self._records[agent_id] = record
        if parent_id is not None:
            parent = self._records[parent_id]
            if agent_id not in parent.children:
                parent.children.append(agent_id)
        return record

    def deregister(self, agent_id: str) -> None:
        record = self._records.get(agent_id)
        if record is None:
            return
        record.active = False

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._records

    def __len__(self) -> int:
        return len(self._records)

    def get(self, agent_id: str) -> Optional[AgentRecord]:
        return self._records.get(agent_id)

    def all(self) -> List[AgentRecord]:
        return [self._records[k] for k in sorted(self._records)]

    def of_kind(self, kind: AgentKind) -> List[AgentRecord]:
        return [r for r in self.all() if r.kind is kind]

    def children_of(self, agent_id: str) -> List[str]:
        record = self._records.get(agent_id)
        return list(record.children) if record else []

    def parent_of(self, agent_id: str) -> Optional[str]:
        record = self._records.get(agent_id)
        return record.parent_id if record else None

    # --------------------------------------------------------------- routing
    def may_send(self, sender: str, receiver: str) -> tuple:
        """
        (allowed, reason). The reason is written to the log on a refusal, so it
        has to say something a person reading the log can act on.
        """
        a = self._records.get(sender)
        b = self._records.get(receiver)
        if a is None:
            return False, f"unknown sender {sender!r}"
        if b is None:
            return False, f"unknown receiver {receiver!r}"
        if not b.active:
            return False, f"{receiver} has left the ecosystem"
        if sender == receiver:
            return False, "an agent may not address itself"

        if a.kind is AgentKind.SUBAGENT:
            if receiver != a.parent_id:
                return False, (f"{sender} is a sub-agent of {a.parent_id} and may "
                               f"only address its parent, not {receiver}")
            return True, ""

        if b.kind is AgentKind.SUBAGENT and b.parent_id != sender:
            return False, (f"{receiver} belongs to {b.parent_id}; {sender} must go "
                           f"through it rather than reach in")

        if b.kind not in ALLOWED_KINDS[a.kind]:
            return False, (f"a {a.kind.value.lower()} may not address a "
                           f"{b.kind.value.lower()}")
        return True, ""

    # ----------------------------------------------------------------- shape
    def tree(self) -> dict:
        """The hierarchy as nested dictionaries, for the API and for the UI."""
        def node(record: AgentRecord) -> dict:
            return {
                "agent_id": record.agent_id,
                "kind": record.kind.value,
                "role": record.role,
                "children": [node(self._records[c]) for c in record.children],
            }
        roots = [r for r in self.all() if r.parent_id is None]
        return {"roots": [node(r) for r in roots]}

    def as_dict(self) -> dict:
        return {
            "count": len(self._records),
            "agents": [r.as_dict() for r in self.all()],
            "tree": self.tree(),
        }
