"""
The decision-to-action pathway of a run, linked by identifiers only.

A read-only observer beside an ecosystem: it listens to the event logger
(`EventLogger.subscribe`) and to the bus's inbox takes (`MessageBus.
watch_inbox`), builds one trace per decision and one per message, and changes
nothing. It emits no event, so the run's event stream is the same with it or
without it.

Every link below is made on an identifier the run itself wrote, and each one
names its `basis`. Two events are never joined because they are close in time
or because one happens to follow the other.

decision -> consultation      `consult_opened/closed.decision_id` and
                              `llm_call.decision_id` equal the decision's
                              `call_id`
decision -> request           a message the deciding agent took from its inbox
                              in the decision's tick whose `content.operation`
                              is the decision's name and which, or the request
                              its `in_reply_to` names, carries the decision's
                              subject (below)
decision -> effects           registry events (`task_assigned`, ...) and
                              messages the deciding agent emitted in the same
                              tick, after the decision event and before its
                              next decision event, that carry the decision's
                              subject (`correlation_id`, `detail.task_id`,
                              `content.task_id` or `content.correlation_id`)
decision -> later             ROBOT_COMMAND messages and task registry events
                              in later ticks that carry the subject task id
                              (`content.task_id`, or a `correlation_id` the
                              registry created as a task; never a parcel or
                              robot id), attached to the latest decision on
                              that task
message -> delivery           `message_dropped.message_id`; an inbox take of
                              that message by its receiver (on time);
                              `agent_message_received.message_id` (late)
message -> replies            messages whose `in_reply_to` is its id
ROBOT_COMMAND -> applied      a `command_<operation>` event in the tick the
                              robot took the command, with the command's
                              sender as actor, the robot as target and the
                              command's `correlation_id`; several identical
                              commands taken together are matched in inbox
                              order (the order the robot handles them) and
                              the match says how many there were
transport -> parcel           `parcel_lifted` / `parcel_dropped` of the
                              command's `parcel_id` by the commanded robot

A decision's subject is its event's `correlation_id`, except for SCHEDULING's
`choose_next_task`, whose event has no correlation and whose choice is the
task chosen. A message that carries no decision's subject is still traced as a
message (with its delivery outcome, replies and application); it is simply not
attached to a decision. That is the case of PLANNER's TASK_ASSIGNMENT, whose
`release_work` decision names no task; a decision on a task does record the
TASK_ASSIGNMENT that carried its task id, under `assignment`.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

#: The message types the pathway distinguishes; any other is `OTHER`.
KINDS = ("ROUTE_REQUEST", "RESOURCE_REQUEST", "TASK_ASSIGNMENT", "ROBOT_COMMAND")

#: Task registry topics followed on a decision's subject task.
TASK_TOPICS = ("task_assigned", "task_started", "task_completed", "task_failed",
               "task_released", "task_cancelled")

#: Registry and floor events of the deciding agent that count as an effect.
EFFECT_TOPICS = TASK_TOPICS + ("block_resolved", "errand_handed_over", "parcel_classified",
                               "parcel_received", "parcel_refused", "storage_claimed")

#: Decisions whose subject is their choice rather than their correlation id.
CHOICE_IS_SUBJECT = ("choose_next_task",)


def kind_of(message_type: str) -> str:
    return message_type if message_type in KINDS else "OTHER"


def _content(detail: Dict[str, Any]) -> Dict[str, Any]:
    content = detail.get("content")
    return content if isinstance(content, dict) else {}


def _keys_of_message(correlation_id: str, content: Dict[str, Any]) -> List[str]:
    keys = [correlation_id, str(content.get("task_id") or ""),
            str(content.get("correlation_id") or "")]
    return [k for k in keys if k]


def subject_of(decision: str, correlation_id: str, choice: Any) -> str:
    if decision in CHOICE_IS_SUBJECT:
        return str(choice or "")
    return str(correlation_id or "")


class DecisionTracer:
    """One run's decision and message traces, built as the run goes."""

    def __init__(self, eco: Any, keep_decisions: int = 20000,
                 keep_messages: int = 60000) -> None:
        self.eco = eco
        self.keep_decisions = int(keep_decisions)
        self.keep_messages = int(keep_messages)
        self.decisions: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self.messages: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self.errors: List[str] = []
        #: Taken by the tick thread (the callbacks) and the request threads
        #: (the reads), so a read never iterates a dict a tick is changing.
        self._lock = threading.RLock()
        #: The latest decision of each agent: (tick, decision_id, subject).
        self._open: Dict[str, tuple] = {}
        #: The latest decision on each subject id.
        self._by_subject: Dict[str, str] = {}
        #: Consultation rows waiting for their decision event, by decision id.
        self._consult: Dict[str, Dict[str, Any]] = {}
        #: What each agent took from its inbox, by (agent, tick): message ids.
        self._taken: Dict[tuple, List[str]] = {}
        #: Commands taken and not yet matched to a `command_*` event, by (robot, tick).
        self._unapplied: Dict[tuple, List[str]] = {}
        #: Every task id the registry has created (`task_created`).
        self._tasks: set = set()
        #: TASK_ASSIGNMENT message id by task id.
        self._assignment: Dict[str, str] = {}
        #: Transport commands awaiting their parcel's lift/drop: parcel -> message id.
        self._transport: Dict[str, str] = {}
        self._unsubscribe = eco.logger.subscribe(self._on_event)
        watch = getattr(eco.bus, "watch_inbox", None)
        self._unwatch = watch(self._on_take) if callable(watch) else None

    def close(self) -> None:
        for undo in (self._unsubscribe, self._unwatch):
            if undo is not None:
                try:
                    undo()
                except Exception:
                    pass
        self._unsubscribe = self._unwatch = None

    # ------------------------------------------------------------- intake
    def _on_take(self, receiver: str, tick: int, messages: List[Any]) -> None:
        with self._lock:
            self._take(receiver, tick, messages)

    def _take(self, receiver: str, tick: int, messages: List[Any]) -> None:
        try:
            ids = []
            for message in messages:
                mid = message.message_id
                ids.append(mid)
                row = self.messages.get(mid)
                if row is None:
                    continue
                if row["outcome"]["state"] in ("pending", "held"):
                    row["outcome"] = {"state": "received", "tick": int(tick),
                                      "basis": "taken from the receiver's inbox"}
                if row["type"] == "ROBOT_COMMAND":
                    self._unapplied.setdefault((receiver, int(tick)), []).append(mid)
            self._taken.setdefault((receiver, int(tick)), []).extend(ids)
            self._forget_old(int(tick))
        except Exception as exc:
            self.errors.append(f"take: {type(exc).__name__}: {exc}")

    def _forget_old(self, tick: int) -> None:
        # Inbox takes older than the previous tick can no longer be matched.
        for key in [k for k in self._taken if k[1] < tick - 1]:
            del self._taken[key]
        for key in [k for k in self._unapplied if k[1] < tick - 1]:
            for mid in self._unapplied.pop(key):
                row = self.messages.get(mid)
                if row is not None and row.get("applied") is None:
                    row["applied"] = {"state": "no command event", "tick": None,
                                      "basis": "taken, and no matching command_<operation> "
                                               "event in that tick"}

    def _on_event(self, event: Any) -> None:
        with self._lock:
            self._event(event)

    def _event(self, event: Any) -> None:
        try:
            topic = event.topic
            if topic == "task_created" and (event.detail or {}).get("task_id"):
                self._tasks.add(str(event.detail["task_id"]))
            if topic == "decision":
                self._decision(event)
            elif topic in ("consult_opened", "consult_closed", "llm_call",
                           "consult_question", "consult_delegation", "consult_response"):
                self._consultation(event)
            elif topic in ("message", "subagent_message"):
                self._message(event)
            elif topic == "message_dropped":
                self._delivery(event, "dropped")
            elif topic == "agent_message_received":
                self._delivery(event, "late")
            elif topic.startswith("command_") and event.category == "robot":
                self._applied(event)
            elif topic in ("parcel_lifted", "parcel_dropped"):
                self._parcel(event)
            if topic in EFFECT_TOPICS:
                self._effect(event)
        except Exception as exc:
            self.errors.append(f"{event.topic}: {type(exc).__name__}: {exc}")

    # ---------------------------------------------------------- decisions
    def _decision(self, event: Any) -> None:
        detail = event.detail or {}
        decision = str(detail.get("decision") or "")
        decision_id = str(detail.get("call_id") or f"{event.actor}:{decision}:{event.tick}:{event.seq}")
        subject = subject_of(decision, event.correlation_id, detail.get("choice"))
        trace: Dict[str, Any] = {
            "decision_id": decision_id, "seq": event.seq, "tick": int(event.tick),
            "actor": event.actor, "decision": decision, "subject": subject,
            "eligible": bool(detail.get("trigger")), "trigger": detail.get("trigger") or "",
            "trigger_detail": detail.get("trigger_detail") or "",
            "status": detail.get("status") or "", "path": detail.get("path") or "",
            "mode": detail.get("mode") or "", "source": detail.get("source") or "",
            "choice": detail.get("choice"),
            "validation": detail.get("validation") or "",
            "violation": detail.get("violation") or "",
            "consultation": None, "request": None,
            "assignment": self._assignment.get(subject),
            "effects": [], "messages": [], "later": [],
        }
        consult = self._consult.pop(decision_id, None)
        if consult is not None:
            trace["consultation"] = consult
        trace["request"] = self._request_of(event.actor, int(event.tick), decision, subject)
        self.decisions[decision_id] = trace
        if len(self.decisions) > self.keep_decisions:
            self.decisions.popitem(last=False)
        self._open[event.actor] = (int(event.tick), decision_id, subject)
        if subject:
            self._by_subject[subject] = decision_id

    def _request_of(self, actor: str, tick: int, decision: str,
                    subject: str) -> Optional[Dict[str, Any]]:
        """The reply the agent took this tick that asked for this decision, by its ids."""
        found = []
        for mid in self._taken.get((actor, tick), []):
            row = self.messages.get(mid)
            if row is None or row.get("operation") != decision:
                continue
            # The reply's own ids, and those of the request it answers
            # (`in_reply_to`): SUB-ASSIGNMENT's result names the parcel, its
            # request the task.
            keys = list(row["keys"])
            asked = self.messages.get(row.get("in_reply_to") or "")
            if asked is not None:
                keys += asked["keys"]
            if subject and subject not in keys:
                continue
            found.append(row)
        if not found:
            return None
        first = found[0]
        return {"result_message_id": first["message_id"],
                "request_message_id": first.get("in_reply_to") or None,
                "result_type": first["type"], "taken_at": tick,
                "candidates": len(found),
                "basis": "taken by the deciding agent in the decision's tick; "
                         "content.operation is the decision, and it or the request it "
                         "answers (in_reply_to) carries the subject"}

    def _consultation(self, event: Any) -> None:
        detail = event.detail or {}
        decision_id = str(detail.get("decision_id") or "")
        if not decision_id:
            return
        trace = self.decisions.get(decision_id)
        row = trace["consultation"] if trace and trace["consultation"] else self._consult.get(decision_id)
        if row is None:
            row = {"consultation_id": detail.get("consultation_id") or event.correlation_id,
                   "opened_tick": None, "outcome": None, "choice": None,
                   "llm_calls": [], "peer": detail.get("peer"),
                   "basis": "decision_id of the consultation events equals the decision's call_id"}
            if trace is not None:
                trace["consultation"] = row
            else:
                self._consult[decision_id] = row
        topic = event.topic
        if topic == "consult_opened":
            row["opened_tick"] = int(event.tick)
            row["options"] = detail.get("options")
        elif topic == "consult_closed":
            row["outcome"] = detail.get("outcome")
            row["choice"] = detail.get("choice")
            row["closed_tick"] = int(event.tick)
            row["latency_ms"] = detail.get("latency_ms")
        elif topic == "llm_call":
            row["llm_calls"].append({
                "call_id": detail.get("call_id"), "phase": detail.get("phase"),
                "status": detail.get("status"), "error": detail.get("error") or "",
                "requested_model": detail.get("requested_model"),
                "served_model": detail.get("served_model"),
                "latency_ms": detail.get("latency_ms"), "tick": int(event.tick)})
        else:
            row.setdefault("exchanges", []).append({"topic": topic, "tick": int(event.tick)})

    # ----------------------------------------------------------- messages
    def _message(self, event: Any) -> None:
        detail = event.detail or {}
        mid = str(detail.get("message_id") or "")
        if not mid:
            return
        content = _content(detail)
        mtype = str(detail.get("message_type") or "")
        row = {"message_id": mid, "tick": int(event.tick), "seq": event.seq,
               "sender": event.actor, "receiver": event.target, "type": mtype,
               "kind": kind_of(mtype), "operation": content.get("operation"),
               "correlation_id": event.correlation_id,
               "task_id": content.get("task_id"), "parcel_id": content.get("parcel_id"),
               "robot_id": content.get("robot_id"),
               "in_reply_to": detail.get("in_reply_to") or None,
               "keys": _keys_of_message(event.correlation_id, content),
               "outcome": {"state": "pending", "tick": None}, "replies": [],
               "applied": None, "decision_id": None}
        self.messages[mid] = row
        if len(self.messages) > self.keep_messages:
            self.messages.popitem(last=False)
        if mtype == "TASK_ASSIGNMENT" and row["task_id"]:
            self._assignment.setdefault(str(row["task_id"]), mid)
        parent = self.messages.get(row["in_reply_to"] or "")
        if parent is not None:
            parent["replies"].append(mid)
        # Attached to the sender's open decision when it carries its subject.
        opened = self._open.get(event.actor)
        if opened and opened[0] == int(event.tick) and opened[2] and opened[2] in row["keys"]:
            trace = self.decisions.get(opened[1])
            if trace is not None:
                row["decision_id"] = opened[1]
                row["link"] = "effect"
                trace["messages"].append(mid)
                if mtype == "ROBOT_COMMAND" and row["operation"] == "transport" and row["parcel_id"]:
                    self._transport[str(row["parcel_id"])] = mid
                return
        # Otherwise: a later command on a task some decision chose. Only task
        # ids count here (`content.task_id`, or a `correlation_id` that the
        # task registry created as a task): a parcel or robot id would join
        # the command to a decision about something else.
        if mtype == "ROBOT_COMMAND":
            keys = [str(row["task_id"])] if row["task_id"] else []
            if row["correlation_id"] in self._tasks:
                keys.append(row["correlation_id"])
            for key in keys:
                decision_id = self._by_subject.get(key)
                trace = self.decisions.get(decision_id or "")
                if trace is not None and trace["tick"] <= int(event.tick):
                    row["decision_id"] = decision_id
                    row["link"] = "later, same task id"
                    trace["later"].append({"message_id": mid, "tick": int(event.tick),
                                           "type": mtype, "operation": row["operation"]})
                    if row["operation"] == "transport" and row["parcel_id"]:
                        self._transport[str(row["parcel_id"])] = mid
                    break

    def _delivery(self, event: Any, state: str) -> None:
        detail = event.detail or {}
        row = self.messages.get(str(detail.get("message_id") or ""))
        if row is None:
            return
        if state == "dropped":
            row["outcome"] = {"state": "dropped", "tick": int(event.tick),
                              "basis": "message_dropped.message_id"}
        else:
            row["outcome"] = {"state": "received late", "tick": int(event.tick),
                              "late_by": detail.get("late_by"),
                              "basis": "agent_message_received.message_id"}

    def _applied(self, event: Any) -> None:
        operation = event.topic[len("command_"):]
        key = (event.target, int(event.tick))
        waiting = self._unapplied.get(key, [])
        matches = [mid for mid in waiting
                   if (row := self.messages.get(mid)) is not None
                   and row["sender"] == event.actor and row["operation"] == operation
                   and row["correlation_id"] == event.correlation_id]
        if not matches:
            return
        mid = matches[0]
        waiting.remove(mid)
        self.messages[mid]["applied"] = {
            "state": "applied", "tick": int(event.tick), "event_seq": event.seq,
            "event": event.topic, "identical_taken": len(matches),
            "basis": ("command_<operation> event: actor = sender, target = robot, same "
                      "correlation_id, in the tick the robot took the command"
                      + ("" if len(matches) == 1 else "; matched in inbox order"))}

    def _parcel(self, event: Any) -> None:
        detail = event.detail or {}
        parcel = str(detail.get("parcel_id") or event.correlation_id or "")
        mid = self._transport.get(parcel)
        row = self.messages.get(mid or "")
        if row is None:
            return
        robot = detail.get("robot_id") if event.topic == "parcel_lifted" else None
        if event.topic == "parcel_lifted" and robot and robot != row["receiver"]:
            return
        if event.topic == "parcel_lifted" and not (row.get("applied") or {}).get("tick"):
            return
        effect = row.setdefault("parcel", {})
        name = "lifted" if event.topic == "parcel_lifted" else "dropped"
        if name in effect:
            return
        effect[name] = {"tick": int(event.tick), "zone": detail.get("zone"),
                        "basis": "same parcel_id" + (" and robot_id" if robot else "")}
        if name == "dropped":
            self._transport.pop(parcel, None)

    def _effect(self, event: Any) -> None:
        detail = event.detail or {}
        keys = [k for k in (event.correlation_id, str(detail.get("task_id") or "")) if k]
        opened = self._open.get(event.actor)
        if opened and opened[0] == int(event.tick) and opened[2] in keys:
            trace = self.decisions.get(opened[1])
            if trace is not None:
                trace["effects"].append({"topic": event.topic, "seq": event.seq,
                                         "tick": int(event.tick),
                                         "robot_id": detail.get("robot_id"),
                                         "action": detail.get("action")})
                return
        if event.topic in TASK_TOPICS and detail.get("task_id"):
            trace = self.decisions.get(self._by_subject.get(str(detail["task_id"]), ""))
            if trace is not None and trace["tick"] <= int(event.tick):
                trace["later"].append({"topic": event.topic, "tick": int(event.tick),
                                       "robot_id": detail.get("robot_id")})

    # ------------------------------------------------------------- reading
    def message_view(self, mid: str) -> Optional[Dict[str, Any]]:
        row = self.messages.get(mid)
        if row is None:
            return None
        out = {k: v for k, v in row.items() if k != "keys"}
        out["replies"] = [{"message_id": r, "type": self.messages[r]["type"],
                           "tick": self.messages[r]["tick"],
                           "outcome": self.messages[r]["outcome"]["state"]}
                          for r in row["replies"] if r in self.messages]
        return out

    def decision_view(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(trace)
        out["messages"] = [self.message_view(mid) for mid in trace["messages"]
                           if mid in self.messages]
        out["later"] = [dict(item, **({"message": self.message_view(item["message_id"])}
                                      if "message_id" in item else {}))
                        for item in trace["later"]]
        return out

    def traces(self, limit: int = 50, eligible_only: bool = False,
               after_tick: int = -1) -> List[Dict[str, Any]]:
        with self._lock:
            rows = [t for t in self.decisions.values()
                    if t["tick"] > after_tick and (t["eligible"] or not eligible_only)]
            return [self.decision_view(t) for t in rows[-int(limit):]]

    def summary(self, fault_tick: Optional[int] = None) -> Dict[str, Any]:
        """Counts, split at `fault_tick` (pre: tick < fault_tick) when given."""
        with self._lock:
            return self._summary(fault_tick)

    def _summary(self, fault_tick: Optional[int]) -> Dict[str, Any]:
        def phase(tick: int) -> str:
            if fault_tick is None:
                return "all"
            return "pre" if tick < fault_tick else "post"

        out: Dict[str, Any] = {"fault_tick": fault_tick, "phases": {}}

        def bucket(name: str) -> Dict[str, Any]:
            return out["phases"].setdefault(name, {
                "decisions": 0, "eligible": 0, "consulted": 0,
                "status": {}, "messages": {}, "robot_commands": {
                    "sent": 0, "dropped": 0, "received": 0, "received_late": 0,
                    "pending": 0, "applied": 0},
                "decision_messages": 0, "decision_messages_received": 0,
                "decision_robot_commands_applied": 0})

        for trace in self.decisions.values():
            b = bucket(phase(trace["tick"]))
            b["decisions"] += 1
            b["eligible"] += int(trace["eligible"])
            b["consulted"] += int(trace["consultation"] is not None)
            b["status"][trace["status"]] = b["status"].get(trace["status"], 0) + 1
            for mid in trace["messages"]:
                row = self.messages.get(mid)
                if row is None:
                    continue
                b["decision_messages"] += 1
                if row["outcome"]["state"] in ("received", "received late"):
                    b["decision_messages_received"] += 1
                if (row.get("applied") or {}).get("state") == "applied":
                    b["decision_robot_commands_applied"] += 1
        for row in self.messages.values():
            b = bucket(phase(row["tick"]))
            per = b["messages"].setdefault(row["kind"], {})
            state = row["outcome"]["state"]
            per[state] = per.get(state, 0) + 1
            if row["type"] == "ROBOT_COMMAND":
                rc = b["robot_commands"]
                rc["sent"] += 1
                rc[{"dropped": "dropped", "received": "received",
                    "received late": "received_late"}.get(state, "pending")] += 1
                if (row.get("applied") or {}).get("state") == "applied":
                    rc["applied"] += 1
        out["errors"] = list(self.errors[:20])
        return out

    def write(self, path: Any) -> int:
        """Every decision trace as one JSON line, oldest first. Returns the count."""
        with self._lock:
            rows = [self.decision_view(t) for t in self.decisions.values()]
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, default=str) + "\n")
                n += 1
        return n

    def write_messages(self, path: Any, kinds: Iterable[str] = KINDS) -> int:
        """The traced messages of the four pathway kinds, one JSON line each."""
        wanted = set(kinds)
        with self._lock:
            rows = [self.message_view(mid) for mid, row in self.messages.items()
                    if row["kind"] in wanted]
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, default=str) + "\n")
                n += 1
        return n


__all__ = ["DecisionTracer", "KINDS", "kind_of", "subject_of"]
