"""
Stress experiments: collapse-only runs, isolated from the Normal scenario.

This package holds the experiment definitions, the scheduled faults,
the per-tick measurement and the collapse criterion for the experiments that
put the facility under sustained pressure. Nothing in `post_office` imports
it at load; a driver under `tools/` assembles a run from it beside an
ordinary ecosystem, the way DK-RMM is attached beside one, and the live app
(`config/settings.py::config`, `api/runner.py`) reaches it lazily for the
`c2near-*` presets only.

Rules of the package:

- it never writes under `results/normal/`
- it has no removal or restoration code path: a fault, once applied, holds
  to the end of the run
- it adds no perturbation keys (`perturbations`, `interceptors`) to any
  configuration; the ecosystem refuses them

The first experiment is `C2-NEAR-SYSTEM-OVERRIDE`
(`c2near_system_override.py`), with its System Override campaign in
`system_override.py` and the attack-outcome join in `analysis.py`. Those two
are imported by name (`post_office.stress.system_override`,
`post_office.stress.analysis`), not from here: the campaign is built by
`crew/interception.py::from_config` lazily, only for a configuration that
carries the `c2near_system_override` key.
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
from .operational import OperationalStress, ScheduledFaults

__all__ = [
    "ARRIVAL_FACTOR", "CHARGING_CUT_AT", "CHARGING_KEPT", "CHARGING_REMOVED",
    "COLLAPSE", "CONDITIONS", "Collector", "Condition", "EXPERIMENT", "LABEL",
    "OperationalStress", "RESULTS_DIR", "ROUTE_CLOSURES", "RUN_TICKS", "SEEDS",
    "STRESS_START", "ScheduledFaults", "TARGETS", "classify", "condition", "config",
    "definition", "fingerprint", "schedule",
]
