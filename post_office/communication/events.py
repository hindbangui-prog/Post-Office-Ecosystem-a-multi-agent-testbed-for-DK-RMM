"""
The event log: one append-only line per thing that happened.

Written now, in Phase 3, because the runtime monitoring component you will add
later can only see what this file records. If a decision is taken inside an
agent and never emitted, no monitor, metric or dashboard will ever find it --
so the rule for the rest of the package is that every branch emits, including
the branches where a request was refused and nothing happened.

The format is JSON Lines rather than a database on purpose: a run that dies
half way through still leaves a usable file, `wc -l` is a progress bar and
`grep` is a good enough debugger. Every line has the same eight keys, so a
reader never has to switch on the category to find the tick or the actor.

    {"seq":412,"tick":37,"category":"communication","topic":"message",
     "actor":"SORTING","target":"SUB-BARCODE","correlation_id":"P-0007",
     "run_id":"demo","detail":{...}}
"""

from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, Iterable, Iterator, List, Optional


from . import provenance


class EventCategory:
    """
    The families of event. A plain class of constants rather than an Enum: a
    monitor written next month will want to add one without editing this file.
    """

    AGENT = "agent"                  # created, started, stopped
    COMMUNICATION = "communication"  # a message, or a refused message
    TASK = "task"                    # created, assigned, progressed, finished
    ROBOT = "robot"                  # moved, picked, delivered, blocked
    PARCEL = "parcel"                # arrived, classified, moved, departed
    RESOURCE = "resource"            # storage and charge points, granted or not
    BATTERY = "battery"              # level changes worth noticing
    SUPERVISOR = "supervisor"        # objectives, policies, approvals
    SIMULATION = "simulation"        # started, tick, stopped, reset


class Event:
    """One line of the log. Built by the logger; nobody else constructs these."""

    __slots__ = ("seq", "tick", "category", "topic", "actor", "target",
                 "correlation_id", "detail", "wall_clock", "run_id")

    def __init__(self, seq: int, tick: int, category: str, topic: str,
                 actor: str, target: str, correlation_id: str,
                 detail: Dict[str, Any], wall_clock: str, run_id: str) -> None:
        self.seq = seq
        self.tick = tick
        self.category = category
        self.topic = topic
        self.actor = actor
        self.target = target
        self.correlation_id = correlation_id
        self.detail = detail
        self.wall_clock = wall_clock
        self.run_id = run_id

    def as_dict(self) -> dict:
        return {
            "seq": self.seq,
            "tick": self.tick,
            "wall_clock": self.wall_clock,
            "run_id": self.run_id,
            "category": self.category,
            "topic": self.topic,
            "actor": self.actor,
            "target": self.target,
            "correlation_id": self.correlation_id,
            "detail": self.detail,
        }

    def __repr__(self) -> str:
        arrow = f" -> {self.target}" if self.target else ""
        return f"<{self.tick:>4} {self.category}/{self.topic} {self.actor}{arrow}>"


class EventLogger:
    """
    Writes a JSONL file and keeps the tail in memory for the API.

    `path=None` keeps everything in memory only, which is what the tests use --
    a test suite that leaves a trail of log files behind is a test suite people
    stop running.

    One logger is one run, and the file is initialised to match: starting or
    resetting a simulation builds a new logger, which empties the file it
    writes to. It used to append, so every run piled onto the one before it --
    weeks of runs in a single file separated by nothing but a `run_id` field,
    and on the machine this was written on, 1.4 GB of them. `append=True` is
    there for a caller that really does mean to continue a file, and nothing
    in the simulation does.
    """

    def __init__(self, run_id: str = "run", path: Optional[str] = None,
                 keep: int = 5000, also: Optional[Callable[[Event], None]] = None,
                 append: bool = False) -> None:
        self.run_id = run_id
        self.path = path
        self._seq = 0
        self._recent: Deque[Event] = deque(maxlen=keep)
        self._counts: Dict[str, int] = {}
        self._handle = None
        self._subscribers: List[Callable[[Event], None]] = []
        if also is not None:
            self._subscribers.append(also)
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._handle = open(path, "a" if append else "w", encoding="utf-8")

    # ---------------------------------------------------------------- writing
    def emit(self, category: str, topic: str, tick: int = 0, actor: str = "",
             target: str = "", correlation_id: str = "", **detail) -> Event:
        # Provenance, when a perturbation injector is what is running. Outside
        # one this is a dict lookup that returns nothing, so the ordinary path
        # is unchanged -- and the stamp goes in `detail`, which is a free dict,
        # so no reader of the log has to learn anything new.
        detail = provenance.stamp(detail)
        self._seq += 1
        event = Event(
            seq=self._seq, tick=tick, category=category, topic=topic,
            actor=actor, target=target, correlation_id=correlation_id,
            detail=detail,
            wall_clock=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            run_id=self.run_id,
        )
        self._recent.append(event)
        key = f"{category}.{topic}"
        self._counts[key] = self._counts.get(key, 0) + 1
        if self._handle is not None:
            self._handle.write(json.dumps(event.as_dict(), default=str) + "\n")
        for subscriber in list(self._subscribers):
            try:
                subscriber(event)
            except Exception:          # a broken listener must not stop a run
                pass
        return event

    def routed_sink(self, routes: Dict[str, str], default: str,
                    actor: str = "") -> Callable[..., None]:
        """
        A sink that files each topic under the category it belongs to.

        The environment announces parcels arriving, shelves filling and charge
        points being taken through one callback; filing all of it under one
        category would make "show me everything about resources" a query nobody
        can write.
        """
        def sink(topic: str, tick: int = 0, **detail) -> None:
            category = default
            for prefix, name in routes.items():
                if topic.startswith(prefix):
                    category = name
                    break
            self.emit(category, topic, tick=tick,
                      actor=detail.pop("actor", actor),
                      target=detail.pop("target", ""),
                      correlation_id=detail.pop("correlation_id",
                                                detail.get("parcel_id", "") or ""),
                      **detail)
        return sink

    def sink_for(self, category: str, actor: str = "") -> Callable[..., None]:
        """
        A keyword-only callable for a layer that must not import this module.

        The environment and the task registry take one of these, so they can
        announce what they do without ever learning what a logger is.
        """
        def sink(topic: str, tick: int = 0, **detail) -> None:
            self.emit(category, topic, tick=tick,
                      actor=detail.pop("actor", actor),
                      target=detail.pop("target", ""),
                      correlation_id=detail.pop("correlation_id",
                                                detail.get("parcel_id", "") or ""),
                      **detail)
        return sink

    def subscribe(self, fn: Callable[[Event], None]) -> Callable[[], None]:
        """Listen live -- this is how the WebSocket stream is fed."""
        self._subscribers.append(fn)

        def unsubscribe() -> None:
            if fn in self._subscribers:
                self._subscribers.remove(fn)
        return unsubscribe

    def flush(self) -> None:
        if self._handle is not None:
            self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "EventLogger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------------------------------------------------------- reading
    def recent(self, limit: int = 50, category: Optional[str] = None,
               actor: Optional[str] = None,
               correlation_id: Optional[str] = None) -> List[Event]:
        out = []
        for event in reversed(self._recent):
            if category is not None and event.category != category:
                continue
            if actor is not None and actor not in (event.actor, event.target):
                continue
            if correlation_id is not None and event.correlation_id != correlation_id:
                continue
            out.append(event)
            if len(out) >= limit:
                break
        out.reverse()
        return out

    def counts(self) -> Dict[str, int]:
        return dict(sorted(self._counts.items()))

    @property
    def total(self) -> int:
        return self._seq

    def __len__(self) -> int:
        return len(self._recent)


def read_events(path: str) -> Iterator[dict]:
    """Read a recorded run back. Bad lines are skipped, not fatal."""
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
