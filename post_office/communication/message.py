"""
The envelope every agent-to-agent interaction travels in.

One shape for all of it. A supervisor setting an objective, a barcode
sub-agent reporting a scan, a robot saying it has arrived -- same six fields,
because a monitoring layer that has to learn a different format per sender is a
monitoring layer nobody will write.

`correlation_id` is the field that earns its keep. Set it to the parcel id and
the whole chain -- scan, classification, plan, assignment, route, charge
request, delivery -- becomes one filterable thread through a log of tens of
thousands of lines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class MessageType(str, Enum):
    """
    The vocabulary agents speak.

    Deliberately about interaction rather than about parcels: `TASK_ASSIGNMENT`
    means the same thing whoever sends it, so a monitor can count assignments
    without knowing a post office from a warehouse.
    """

    # supervisor <-> planner
    OBJECTIVE = "OBJECTIVE"
    POLICY = "POLICY"
    PLAN_PROPOSAL = "PLAN_PROPOSAL"
    PLAN_APPROVAL = "PLAN_APPROVAL"
    PLAN_REJECTION = "PLAN_REJECTION"
    STATUS_REQUEST = "STATUS_REQUEST"
    STATUS_REPORT = "STATUS_REPORT"

    # planner <-> experts, experts <-> experts
    WORK_NOTICE = "WORK_NOTICE"          # "here is something that needs doing"
    TASK_ASSIGNMENT = "TASK_ASSIGNMENT"
    TASK_ACCEPTED = "TASK_ACCEPTED"
    TASK_REJECTED = "TASK_REJECTED"
    TASK_PROGRESS = "TASK_PROGRESS"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"

    # expert <-> sub-agent
    SUBTASK_REQUEST = "SUBTASK_REQUEST"
    SUBTASK_RESULT = "SUBTASK_RESULT"

    # expert <-> expert, specific consultations
    ROUTE_REQUEST = "ROUTE_REQUEST"
    ROUTE_RESPONSE = "ROUTE_RESPONSE"
    SCHEDULE_REQUEST = "SCHEDULE_REQUEST"
    SCHEDULE_RESPONSE = "SCHEDULE_RESPONSE"
    RESOURCE_REQUEST = "RESOURCE_REQUEST"
    RESOURCE_GRANT = "RESOURCE_GRANT"
    RESOURCE_DENIAL = "RESOURCE_DENIAL"

    # expert <-> robot
    ROBOT_COMMAND = "ROBOT_COMMAND"
    ROBOT_REPORT = "ROBOT_REPORT"
    CHARGE_REQUEST = "CHARGE_REQUEST"

    # Expert consultations: one owner asks the one peer the peer map allows, synchronously, for one decision.
    CONSULT_REQUEST = "CONSULT_REQUEST"
    CONSULT_RESPONSE = "CONSULT_RESPONSE"
    CONSULT_CLOSE = "CONSULT_CLOSE"

    # anyone
    ALERT = "ALERT"
    BROADCAST = "BROADCAST"


@dataclass(frozen=True, slots=True)
class Message:
    """One message. Immutable: a delivered message is a fact, not a buffer."""

    message_id: str
    tick: int
    sender: str
    receiver: str
    message_type: MessageType
    content: Dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    timestamp: str = ""
    text: str = ""              # the natural-language form, when there is one
    in_reply_to: Optional[str] = None

    @staticmethod
    def now() -> str:
        """Wall-clock time, for a human reading the log. Never for ordering."""
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    def reply_content(self, **fields) -> Dict[str, Any]:
        """Content for a reply, carrying the correlation forward by default."""
        base = {"correlation_id": self.correlation_id}
        base.update(fields)
        return base

    def as_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "tick": self.tick,
            "timestamp": self.timestamp,
            "sender": self.sender,
            "receiver": self.receiver,
            "message_type": self.message_type.value,
            "content": dict(self.content),
            "correlation_id": self.correlation_id,
            "text": self.text,
            "in_reply_to": self.in_reply_to,
        }

    def __repr__(self) -> str:
        return (f"<{self.tick:>4} {self.sender} -> {self.receiver} "
                f"{self.message_type.value}>")
