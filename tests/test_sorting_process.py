"""
The five steps of a real sorting process, and which agent owns each.

    collection            the dock, and the gate that decides what comes in
    initial separation    flats from packages, by size
    scanning and reading  OCR the address into a route and a service
    applying barcodes     print a label encoding where the parcel is going
    batching              group by destination onto the outbound vans

The model had the third and fourth of those backwards. A parcel was created
carrying a perfect machine-readable barcode, so "reading the label" decoded a
string the simulation had written itself, and nothing ever *applied* a barcode
to anything -- which is the step a sorting facility exists to perform. What
arrives at a post office is an address, in handwriting or on a label; the
facility reads it and prints the barcode the rest of the building tracks by.

So a parcel now arrives with an address and no barcode, and carrying a barcode
means this building has processed it. The gate at the door glances at the
address -- can this be read at all, is it even somewhere we go -- which is what
a clerk does and is enough to accept or turn away. Sorting does the machine
read, and prints the label once it knows where the parcel is going.
"""

from __future__ import annotations

import pytest

from post_office.environment import ParcelStatus
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=3, run_id="process")
    made.start()
    yield made
    made.close()


@pytest.fixture
def busy():
    """
    A run the gate actually has to turn parcels away in.

    The default configuration is a quiet day: twenty-five parcels, none of them
    unreadable enough to refuse. Refusals are the interesting case and they are
    rare by construction, so the tests about them run the dock hard rather than
    waiting for a quiet day to produce one by luck.
    """
    made = build(seed=1, run_id="busy",
                 config={"arrival_interval": 10.0, "initial_parcels": 12,
                         "max_on_dock": 40})
    made.start()
    for _ in range(2000):
        made.step()
    yield made
    made.close()


def run(eco, ticks):
    for _ in range(ticks):
        eco.step()
    return eco


# ------------------------------------------------- what arrives at the door
def test_a_parcel_arrives_with_an_address_and_no_barcode(eco):
    on_dock = [p for p in eco.env.parcels.values()
               if p.status is ParcelStatus.ARRIVED]
    assert on_dock, "the dock is seeded at the start of a run"
    for parcel in on_dock:
        assert parcel.address, f"{parcel.parcel_id} arrived with no address"
        assert not parcel.barcode, "the facility prints the barcode, not the sender"


def test_the_barcode_is_something_this_building_applies(eco):
    """
    A parcel carrying a barcode is one this facility has processed. That is the
    step the whole trade is named after, and nothing in the model performed it.
    """
    run(eco, 200)
    labelled = [p for p in eco.env.all_parcels().values() if p.barcode]
    assert labelled, "nothing was ever labelled"
    for parcel in labelled:
        assert parcel.destination is not None, \
            f"{parcel.parcel_id} was labelled before anybody knew where it goes"
        # The label encodes where it is going, which is what a barcode is for.
        assert parcel.route_label and parcel.route_label in parcel.barcode


def test_a_parcel_the_gate_turned_away_is_never_labelled(busy):
    refused = [p for p in busy.env.all_parcels().values()
               if p.status is ParcelStatus.REFUSED]
    assert refused
    for parcel in refused:
        assert not parcel.barcode, "the facility labelled something it rejected"


# ------------------------------------------------------ who does which step
def test_reading_the_address_belongs_to_sorting(eco):
    """
    Scanning and reading is the sorting machinery's step, not the door's. The
    gate reads the address the way a clerk does -- well enough to decide -- and
    sorting does the machine read that turns it into a route.
    """
    owned = {e: sorted(c for c in eco.directory.children_of(e)
                       if c in eco.subagents)
             for e in ("INTAKE", "SORTING")}
    assert owned == {"INTAKE": ["SUB-REGISTRATION", "SUB-VALIDATION"],
                     "SORTING": ["SUB-BARCODE", "SUB-DESTINATION",
                                 "SUB-PRIORITY"]}


def test_the_gate_still_turns_away_what_it_cannot_read_or_does_not_serve(busy):
    """
    The door's own read. It has no barcode to go on any more -- only the
    address -- which is the honest version: an illegible address and one for a
    city off this network are both visible to a person at the dock.
    """
    reasons = set()
    for parcel in busy.env.all_parcels().values():
        for row in parcel.processing_history:
            if (row.get("action") == "status_change"
                    and row.get("status") == "REFUSED"):
                reasons.add(str(row.get("reason", "")))
    assert any("read" in r for r in reasons), reasons
    assert any("serve" in r for r in reasons), reasons


def test_a_parcel_the_scanner_cannot_read_goes_back_rather_than_standing_there(busy):
    """
    The third ending, and the one that was missing.

    A lightly smudged address passes the clerk's glance and defeats the
    scanner, so the facility ends up holding a parcel it accepted, promised and
    cannot sort. It used to stand in the building for the rest of the run,
    quietly counting as late against a promise nothing could ever keep. It goes
    back to the sender instead, and the promise goes with it.
    """
    returned = [p for p in busy.env.all_parcels().values()
                if p.status is ParcelStatus.RETURNED]
    assert returned, "no parcel was ever returned"
    assert busy.env.returned_count == len(returned)
    for parcel in returned:
        assert parcel.timestamps.get("received") is not None, \
            "a returned parcel is one the facility had taken"
        assert parcel.due_by is None, "its promise went back with it"
        assert not parcel.barcode, "nothing unreadable was ever labelled"
        assert busy.env.parcels.get(parcel.parcel_id) is None, "off the floor"

    # And it is counted apart from both the refusals and the dispatches: the
    # facility took this one on and could not do the work, which is neither
    # declining it nor delivering it.
    summary = busy.summary()
    assert summary["parcels_returned"] == len(returned)
    assert summary["parcels_refused"] == busy.experts["INTAKE"].refused, \
        "a return was counted as a refusal"
    assert all(p.status is not ParcelStatus.RETURNED
               for p in busy.env.all_parcels().values()
               if p.timestamps.get("dispatched") is not None)


def test_sorting_can_fail_to_read_an_address_the_door_accepted():
    """
    A second failure point rather than a duplicate of the first. The gate
    glances and the machine reads properly, so a smudged address can pass the
    door and defeat the scanner -- which is a real thing that happens, and was
    impossible while the label was a perfect string the simulation wrote.
    """
    from post_office.agents.subagents.sorting_subagents import read_address

    assert read_address("Brno 602 00, standard")["ok"] is True
    assert read_address("Brno 602 00, standard")["route"] == "BRNO"
    unreadable = read_address("8rn0 ^^2 0O, st@nd@rd")
    assert unreadable["ok"] is False
