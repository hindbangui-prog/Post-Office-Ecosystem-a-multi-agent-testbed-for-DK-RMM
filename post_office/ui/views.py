"""
The data behind each view, built from an ecosystem.

The source built the same shapes for its captured files and its server, so
that the page you watch and the page you send somebody could not drift apart.
Prototype II keeps the server half: the runner calls `static_of` once per
ecosystem and `frame_of` after every tick, under its lock, and `ui/live.py`
serves what they built without touching the running ecosystem again.

Nothing here knows about HTML. Each function answers one question -- what does
this view need to know -- and the templates are the only thing that decides how
it looks.

Adapted from the source `post_office/ui/views.py`: `static_of`, `frame_of`,
`describe`, the trajectory fold (`trajectory_row`, `trajectory_data`,
`trajectory_tail`, with the source sink's `event_type_for`) and
`dkrmm_catalogue` are kept; the trajectory reads the event logger the runner
holds rather than the removed trace store. The trace and history folds and the
discussion rows of the frame are not part of this prototype.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..communication import taxonomy
from ..communication.directory import AgentKind

#: Interned so the per-tick arrays stay small; the page maps them back.
#: Appended to, never reordered: a robot's state travels to the floor view as
#: its index here, so moving an entry relabels every robot in every replay
#: captured before the change.
ROBOT_STATES = ["IDLE", "MOVING", "PICKING", "DELIVERING", "CHARGING",
                "WAITING", "BLOCKED", "UNLOADING"]
#: Appended to, never reordered: the floor view sends a parcel's state as its
#: index in this list, so moving an entry would silently relabel every parcel in
#: every replay captured before the change.
PARCEL_STATES = ["ARRIVED", "REGISTERED", "CLASSIFIED", "AWAITING_PICKUP",
                 "IN_TRANSIT", "SORTED", "STORED", "DISPATCHED",
                 "AWAITING_DISPATCH", "REFUSED", "RETURNED"]
PRIORITIES = ["NORMAL", "EXPRESS", "URGENT"]

#: What each agent is for, in one line, for the legend beside the interaction
#: graph. The directory's `role` is a label; this is the job.
WHAT_THEY_DO = {
    "INTAKE": "The front door. Receives a parcel, and decides whether the "
              "facility takes it at all or turns it away.",
    "DISPATCH": "The back door. Releases a parcel from the building, or holds "
                "it a little longer for a fuller load.",
    "SUB-VALIDATION": "Looks at a parcel the facility has not yet taken: can "
                      "the address be read at all, and is the town one this "
                      "network goes to.",
    "SUB-REGISTRATION": "Books an accepted parcel into the postal system, and "
                        "stamps the moment the facility took it on.",
    "SUB-PACKING": "Packs a parcel into the bag for its destination and mail "
                   "class, so what leaves the building is a sorted receptacle "
                   "rather than a heap of parcels.",
    "SUB-MANIFEST": "Books a parcel out: what left, for which route, and how "
                    "long it had been waiting at the door.",
    "SUPERVISOR": "Sets the objective and the standing policy, approves the "
                  "plan, and is the only agent that can stop the system. Plain "
                  "Python, no model.",
    "PLANNER": "Watches the floor and turns what it sees into tasks. Decides "
               "how much work to release onto the floor each tick.",
    "SORTING": "Owns where a parcel goes next. Its clerks read the label and "
               "measure the shelves; the judgement -- storage or straight out "
               "-- is this agent's, and the grade is whatever the sender paid "
               "for.",
    "ROUTING": "Turns 'get that robot there' into a list of cells, and decides "
               "what to do when the way is blocked.",
    "SCHEDULING": "Matches work to robots and shepherds each errand to its end. "
                  "The only expert that commands a robot.",
    "RESOURCE": "Owns everything that can run out -- battery, charge points, "
                "shelves -- and is the only agent allowed to refuse work.",
    "SUB-BARCODE": "Reads the label. The one sub-agent with no judgement to "
                   "exercise: either it scans or it does not.",
    "SUB-PRIORITY": "Reports the service written on the label. It does not "
                    "grade anything: the class was paid for at the counter, so "
                    "there is nothing here to decide.",
    "SUB-DESTINATION": "Measures the shelves and reports what it finds. Shelf "
                       "or straight out is SORTING's call, taken afresh on "
                       "every leg because storage fills and drains.",
    "SUB-ROUTE": "A* across the floor. Geometry, with one right answer.",
    "SUB-COLLISION": "Finds the ways out of a block -- is there a detour, how "
                     "much longer, is there anywhere to step aside. ROUTING "
                     "chooses between them.",
    "SUB-ASSIGNMENT": "Reports which robots could take a job at all, and how "
                      "far each one would have to walk. Which of them goes is "
                      "SCHEDULING's call.",
    "SUB-QUEUE": "Puts the ready work in order: priority first, then how long it "
                 "has waited.",
    "SUB-DEADLINE": "Finds the jobs ageing badly. Pulls against the queue, which "
                    "would happily serve urgent parcels for ever.",
    "SUB-BATTERY": "Estimates what an errand will cost against what the robot "
                   "has left. Whether that is enough is RESOURCE's judgement, "
                   "not a threshold here.",
    "SUB-CHARGING": "Reports which points are free, how far each is, and who "
                    "else is queueing with what on board. Four points, five "
                    "robots, and RESOURCE decides who gets one.",
    "SUB-STORAGE": "Watches the shelves: how full they are, and whether to keep "
                   "filling them.",
}
ROBOT_ROLE = ("Carries parcels. Owns its own body and reports everything it "
              "does; routes, work and permission to charge all come from "
              "elsewhere.")


# --------------------------------------------------------------- the floor
def static_of(eco, ticks: int = 0, preset: str = "default") -> Dict[str, Any]:
    """Everything about a run that does not change: the building and the cast."""
    env = eco.env
    return {
        "seed": eco.seed, "ticks": ticks, "preset": preset,
        "objective": eco.supervisor.objective,
        "grid": {"w": env.grid.width, "h": env.grid.height},
        "obstacles": [[p.x, p.y] for p in sorted(env.grid.obstacles)],
        "zones": {z.value: [env.zones[z].x0, env.zones[z].y0,
                            env.zones[z].x1, env.zones[z].y1]
                  for z in env.zones.zones()},
        "stations": [[s.position.x, s.position.y] for s in
                     sorted(env.stations.values(), key=lambda s: s.station_id)],
        "robots": eco.fleet.ids(),
        # The declared van routes, in the timetable's order. The floor draws one
        # bay per route from this list, so a route the run has closed (no van
        # at its bay any more) still shows, as an empty slot. The floor names
        # the bays by position (Route A, B, ...), not by these identifiers.
        "routes": (list(env.departures.routes)
                   if getattr(env, "departures", None) is not None else []),
        "hierarchy": eco.directory.tree(),
        "agents": [{"id": r.agent_id, "kind": r.kind.value, "role": r.role,
                    "parent": r.parent_id,
                    "does": WHAT_THEY_DO.get(r.agent_id, ROBOT_ROLE)}
                   for r in eco.directory.all()],
        "robot_states": ROBOT_STATES,
        "parcel_states": PARCEL_STATES,
        "priorities": PRIORITIES,
        "storage_capacity": env.storage.capacity,
    }


def _channel_and_type(eco, message) -> List[str]:
    """
    `[channel, interaction_type]` of a bus message, as the logger stamped its
    event: `taxonomy.classify` over category `communication`, the topic the bus
    gave it (`bus.py`: `subagent_message` when the directory record of the
    sender is a sub-agent, `message` otherwise), sender, receiver and type,
    with the content's `interaction_type` as `content_type`.
    """
    record = eco.directory.get(message.sender)
    topic = ("subagent_message"
             if record is not None and record.kind is AgentKind.SUBAGENT
             else "message")
    content = message.content
    label = taxonomy.classify(
        "communication", topic, message.sender, message.receiver,
        message.message_type.value,
        content_type=content.get("interaction_type", "")
        if isinstance(content, dict) else "")
    return [label.channel, label.interaction_type]


def frame_of(eco, tick: Optional[int] = None) -> Dict[str, Any]:
    """
    One tick: where everything is, and what was said.

    Positional arrays rather than objects. A thousand ticks of named keys is
    most of a replay's weight and none of its meaning, and the live view sends
    one of these every few hundred milliseconds.
    """
    tick = eco.world.tick if tick is None else tick
    # Two counters appended to the row, never inserted: how many ticks the
    # robot has stood blocked at its next cell, and how many it has waited on
    # somebody else. A page that reads only the first six still reads; a page
    # that wants "R3 blocked 18 ticks" has it from the frame, not from a
    # reconstruction.
    robots = [[r.current_position.x, r.current_position.y,
               ROBOT_STATES.index(r.status.value), round(r.battery_level),
               r.carrying or "", r.current_task or "",
               int(getattr(r, "_blocked_for", 0) or 0),
               int(getattr(r, "_waited", 0) or 0)]
              for r in eco.fleet.all()]

    # Likewise appended: which robot the parcel is assigned to, the tick its
    # current status began (so "waiting since" is a subtraction, not a
    # search), and its deadline. -1 where the parcel has none.
    def _since(p):
        t = p.timestamps.get(str(p.status.value).lower())
        return -1 if t is None else int(t)

    parcels = sorted([[p.parcel_id, p.position.x, p.position.y,
                       PRIORITIES.index(p.priority.value),
                       PARCEL_STATES.index(p.status.value),
                       p.assigned_robot or "", _since(p),
                       -1 if p.due_by is None else int(p.due_by)]
                      for p in eco.env.parcels.values() if p.position is not None])

    # The message type is appended, so a page that reads four still reads;
    # then the taxonomy's channel and interaction type, appended likewise, so
    # the floor graph can colour an edge by its channel. The two are what the
    # logger stamped on the message's event: the same `classify`, over the same
    # five fields, with the topic named as the bus names it (`subagent_message`
    # when the directory says the sender is a sub-agent, `message` otherwise)
    # and the content's own `interaction_type` as `content_type`.
    said = [[m.sender, m.receiver, m.text or m.message_type.value,
             m.correlation_id, m.message_type.value, *_channel_and_type(eco, m)]
            for m in eco.bus.log.recent(400) if m.tick == tick]

    # Which experts stopped to think on this tick, and what set them off.
    # Positional like everything else here: agent, decision, mode, trigger,
    # the short rationale. `mode` is "llm" only when a model was actually
    # asked -- with the deterministic brain a fired trigger still shows, as
    # the decision that would have gone to a model, which is the number worth
    # seeing before paying for the calls. A condition that was only *noted*
    # (the rule stood) is not here: the rule answered, nobody stopped.
    reasoned = []
    for agent in list(eco.experts.values()) + [eco.planner]:
        for row in agent.decisions[-12:]:
            if row.get("tick") == tick and row.get("trigger"):
                reasoned.append([agent.agent_id, row.get("kind", ""),
                                 row.get("mode", ""), row.get("trigger", ""),
                                 (row.get("reason") or "")[:90]])

    board = eco.env.departures
    frame = {
        "t": tick, "r": robots, "p": parcels, "m": said, "d": reasoned,
        "c": [len(parcels), eco.env.dispatched_count, eco.bus.log.sent,
              eco.logger.total, round(eco.fleet.battery_summary()["mean"])],
        # The timetable, as of this tick: what is standing at each bay, when it
        # goes, and how full it is. Appended rather than folded into "c" so an
        # older replay, whose counters are positional, still reads -- and the
        # van's name and parcel count are appended to the row for the same
        # reason, so a replay captured before the board was drawn still loads.
        "v": ([[van.route, van.departs_at, van.units, van.capacity,
                van.vehicle_id, len(van.loaded)]
               for _route, van in sorted(board._bay.items())]
              if board is not None else []),
        # The bag room: how many receptacles are open, sealed and gone. Also
        # appended, for the same reason.
        "g": (eco.env.bags.summary() if getattr(eco.env, "bags", None)
              is not None else {}),
    }
    return frame


def replay_data(static: Dict[str, Any], summary: Dict[str, Any],
                frames: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    The floor view's whole payload: the building, the run's summary and the
    frames so far (one, when the page is about to go live).

    Built from what the runner published rather than from an ecosystem, so a
    page can be served while a tick is in progress.
    """
    return {"static": {**static, "summary": summary}, "frames": list(frames)}


# ---------------------------------------------------------------- one event
def _bits(mapping, keep: int = 5) -> str:
    """The scalar fields of a payload, as `k=v k=v`. Lists become their length."""
    out = []
    for key, value in list(mapping.items())[:keep]:
        if isinstance(value, dict) and "_n" in value:
            out.append(f"{key}[{value['_n']}]")
        elif isinstance(value, (list, tuple)):
            out.append(f"{key}[{len(value)}]")
        elif not isinstance(value, dict):
            out.append(f"{key}={value}")
    return " ".join(out)


def describe(event, limit: int = 160) -> str:
    """
    One line saying what an event was, for a human reading a list of them.

    Takes an event of the run's log (`communication.events.Event`) or its
    `as_dict()`. A decision reads `decision -> choice (reason)`; a message with
    no text reads as its type and its content's scalar fields; anything else
    is its text, choice, tool, action or topic, whichever it has first.
    """
    row = event.as_dict() if hasattr(event, "as_dict") else dict(event)
    payload = row.get("detail") or {}
    text = (payload.get("text") or payload.get("choice")
            or payload.get("tool") or payload.get("action")
            or payload.get("topic") or "")
    if row.get("topic") == "decision" and payload.get("decision"):
        text = f"{payload.get('decision', '')} -> {payload.get('choice', '')}"
        if payload.get("reason"):
            text += f"  ({payload['reason']})"
    elif payload.get("message_type") and not payload.get("text"):
        text = (f"{str(payload['message_type']).lower()}  "
                f"{_bits(payload.get('content') or {})}").strip()
    return str(text or row.get("topic") or "")[:limit]


# ---------------------------------------------------------- the trajectory
#: The type prefixes the source's trace store accepted. A category outside
#: them is filed as `agent/<category>.<topic>` (the source sink's rule).
EVENT_PREFIXES = ("agent/", "step/", "user/", "assistant/", "tool/",
                  "session/", "run/", "robot/", "task/", "parcel/",
                  "resource/", "battery/", "supervisor/", "simulation/",
                  "communication/")

#: How an event's `category`/`topic` becomes the trajectory's `type`.
#:
#: Most of it is mechanical -- `robot`/`moved` becomes `robot/moved`. The
#: exceptions are the source sink's: a decision, a message and a refusal get
#: stable names. A bus message is `message` or, from a sub-agent,
#: `subagent_message`; both are a message. A refusal is `message_refused`.
_SPECIAL = {
    ("agent", "decision"): "agent/decision",
    ("communication", "message"): "agent/message",
    ("communication", "subagent_message"): "agent/message",
    ("communication", "message_refused"): "agent/refused",
}


def event_type_for(category: str, topic: str) -> str:
    """The trajectory's event type for one logged event."""
    special = _SPECIAL.get((category, topic))
    if special is not None:
        return special
    prefix = f"{category}/"
    if not prefix.startswith(EVENT_PREFIXES):
        # A category invented later by a monitoring component still has to land
        # somewhere findable rather than being refused into the void.
        return f"agent/{category}.{topic}"
    return f"{category}/{topic}"


#: Payload keys worth keeping on every trajectory row. `content` is left out
#: because `describe` has already rendered it into the row's own text.
KEEP = (
    "text", "reason", "error", "traceback", "message_type",
    "tool", "called_by", "ok", "operation", "answered",
    "decision", "choice", "source", "confidence",
    "action", "accepted", "changed", "before", "after", "target",
    "status", "task_id", "parcel_id", "robot_id", "destination", "priority",
    "model", "usage", "finish_reason", "seed", "ticks",
    "arguments", "result", "facts",
    # The source's expert-discussion keys, kept as the source had them.
    "discussion_id", "owner", "peer", "outcome", "seconds", "turn",
    # The taxonomy's stamp (the page's lanes read `interaction_type`), the
    # consultations and their model calls (the consultation view), and the
    # message ids a request and its reply are paired by.
    "interaction_type", "channel", "consultation_id", "phase", "served_model",
    "latency_ms", "options", "in_reply_to", "message_id",
)


def _trim(value, depth: int = 0):
    if isinstance(value, str):
        return value if len(value) <= 600 else value[:597] + "..."
    if isinstance(value, dict):
        if depth >= 2:
            return {"_keys": len(value)}
        return {k: _trim(v, depth + 1) for k, v in list(value.items())[:12]}
    if isinstance(value, (list, tuple)):
        if depth >= 2 or len(value) > 12:
            return {"_n": len(value)}
        return [_trim(v, depth + 1) for v in value]
    return value


def _offset_ms(timestamp: str, base: str) -> float:
    """Milliseconds from the page's first row to this one."""
    from datetime import datetime

    try:
        return round((datetime.fromisoformat(timestamp)
                      - datetime.fromisoformat(base)).total_seconds() * 1000.0, 1)
    except (TypeError, ValueError):
        return 0.0


def trajectory_row(event, base: str) -> List[Any]:
    """
    One event as the trajectory page holds it, from an `Event` or its
    `as_dict()`.

    Positional, because eleven thousand copies of ten key names is most of that
    page's weight and none of its meaning:

        [id, tick, ms, type, actor, target, correlation, duration, text, payload]

    `id` is the event's `seq`; `ms` is its wall clock's offset from `base`;
    `duration` is the event's own `latency_ms` (a model call, a response, a
    closed consultation, a model decision), else None; `payload` is the
    event's detail with the taxonomy's stamp (`interaction_type`, `channel`),
    the `KEEP` keys only, trimmed.

    Shared by the initial fold and by the live tail, so a row that arrives while
    you are watching reads exactly like the same row folded a minute later.
    Two implementations of this would be two vocabularies.
    """
    row = event.as_dict() if hasattr(event, "as_dict") else dict(event)
    detail = dict(row.get("detail") or {})
    detail["interaction_type"] = row.get("interaction_type", "")
    detail["channel"] = row.get("channel", "")
    latency = detail.get("latency_ms")
    timed = isinstance(latency, (int, float)) and not isinstance(latency, bool)
    return [
        row.get("seq"), row.get("tick"), _offset_ms(row.get("wall_clock"), base),
        event_type_for(row.get("category", ""), row.get("topic", "")),
        row.get("actor", ""), row.get("target", ""), row.get("correlation_id", ""),
        round(latency, 3) if timed else None,
        describe(row, 200),
        {k: _trim(v) for k, v in detail.items()
         if k in KEEP and v not in (None, "", [], {})},
    ]


#: More than the logger ever holds (`keep_events`, 8000 by default), so
#: "everything the logger holds" is one read.
_HELD = 10 ** 6


def trajectory_tail(runner, after_id: int = 0, started: str = "",
                    limit: int = 800) -> Dict[str, Any]:
    """
    The rows logged since `after_id`, for a page that is following the run.

    `started` is the timestamp the page opened with, so the offsets it appends
    are measured from the same zero as the ones it already has. Without it a
    live row would be timed from itself and the duration axis would fold back on
    itself every poll. Read through the runner's lock-free `events` accessor
    (`logger.since`), never the step lock.
    """
    events = runner.events(after=after_id, limit=limit)
    base = started or (events[0]["wall_clock"] if events else "")
    rows = [trajectory_row(event, base) for event in events]
    return {"rows": rows,
            "last_id": rows[-1][0] if rows else after_id,
            "total": runner.event_counts()["total"]}


def _summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The source's run summary, counted over the events the logger holds."""
    return {
        "events": len(events),
        "started": events[0]["wall_clock"] if events else None,
        "last_event": events[-1]["wall_clock"] if events else None,
        "ticks": max((e["tick"] for e in events), default=0),
        "actors": len({e["actor"] for e in events if e["actor"]}),
        "correlations": len({e["correlation_id"] for e in events if e["correlation_id"]}),
        # A model request is one `llm_call`; a tool call is one expert asking a
        # sub-agent (`SUBTASK_REQUEST`). Nothing here has tool errors or an
        # operator's actions.
        "model_requests": sum(e["topic"] == "llm_call" for e in events),
        "tool_calls": sum(e["category"] == "communication"
                          and e["topic"] in ("message", "subagent_message")
                          and (e.get("detail") or {}).get("message_type") == "SUBTASK_REQUEST"
                          for e in events),
        "tool_errors": 0,
        "user_actions": 0,
        "finished": any(e["topic"] == "simulation_stopped" for e in events),
    }


def trajectory_data(runner, limit: int = 9000) -> Dict[str, Any]:
    """
    The newest `limit` rows the event logger holds, with enough payload for the
    inspector, and the run they belong to.

    The logger keeps the newest `keep_events` events (8000 by default) in
    memory and nothing older: there is no store of a run's earlier events, so
    on a run that has logged more, the page shows the newest it holds,
    `truncated` is true and `total` is how many the run has logged
    (`logger.total`). `archived` is always false: only the live run is served.
    Read through the runner's lock-free accessors (`events`, `event_counts`,
    `last_frame`), never the step lock.
    """
    import json

    from ..config.settings import scenario_name

    held = runner.events(after=0, limit=_HELD)
    # Never fewer than the rows just read: a tick may log between the two reads.
    total = max(runner.event_counts()["total"], held[-1]["seq"] if held else 0)
    # The newest rows, not the first ones. A run that is still going has far
    # more than fit on a page, and the half you want is the half nearest now.
    events = held[-limit:] if limit and len(held) > limit else held
    # Decided from the rows themselves: a run's `seq` starts at 1, so a first
    # row after 1 means older rows were dropped (by `limit`, or by the logger).
    truncated = bool(events) and events[0]["seq"] > 1

    rows, started, span, ticks = [], "", 0, 1
    if events:
        started = events[0]["wall_clock"]
        rows = [trajectory_row(event, started) for event in events]
        span = rows[-1][2] or 1
        ticks = max(event["tick"] for event in events) or 1

    frame = runner.last_frame
    run_id = frame.get("run_id") or (held[-1]["run_id"] if held else "")
    begun = next((e["wall_clock"] for e in held if e["topic"] == "simulation_started"), "")
    run = {"run_id": run_id, "seed": frame.get("seed"),
           "preset": scenario_name(runner.preset),
           "model": getattr(getattr(runner, "settings", None), "model", None) or "",
           "started_at": begun, "ticks": frame.get("tick")}
    summary = _summary(held)
    agents: Dict[str, int] = {}
    for event in events:
        if event["actor"]:
            agents[event["actor"]] = agents.get(event["actor"], 0) + 1
    return {
        "events": rows, "started": started, "span": span, "ticks": ticks,
        "truncated": truncated, "total": total,
        # Said on the page rather than inferred from it.
        "run_id": run_id, "archived": False,
        "run": run,
        "summary": summary,
        "log": json.dumps(
            {"run": run, "summary": summary,
             "showing": (f"the newest {len(rows):,} of {total:,} rows"
                         if truncated else f"all {len(rows):,} rows"),
             "agents": dict(sorted(agents.items(), key=lambda kv: -kv[1]))},
            indent=2, default=str),
    }


# ---------------------------------------------------------------- DK-RMM
def dkrmm_catalogue():
    """
    The twelve indicators and what each one is for, for the page to label.

    Imported here rather than in the page so that the wording lives in one
    place: the monitor's own description of an indicator and the caption a
    reader sees under it are the same string, and cannot drift.
    """
    from ..dkrmm.indicators import INDICATORS

    return list(INDICATORS)
