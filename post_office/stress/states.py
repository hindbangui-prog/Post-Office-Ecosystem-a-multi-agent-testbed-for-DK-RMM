"""
The four-state view of DK-RMM for the study scenarios.

DK-RMM's five states (STABLE, DEVIATING, UNSTABLE, RCT, RECOVERY) are the
Normal scenario's. The study scenarios (the C2-NEAR conditions and the four
collapse scenarios) present four: STABLE, DEVIATING, UNSTABLE and RCT.
RECOVERY, the monitor's name for a window back at baseline right after an
escalated window, is shown as STABLE in every study view: the live strip,
the study blocks of `/summary`, the measurement's four-state summary, the
results page and the drivers' printed tables. This is a view and nothing
more: the monitor under `post_office/dkrmm/` is untouched, its history, its
record (`dkrmm.json`, `monitor.history`) and the Normal page keep the five
states, and every study artefact that shows the four states keeps the
monitor's own word beside them (`raw_state`, `dkrmm_state`, the raw block).
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

#: The states a study view shows, in the monitor's severity order.
FOUR_STATES = ("STABLE", "DEVIATING", "UNSTABLE", "RCT")

#: The monitor's word that the view folds, and what it is shown as.
FOLDED = {"RECOVERY": "STABLE"}


def four_state(name: Any) -> Any:
    """
    The four-state name of a monitor state: RECOVERY becomes STABLE, the
    other four pass through. None and "" (no reading yet) pass through too,
    so a caller can map a current state that may be absent.
    """
    if name is None:
        return None
    key = str(getattr(name, "value", name))     # the monitor's enum, or its word
    return FOLDED.get(key, key)


def four_state_counts(counts: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    """
    The monitor's `counts` (a state name to how many assessments) with
    RECOVERY folded into STABLE, one entry per state of `FOUR_STATES`, in
    that order. Unknown keys are kept after them, so nothing is lost.
    """
    out: Dict[str, int] = {state: 0 for state in FOUR_STATES}
    for key, value in (counts or {}).items():
        mapped = four_state(key)
        out[mapped] = out.get(mapped, 0) + int(value or 0)
    return out


__all__ = ["FOLDED", "FOUR_STATES", "four_state", "four_state_counts"]
