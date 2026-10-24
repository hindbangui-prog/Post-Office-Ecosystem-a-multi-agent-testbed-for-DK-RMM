"""
Who an expert discusses a decision with.

Keyed by (owner, decision kind, name of the condition that fired). The owner
decides; the peer is the expert holding the knowledge the owner lacks. One
table, so a pairing is changed by editing one line.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

PEER_MAP: Dict[Tuple[str, str, str], str] = {
    ("PLANNER", "release_work", "contention"): "SCHEDULING",
    ("PLANNER", "release_work", "no_robots"): "SCHEDULING",
    ("PLANNER", "release_work", "shelves_filling"): "RESOURCE",
    ("INTAKE", "accept_parcel", "dock_backing_up"): "PLANNER",
    ("INTAKE", "accept_parcel", "no_destination"): "SORTING",
    ("SORTING", "classify_destination", "no_shelf"): "RESOURCE",
    ("SORTING", "classify_destination", "shelves_tight"): "RESOURCE",
    ("SORTING", "classify_destination", "paid_parcel"): "DISPATCH",
    ("SCHEDULING", "choose_robot", "nobody_able"): "RESOURCE",
    ("SCHEDULING", "choose_robot", "paid_errand_thin_robot"): "RESOURCE",
    ("SCHEDULING", "choose_robot", "equally_placed"): "ROUTING",
    ("SCHEDULING", "choose_next_task", "already_late"): "DISPATCH",
    ("SCHEDULING", "choose_next_task", "competing_tasks"): "DISPATCH",
    ("SCHEDULING", "choose_next_task", "promoted_work"): "DISPATCH",
    ("ROUTING", "resolve_block", "low_on_charge"): "RESOURCE",
    ("ROUTING", "resolve_block", "still_blocked"): "SCHEDULING",
    ("ROUTING", "resolve_block", "expensive_detour"): "SCHEDULING",
    ("RESOURCE", "allocate_charge_point", "points_contested"): "SCHEDULING",
    ("RESOURCE", "allocate_charge_point", "laden_rival"): "SCHEDULING",
    ("RESOURCE", "accept_into_storage", "shelves_near_ceiling"): "DISPATCH",
    ("RESOURCE", "accept_into_storage", "more_coming"): "DISPATCH",
    ("DISPATCH", "release_parcel", "past_the_promise"): "SCHEDULING",
    ("DISPATCH", "release_parcel", "promise_before_departure"): "SCHEDULING",
    ("DISPATCH", "release_parcel", "van_too_small"): "SCHEDULING",
}


def peer_for(owner: str, kind: str, condition: str) -> Optional[str]:
    """The expert `owner` discusses this decision with, or None to ask alone."""
    return PEER_MAP.get((owner, kind, condition))
