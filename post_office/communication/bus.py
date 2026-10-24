"""
The message bus: the only way one agent reaches another.

Three things happen here and nowhere else.

*Routing.* A message is checked against the directory before it is delivered.
A sub-agent addressing the supervisor is refused, and the refusal is logged
with a reason. The hierarchy in the spec is therefore a property the system
has, not a convention it relies on everybody remembering.

*Recording.* Every message -- delivered or refused -- goes into the
communication log and into the event stream. There is no private channel.

*Timing.* Messages sent during a tick are delivered at the start of the next
one. Without that, the order in which the orchestrator happens to iterate over
the experts would decide who hears what first, and a reordering of two lines in
an unrelated file would change the outcome of a run. One tick of latency is a
small price for a system whose results survive a refactor.

The bus does not import a single agent class, and no agent imports the bus: an
agent is handed a `send` callable and an inbox. That is the whole coupling.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple

from ..core.ids import IdFactory
from .directory import AgentKind, Directory
from . import provenance
from .events import EventCategory, EventLogger
from .message import Message, MessageType


class CommunicationLog:
    """Every message the ecosystem has produced, newest queries first."""

    def __init__(self, keep: int = 5000) -> None:
        self._messages: Deque[Message] = deque(maxlen=keep)
        self._refused: Deque[Dict[str, Any]] = deque(maxlen=1000)
        self.sent = 0
        self.refused = 0

    def add(self, message: Message) -> None:
        self._messages.append(message)
        self.sent += 1

    def add_refusal(self, message: Message, reason: str) -> None:
        self._refused.append({"message": message.as_dict(), "reason": reason})
        self.refused += 1

    def recent(self, limit: int = 50, agent_id: Optional[str] = None,
               correlation_id: Optional[str] = None,
               message_type: Optional[str] = None) -> List[Message]:
        out: List[Message] = []
        for message in reversed(self._messages):
            if agent_id is not None and agent_id not in (message.sender,
                                                         message.receiver):
                continue
            if correlation_id is not None and message.correlation_id != correlation_id:
                continue
            if message_type is not None and message.message_type.value != message_type:
                continue
            out.append(message)
            if len(out) >= limit:
                break
        out.reverse()
        return out

    def thread(self, correlation_id: str) -> List[Message]:
        """Everything said about one parcel, in order. The most useful view here."""
        return [m for m in self._messages if m.correlation_id == correlation_id]

    def refusals(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._refused)[-limit:]

    def interaction_counts(self) -> Dict[str, int]:
        """
        The edges of the interaction graph, as "SENDER->RECEIVER": n.

        Enough to reconstruct who talks to whom without any knowledge of what a
        parcel is, which is what a monitoring layer will want.
        """
        counts: Dict[str, int] = {}
        for message in self._messages:
            key = f"{message.sender}->{message.receiver}"
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    def __len__(self) -> int:
        return len(self._messages)

    def as_dict(self, limit: int = 100) -> dict:
        return {
            "sent": self.sent,
            "refused": self.refused,
            "held": len(self._messages),
            "messages": [m.as_dict() for m in self.recent(limit)],
            "interactions": self.interaction_counts(),
        }


class MessageBus:
    """Routes messages between registered agents, and records all of it."""

    def __init__(self, directory: Directory, logger: EventLogger,
                 ids: Optional[IdFactory] = None, keep: int = 5000) -> None:
        self.directory = directory
        self.logger = logger
        self.log = CommunicationLog(keep=keep)
        self._ids = ids or IdFactory(width=6)
        self._inboxes: Dict[str, List[Message]] = {}
        self._pending: List[Message] = []      # sent this tick, read the next
        #: A perturbation's hold on delivery, or None -- which is the normal
        #: state and costs one `if` a message. It is consulted in `deliver`
        #: because that is the single place delivery is decided; putting it
        #: anywhere else would mean two answers to "has this arrived yet".
        self.delay_rule: Optional[Callable[[Message], Optional[int]]] = None
        #: Messages a rule is holding: when to release, the message, and what
        #: to attribute the late arrival to. Held rather than dropped, because
        #: a delay that quietly became a deletion would be a different
        #: experiment from the one that was configured.
        self._held: List[Tuple[int, Message, Dict[str, Any]]] = []
        self.tick = 0
        #: Read-only observers of `inbox`: each is called with the receiver,
        #: the tick and the messages it has just taken. Empty is the normal
        #: state and costs one `if` a call; an observer never changes what is
        #: taken, and one that raises is ignored. The live runner's decision
        #: trace (`observability/decision_trace.py`) is the one user: a
        #: message taken from an inbox is the only evidence the bus keeps that
        #: it reached its receiver on time, since on-time delivery logs no event.
        self._inbox_watchers: List[Callable[[str, int, List[Message]], None]] = []

    # ------------------------------------------------------------- lifecycle
    def register(self, agent_id: str, kind: AgentKind, role: str = "",
                 parent_id: Optional[str] = None) -> None:
        self.directory.register(agent_id, kind, role=role, parent_id=parent_id,
                                created_tick=self.tick)
        self._inboxes.setdefault(agent_id, [])
        self.logger.emit(EventCategory.AGENT, "agent_created", tick=self.tick,
                         actor=agent_id, target=parent_id or "",
                         kind=kind.value, role=role, parent_id=parent_id)

    def deregister(self, agent_id: str) -> None:
        self.directory.deregister(agent_id)
        self.logger.emit(EventCategory.AGENT, "agent_removed", tick=self.tick,
                         actor=agent_id)

    def sender_for(self, agent_id: str) -> Callable[..., Optional[Message]]:
        """
        The `send` an agent is given. It closes over the agent's own id, so an
        agent cannot forge a message from somebody else even by accident.
        """
        def send(receiver: str, message_type: MessageType,
                 content: Optional[Dict[str, Any]] = None,
                 correlation_id: str = "", text: str = "",
                 in_reply_to: Optional[str] = None) -> Optional[Message]:
            return self.send(agent_id, receiver, message_type, content,
                             correlation_id, text, in_reply_to)
        return send

    # --------------------------------------------------------------- sending
    def send(self, sender: str, receiver: str, message_type: MessageType,
             content: Optional[Dict[str, Any]] = None,
             correlation_id: str = "", text: str = "",
             in_reply_to: Optional[str] = None) -> Optional[Message]:
        """
        Post one message. Returns it when accepted, None when refused.

        A refusal is never silent and never raises: raising would let one
        misdirected message stop a whole run, and a run that stops is a run you
        cannot study.
        """
        message = Message(
            message_id=self._ids.next("M"),
            tick=self.tick,
            sender=sender,
            receiver=receiver,
            message_type=message_type,
            content=dict(content or {}),
            correlation_id=correlation_id,
            timestamp=Message.now(),
            text=text,
            in_reply_to=in_reply_to,
        )

        allowed, reason = self.directory.may_send(sender, receiver)
        if not allowed:
            self.log.add_refusal(message, reason)
            self.logger.emit(EventCategory.COMMUNICATION, "message_refused",
                             tick=self.tick, actor=sender, target=receiver,
                             correlation_id=correlation_id,
                             message_id=message.message_id,
                             message_type=message_type.value, reason=reason)
            return None

        self._pending.append(message)
        self.log.add(message)
        record = self.directory.get(sender)
        self.logger.emit(EventCategory.COMMUNICATION,
                         "subagent_message"
                         if record is not None and record.kind is AgentKind.SUBAGENT
                         else "message",
                         tick=self.tick, actor=sender, target=receiver,
                         correlation_id=correlation_id,
                         message_id=message.message_id,
                         message_type=message_type.value,
                         content=dict(message.content), text=text,
                         in_reply_to=message.in_reply_to or "")
        return message

    def broadcast(self, sender: str, receivers: Iterable[str],
                  message_type: MessageType,
                  content: Optional[Dict[str, Any]] = None,
                  correlation_id: str = "", text: str = "") -> List[Message]:
        out = []
        for receiver in receivers:
            message = self.send(sender, receiver, message_type, content,
                                correlation_id, text)
            if message is not None:
                out.append(message)
        return out

    # ------------------------------------------------------------- receiving
    def deliver(self) -> int:
        """
        Move everything sent last tick into the inboxes. Called once per tick by
        the orchestrator, before any agent acts.
        """
        delivered = 0
        rule = self.delay_rule
        for message in self._pending:
            hold = rule(message) if rule is not None else None
            if hold is not None:
                if hold < 0:
                    self.logger.emit(
                        EventCategory.COMMUNICATION, "message_dropped",
                        tick=self.tick, actor=message.sender,
                        target=message.receiver,
                        correlation_id=message.correlation_id,
                        message_id=message.message_id)
                    continue
                self._held.append((self.tick + int(hold), message,
                                   provenance.current()))
                continue
            self._inboxes.setdefault(message.receiver, []).append(message)
            delivered += 1
        self._pending = []

        # Anything whose wait is over. Attributed to whatever held it, because
        # the lateness is the perturbation's doing and the code knows it --
        # everything further down the line is the facility's own.
        if self._held:
            still = []
            for release_at, message, mark in self._held:
                if release_at > self.tick:
                    still.append((release_at, message, mark))
                    continue
                self._inboxes.setdefault(message.receiver, []).append(message)
                delivered += 1
                waited = self.tick - message.tick - 1
                if mark:
                    with provenance.attributed(
                            mark.get("perturbation_id", ""),
                            relation=mark.get("relation", provenance.CAUSED_BY)):
                        self._late(message, waited)
                else:
                    self._late(message, waited)
            self._held = still
        return delivered

    def _late(self, message: Message, waited: int) -> None:
        self.logger.emit(EventCategory.COMMUNICATION, "agent_message_received",
                         tick=self.tick, actor=message.sender,
                         target=message.receiver,
                         correlation_id=message.correlation_id,
                         message_id=message.message_id,
                         message_type=message.message_type.value,
                         late_by=max(0, int(waited)))

    def release_held(self) -> int:
        """
        Let go of everything still waiting. Called when a delay expires.

        The count is returned rather than logged here: the injector that held
        them is the one that knows why they were held.
        """
        released = len(self._held)
        for _, message, _mark in self._held:
            self._inboxes.setdefault(message.receiver, []).append(message)
        self._held = []
        return released

    def inbox(self, agent_id: str) -> List[Message]:
        """Take everything waiting for this agent. The inbox is then empty."""
        messages = self._inboxes.get(agent_id, [])
        self._inboxes[agent_id] = []
        if self._inbox_watchers and messages:
            taken = list(messages)
            for watcher in list(self._inbox_watchers):
                try:
                    watcher(agent_id, self.tick, taken)
                except Exception:      # an observer never stops delivery
                    pass
        return messages

    def watch_inbox(self, fn: Callable[[str, int, List[Message]], None]) -> Callable[[], None]:
        """Observe every `inbox` take (receiver, tick, messages). Returns the undo."""
        self._inbox_watchers.append(fn)

        def unwatch() -> None:
            if fn in self._inbox_watchers:
                self._inbox_watchers.remove(fn)
        return unwatch

    def peek(self, agent_id: str) -> List[Message]:
        return list(self._inboxes.get(agent_id, []))

    def pending_count(self) -> int:
        return len(self._pending) + sum(len(v) for v in self._inboxes.values())

    # ------------------------------------------------------------------ state
    def advance(self, tick: int) -> None:
        self.tick = tick

    def as_dict(self, limit: int = 100) -> dict:
        return {
            "tick": self.tick,
            "in_flight": len(self._pending),
            "waiting_in_inboxes": sum(len(v) for v in self._inboxes.values()),
            **self.log.as_dict(limit=limit),
        }
