"""
Short answers for the top of the app: what the monitor makes of the run as it
stands, and the twelve indicators behind that reading.

Digests and not summaries. The full readings stay at `/dkrmm/state` and
`/dkrmm/series`; these exist so a strip at the top of the window can say the
state without the shell fetching more documents every second, and so the
DK-RMM pane can label each indicator with the monitor's own description.

Adapted from the source `post_office/api/digest.py`: `monitor_digest` is kept
as it was; the second digest, which read the source's disturbance controller,
is not part of this prototype.
"""

from __future__ import annotations

from typing import Any, Dict, List


# --------------------------------------------------------------- the monitor
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

    return {
        "attached": True,
        "state": current.get("state") or "-",
        "previous": current.get("previous"),
        "status": current.get("status"),
        "tick": tick,
        "severity": current.get("severity"),
        # The kinds of evidence, which is what separates DEVIATING from
        # UNSTABLE: one kind is a bad minute, several at once is the claim.
        "kinds": list(current.get("kinds") or []),
        "evidence": list(current.get("evidence") or [])[:3],
        # A window with nothing in it is not a quiet facility, and the monitor
        # says so rather than reporting STABLE over an empty window.
        "enough_activity": current.get("enough_activity", True),
        "assessments": state.get("assessments", 0),
        "next_at": (tick + every) if (tick is not None and every) else None,
        "every": every,
        "window": state.get("window"),
        "baseline": state.get("baseline"),
        "counts": counts,
    }


# ------------------------------------------------------------ the twelve
def indicator_rows(monitor: Any) -> List[Dict[str, Any]]:
    """
    The twelve indicators of the current reading, in the monitor's order: the
    name, what it measures (the monitor's own sentence), this window's value
    and its distance from the baseline. Zeros before the first reading, and
    [] when no monitor is running or it throws.
    """
    if monitor is None:
        return []
    try:
        from ..dkrmm.indicators import INDICATORS

        current = (monitor.state().get("current") or {})
    except Exception:                      # never let a digest break a run
        return []
    values = current.get("indicators") or {}
    z = current.get("z") or {}
    return [{"name": name, "about": about,
             "value": float(values.get(name, 0.0) or 0.0),
             "z": float(z.get(name, 0.0) or 0.0)}
            for name, about in INDICATORS]
