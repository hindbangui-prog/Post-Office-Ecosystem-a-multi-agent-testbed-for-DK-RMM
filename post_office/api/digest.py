"""
Short answers for the top of the app: what the monitor makes of the run as it
stands, and the indicators behind that reading.

Digests and not summaries. The full readings stay at `/dkrmm/state` and
`/dkrmm/series`; these exist so a strip at the top of the window can say the
state without the shell fetching more documents every second, and so the
DK-RMM pane can label each indicator with the monitor's own description.

Adapted from the source `post_office/api/digest.py`: `monitor_digest` is kept
as it was; the second digest, which read the source's disturbance controller,
is not part of this prototype.

Extended on 2026-10-12 with the operational indicators (design of the same
date, section 7): the digest carries what was observed this window and a
compact operations block, and each indicator row carries its kind, direction,
baseline, whether it could be read, which way it deviated, the evidence kind
it fed and the counts it was read from.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _num(value: Any) -> Optional[float]:
    """A float, or None for anything that is not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _observed(kinds: List[str], not_evaluated: List[str]) -> str:
    """
    One line saying which evidence kinds were present this window and which
    kinds were not read at all, so STABLE with delivery failures observed is
    told apart from plain STABLE, and from a window too quiet to read.
    """
    parts: List[str] = []
    if kinds:
        parts.append(", ".join(kinds) + " observed")
    else:
        parts.append("no evidence kinds")
    if not_evaluated:
        try:
            from ..dkrmm.monitor import BEHAVIOURAL_KINDS

            behavioural = set(BEHAVIOURAL_KINDS)
        except Exception:
            behavioural = set()
        if behavioural and set(not_evaluated) >= behavioural:
            parts.append("behavioural kinds not evaluated")
        else:
            parts.append(", ".join(not_evaluated) + " not evaluated")
    return "; ".join(parts)


def _operations(current: Dict[str, Any]) -> Dict[str, Any]:
    """
    The compact operations block: delivery, backlog, throughput and the
    per-category resources, each value None where it was not read. Empty
    readings before the first assessment give a block of Nones, so the page
    can draw the same four groups whatever the monitor has seen.
    """
    indicators = current.get("indicators") or {}
    detail = indicators.get("detail") or {}
    evaluable = current.get("evaluable") or indicators.get("evaluable") or {}
    delivery = detail.get("delivery") or {}
    backlog = detail.get("backlog") or {}
    throughput = detail.get("throughput") or {}
    resources = detail.get("resources") or {}

    def read(name: str) -> Optional[float]:
        return (_num(indicators.get(name))
                if evaluable.get(name) else None)

    growth = read("backlog_growth")
    completed = read("task_completion_rate")
    gap = read("completion_gap")
    return {
        "delivery": {
            "attempted": delivery.get("attempted"),
            "delivered": delivery.get("delivered"),
            "dropped": delivery.get("dropped"),
            "late": delivery.get("late"),
            "held_now": delivery.get("held_now"),
            "rate": read("communication_failure_rate"),
        },
        "backlog": {
            "now": backlog.get("backlog_now"),
            "per_tick": growth,
            "zones": dict(backlog.get("by_zone") or {}) or None,
            "unfinished_tasks": backlog.get("unfinished_tasks"),
            "increasing_for": (backlog.get("increasing_for")
                               if growth is not None else None),
        },
        "throughput": {
            "completed_per_tick": (completed if completed is not None
                                   else _num(throughput.get("completed_per_tick"))),
            "incoming_per_tick": _num(throughput.get("incoming_per_tick")),
            "gap": (gap if gap is not None
                    else _num(throughput.get("completion_gap"))),
        },
        "resources": {
            str(category): (_num(row.get("value")) if isinstance(row, dict)
                            and row.get("evaluable") else None)
            for category, row in resources.items()
        } or None,
    }


# --------------------------------------------------------------- the monitor
def _dragons(monitor: Any, current: Dict[str, Any]) -> Dict[str, Any]:
    """`dragon`, `previous_dragon` and `dk_readings`, read off the monitor's history."""
    try:
        history = list(getattr(monitor, "history", []) or [])
        held = [bool(getattr(getattr(a, "dragon", None), "is_dragon", False)) for a in history]
        rct = [getattr(getattr(a, "state", None), "value", None) == "RCT" for a in history]
        return {"dragon": bool((current.get("dragon") or {}).get("is_dragon")),
                "previous_dragon": held[-2] if len(held) > 1 else False,
                "dk_readings": sum(1 for d, r in zip(held, rct) if d and r)}
    except Exception:                      # a digest never throws
        return {"dragon": False, "previous_dragon": False, "dk_readings": 0}


def monitor_digest(monitor: Any) -> Dict[str, Any]:
    """
    The current assessment in one line's worth of fields.

    `attached` is false rather than the whole key being absent when no monitor
    is running: a strip that simply vanished would read as STABLE to anyone
    glancing at it, and "not being watched" is a different thing from "watched
    and found ordinary".
    """
    if monitor is None:
        return {"attached": False}

    try:
        state = monitor.state()
    except Exception:                      # never let a digest break a run
        return {"attached": False}

    current = state.get("current") or {}
    counts = state.get("counts") or {}
    tick = current.get("tick")
    every = state.get("every") or 0
    kinds = list(current.get("kinds") or [])
    not_evaluated = list(current.get("not_evaluated") or [])
    try:
        operations = _operations(current)
    except Exception:                      # a digest never throws
        operations = {"delivery": None, "backlog": None,
                      "throughput": None, "resources": None}

    return {
        "attached": True,
        "state": current.get("state") or "-",
        "previous": current.get("previous"),
        "status": current.get("status"),
        "tick": tick,
        "severity": current.get("severity"),
        # The kinds of evidence, which is what separates DEVIATING from
        # UNSTABLE: one kind is a bad minute, several at once is the claim.
        "kinds": kinds,
        "evidence": list(current.get("evidence") or [])[:3],
        # A window with nothing in it is not a quiet facility, and the monitor
        # says so rather than reporting STABLE over an empty window.
        "enough_activity": current.get("enough_activity", True),
        # The kinds the quiet rule left unread, and one line a reader can set
        # beside the state: what was seen, and what was not looked at.
        "not_evaluated": not_evaluated,
        "observed": (_observed(kinds, not_evaluated) if tick is not None
                     else "no reading yet"),
        "operations": operations,
        "assessments": state.get("assessments", 0),
        "next_at": (tick + every) if (tick is not None and every) else None,
        "every": every,
        "window": state.get("window"),
        "baseline": state.get("baseline"),
        "counts": counts,
        # The dragon-king test of the current and the previous reading, and
        # how many RCT readings it held in: an RCT reached by the dragon-king
        # test is shown as DK on the page (`stress/states.py`). The monitor
        # records the test on every reading; nothing is computed here.
        **_dragons(monitor, current),
    }


# ---------------------------------------------------------- the indicators
#: The refusal split kept beside `guardrail_events`.
_REFUSAL_SPLIT = ("refusals", "gate_rejections", "intake_rejections",
                  "resource_denials", "message_refusals", "other_refusals")


def _detail_for(name: str, indicators: Dict[str, Any]) -> Dict[str, Any]:
    """The part of the reading's detail that belongs to one indicator."""
    detail = indicators.get("detail") or {}
    counts = indicators.get("counts") or {}
    if name == "communication_failure_rate":
        delivery = dict(detail.get("delivery") or {})
        delivery.pop("late_by", None)            # a list, not a count
        return delivery
    if name == "resource_saturation":
        return dict(detail.get("resources") or {})
    if name == "backlog_growth":
        return dict(detail.get("backlog") or {})
    if name in ("task_completion_rate", "completion_gap"):
        return dict(detail.get("throughput") or {})
    if name == "dependency_graph_divergence":
        return dict(detail.get("structure") or {})
    if name == "tail_deviation":
        return dict(detail.get("tail") or {})
    if name == "activity_synchronization":
        return dict(detail.get("synchronization") or {})
    if name == "guardrail_events":
        return {key: counts[key] for key in _REFUSAL_SPLIT if key in counts}
    if name == "execution_latency":
        return {"p95": detail.get("execution_latency_p95"),
                "waits": len(detail.get("waits") or [])}
    return {}


def _status(evaluable: bool, deviation: str) -> str:
    if not evaluable:
        return "n/a"
    if deviation == "up":
        return "deviating up"
    if deviation == "down":
        return "deviating down"
    return "ok"


def indicator_rows(monitor: Any) -> List[Dict[str, Any]]:
    """
    The indicators of the current reading, in the registry's order: the
    name, its kind (base or derived), the direction a deviation counts in,
    what it measures (the monitor's own sentence), this window's value (None
    when it could not be read), the mean of its baseline (None with fewer
    than four points), its distance from that baseline, whether it could be
    read, which way it deviated, the evidence kind it fed, the counts behind
    it, the assessment tick and a status word. Before the first reading
    every row is not evaluable; [] when no monitor is running or it throws.
    """
    if monitor is None:
        return []
    try:
        from ..dkrmm.indicators import INDICATOR_META, INDICATORS

        current = (monitor.state().get("current") or {})
    except Exception:                      # never let a digest break a run
        return []
    values = current.get("indicators") or {}
    z = current.get("z") or {}
    read = current.get("evaluable") or values.get("evaluable") or {}
    deviation = current.get("deviation") or {}
    in_evidence = current.get("in_evidence") or {}
    baseline = current.get("baseline") or {}
    tick = current.get("tick")
    rows: List[Dict[str, Any]] = []
    for name, about in INDICATORS:
        meta = INDICATOR_META.get(name, {})
        # The original twelve carry no flag in an older reading; they are
        # always readable. With no reading at all nothing is.
        evaluable = bool(read.get(name, bool(current)))
        value = _num(values.get(name)) if evaluable else None
        if evaluable and value is None:
            value = 0.0
        way = str(deviation.get(name) or "none") if evaluable else "none"
        try:
            detail = _detail_for(name, values)
        except Exception:
            detail = {}
        rows.append({
            "name": name, "about": about,
            "kind": meta.get("kind", "base"),
            "direction": meta.get("direction", "up"),
            "value": value,
            "baseline": _num(baseline.get(name)),
            "z": float(z.get(name, 0.0) or 0.0) if evaluable else 0.0,
            "evaluable": evaluable,
            "deviation": way,
            "in_evidence": in_evidence.get(name),
            "detail": detail,
            "tick": tick,
            "status": _status(evaluable, way),
        })
    return rows
