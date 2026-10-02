"""
What drove a DK-RMM reading, read back out of the event log.

DK-RMM says a window deviated and by how much; it does not say which events,
which agents, or which expert consultations were behind it. This reads the same
window of the log and lays that out, for a person looking at one reading. It is
an explanation, not a second monitor: nothing here feeds DK-RMM, and DK-RMM's
windows, thresholds and states are read, never changed.

For a reading at tick T it reports:

- the events of the window (T - WINDOW, T], grouped by the evidence kind each
  one feeds (retry, refusal, congestion, spread), by type and by agent;
- the expert consultations open in the window or closed shortly before it, with
  how many of the window's trouble events each can be linked to. A link is
  *strong* when the event concerns a task or parcel the consultation was about,
  and *weak* when the only thing in common is a robot. A consultation is read
  from its `consult_opened` and `consult_closed` events and its
  `CONSULT_REQUEST` message; the result keeps the keys `discussions` and
  `discussion_messages`, which the RCT log page reads;
- the trouble in the window against the windows DK-RMM compared it with,
  which shows a jump that is really a return to normal after a quiet stretch.

Linking is evidence, not proof of cause. The causal test is a control run.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set

from ..communication.topics import (REFUSAL_TOPICS, RETRY_TOPICS, SWITCH_TOPICS,
                                    TROUBLE_TOPICS)
from ..dkrmm.monitor import BASELINE, EVERY, WINDOW

#: Trouble that is neither a retry nor a refusal: it only counts towards
#: spread (how many agents are in difficulty), not towards a volume indicator.
SPREAD_ONLY = TROUBLE_TOPICS - RETRY_TOPICS - REFUSAL_TOPICS

KIND_ORDER = ("congestion", "retry", "refusal", "spread")
KIND_ABOUT = {
    "congestion": "work changing hands (task switching)",
    "retry": "attempts given up and made again",
    "refusal": "refused at a gate or by the policy check",
    "spread": "robots or agents in difficulty",
}

_ROBOT_PREFIX = "R"


def _is_robot(name: str) -> bool:
    return bool(name) and name[0] == _ROBOT_PREFIX and name[1:].isdigit()


def _governed(event) -> bool:
    detail = getattr(event, "detail", None) or {}
    return event.topic == "decision" and str(detail.get("validation") or "") in (
        "policy", "state")


def kinds_of(event) -> List[str]:
    """The evidence kinds this event feeds, as DK-RMM counts it."""
    topic = event.topic
    out = []
    if topic in SWITCH_TOPICS:
        out.append("congestion")
    if topic in RETRY_TOPICS:
        out.append("retry")
    if topic in REFUSAL_TOPICS or _governed(event):
        out.append("refusal")
    if topic in SPREAD_ONLY:
        out.append("spread")
    return out


def _subjects(event, task_parcel: Dict[str, str]):
    """(tasks and parcels, robots) the event concerns."""
    detail = getattr(event, "detail", None) or {}
    things: Set[str] = set()
    robots: Set[str] = set()
    for key in ("task_id", "parcel_id"):
        if detail.get(key):
            things.add(str(detail[key]))
    if detail.get("robot_id"):
        robots.add(str(detail["robot_id"]))
    if event.correlation_id:
        things.add(str(event.correlation_id))
    for name in (event.actor, getattr(event, "target", "")):
        if _is_robot(str(name or "")):
            robots.add(str(name))
    things |= {task_parcel[t] for t in list(things) if t in task_parcel}
    return things, robots


def _discussions(events: Iterable, task_parcel: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    for event in events:
        detail = getattr(event, "detail", None) or {}
        topic = event.topic
        if topic == "consult_opened" and detail.get("consultation_id"):
            found.setdefault(detail["consultation_id"], {}).update(
                id=detail["consultation_id"], owner=event.actor or "",
                peer=detail.get("peer", ""), decision=detail.get("decision", ""),
                opened=event.tick, options=[str(o) for o in detail.get("options") or []])
        elif topic == "consult_closed" and detail.get("consultation_id"):
            d = found.setdefault(detail["consultation_id"], {"id": detail["consultation_id"]})
            d.update(closed=event.tick, outcome=detail.get("outcome") or "closed",
                     choice=detail.get("choice"))
            for key, value in (("owner", event.actor), ("peer", getattr(event, "target", "")),
                               ("decision", detail.get("decision"))):
                d.setdefault(key, value or "")
        elif topic == "message" and detail.get("message_type") == "CONSULT_REQUEST":
            content = detail.get("content") or {}
            if content.get("consultation_id") and "options" in content:
                found.setdefault(content["consultation_id"], {"id": content["consultation_id"]})[
                    "options"] = [str(o) for o in content.get("options") or []]
    for d in found.values():
        named = set(d.get("options") or [])
        if d.get("choice"):
            named.add(str(d["choice"]))
        d["robots"] = {n for n in named if _is_robot(n)}
        d["things"] = {n for n in named if not _is_robot(n)}
        d["things"] |= {task_parcel[t] for t in list(d["things"]) if t in task_parcel}
    return found


def _trouble_in(events: Iterable, lo: int, hi: int) -> int:
    return sum(1 for e in events if lo < e.tick <= hi and kinds_of(e))


def explain(events: List, tick: int, window: int = WINDOW, every: int = EVERY,
            baseline: int = BASELINE) -> Dict[str, Any]:
    """The explanation of the reading at `tick` (see the module docstring)."""
    events = [e for e in events if isinstance(getattr(e, "tick", None), int)]
    lo, hi = tick - window, tick
    task_parcel: Dict[str, str] = {}
    for e in events:
        detail = getattr(e, "detail", None) or {}
        if detail.get("task_id") and detail.get("parcel_id"):
            task_parcel[str(detail["task_id"])] = str(detail["parcel_id"])

    inside = [e for e in events if lo < e.tick <= hi]
    trouble = [e for e in inside if kinds_of(e)]

    # By kind, then by topic, then by agent.
    grouped: Dict[str, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for e in trouble:
        for kind in kinds_of(e):
            grouped[kind][e.topic][e.actor or "?"] += 1
    kinds = []
    for kind in KIND_ORDER:
        if kind not in grouped:
            continue
        topics = [{"topic": topic, "count": sum(agents.values()),
                   "agents": [[a, n] for a, n in agents.most_common(6)]}
                  for topic, agents in sorted(grouped[kind].items(),
                                              key=lambda kv: -sum(kv[1].values()))]
        kinds.append({"kind": kind, "about": KIND_ABOUT[kind],
                      "count": sum(t["count"] for t in topics), "topics": topics})

    # Chatter: messages in the window, and how many of them were discussions.
    messages = [e for e in inside if e.topic in ("message", "subagent_message")]
    discussion_messages = sum(1 for e in messages if str(
        (getattr(e, "detail", None) or {}).get("message_type", "")).startswith("CONSULT_"))

    # Discussions open in the window or closed at most one window before it.
    found = _discussions(events, task_parcel)
    near = [d for d in found.values() if d.get("opened") is not None
            and d["opened"] <= hi and d.get("closed", hi) >= lo - window]
    linked = {"strong": 0, "weak": 0, "none": 0}
    per = {d["id"]: {"strong": 0, "weak": 0} for d in near}
    for e in trouble:
        things, robots = _subjects(e, task_parcel)
        best = "none"
        for d in near:
            if e.tick < d["opened"]:
                continue
            if things & d["things"]:
                per[d["id"]]["strong"] += 1
                best = "strong"
            elif robots & d["robots"]:
                per[d["id"]]["weak"] += 1
                if best == "none":
                    best = "weak"
        linked[best] += 1
    rows = []
    for d in sorted(near, key=lambda d: (-per[d["id"]]["strong"], -per[d["id"]]["weak"],
                                         d["opened"])):
        rows.append({"id": d["id"], "owner": d.get("owner", ""), "peer": d.get("peer", ""),
                     "decision": d.get("decision", ""), "outcome": d.get("outcome", "open"),
                     "choice": d.get("choice"), "opened": d["opened"],
                     "closed": d.get("closed"), **per[d["id"]]})

    # The windows DK-RMM compared this one with.
    ends = [hi - every * k for k in range(1, baseline + 1) if hi - every * k - window >= 0]
    counts = [_trouble_in(events, end - window, end) for end in ends]
    base = {"windows": len(counts), "this": len(trouble),
            "mean": round(sum(counts) / len(counts), 1) if counts else None,
            "min": min(counts) if counts else None, "max": max(counts) if counts else None}

    return {"tick": tick, "window": [lo + 1, hi], "events": len(inside),
            "trouble": len(trouble), "kinds": kinds,
            "messages": len(messages), "discussion_messages": discussion_messages,
            "discussions": rows, "linked": linked, "baseline": base,
            "summary": _summary(trouble, linked, rows, base)}


def _summary(trouble, linked, rows, base) -> str:
    total = len(trouble)
    if not total:
        return "No trouble events in this window."
    parts = []
    # The single most common kind of trouble event, counted once per event.
    topic, count = Counter(e.topic for e in trouble).most_common(1)[0]
    who = ", ".join(a for a, _ in Counter(
        e.actor or "?" for e in trouble if e.topic == topic).most_common(3))
    parts.append(f"Mostly {topic.replace('_', ' ')} ({count} of {total} trouble "
                 f"events; {who})")
    strong = linked["strong"]
    share = round(100 * strong / total)
    lead = next((r for r in rows if r["strong"]), None)
    parts.append(f"{share}% strongly linked to a consultation"
                 + (f" (most: {lead['id']} {lead['owner']}↔{lead['peer']}, "
                    f"{lead['outcome'].replace('_', ' ')})" if lead else "")
                 + (f", {round(100 * linked['weak'] / total)}% only through a shared robot"
                    if linked["weak"] else ""))
    if base["mean"] is not None:
        if base["mean"] and base["this"] >= 3 * base["mean"]:
            parts.append(f"{base['this']} trouble events against a quiet baseline "
                         f"(mean {base['mean']}, range {base['min']}–{base['max']})")
        else:
            parts.append(f"{base['this']} trouble events against a baseline mean of "
                         f"{base['mean']} (range {base['min']}–{base['max']})")
    return "; ".join(parts) + "."


# ------------------------------------------------------------------ reading
_CACHE: Dict[str, Dict[str, Any]] = {}


def events_from_log(path: str, run_id: str = "") -> List:
    """
    Every event in a run's JSON-lines log, read incrementally.

    The whole log is needed, not only the window: a task's parcel is named when
    the task is created, which can be long before the reading. Kept per path
    with the offset reached, so a second click reads only what was appended.
    """
    import json
    import os
    from types import SimpleNamespace

    entry = _CACHE.get(path)
    size = os.path.getsize(path)
    # A new or rewritten log -- a Reset or a new run writes the file afresh,
    # and may already have grown past where the old one was read to.
    if (entry is None or size < entry["offset"]
            or (run_id and entry.get("run_id") not in ("", run_id))):
        entry = {"offset": 0, "events": [], "run_id": run_id}
        _CACHE[path] = entry
    with open(path, "rb") as handle:
        handle.seek(entry["offset"])
        chunk = handle.read()
    # Only whole lines: the last one may still be being written.
    end = chunk.rfind(b"\n") + 1
    for line in chunk[:end].splitlines():
        try:
            raw = json.loads(line)
        except ValueError:
            continue
        raw["detail"] = raw.get("detail") or {}
        entry["events"].append(SimpleNamespace(**raw))
    entry["offset"] += end
    return entry["events"]


def wall_clock_at(events: List, ticks: Iterable[int]) -> Dict[int, str]:
    """The clock time each tick was reached: the last event logged at or before it."""
    last_at: Dict[int, str] = {}
    for e in events:
        clock = getattr(e, "wall_clock", "") or ""
        if clock and isinstance(getattr(e, "tick", None), int):
            last_at[e.tick] = clock
    known = sorted(last_at)
    out: Dict[int, str] = {}
    import bisect
    for tick in ticks:
        i = bisect.bisect_right(known, tick) - 1
        out[tick] = last_at[known[i]] if i >= 0 else ""
    return out
