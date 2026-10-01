"""
The service class is sold, not assigned. The facility does not re-grade it.

`SORTING` used to treat the label as an opening bid. Its rule read "what the
facility actually does about a customer's claim", and on a busy day it did
this:

    busy: grade changed from what was paid for -> {('URGENT', 'EXPRESS'): 3}

    if claimed is URGENT and size == "LARGE" and queue >= 10:
        return Answer(EXPRESS, "urgent claimed, but a LARGE parcel with 10
                                waiting would hold up the dock")

Three parcels sold as urgent were quietly moved to express because the dock was
backed up. That is not a grading decision, it is a refund nobody issued. A
carrier that finds an urgent parcel inconvenient still owes the customer the
urgent departure; the inconvenience is the carrier's problem, and if it cannot
meet the promise the outcome is a missed promise -- which this model already
counts -- rather than a cheaper service delivered quietly.

The same argument rules out the other branch, which promoted a standard parcel
to express once it had waited. That reads as generous and is the same mistake
from the other side: the class the parcel carries decides which bag it travels
in and which departure it is owed, so promoting one gives away an express
service nobody bought, and it does it by rewriting what the customer's contract
says rather than by the facility working harder.

So the class is what the label says, start to finish. That does not leave the
facility without a way to hurry a parcel along: a deadline that is closer is
exactly what "hurry this one" means here, the queue is earliest-deadline-first,
and an ageing parcel's slack shrinks on its own. Urgency is expressed in the
schedule, where it costs the facility something, rather than in the contract,
where it costs the customer.
"""

from __future__ import annotations

import pytest

from post_office.environment.parcels import ParcelPriority
from post_office.simulation import build
from tests.presets import busy_config


SERVICE_GRADE = {"URG": "URGENT", "EXP": "EXPRESS", "STD": "NORMAL"}


def paid_and_delivered(eco):
    """(what the label said, what the facility settled on) for every parcel."""
    pairs = []
    for parcel in eco.env.all_parcels().values():
        paid = None
        for row in parcel.processing_history:
            if row.get("action") == "address_read" and row.get("service"):
                paid = SERVICE_GRADE.get(row["service"])
        if paid:
            pairs.append((parcel, paid, parcel.priority.value))
    return pairs


@pytest.fixture
def busy():
    """The load the downgrade used to happen under."""
    made = build(seed=1, run_id="paid-service", config=busy_config())
    made.start()
    for _ in range(6000):
        made.step()
    yield made
    made.close()


# --------------------------------------------------------- what was bought
def test_no_parcel_is_delivered_a_cheaper_service_than_it_paid_for(busy):
    """
    The defect, stated as the thing a customer would complain about.
    """
    rank = {"NORMAL": 0, "EXPRESS": 1, "URGENT": 2}
    downgraded = [(p.parcel_id, paid, got)
                  for p, paid, got in paid_and_delivered(busy)
                  if rank[got] < rank[paid]]
    assert not downgraded, f"sold a service and delivered a lesser one: {downgraded[:5]}"


def test_no_parcel_is_given_a_service_it_did_not_pay_for(busy):
    """
    The same rule from the other side. The class decides which bag a parcel
    travels in and which departure it is owed, so promoting one hands out an
    express service nobody bought.
    """
    rank = {"NORMAL": 0, "EXPRESS": 1, "URGENT": 2}
    upgraded = [(p.parcel_id, paid, got)
                for p, paid, got in paid_and_delivered(busy)
                if rank[got] > rank[paid]]
    assert not upgraded, f"gave away a service nobody bought: {upgraded[:5]}"


def test_the_class_on_the_parcel_is_the_class_on_the_label(busy):
    """Per parcel, both directions at once, across a whole busy run."""
    pairs = paid_and_delivered(busy)
    assert len(pairs) > 80, "not enough parcels were read to say anything"
    for parcel, paid, got in pairs:
        assert got == paid, f"{parcel.parcel_id} paid {paid} and got {got}"


def test_a_busy_dock_is_the_facilitys_problem_rather_than_the_customers(busy):
    """
    The case the old rule existed for: a large urgent parcel while the dock is
    backed up. It is still awkward -- it still occupies a robot for a whole
    errand -- and the facility still has to carry it. What it may not do is
    move the customer to a cheaper service to make its own day easier.
    """
    large_urgent = [p for p, paid, _ in paid_and_delivered(busy)
                    if paid == "URGENT" and p.size.value == "LARGE"]
    assert large_urgent, "the busy run never produced the awkward case"
    for parcel in large_urgent:
        assert parcel.priority is ParcelPriority.URGENT
        assert not any(row.get("action") == "priority_set"
                       and row.get("priority") != "URGENT"
                       for row in parcel.processing_history)


# ------------------------------------------------------- where urgency lives
def test_hurrying_a_parcel_is_done_in_the_schedule_not_in_the_contract(busy):
    """
    Removing the promotion branch does not leave the facility unable to hurry
    anything. The queue is earliest-deadline-first and a waiting parcel's slack
    shrinks by one every tick, so an ageing standard parcel climbs the queue on
    its own -- without its contract being rewritten.
    """
    board = busy.env.departures
    assert board is not None
    standard = [p for p, paid, _ in paid_and_delivered(busy) if paid == "NORMAL"]
    assert standard
    # Its promise is the standard one, whatever happened to it on the way.
    for parcel in standard[:40]:
        if parcel.due_by is None or not parcel.route_label:
            continue
        booked = parcel.timestamps.get("received")
        if booked is None:
            continue
        assert parcel.due_by == board.promise_for("NORMAL", booked,
                                                  parcel.route_label)


def test_the_promise_still_matches_the_class_for_every_grade(busy):
    """
    The consequence worth pinning: class, promise and bag now agree, because
    only one thing sets all three.
    """
    for parcel, paid, got in paid_and_delivered(busy):
        if not parcel.bagged_in:
            continue
        bag = next((b for b in busy.env.bags.all_bags()
                    if b.receptacle_id == parcel.bagged_in), None)
        if bag is None:
            continue
        assert bag.mail_class == paid, \
            f"{parcel.parcel_id} paid {paid} and travelled in a {bag.mail_class} bag"


def test_the_facility_still_keeps_what_it_sold(busy):
    """A promise honoured is the point; a promise re-graded is not."""
    summary = busy.summary()
    assert summary["parcels_dispatched"] > 50
    late = [p for p in busy.env.all_parcels().values()
            if p.late_at(busy.world.tick)]
    assert not late, f"{len(late)} parcels missed the service they paid for"
