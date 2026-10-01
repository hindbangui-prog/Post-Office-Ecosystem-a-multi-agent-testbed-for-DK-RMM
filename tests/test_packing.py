"""
The two steps at the back door, and the object the model was missing.

A real facility does not hand loose parcels to a driver. It packs them into a
receptacle -- a bag, a tray, a container -- holding items that share an origin,
a destination and a mail class, and hands the receptacle over. That grouping is
the whole reason the sort exists: the van does not care which parcel is which,
it cares that the bag for Brno is on it.

    packing and bagging   parcels into a receptacle by destination and class
    handover              the sealed receptacle onto the outbound van

Before this the gate loaded parcels onto a van one at a time and nothing was
ever grouped, so "batching" had no representation in the model at all. What is
kept from the old arrangement is the judgement: whether a parcel goes now or
waits for a fuller bag is still DISPATCH's call, and it is still the only part
of the back door worth spending a model call on. Choosing *which* bag a parcel
belongs in is arithmetic, and that belongs to a clerk.
"""

from __future__ import annotations

import pytest

from post_office.environment import ParcelStatus
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=1, run_id="packing")
    made.start()
    for _ in range(1200):
        made.step()
    yield made
    made.close()


# ------------------------------------------------------------- the receptacle
def test_a_receptacle_holds_one_destination_and_one_mail_class():
    """
    What makes a bag a bag. Mixing two destinations into one receptacle is the
    one mistake this step exists to prevent -- the bag is sorted so nothing
    downstream has to sort it again.
    """
    from post_office.environment.receptacles import Receptacle

    bag = Receptacle(receptacle_id="B-0001", route="BRNO", mail_class="NORMAL",
                     capacity=6)
    assert bag.accepts("BRNO", "NORMAL")
    assert not bag.accepts("PLZEN", "NORMAL"), "a bag is for one destination"
    assert not bag.accepts("BRNO", "URGENT"), "a bag is for one mail class"

    assert bag.put("P-0001", 1)
    assert bag.put("P-0002", 3)
    assert bag.units == 4 and bag.count == 2
    assert not bag.put("P-0003", 3), "a full bag takes no more"
    assert bag.put("P-0004", 2), "and one that still has room does"
    assert bag.is_full


def test_a_sealed_receptacle_is_closed_to_anything_else():
    """
    Sealing is the moment the bag stops being a work-in-progress. A parcel put
    into a bag that has already gone to the van is a parcel nobody can find.
    """
    from post_office.environment.receptacles import Receptacle

    bag = Receptacle(receptacle_id="B-0002", route="BRNO", mail_class="NORMAL",
                     capacity=6)
    bag.put("P-0001", 1)
    bag.seal(tick=10)
    assert bag.sealed_at == 10
    assert not bag.accepts("BRNO", "NORMAL")
    assert not bag.put("P-0002", 1)


def test_the_bag_room_keeps_one_open_bag_per_destination_and_class():
    """
    Where a parcel goes is decided by what is written on it, so two parcels for
    the same place and the same service land in the same bag and a third for
    somewhere else starts a new one.
    """
    from post_office.environment.receptacles import BagRoom

    room = BagRoom(capacity=6)
    first = room.open_bag("BRNO", "NORMAL")
    assert room.open_bag("BRNO", "NORMAL") is first
    assert room.open_bag("BRNO", "URGENT") is not first
    assert room.open_bag("PLZEN", "NORMAL") is not first

    # Once sealed, the next parcel for that pair starts a fresh bag.
    room.seal(first, tick=5)
    replacement = room.open_bag("BRNO", "NORMAL")
    assert replacement is not first
    assert first in room.sealed


# ---------------------------------------------------------------- the clerk
def test_the_packing_clerk_says_which_bag_and_decides_nothing(eco):
    """
    SUB-PACKING is clerical, like the other two clerks at the gates. It reads
    the parcel, names the bag, and reports how full it is. Whether the parcel
    goes now is not its business.
    """
    from post_office.config.settings import LLM_CANDIDATES

    assert "SUB-PACKING" in eco.subagents
    assert eco.directory.parent_of("SUB-PACKING") == "DISPATCH"
    assert "SUB-PACKING" not in LLM_CANDIDATES, \
        "choosing a bag by destination and class is arithmetic"


def test_every_parcel_that_leaves_left_in_a_bag(eco):
    """
    The handover is the bag, not the parcel. Anything on a van got there by
    being packed into a receptacle first, and the receptacle says where it went
    and what class it was.
    """
    loaded = [p for p in eco.env.all_parcels().values() if p.loaded_on]
    assert loaded, "nothing was ever loaded"
    for parcel in loaded:
        packed = [row for row in parcel.processing_history
                  if row.get("action") == "packed"]
        assert packed, f"{parcel.parcel_id} reached a van without being bagged"
        assert packed[-1].get("receptacle"), "packed into an unnamed bag"


def test_a_bag_on_a_van_carries_one_destination_and_one_class(eco):
    """
    The invariant that makes the grouping worth doing, checked against a whole
    run rather than a constructed bag.
    """
    parcels = eco.env.all_parcels()
    for bag in eco.env.bags.sealed:
        assert bag.parcel_ids
        routes = {parcels[p].route_label for p in bag.parcel_ids}
        classes = {parcels[p].priority.value for p in bag.parcel_ids}
        assert routes == {bag.route}, f"{bag.receptacle_id} mixed destinations"
        assert classes == {bag.mail_class}, f"{bag.receptacle_id} mixed classes"


def test_handover_puts_the_whole_bag_on_one_van(eco):
    """
    A bag is handed over as a unit. Half a bag on one van and half on the next
    is exactly the thing bagging prevents.
    """
    handed = [b for b in eco.env.bags.sealed if b.loaded_on]
    assert handed, "no bag was ever handed over"
    for bag in handed:
        van = next(v for v in eco.env.departures.all_vans()
                   if v.vehicle_id == bag.loaded_on)
        assert van.route == bag.route
        for parcel_id in bag.parcel_ids:
            assert parcel_id in van.loaded, \
                f"{parcel_id} was in {bag.receptacle_id} but not on {van.vehicle_id}"


def test_the_judgement_is_still_the_gates_and_the_bagging_is_not(eco):
    """
    The split this project keeps making. DISPATCH still decides whether a
    parcel goes now or waits, and that decision is still the one worth a model
    call; packing a parcel into the right bag never was.
    """
    from post_office.config.settings import LLM_CANDIDATES

    assert "DISPATCH" in LLM_CANDIDATES
    gate = eco.experts["DISPATCH"]
    assert gate.released > 0 and gate.packed > 0
    assert gate.handed_over > 0, "no bag was ever handed to a van"
