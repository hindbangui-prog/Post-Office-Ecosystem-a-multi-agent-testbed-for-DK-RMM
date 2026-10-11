"""
Stress experiments: collapse-only runs, isolated from the Normal scenario.

This package holds the experiment definitions, the operational stressors,
the per-tick measurement and the collapse criterion for the experiments that
put the facility under sustained pressure. Nothing in `post_office` imports
it; a driver under `tools/` assembles a run from it beside an ordinary
ecosystem, the way DK-RMM is attached beside one.

Rules of the package:

- it never writes under `results/normal/`
- it has no removal or restoration code path: a fault, once applied, holds
  to the end of the run
- it adds no perturbation keys (`perturbations`, `interceptors`) to any
  configuration; the ecosystem refuses them

The first experiment is `C2-NEAR-SYSTEM-OVERRIDE`
(`c2near_system_override.py`), with its System Override campaign in
`system_override.py` (a later task).
"""

from .c2near_system_override import (ARRIVAL_FACTOR, CHARGING_CUT_AT,
                                     CHARGING_KEPT, CHARGING_REMOVED,
                                     CONDITIONS, EXPERIMENT, LABEL,
                                     RESULTS_DIR, ROUTE_CLOSURES, RUN_TICKS,
                                     SEEDS, STRESS_START, TARGETS, Condition,
                                     condition, config, definition,
                                     fingerprint, schedule)
from .collapse import COLLAPSE, classify
from .measure import Collector
from .operational import OperationalStress

__all__ = [
    "ARRIVAL_FACTOR", "CHARGING_CUT_AT", "CHARGING_KEPT", "CHARGING_REMOVED",
    "COLLAPSE", "CONDITIONS", "Collector", "Condition", "EXPERIMENT", "LABEL",
    "OperationalStress", "RESULTS_DIR", "ROUTE_CLOSURES", "RUN_TICKS", "SEEDS",
    "STRESS_START", "TARGETS", "classify", "condition", "config", "definition",
    "fingerprint", "schedule",
]
