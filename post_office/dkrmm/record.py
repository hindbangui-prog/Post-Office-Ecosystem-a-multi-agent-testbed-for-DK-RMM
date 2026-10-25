"""
One run, as the DK-RMM analysis needs to read it.

The monitor already keeps everything: `DKRMM.history` is every assessment it
made, and each one carries its indicators, its z-scores against the indicator's
own baseline, the evidence kinds that fired, the severity it computed, and the
precursor and dragon-king readings of the severity series. Nothing here
recomputes any of that, and nothing here changes a definition. This module
transposes it -- assessments are a list of windows, and an analysis wants a
series per indicator -- and writes it out beside the uptake record and the
event log, so that the three levels of the experiment can be read together:

    level 1   did the stimulus move an agent          (uptake)
    level 2   did the facility respond                (events, propagation)
    level 3   did the monitor see it, and as what     (this)

**The timings are the point.** A Dragon-King reading is a claim about order:
that precursor structure appeared *before* the extreme collective episode, not
with it and not after. So the record carries a `timeline` of firsts -- when the
perturbation started, when a decision first changed, when an indicator first
went off baseline, when several kinds first fired together, when the state
first escalated -- and those are timestamps to be compared, not a verdict. A
single extreme value is not a Dragon King; an extreme value with nothing before
it is a spike.

Nothing here decides whether a run contains a Dragon King. It writes down what
would have to be true.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Sequence

from .indicators import INDICATOR_NAMES
from .states import ESCALATED, OperationalState

#: The schema version of the artifact, so an analysis written against one
#: shape can say plainly that it is reading another.
FORMAT = 1


def _first(rows: Sequence[Dict[str, Any]], predicate) -> Optional[int]:
    """The tick of the first row that satisfies `predicate`, or None."""
    for row in rows:
        try:
            if predicate(row):
                return int(row["tick"])
        except Exception:
            continue
    return None


def series_of(history: Sequence[Any]) -> Dict[str, Any]:
    """
    The assessment history, transposed into series.

    `ticks` is the spine: every other list here is the same length and in the
    same order, so a reader can zip them without matching on anything.
    """
    rows = [a.as_dict() if hasattr(a, "as_dict") else dict(a) for a in history]
    ticks = [int(r["tick"]) for r in rows]

    indicator_series: Dict[str, List[float]] = {
        name: [float(r["indicators"].get(name, 0.0)) for r in rows]
        for name in INDICATOR_NAMES}
    # The same twelve against their own baselines. This is what "off baseline"
    # is read from, and it is not recoverable from the raw values alone because
    # the baseline moves.
    z_series: Dict[str, List[float]] = {
        name: [float(r["z"].get(name, 0.0)) for r in rows]
        for name in INDICATOR_NAMES}
    # The raw counts behind the rates, kept because "0.04 refusals a tick" and
    # "two refusals" answer different questions.
    count_keys: List[str] = sorted(
        {k for r in rows for k in (r["indicators"].get("counts") or {})})
    count_series: Dict[str, List[int]] = {
        key: [int((r["indicators"].get("counts") or {}).get(key, 0))
              for r in rows]
        for key in count_keys}

    return {
        "ticks": ticks,
        "indicator_series": indicator_series,
        "z_series": z_series,
        "count_series": count_series,
        "severity_series": [float(r["severity"]) for r in rows],
        "events_series": [int(r["indicators"].get("events", 0)) for r in rows],
        "enough_activity": [bool(r["enough_activity"]) for r in rows],
    }


def states_of(history: Sequence[Any]) -> List[Dict[str, Any]]:
    """One row per assessment: what the monitor said, and what it said it on."""
    out = []
    for assessment in history:
        row = assessment.as_dict() if hasattr(assessment, "as_dict") \
            else dict(assessment)
        out.append({
            "tick": int(row["tick"]),
            "state": row["state"],
            "previous": row["previous"],
            "kinds": list(row["kinds"]),
            "severity": row["severity"],
            "enough_activity": row["enough_activity"],
            "evidence": list(row["evidence"]),
            "persistence": int(row.get("persistence", 0) or 0),
            "precursors": {
                "rising": int(row["precursors"].get("rising", 0)),
                "slowing_down": bool(row["precursors"].get("slowing_down")),
                "variance_rising": bool(
                    row["precursors"].get("variance_rising")),
                "autocorrelation_rising": bool(
                    row["precursors"].get("autocorrelation_rising")),
                "skewness_rising": bool(
                    row["precursors"].get("skewness_rising")),
                "enough": bool(row["precursors"].get("enough")),
            },
            "dragon": {
                "is_dragon": bool(row["dragon"].get("is_dragon")),
                "ratio": row["dragon"].get("ratio", 0.0),
                "observed": row["dragon"].get("observed", 0.0),
                "expected": row["dragon"].get("expected", 0.0),
                "fit_quality": row["dragon"].get("fit_quality", 0.0),
                "enough": bool(row["dragon"].get("enough")),
            },
        })
    return out


def transitions_of(states: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Every change of operational state, with what the monitor had at the time.

    Called transitions rather than RCT events because most of them are not
    RCTs: the list holds each move between states, and `to` says which. An
    analysis that wants only the candidate RCTs filters on that, and can still
    see what led there -- which is the part that matters.
    """
    out: List[Dict[str, Any]] = []
    previous: Optional[str] = None
    for row in states:
        state = row["state"]
        if previous is not None and state != previous:
            out.append({
                "tick": row["tick"],
                "from": previous,
                "to": state,
                "escalation": state in {s.value for s in ESCALATED}
                and previous not in {s.value for s in ESCALATED},
                "kinds": list(row["kinds"]),
                "severity": row["severity"],
                "evidence": list(row["evidence"]),
                "precursors_rising": row["precursors"]["rising"],
                "slowing_down": row["precursors"]["slowing_down"],
                "dragon": row["dragon"]["is_dragon"],
            })
        previous = state
    return out


def timeline_of(states: Sequence[Dict[str, Any]],
                series: Dict[str, Any],
                uptake: Optional[Dict[str, Any]] = None,
                perturbation: Optional[Dict[str, Any]] = None,
                changes: Optional[Sequence[Dict[str, Any]]] = None,
                deviation_z: float = 2.0) -> Dict[str, Any]:
    """
    The firsts, in tick order, for reading the sequence rather than the levels.

    Every entry is a tick or None. None means "not observed in this run", not
    "did not happen": a window that never escalated has no escalation tick, and
    an analysis must not read the absence as a negative finding about the
    facility when it may be a negative finding about the window length.
    """
    ticks: List[int] = series["ticks"]
    z_series: Dict[str, List[float]] = series["z_series"]

    # The first window in which any indicator stood more than `deviation_z`
    # above its own baseline, and which indicator it was.
    first_deviation: Optional[int] = None
    first_deviation_by: List[str] = []
    first_multi: Optional[int] = None
    for index, tick in enumerate(ticks):
        hot = [name for name in INDICATOR_NAMES
               if z_series[name][index] >= deviation_z]
        if hot and first_deviation is None:
            first_deviation = int(tick)
            first_deviation_by = hot
        # Several indicators moving together is the coordination claim, and it
        # is deliberately counted over indicators rather than over evidence
        # kinds: the kinds are already grouped to stop correlated indicators
        # being counted twice, which is right for the state machine and wrong
        # for asking whether movement is coordinated.
        if len(hot) >= 2 and first_multi is None:
            first_multi = int(tick)

    escalated = {s.value for s in ESCALATED}
    changes = list(changes or [])

    return {
        "perturbation_start": (int(perturbation.get("start_tick"))
                               if perturbation and
                               perturbation.get("start_tick") is not None
                               else None),
        "perturbation_end": (int(perturbation.get("end_tick"))
                             if perturbation and
                             perturbation.get("end_tick") is not None
                             else None),
        "first_changed_decision": (int(changes[0]["tick"])
                                   if changes and "tick" in changes[0]
                                   else None),
        "last_changed_decision": (int(changes[-1]["tick"])
                                  if changes and "tick" in changes[-1]
                                  else None),
        "first_indicator_deviation": first_deviation,
        "first_indicator_deviation_by": first_deviation_by,
        "first_multi_indicator_deviation": first_multi,
        "first_evidence_kind": _first(states, lambda r: bool(r["kinds"])),
        "first_escalation": _first(states, lambda r: r["state"] in escalated),
        "first_unstable": _first(
            states, lambda r: r["state"] == OperationalState.UNSTABLE.value),
        "first_rct": _first(
            states, lambda r: r["state"] == OperationalState.RCT.value),
        "first_slowing_down": _first(
            states, lambda r: r["precursors"]["slowing_down"]),
        "first_dragon_flag": _first(states, lambda r: r["dragon"]["is_dragon"]),
        "peak_severity_tick": (
            int(ticks[series["severity_series"].index(
                max(series["severity_series"]))])
            if series["severity_series"] else None),
        "peak_severity": (max(series["severity_series"])
                          if series["severity_series"] else None),
        "recovery": _first(
            states, lambda r: r["state"] == OperationalState.RECOVERY.value),
    }


def build_record(run_id: str, monitor, *, scenario: str = "",
                 seed: Optional[int] = None, target: str = "",
                 attack: Optional[Dict[str, Any]] = None,
                 uptake: Optional[Dict[str, Any]] = None,
                 perturbation: Optional[Dict[str, Any]] = None,
                 changes: Optional[Sequence[Dict[str, Any]]] = None,
                 propagation: Optional[Dict[str, Any]] = None,
                 config: Optional[Dict[str, Any]] = None,
                 control: bool = False) -> Dict[str, Any]:
    """
    Assemble the artifact. Reads; computes nothing the monitor has not.

    `control` marks a run of the same configuration with no perturbation
    installed. It is the comparison every level-2 and level-3 claim needs, and
    it is flagged in the record rather than inferred from an empty uptake,
    because "no perturbation" and "a perturbation that did nothing" are
    different runs and must not be read as one.
    """
    history = list(getattr(monitor, "history", []) or [])
    series = series_of(history)
    states = states_of(history)
    return {
        "format": FORMAT,
        "run_id": run_id,
        "scenario": scenario,
        "seed": seed,
        "target": target,
        "control": bool(control),
        "attack": dict(attack or {}),
        "config": dict(config or {}),
        "monitor": {
            "every": getattr(monitor, "every", None),
            "window": getattr(monitor, "window", None),
            "baseline": getattr(monitor, "baseline", None),
            "assessments": len(history),
        },
        "uptake": dict(uptake) if uptake else None,
        **series,
        "state_series": states,
        "transitions": transitions_of(states),
        # The subset an RCT analysis asks for first. Kept as its own key
        # because the schema names it, and derived from `transitions` so the
        # two can never disagree.
        "rct_events": [t for t in transitions_of(states)
                       if t["to"] == OperationalState.RCT.value],
        "timeline": timeline_of(states, series, uptake=uptake,
                                perturbation=perturbation, changes=changes),
        "changed_decisions": [dict(c) for c in (changes or [])],
        "propagation": dict(propagation or {}),
    }


def compare_records(perturbed: Dict[str, Any],
                    control: Dict[str, Any]) -> Dict[str, Any]:
    """
    Two runs of one configuration, read against each other.

    This exists because the firsts in `timeline` are absolute, and a facility
    is not quiet before a perturbation arrives: in validation both a perturbed
    run and its matched control reached DEVIATING at tick 81 and UNSTABLE at
    101, long before anything was injected, purely from the load the facility
    starts under. Read on its own, either run looks like it went unstable. Read
    against each other, the difference is elsewhere entirely.

    So the quantity that carries a claim is not "when did this run first
    deviate" but "when did the two runs stop agreeing". `first_divergence` is
    that tick. Everything else here is levels; that one is the comparison.

    Both records must come from the same configuration and seed. That is not
    checked, because a caller comparing two different configurations has made a
    decision this function has no business overriding -- but the mismatch is
    reported so it cannot pass unnoticed.
    """
    mismatch = [key for key in ("seed", "target")
                if perturbed.get(key) != control.get(key)]

    a_states = {int(r["tick"]): r for r in perturbed["state_series"]}
    b_states = {int(r["tick"]): r for r in control["state_series"]}
    shared = sorted(set(a_states) & set(b_states))

    first_divergence: Optional[int] = None
    divergences: List[Dict[str, Any]] = []
    for tick in shared:
        left, right = a_states[tick], b_states[tick]
        if left["state"] != right["state"]:
            if first_divergence is None:
                first_divergence = tick
            divergences.append({"tick": tick, "perturbed": left["state"],
                                "control": right["state"],
                                "perturbed_kinds": list(left["kinds"]),
                                "control_kinds": list(right["kinds"])})

    def sev(record):
        return list(record.get("severity_series") or [])

    a_sev, b_sev = sev(perturbed), sev(control)
    span = min(len(a_sev), len(b_sev))
    # The first window where the perturbed run's composite severity stands a
    # clear margin above the control's. A margin rather than any difference,
    # because two runs of a stochastic facility differ everywhere by a little.
    first_severity_gap: Optional[int] = None
    for index in range(span):
        if a_sev[index] - b_sev[index] >= 0.5:
            first_severity_gap = int(perturbed["ticks"][index])
            break

    states_seen = {r["state"] for r in perturbed["state_series"]}
    control_seen = {r["state"] for r in control["state_series"]}

    return {
        "configuration_mismatch": mismatch,
        "windows_compared": len(shared),
        "first_divergence": first_divergence,
        "divergent_windows": len(divergences),
        "divergences": divergences[:40],
        "first_severity_gap": first_severity_gap,
        "severity": {
            "perturbed_peak": max(a_sev) if a_sev else None,
            "control_peak": max(b_sev) if b_sev else None,
            "perturbed_mean": (sum(a_sev) / len(a_sev)) if a_sev else None,
            "control_mean": (sum(b_sev) / len(b_sev)) if b_sev else None,
        },
        # States the perturbed run reached and the control did not. This is the
        # only sense in which "it went unstable" is a finding: a state the
        # matched control also reached is a property of the facility, not of
        # the perturbation.
        "states_only_in_perturbed": sorted(states_seen - control_seen),
        "states_only_in_control": sorted(control_seen - states_seen),
        "rct": {
            "perturbed": perturbed["timeline"].get("first_rct"),
            "control": control["timeline"].get("first_rct"),
        },
        "slowing_down": {
            "perturbed": perturbed["timeline"].get("first_slowing_down"),
            "control": control["timeline"].get("first_slowing_down"),
        },
        "propagation": {
            "perturbed_cascades": (perturbed.get("propagation") or {}).get("count"),
            "control_cascades": (control.get("propagation") or {}).get("count"),
            "perturbed_deepest": (perturbed.get("propagation") or {}).get("deepest"),
            "control_deepest": (control.get("propagation") or {}).get("deepest"),
        },
    }


def write_record(record: Dict[str, Any], path: str) -> str:
    """Write the artifact, making the directory if it is not there."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, default=str)
    return path
