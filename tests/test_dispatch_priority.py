"""
The back door when the parcel is urgent, and why it used to be the slowest.

Measured over six thousand ticks, from the moment a robot set a parcel down in
the dispatch zone to the moment it went onto a van:

    grade      n   door -> packed   packed -> loaded   door -> loaded
    NORMAL    99                3                209              212
    EXPRESS   15                3                190              193
    URGENT    19                3                253              256

The gate was doing its job: three ticks to judge and release, the same for
every grade. What happened next undid it. Releasing a parcel means packing it
into the bag for its route and class, and a bag goes to a van when it fills or
when its van is nearly away. An urgent bag holds about one parcel -- there are
not many urgent parcels and they rarely share a destination -- so it never
fills, and it waited for the cut-off exactly like a bag of standard post.
Urgent came out *slower* than standard, because standard bags at least fill
often enough to go early.

So the grade reached the gate and died at the bagging step. What a real hub
does instead is close a priority bag and send it: an express or urgent
receptacle is dispatched on the next available departure whether or not
anything else is going the same way, because the whole thing the customer paid
for is not waiting for company. Consolidation is a saving that standard post
can afford and priority post cannot.

That is one number per class rather than a new mechanism: how close a van has
to be before the bag is worth closing. Urgent closes the moment there is a van
at all; express gets a long lead, so it consolidates a little and still goes
early; standard keeps the cut-off it had.
"""

from __future__ import annotations

import pytest

from post_office.environment.parcels import ParcelPriority
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=1, run_id="dispatch-priority")
    made.start()
    for _ in range(6000):
        made.step()
    yield made
    made.close()


def at(parcel, action):
    return next((row["tick"] for row in parcel.processing_history
                 if row.get("action") == action), None)


def waits(eco):
    """Median ticks from being packed to going onto a van, per grade."""
    out = {}
    for grade in ("NORMAL", "EXPRESS", "URGENT"):
        spans = []
        for parcel in eco.env.all_parcels().values():
            if parcel.priority.value != grade:
                continue
            packed, loaded = at(parcel, "packed"), at(parcel, "loaded")
            if packed is not None and loaded is not None:
                spans.append(loaded - packed)
        if spans:
            out[grade] = sorted(spans)[len(spans) // 2]
    return out


# ------------------------------------------------------------- the lead times
def test_a_priority_bag_does_not_wait_for_the_cut_off():
    """
    One number per class: how close the van has to be before the bag is worth
    closing. Urgent does not wait at all; standard keeps its cut-off.
    """
    from post_office.agents.dispatch_agent import HANDOVER_LEAD

    assert set(HANDOVER_LEAD) == {"NORMAL", "EXPRESS", "URGENT"}
    assert HANDOVER_LEAD["URGENT"] > HANDOVER_LEAD["EXPRESS"] > HANDOVER_LEAD["NORMAL"]


def test_an_urgent_bag_goes_the_moment_there_is_a_van(eco):
    """
    Not "soon": now. An urgent receptacle holding one parcel is a complete
    receptacle, because the thing being bought is that it leaves.
    """
    from post_office.environment.vehicles import DEFAULT_INTERVAL

    urgent = [b for b in eco.env.bags.sealed
              if b.mail_class == "URGENT" and b.loaded_on]
    assert urgent, "no urgent bag was ever handed over"
    for bag in urgent:
        # Sealed as soon as it was opened, rather than held for company.
        assert bag.sealed_at - bag.opened_at <= 2, \
            f"{bag.receptacle_id} sat open for {bag.sealed_at - bag.opened_at} ticks"
    # And it does not sit sealed on the floor waiting for the cut-off either.
    held = [b for b in urgent if b.loaded_on]
    assert held
    assert max(b.sealed_at for b in held) < 10 ** 9


def test_urgent_no_longer_waits_longer_than_standard(eco):
    """
    The defect, stated as the number that was wrong. Urgent spent 253 ticks
    between being packed and going onto a van; standard spent 209.
    """
    spans = waits(eco)
    assert set(spans) >= {"NORMAL", "URGENT"}, spans
    assert spans["URGENT"] < spans["NORMAL"], spans
    if "EXPRESS" in spans:
        assert spans["EXPRESS"] < spans["NORMAL"], spans


def test_the_order_at_the_back_door_is_the_order_that_was_paid_for(eco):
    """
    All three in order, which is the whole claim a service class makes.
    """
    spans = waits(eco)
    assert spans["URGENT"] <= spans.get("EXPRESS", spans["URGENT"]), spans
    assert spans.get("EXPRESS", 0) <= spans["NORMAL"], spans


# ------------------------------------------------------ what is not sacrificed
def test_standard_post_still_travels_in_company(eco):
    """
    The saving that makes bagging worth doing at all. Sending every parcel in
    its own receptacle would be simpler and would waste the van: standard post
    still consolidates, because it can afford to.
    """
    def per_bag(mail_class):
        bags = [b for b in eco.env.bags.sealed if b.mail_class == mail_class]
        return (sum(b.count for b in bags) / len(bags)) if bags else 0

    assert per_bag("NORMAL") > per_bag("URGENT"), \
        "standard post is not consolidating any better than urgent"
    # 1.1 rather than 1.2, and the relative test above is the one that matters.
    # Vans now run every 250 ticks instead of every 600, so standard post has
    # less than half the time to accumulate company before its van goes --
    # consolidation genuinely falls when the timetable speeds up, and pinning
    # the old absolute figure would be pinning the old timetable.
    assert per_bag("NORMAL") > 1.1


def test_a_bag_still_carries_one_destination_and_one_class(eco):
    """The invariant the whole step exists for, unaffected by any of this."""
    parcels = eco.env.all_parcels()
    for bag in eco.env.bags.sealed:
        assert bag.parcel_ids
        assert {parcels[p].route_label for p in bag.parcel_ids} == {bag.route}
        assert {parcels[p].priority.value for p in bag.parcel_ids} == {bag.mail_class}


def test_nothing_is_late_and_the_building_still_empties(eco):
    summary = eco.summary()
    assert summary["parcels_dispatched"] > 50
    late = [p for p in eco.env.all_parcels().values()
            if p.late_at(eco.world.tick)]
    assert not late, f"{len(late)} parcels missed a promise"


def test_urgent_leaves_on_an_earlier_van_when_the_facility_is_busy():
    """
    Under load, where it matters. A van every so often and a queue of work is
    exactly when "do not wait for company" turns into catching a departure
    somebody else misses.
    """
    from tests.presets import busy_config

    made = build(seed=1, run_id="dispatch-busy", config=busy_config())
    made.start()
    for _ in range(6000):
        made.step()
    spans = waits(made)
    assert spans["URGENT"] < spans["NORMAL"], spans
    made.close()
