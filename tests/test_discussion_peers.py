"""Who an expert discusses which decision with."""
from post_office.communication.message import MessageType
from post_office.config.settings import LLM_CANDIDATES, config
from post_office.discussion.peers import PEER_MAP, peer_for
from post_office.simulation import build


def test_lookup():
    assert peer_for("SCHEDULING", "choose_robot", "nobody_able") == "RESOURCE"
    assert peer_for("SCHEDULING", "choose_robot", "equally_placed") == "ROUTING"
    assert peer_for("INTAKE", "accept_parcel", "unreadable") is None
    assert peer_for("NOBODY", "x", "y") is None


def test_the_map_has_the_24_rows_of_the_spec():
    assert len(PEER_MAP) == 24


def test_every_row_names_a_real_condition_and_a_peer_it_may_address():
    eco = build(seed=1, config=config("default"))
    try:
        for (owner, kind, condition), peer in PEER_MAP.items():
            assert owner in LLM_CANDIDATES and peer in LLM_CANDIDATES
            assert owner != peer
            names = [c.__name__ for c in eco.agents[owner].triggers._conditions.get(kind, ())]
            assert condition in names, f"{owner}.{kind} has no condition {condition}"
            allowed, why = eco.bus.directory.may_send(owner, peer)
            assert allowed, why
            allowed, why = eco.bus.directory.may_send(peer, owner)
            assert allowed, why
    finally:
        eco.close()


#: The 24 (owner, kind, condition) -> peer rows of the source `discussion/peers.py`,
#: copied here so a change to the carried table is caught.
SOURCE_PEER_MAP = {
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


def test_peer_map_is_the_source_table_verbatim():
    assert dict(PEER_MAP) == SOURCE_PEER_MAP
