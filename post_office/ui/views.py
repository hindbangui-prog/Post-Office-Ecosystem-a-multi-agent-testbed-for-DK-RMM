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
`describe` and `dkrmm_catalogue` are kept; the trace, trajectory and history
folds (which read the removed observability store) and the discussion rows of
the frame are not part of this prototype.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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

    # The message type is appended, so a page that reads four still reads.
    said = [[m.sender, m.receiver, m.text or m.message_type.value,
             m.correlation_id, m.message_type.value]
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
