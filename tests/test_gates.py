"""
The two doors: a reception gate at the front and a departure gate at the back.

Before these existed a parcel materialised on the dock already barcoded and the
planner sent it straight to sorting, and at the other end a parcel turned into
"dispatched" the instant a robot set it down in the zone and vanished from the
building in the same tick. Nothing received anything and nothing handed anything
over; both doors were a formality.

What the tests below fix in place is that each door now has a clerk and a
judgement. `SUB-REGISTRATION` books a parcel in and `SUB-MANIFEST` books it out
-- both clerical, both deterministic. The judgements belong to the experts:
INTAKE decides whether the facility accepts a parcel at all, and DISPATCH
decides whether one leaves now or waits. Those are the two decisions in this
subsystem that have no formula, which is why they are the ones worth a model.
"""

from __future__ import annotations

import pytest

from post_office.communication import AgentKind, MessageType
from post_office.environment import ParcelStatus, Zone
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=3, run_id="gates")
    made.start()
    yield made
    made.close()


def run(eco, ticks):
    for _ in range(ticks):
        eco.step()
    return eco


# --------------------------------------------------------------- the shape
def test_both_gates_are_experts_with_a_clerk_each(eco):
    assert "INTAKE" in eco.experts and "DISPATCH" in eco.experts
    assert eco.experts["INTAKE"].kind is AgentKind.EXPERT
    owned = {e: sorted(c for c in eco.directory.children_of(e)
                       if c in eco.subagents)
             for e in ("INTAKE", "DISPATCH")}
    assert owned == {"INTAKE": ["SUB-REGISTRATION", "SUB-VALIDATION"],
                     "DISPATCH": ["SUB-MANIFEST", "SUB-PACKING"]}
    for gate in ("INTAKE", "DISPATCH"):
        assert eco.directory.parent_of(gate) == "PLANNER"


def test_the_hierarchy_grew_by_two_experts_and_two_sub_agents(eco):
    assert len(eco.experts) == 6
    assert len(eco.subagents) == 15
    assert len(eco.agents) == 28          # 1 + 1 + 6 + 15 + 5


# ------------------------------------------------------------ the front door
def test_a_parcel_is_received_before_it_is_sorted(eco):
    """
    The stage that did not exist. A parcel arrives, INTAKE books it in, and only
    then is it any of sorting's business -- so REGISTERED is now something the
    front door did rather than a side effect of reading a barcode.
    """
    run(eco, 60)
    seen = [p for p in eco.env.parcels.values()
            if p.status is not ParcelStatus.ARRIVED]
    assert seen, "a 60-tick run receives something"
    for parcel in seen:
        history = [row for row in parcel.processing_history
                   if row.get("actor") in ("INTAKE", "SUB-REGISTRATION")]
        assert history, f"{parcel.parcel_id} was never received by anybody"


def test_the_two_clerks_at_the_door_do_different_jobs(eco):
    """
    The line each one does not cross. Validation reads the address well enough
    to decide and writes nothing; registration writes the receipt and reads
    nothing. Neither decodes the route -- that is still SUB-BARCODE's job a
    stage later, and two agents parsing one address would be two
    implementations of one rule.

    The order those two are asked in, and what happens to a refused parcel, are
    pinned in `test_validation.py`.
    """
    # Before any ticking: `start()` seeds the dock, so these are parcels
    # nobody has looked at yet.
    parcel = next(p for p in eco.env.parcels.values()
                  if p.status is ParcelStatus.ARRIVED)
    assert parcel.route_label == ""

    checked = eco.subagents["SUB-VALIDATION"].perform(
        _ask_about("SUB-VALIDATION", parcel.parcel_id))
    assert checked["ok"] and checked["legible"]
    assert checked["declared_route"], "the gate is told what was made out"
    assert parcel.timestamps.get("received") is None, "nothing accepted yet"

    booked = eco.subagents["SUB-REGISTRATION"].perform(
        _ask_about("SUB-REGISTRATION", parcel.parcel_id))
    assert booked["ok"]
    assert parcel.timestamps.get("received") is not None, "it was booked in"
    assert parcel.route_label == "", "but decoding it is still sorting's job"


def _ask_about(clerk, parcel_id):
    """A SUBTASK_REQUEST as an expert would send it."""
    from post_office.communication.message import Message

    return Message(message_id="m-test", tick=0, sender="INTAKE",
                   receiver=clerk,
                   message_type=MessageType.SUBTASK_REQUEST,
                   content={"parcel_id": parcel_id})


def test_a_parcel_the_facility_will_not_take_leaves_with_a_reason(eco):
    """
    Refusal has to be a real outcome rather than an error, or the judgement is
    not a judgement. A refused parcel is terminal, off the floor, and carries
    the reason it was turned away.
    """
    gate = eco.experts["INTAKE"]
    run(eco, 10)
    # The gate may already have turned one away on its own by now -- the world
    # prints the odd bad label -- so this counts the change, not the total.
    before = eco.env.refused_count
    parcel = next(iter(eco.env.parcels.values()))
    gate.refuse(parcel.parcel_id, "unreadable label")

    assert parcel.status is ParcelStatus.REFUSED
    assert parcel.status not in __import__(
        "post_office.environment.parcels", fromlist=["OPEN_STATUSES"]
    ).OPEN_STATUSES
    assert eco.env.parcels.get(parcel.parcel_id) is None, "off the floor"
    assert eco.env.refused_count == before + 1


# ------------------------------------------------------------- the back door
def test_a_parcel_waits_at_the_back_door_instead_of_vanishing(eco):
    """
    The change that makes holding possible at all. A parcel delivered into the
    dispatch zone used to become DISPATCHED and be removed in the same tick, so
    there was no moment at which anyone could decide anything about it.
    """
    run(eco, 400)
    waited = [p for p in eco.env.parcels.values()
              if p.timestamps.get("awaiting_dispatch") is not None]
    assert waited, "something reached the back door in 400 ticks"
    assert any(p.status is ParcelStatus.AWAITING_DISPATCH
               for p in eco.env.parcels.values()) or eco.env.dispatched_count


def test_only_dispatch_sends_a_parcel_out_of_the_building(eco):
    """
    `DISPATCHED` now means the departure gate released it, not that a robot
    touched the zone. Which is what makes the dispatched count and the dwell
    time mean something.
    """
    run(eco, 1400)
    assert eco.env.dispatched_count > 0
    gate = eco.experts["DISPATCH"]
    # Loading and leaving are no longer the same event. Everything that has
    # left was loaded by this gate, and the difference between the two numbers
    # is what is sitting on a van that has not gone yet -- which is exactly the
    # gap a cut-off exists to create.
    assert gate.loaded >= eco.env.dispatched_count
    on_vans = sum(len(v.loaded) for v in eco.env.departures.all_vans()
                  if not v.has_gone)
    assert gate.loaded == eco.env.dispatched_count + on_vans


def test_manifesting_a_parcel_records_what_left(eco):
    run(eco, 1400)
    gate = eco.experts["DISPATCH"]
    assert gate.manifest, "the gate keeps a record of what went out"
    entry = gate.manifest[0]
    assert entry["parcel_id"] and entry["route"] is not None
    assert entry["tick"] >= 0


# ------------------------------------------------------- hierarchy and rules
def test_the_new_clerks_obey_the_hierarchy_like_every_other(eco):
    """
    A sub-agent may address its parent and nobody else. Generic already, but
    worth pinning for the two new ones: they are the first sub-agents whose
    parent is not one of the original four experts.
    """
    run(eco, 400)
    for clerk, parent in (("SUB-REGISTRATION", "INTAKE"),
                          ("SUB-MANIFEST", "DISPATCH")):
        sent = eco.bus.log.recent(limit=4000, agent_id=clerk)
        sent = [m for m in sent if m.sender == clerk]
        assert sent, f"{clerk} never said anything"
        assert {m.receiver for m in sent} == {parent}
        assert all(m.message_type is MessageType.SUBTASK_RESULT for m in sent)


def test_the_judgements_sit_on_the_experts_not_the_clerks(eco):
    """
    Booking a parcel in and booking it out are clerical: verify a label, stamp a
    time. The decisions with no formula -- take it or turn it away, send it now
    or hold it -- are the experts'. That split is what decides which of these
    is worth spending a model call on, so it is worth a test.
    """
    from post_office.config.settings import LLM_CANDIDATES

    assert "INTAKE" in LLM_CANDIDATES and "DISPATCH" in LLM_CANDIDATES
    assert "SUB-REGISTRATION" not in LLM_CANDIDATES
    assert "SUB-MANIFEST" not in LLM_CANDIDATES

    run(eco, 200)
    for gate in ("INTAKE", "DISPATCH"):
        kinds = {d["kind"] for d in eco.agents[gate].decisions}
        assert kinds, f"{gate} never made a judgement"


def test_the_gates_count_their_own_work_not_their_message_traffic(eco):
    """
    `BaseAgent` already counts inbound messages in `self.received`, and the
    intake gate first called its own counter the same thing -- so it reported
    three receipts for every parcel it accepted, which is its message traffic
    wearing the name of its work. Any counter a gate adds has to be its own.
    """
    run(eco, 400)
    intake, dispatch = eco.experts["INTAKE"], eco.experts["DISPATCH"]
    handled = len(eco.env.all_parcels())

    assert intake.accepted + intake.refused <= handled
    assert intake.accepted == sum(
        1 for p in eco.env.all_parcels().values()
        if p.timestamps.get("registered") is not None)
    assert dispatch.loaded >= eco.env.dispatched_count
    # And the base class's own counter is untouched and still means messages.
    assert intake.received >= intake.accepted


# ------------------------------------------- what the gate has to interpret
def test_the_world_produces_parcels_the_gate_has_to_turn_away():
    """
    The intake gate decides whether the facility takes a parcel, on what it can
    make out of the address it arrived with: a line nobody can read, a town
    nobody here serves. Both branches existed and neither could ever fire,
    because the generator wrote a perfect address every time and drew the town
    from the list of routes the facility runs. A judgement that cannot be
    exercised is not a judgement, and the gate was a formality with a docstring.
    """
    from post_office.agents.subagents.sorting_subagents import glance

    made = build(seed=2, run_id="damaged",
                 config={"arrival_interval": 6.0, "initial_parcels": 12,
                         "max_on_dock": 60})
    made.start()
    for _ in range(1500):
        made.step()

    everything = list(made.env.all_parcels().values())
    assert len(everything) > 60, "a busy run to see rare things in"

    seen = {p.parcel_id: glance(p.address) for p in everything}
    unreadable = [p for p in everything if not seen[p.parcel_id]["legible"]]
    misaddressed = [p for p in everything
                    if seen[p.parcel_id]["legible"]
                    and not seen[p.parcel_id]["on_network"]]
    assert unreadable, "no parcel ever arrived with an address nobody can read"
    assert misaddressed, "no parcel ever arrived for somewhere we do not serve"

    # Rare, not routine: a facility where one parcel in five is rubbish is not
    # a facility, and the interesting runs are the ones where the exception is
    # an exception.
    assert len(unreadable) + len(misaddressed) < len(everything) * 0.15
    made.close()


def test_the_gate_turns_those_parcels_away_and_keeps_the_rest():
    made = build(seed=5, run_id="refusing",
                 config={"arrival_interval": 6.0, "initial_parcels": 12,
                         "max_on_dock": 60})
    made.start()
    for _ in range(1500):
        made.step()

    refused = [p for p in made.env.all_parcels().values()
               if p.status is ParcelStatus.REFUSED]
    assert refused, "the gate never refused anything"
    assert made.env.refused_count == len(refused)
    assert made.experts["INTAKE"].refused == len(refused)

    for parcel in refused:
        # Every refusal carries the reason it was refused, on the parcel.
        reasons = [row for row in parcel.processing_history
                   if row.get("action") == "status_change"
                   and row.get("status") == "REFUSED"]
        assert reasons and reasons[0].get("reason"), parcel.parcel_id
        assert parcel.due_by is None, "a parcel never accepted was never promised"

    # And the good ones still get through.
    assert made.summary()["parcels_dispatched"] > 0
    made.close()


# ------------------------------------- what the door reads, and what it does not
def test_a_parcel_reaches_sorting_validated_and_registered_but_not_decoded(eco):
    """
    What the front door is for, and where it stops.

    Intake validates and registers: it glances at the address, decides whether
    the facility takes the parcel, and books the accepted one into the system
    with a promise on it. It does not decode the address -- turning a line of
    handwriting into a route is the scanning step, and that belongs to the
    sorting machinery. So a parcel arriving at sorting is stamped, promised and
    still unread.
    """
    run(eco, 120)
    accepted = [p for p in eco.env.all_parcels().values()
                if p.timestamps.get("registered") is not None]
    assert accepted
    for parcel in accepted:
        assert parcel.address, f"{parcel.parcel_id} arrived with nothing on it"
        assert parcel.timestamps.get("received") is not None, \
            f"{parcel.parcel_id} was registered without being booked in"
        if parcel.status is not ParcelStatus.RETURNED:
            # A returned parcel gave its promise back with it: the facility
            # could not read the address and never had a chance to keep it.
            assert parcel.due_by is not None, \
                f"{parcel.parcel_id} was accepted without a promise"

    # Nothing is decoded before sorting gets to it: whatever carries a route
    # carries it because sorting read the address, not because the door did.
    for parcel in accepted:
        if parcel.route_label:
            assert any(row.get("action") == "address_read"
                       and row.get("actor") == "SORTING"
                       for row in parcel.processing_history), \
                f"{parcel.parcel_id} got a route from somewhere other than sorting"


def test_sorting_still_grades_every_parcel_it_is_given(eco):
    """
    The trap in moving the reading forward. Sorting had a branch that skipped
    straight to the destination question for a parcel that already carried a
    route -- which was nothing, before -- and it skipped the priority question
    with it. Once intake writes the route, that branch would fire for every
    parcel in the run and the grade would never be decided again.
    """
    run(eco, 400)
    graded = [p for p in eco.env.all_parcels().values()
              if p.status is not ParcelStatus.ARRIVED
              and any(row.get("action") == "priority_set"
                      for row in p.processing_history)]
    assert len(graded) >= 5, "the grader stopped being asked"
    # And the decision that *is* sorting's -- where the parcel goes next -- is
    # still being made for each of them. The grade itself is no longer a
    # decision: it is the service the customer paid for, read off the label.
    assert [d for d in eco.experts["SORTING"].decisions
            if d["kind"] == "classify_destination"]
