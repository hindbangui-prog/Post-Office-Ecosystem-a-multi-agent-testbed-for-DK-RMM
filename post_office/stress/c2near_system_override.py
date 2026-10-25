"""
C2-NEAR-SYSTEM-OVERRIDE: the experiment, stated once.

A collapse-only experiment on the Normal facility: exact Normal for the first
400 ticks, then a sustained workload surge, two van routes closed, three of
the four charge points removed, and (in condition C2) a System Override
campaign against the three targeted experts. Nothing is ever restored.

Three conditions, matched by seed:

    N    control: the Normal facility, no stressor of any kind
    C0   the operational stressors only
    C2   the System Override campaign plus the operational stressors

This module is the definition and nothing else: constants, the schedule, the
configuration each condition is built with, and a fingerprint over all of it
so a results directory can say which definition produced it. The stressors
live in `operational.py`, the campaign in `system_override.py`, the
measurement in `measure.py` and the collapse criterion in `collapse.py`.

Design: `docs/superpowers/specs/2026-10-11-c2-near-system-override-design.md`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from ..config.settings import DEFAULT_CONFIG, normal_config
from .collapse import COLLAPSE
from .system_override import corpus_fingerprint

# ------------------------------------------------------------------ identity
EXPERIMENT = "C2-NEAR-SYSTEM-OVERRIDE"
LABEL = "C2-NEAR"
#: Results live here and nowhere else. `results/normal/` is never touched.
RESULTS_DIR = "results/c2_near_system_override"

# ------------------------------------------------------------------- the run
RUN_TICKS = 2800
SEEDS: Tuple[int, ...] = (11, 12, 13, 14, 15)

# -------------------------------------------------------------- the schedule
#: The first tick of the stress. Everything before it is exact Normal.
STRESS_START = 400
#: Arrivals: the configured Normal interval divided by this, from STRESS_START.
ARRIVAL_FACTOR = 3.0
#: Van routes closed, and when. The van is taken off the bay and no
#: replacement is ever brought up; parcels for the route keep arriving.
ROUTE_CLOSURES: Tuple[Tuple[str, int], ...] = (("LIBEREC", 500), ("HRADEC", 700))
#: Charge points removed from `env.stations`, and when. CS-1 remains.
CHARGING_CUT_AT = 800
CHARGING_REMOVED: Tuple[str, ...] = ("CS-2", "CS-3", "CS-4")
CHARGING_KEPT: Tuple[str, ...] = ("CS-1",)
#: The experts the System Override campaign addresses (condition C2 only).
TARGETS: Tuple[str, ...] = ("SCHEDULING", "SORTING", "ROUTING")

#: Fault ids, as they appear in `stress_fault_activated` events.
SO_CAMPAIGN = "SO-CAMPAIGN"
OP_SURGE = "OP-SURGE"
OP_ROUTE = ("OP-ROUTE-1", "OP-ROUTE-2")
OP_CHARGE = "OP-CHARGE"

#: Mechanism names, one per kind of fault.
ATTACK = "attack"
ARRIVAL_SURGE = "arrival_surge"
ROUTE_CLOSED = "route_closed"
CHARGE_LOSS = "charge_loss"

#: What the campaign does after its last message: the final one repeats.
EXHAUSTION = "repeat_final"
#: The delivery policy, in one line, as the activation record states it.
DELIVERY = ("one message per eligible LLM consultation, corpus order, "
            f"{EXHAUSTION}")


# ---------------------------------------------------------------- conditions
@dataclass(frozen=True)
class Condition:
    """One arm of the experiment."""

    id: str
    label: str
    #: Whether the System Override campaign runs.
    override: bool
    #: Whether the operational stressors (surge, route closures, charge
    #: loss) are applied.
    operational: bool


CONDITIONS: Dict[str, Condition] = {
    "N": Condition("N", "control: Normal, no stressor", override=False,
                   operational=False),
    "C0": Condition("C0", "operational stressors only", override=False,
                    operational=True),
    "C2": Condition("C2", "System Override campaign plus operational stressors",
                    override=True, operational=True),
}


def condition(key: str) -> Condition:
    """The condition named `key` (`N`, `C0`, `C2`); a ValueError otherwise."""
    cond = CONDITIONS.get(str(key).upper())
    if cond is None:
        raise ValueError(f"condition is one of {sorted(CONDITIONS)}, not {key!r}")
    return cond


# ------------------------------------------------------------- configuration
def config(cond: Condition) -> Dict[str, Any]:
    """
    The configuration the ecosystem is built with for `cond`.

    For N and C0 this is `normal_config()` unchanged: the control and the
    operational arm are the Normal facility, and the operational stressors
    are applied from outside the ecosystem by `OperationalStress`, never
    through the configuration. For C2 it is `normal_config()` plus the
    `c2near_system_override` key that the interception layer reads
    (`crew/interception.py::from_config`). No `perturbations` or `interceptors` entry is ever added: the
    ecosystem refuses those, and the `interceptors=[]` of `normal_config()`
    stays exactly as it is.
    """
    cfg = normal_config()
    if cond.override:
        cfg["c2near_system_override"] = {
            "targets": list(TARGETS),
            "start_tick": STRESS_START,
            "exhaustion": EXHAUSTION,
        }
    # N and C0: `cfg == normal_config()`, byte for byte.
    return cfg


# ----------------------------------------------------------------- schedule
def schedule(cond: Condition) -> List[Dict[str, Any]]:
    """
    The faults applied in `cond`, one row each, sorted by tick.

    Each row is `{tick, mechanism, fault_id, detail}`. The control condition
    has an empty schedule. The attack row is there for C2 only; the
    operational rows for C0 and C2. The attack row has no operational
    effect: it is the campaign's arming record (the campaign itself is the
    interception layer's agent hooks, installed when the ecosystem is built),
    fired as a `stress_fault_activated` event at its tick like every other
    row so the run's log says when and how the attack was armed.
    """
    rows: List[Dict[str, Any]] = []
    if cond.override:
        rows.append({
            "tick": STRESS_START, "mechanism": ATTACK, "fault_id": SO_CAMPAIGN,
            "detail": {"targets": list(TARGETS), "start_tick": STRESS_START,
                       "exhaustion": EXHAUSTION, "delivery": DELIVERY,
                       "corpus_fingerprint": corpus_fingerprint()},
        })
    if cond.operational:
        baseline = float(DEFAULT_CONFIG["arrival_interval"])
        rows.append({
            "tick": STRESS_START, "mechanism": ARRIVAL_SURGE, "fault_id": OP_SURGE,
            "detail": {"interval_before": baseline, "factor": ARRIVAL_FACTOR,
                       "interval_after": baseline / ARRIVAL_FACTOR},
        })
        for fault_id, (route, tick) in zip(OP_ROUTE, ROUTE_CLOSURES):
            rows.append({
                "tick": tick, "mechanism": ROUTE_CLOSED, "fault_id": fault_id,
                "detail": {"route": route, "replacement": "none"},
            })
        rows.append({
            "tick": CHARGING_CUT_AT, "mechanism": CHARGE_LOSS, "fault_id": OP_CHARGE,
            "detail": {"removed": list(CHARGING_REMOVED), "kept": list(CHARGING_KEPT)},
        })
    # Stable sort: rows that share a tick keep the order above (attack first).
    rows.sort(key=lambda row: row["tick"])
    return rows


# --------------------------------------------------------------- definition
def definition(cond: Condition) -> Dict[str, Any]:
    """
    Everything a run of `cond` is defined by, as one JSON-able dictionary.

    Written into every run directory as `definition.json`, and hashed by
    `fingerprint`, so a result can be matched to the definition that produced
    it rather than to whatever the code says today.
    """
    out: Dict[str, Any] = {
        "experiment": EXPERIMENT,
        "label": LABEL,
        "condition": {"id": cond.id, "label": cond.label,
                      "override": cond.override, "operational": cond.operational},
        "run_ticks": RUN_TICKS,
        "seeds": list(SEEDS),
        "stress_start": STRESS_START,
        "arrival": {"baseline_interval": float(DEFAULT_CONFIG["arrival_interval"]),
                    "factor": ARRIVAL_FACTOR if cond.operational else 1.0},
        "route_closures": [{"route": r, "tick": t} for r, t in ROUTE_CLOSURES]
        if cond.operational else [],
        "charging": {"cut_at": CHARGING_CUT_AT, "removed": list(CHARGING_REMOVED),
                     "kept": list(CHARGING_KEPT)} if cond.operational else None,
        "targets": list(TARGETS) if cond.override else [],
        "schedule": schedule(cond),
        "collapse": dict(COLLAPSE),
        "config": config(cond),
    }
    if cond.override:
        out["corpus_fingerprint"] = corpus_fingerprint()
    return out


def fingerprint(cond: Condition) -> str:
    """sha256 over the canonical JSON of `definition(cond)`."""
    text = json.dumps(definition(cond), sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
