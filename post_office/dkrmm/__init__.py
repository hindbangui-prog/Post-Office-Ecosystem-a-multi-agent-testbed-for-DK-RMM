"""
DK-RMM: the Dragon-King Runtime Monitoring Model.

An independent observer of collective runtime behaviour. It watches the event
stream, computes twelve behavioural indicators against their own moving
baselines, looks for the statistics of a system approaching a critical point,
and names the condition the ecosystem is in -- for a person to confirm or
reject, never for the system to act on by itself.

    from post_office.dkrmm import DKRMM

    monitor = DKRMM(eco).attach()
    for _ in range(600):
        eco.step()
        monitor.tick()
    monitor.state()

Nothing in `post_office` imports this package, and nothing in this package
writes to anything in `post_office`. That is the point of it.
"""

from .indicators import (INDICATOR_NAMES, INDICATORS, BehaviouralIndicators,
                         compute_indicators)
from .monitor import DKRMM, Assessment
from .record import (build_record, compare_records, series_of, states_of,
                     transitions_of, write_record)
from .signals import DragonKing, Precursors, dragon_king, precursors, zscore
from .states import DiscoveryStatus, OperationalState

__all__ = [
    "DKRMM", "Assessment", "BehaviouralIndicators", "DiscoveryStatus",
    "DragonKing", "INDICATORS", "INDICATOR_NAMES", "OperationalState",
    "Precursors", "build_record", "compare_records", "compute_indicators",
    "dragon_king", "precursors", "series_of", "states_of", "transitions_of",
    "write_record", "zscore",
]
