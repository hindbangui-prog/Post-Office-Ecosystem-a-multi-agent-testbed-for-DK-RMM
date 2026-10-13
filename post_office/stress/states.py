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

The live page (2026-10-13) shows one more word, on every scenario: DK, an
RCT reading whose precursor was the dragon-king test (the reading's
`dragon.is_dragon`, which the monitor already records and its RCT rule
already reads). An RCT reached by critical slowing down alone stays RCT. So
a study run on the page reads STABLE, DEVIATING, UNSTABLE, RCT or DK
(`STUDY_STATES`, `study_state`), and Normal its five states with RCT split
the same way. Like the fold, it is a view: the monitor's state is RCT for
both, and the measurement, the results page and the drivers' tables keep
the four states.
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


#: The states a study run shows on the live page: the four, then DK.
DK_STATE = "DK"
STUDY_STATES = FOUR_STATES + (DK_STATE,)


def dk_state(name: Any, dragon: Any) -> Any:
    """
    DK for an RCT reading whose dragon-king test held, the word unchanged
    otherwise (a reading that is not RCT is never DK, whatever `dragon`).
    """
    if name is None:
        return None
    key = str(getattr(name, "value", name))
    return DK_STATE if key == "RCT" and bool(dragon) else key


def study_state(name: Any, dragon: Any = False) -> Any:
    """The live page's word for a study reading: four-state, then DK."""
    return dk_state(four_state(name), dragon)


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


def study_state_counts(words: Any) -> Dict[str, int]:
    """
    How many readings of each `STUDY_STATES` word, in that order, from the
    study words of a sequence (unknown words kept after them).
    """
    out: Dict[str, int] = {state: 0 for state in STUDY_STATES}
    for word in words or ():
        out[str(word)] = out.get(str(word), 0) + 1
    return out


__all__ = ["DK_STATE", "FOLDED", "FOUR_STATES", "STUDY_STATES", "dk_state",
           "four_state", "four_state_counts", "study_state", "study_state_counts"]
