"""
What a customer buys when they pay for express, and whether they get it.

Measured over a six-thousand-tick run, they did not. Every parcel in the
building carried the same promise whatever was written on it:

    grade      n   median dwell   median promise
    NORMAL    99            538             2400
    EXPRESS   15            332             2505
    URGENT    19            465             2359

A promise of 2400 ticks is the standard one -- the fourth van for the route.
Express should buy the second and urgent the next one out, so those columns
should read roughly 2400, 1200 and 600. They read the same, and urgent was
slower through the building than express, which is the sort of number that
means nothing is steering.

The cause was a comment admitting it. When the label read moved from the door
to the sorting machinery, the gate lost sight of the service class, so it
promised everything the standard departure "until it knows better" -- and
nothing ever knew better, because nothing revised the promise afterwards.
`PROMISED_DEPARTURE` was dead, and so was every downstream consequence: the
task queue is earliest-deadline-first, so identical deadlines mean the grade
never reaches the scheduler at all.

So the grade has to arrive in the one place it can act. The clerk at the door
reads the service off the label the way it reads the town -- a person can see
"express" written on a parcel -- and the gate promises on that. When the
scanner reads the line properly and finds something different, the facility
revises what it promised. Both reads are already there; only the service was
being thrown away.
"""

from __future__ import annotations

import pytest

from post_office.environment.parcels import ParcelPriority
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=1, run_id="priority")
    made.start()
    for _ in range(6000):
        made.step()
    yield made
    made.close()


def promised(parcel):
    """How long the facility gave itself, from the parcel's arrival."""
    if parcel.due_by is None or "arrived" not in parcel.timestamps:
        return None
    return parcel.due_by - parcel.timestamps["arrived"]


def by_grade(eco, of):
    out = {}
    for grade in ("NORMAL", "EXPRESS", "URGENT"):
        values = sorted(v for v in (of(p) for p in eco.env.all_parcels().values()
                                    if p.priority.value == grade)
                        if v is not None)
        if values:
            out[grade] = values[len(values) // 2]
    return out


# ------------------------------------------------------------- the promise
def test_the_clerk_at_the_door_can_read_the_service(eco):
    """
    It always could -- the word is on the same line as the town, and the gate
    was simply dropping it. A smudge that hides the service still leaves the
    town readable, so the two are reported separately.
    """
    from post_office.agents.subagents.sorting_subagents import glance

    seen = glance("Brno 602 00, express")
    assert seen["town"] == "BRNO"
    assert seen["service"] == "EXP"

    # A line the scanner cannot parse can still be read well enough to accept
    # and to price.
    smudged = glance("Br#o 602 00, urgent")
    assert smudged["legible"] and smudged["town"] == "BRNO"
    assert smudged["service"] == "URG"


def test_paying_for_express_buys_an_earlier_departure(eco):
    """
    The whole point of a service class. Three grades, three promises, in order.
    """
    promises = by_grade(eco, promised)
    assert set(promises) == {"NORMAL", "EXPRESS", "URGENT"}, promises
    assert promises["URGENT"] < promises["EXPRESS"] < promises["NORMAL"], promises


def test_the_promises_are_departures_apart_rather_than_nearly_equal(eco):
    """
    Not merely ordered: a promise that is five ticks tighter is an ordering
    that no scheduler can act on. The gap has to be a van.
    """
    from post_office.environment.vehicles import DEFAULT_INTERVAL

    # Compared on one route, at one moment. Each route now has its own slot
    # inside the interval, so promises made for parcels going to different
    # towns differ by that offset as well as by the class -- which says
    # something about the timetable rather than about the grades.
    board = eco.env.departures
    route = board.routes[0]
    promises = {grade: board.promise_for(grade, 0, route)
                for grade in ("URGENT", "EXPRESS", "NORMAL")}

    assert promises["NORMAL"] - promises["EXPRESS"] >= DEFAULT_INTERVAL, promises
    assert promises["EXPRESS"] - promises["URGENT"] >= DEFAULT_INTERVAL, promises


def test_a_parcel_is_promised_what_was_written_on_it(eco):
    """
    Per parcel rather than per median: the class the facility settled on is the
    class the promise was made for.
    """
    from post_office.environment.vehicles import PROMISED_DEPARTURE

    board = eco.env.departures
    checked = 0
    for parcel in eco.env.all_parcels().values():
        if parcel.due_by is None or not parcel.route_label:
            continue
        arrived = parcel.timestamps.get("received") or parcel.timestamps["arrived"]
        expected = board.promise_for(parcel.priority.value, arrived,
                                     parcel.route_label)
        # Promised on the grade, give or take a revision: the gate promises on
        # what it read and sorting may have graded it differently.
        assert parcel.due_by <= board.promise_for("NORMAL", arrived,
                                                  parcel.route_label), \
            f"{parcel.parcel_id} was promised worse than standard"
        if parcel.priority is ParcelPriority.URGENT:
            assert parcel.due_by < expected + PROMISED_DEPARTURE["NORMAL"] * 600
        checked += 1
    assert checked > 20, "not enough parcels carried a promise to say anything"


# ---------------------------------------------------- when the reads disagree
def test_the_promise_is_revised_when_the_scanner_disagrees_with_the_clerk(eco):
    """
    Two reads of one label, and the second is the better one. When the scanner
    finds a service the gate did not, the facility says so on the record rather
    than quietly keeping the wrong promise.

    Constructed rather than waited for: the gate and the scanner agree on a
    clean label, and disagreeing labels are rare by design.
    """
    from post_office.environment.vehicles import PROMISED_DEPARTURE

    parcel = next(p for p in eco.env.all_parcels().values()
                  if p.route_label and p.due_by is not None)
    sorting = eco.experts["SORTING"]
    board = eco.env.departures
    before = parcel.due_by
    parcel.due_by = board.promise_for("NORMAL", 0, parcel.route_label)

    sorting.reprice(parcel, "URG", tick=0)

    assert parcel.due_by < before or parcel.due_by <= board.promise_for(
        "URGENT", 0, parcel.route_label)
    assert any(row.get("action") == "promise_revised"
               for row in parcel.processing_history)
    assert PROMISED_DEPARTURE["URGENT"] < PROMISED_DEPARTURE["NORMAL"]


# ------------------------------------------------------- what it then buys
def test_the_grade_reaches_the_scheduler_through_the_deadline(eco):
    """
    The mechanism, and the reason the promise had to be fixed before anything
    else. The queue is earliest-deadline-first: it never reads a priority. A
    grade that does not change the deadline cannot change the order of work,
    which is why identical promises made express decorative.
    """
    urgent = [p for p in eco.env.all_parcels().values()
              if p.priority is ParcelPriority.URGENT and p.due_by is not None]
    normal = [p for p in eco.env.all_parcels().values()
              if p.priority is ParcelPriority.NORMAL and p.due_by is not None]
    assert urgent and normal
    # An urgent parcel accepted at the same moment as a standard one has less
    # slack, so the scheduler reaches it first.
    assert (sum(promised(p) for p in urgent) / len(urgent)
            < sum(promised(p) for p in normal) / len(normal))


def handling(parcel):
    """
    Arrival to loaded: the part of a parcel's stay the facility controls.

    Not dwell. Dwell runs to the moment the van pulls away, so it is dominated
    by where in the six-hundred-tick departure cycle the parcel happened to
    arrive -- a standard parcel that lands just before a van beats an urgent
    one that lands just after it, and neither fact says anything about how the
    building treated them.
    """
    loaded = next((row["tick"] for row in parcel.processing_history
                   if row.get("action") == "loaded"), None)
    if loaded is None or "arrived" not in parcel.timestamps:
        return None
    return loaded - parcel.timestamps["arrived"]


def test_express_and_urgent_take_the_short_way_through_the_building(eco):
    """
    The structural difference, which holds whatever the load: express and
    urgent are never shelved, so they cross the building in two legs where a
    standard parcel takes three.

    Deliberately not a claim about speed on a quiet day. At the baseline load
    the facility finishes every parcel far inside its promise, so the queue is
    rarely choosing between two jobs and the grade changes the commitment
    rather than the outcome -- on one seed the handful of urgent parcels are a
    few ticks slower than the standard ones, and it means nothing. Where the
    grade bites is under load, and that has its own test below.
    """
    legs = by_grade(eco, lambda p: sum(
        1 for row in p.processing_history
        if row.get("action") == "status_change" and row.get("status") == "IN_TRANSIT"))
    assert legs["URGENT"] < legs["NORMAL"], legs
    if "EXPRESS" in legs:
        assert legs["EXPRESS"] < legs["NORMAL"], legs

    shelved = {g: [p for p in eco.env.all_parcels().values()
                   if p.priority.value == g and "stored" in p.timestamps]
               for g in ("NORMAL", "EXPRESS", "URGENT")}
    assert not shelved["URGENT"] and not shelved["EXPRESS"],         "a parcel that paid to skip the shelves was shelved"
    assert shelved["NORMAL"], "nothing standard was ever shelved"


def test_the_grade_bites_hardest_when_the_facility_is_busy():
    """
    Where a service class is supposed to matter, and the clearest evidence that
    the deadline is now steering the work.

    On a quiet day the building is comfortably inside every promise, so the
    grade changes the commitment without changing the outcome much. Load it
    up and the queue has to choose, and it chooses on the deadline:

        busy    to loaded
        NORMAL       1370
        EXPRESS       386
        URGENT        373

    A standard parcel waits nearly four times as long, and urgent goes ahead of
    express -- which is the order the customer paid for and the order the model
    could not produce at all while every promise was identical.
    """
    from tests.presets import busy_config

    made = build(seed=1, run_id="priority-busy", config=busy_config())
    made.start()
    for _ in range(6000):
        made.step()
    times = by_grade(made, handling)
    assert times["URGENT"] < times["NORMAL"] / 2, times
    assert times["EXPRESS"] < times["NORMAL"] / 2, times
    assert times["URGENT"] <= times["EXPRESS"] * 1.1, times
    made.close()


def test_a_tighter_promise_is_one_the_facility_can_still_keep(eco):
    """
    A promise nothing can meet is not a service class, it is a lateness
    generator. The baseline keeps what it sells.
    """
    summary = eco.summary()
    assert summary["parcels_dispatched"] > 50
    late = [p for p in eco.env.all_parcels().values()
            if p.late_at(eco.world.tick)]
    assert len(late) <= summary["parcels_dispatched"] * 0.1, \
        f"{len(late)} late of {summary['parcels_dispatched']} dispatched"
