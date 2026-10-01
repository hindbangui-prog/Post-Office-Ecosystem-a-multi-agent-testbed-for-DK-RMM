"""
The front door in the order a post office actually works it.

A parcel is validated, and only then registered. That order is the whole point:
registering is booking an item into the postal system, and booking in something
you are about to turn away is a record of an item the system does not have. The
gate used to do it backwards -- the clerk stamped the parcel as received, and
the gate decided afterwards whether to keep it -- so every refused parcel left
the building carrying a receipt for a delivery nobody would perform.

So there are two clerks at this door and the judgement sits between them:

    planner --RECEIVE--> intake
                         intake --> SUB-VALIDATION    (can this be read? do we
                                                       even go there?)
                         intake                       (accept it? or not)
                         intake --> SUB-REGISTRATION  (book it in)
                         intake --> planner           (received, or refused)

Both clerks are dull on purpose and neither decides anything. Validation
reports what it can make out; registration records that the facility has taken
responsibility. Between them is the only judgement at this door, and it is the
one worth a model call.
"""

from __future__ import annotations

import pytest

from post_office.communication import MessageType
from post_office.environment import ParcelStatus
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=3, run_id="validation")
    made.start()
    yield made
    made.close()


@pytest.fixture
def busy():
    """A run with enough refusals in it to say something about refusals."""
    made = build(seed=1, run_id="validating-busy",
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


# ------------------------------------------------------------------ the shape
def test_the_front_door_has_a_validator_and_a_registrar(eco):
    owned = sorted(c for c in eco.directory.children_of("INTAKE")
                   if c in eco.subagents)
    assert owned == ["SUB-REGISTRATION", "SUB-VALIDATION"]
    for clerk in owned:
        assert eco.directory.parent_of(clerk) == "INTAKE"


def test_neither_clerk_at_the_door_is_worth_a_model(eco):
    """
    The split this project keeps making. Reading an address well enough to
    decide, and writing down that a parcel was taken in, are both clerical.
    Whether the facility takes it is not.
    """
    from post_office.config.settings import LLM_CANDIDATES

    assert "INTAKE" in LLM_CANDIDATES
    assert "SUB-VALIDATION" not in LLM_CANDIDATES
    assert "SUB-REGISTRATION" not in LLM_CANDIDATES


# ------------------------------------------------------------- what each does
def test_validation_reports_what_it_can_make_out_and_records_nothing(eco):
    """
    A check, not a booking. Validation looks at the parcel and says what it
    found; it does not stamp the parcel, because nothing has been accepted yet.
    """
    clerk = eco.subagents["SUB-VALIDATION"]
    parcel = next(p for p in eco.env.parcels.values()
                  if p.status is ParcelStatus.ARRIVED)

    result = clerk.perform(_ask("SUB-VALIDATION", parcel.parcel_id))

    assert result["operation"] == "validate"
    assert result["ok"] and result["legible"]
    assert result["declared_route"], "the gate is told what was made out"
    assert result["size"] == parcel.size.value
    assert parcel.timestamps.get("received") is None, \
        "nothing is received until the gate has accepted it"
    assert parcel.status is ParcelStatus.ARRIVED
    assert parcel.route_label == "", "decoding it is still sorting's job"


def test_registration_books_the_parcel_into_the_system(eco):
    """
    The second clerk, and the one that writes something down. By the time it is
    asked, the facility has already said yes.
    """
    clerk = eco.subagents["SUB-REGISTRATION"]
    parcel = next(p for p in eco.env.parcels.values()
                  if p.status is ParcelStatus.ARRIVED)

    result = clerk.perform(_ask("SUB-REGISTRATION", parcel.parcel_id))

    assert result["operation"] == "register"
    assert result["ok"]
    assert parcel.timestamps.get("received") is not None
    assert any(row.get("action") == "registered"
               for row in parcel.processing_history)


def _ask(clerk, parcel_id):
    """A SUBTASK_REQUEST as the gate would send it."""
    from post_office.communication.message import Message

    return Message(message_id="m-test", tick=0, sender="INTAKE",
                   receiver=clerk, message_type=MessageType.SUBTASK_REQUEST,
                   content={"parcel_id": parcel_id})


# ---------------------------------------------------------------- the order
def test_a_parcel_is_validated_before_it_is_registered(eco):
    """
    The order, on every parcel the door accepted, read off the parcel's own
    record rather than off the message log -- so it holds however the gate is
    implemented.
    """
    run(eco, 400)
    booked = [p for p in eco.env.all_parcels().values()
              if p.timestamps.get("registered") is not None]
    assert booked, "nothing was booked in during four hundred ticks"
    for parcel in booked:
        actions = [row.get("action") for row in parcel.processing_history]
        assert "validated" in actions, f"{parcel.parcel_id} was never checked"
        assert "registered" in actions
        assert actions.index("validated") < actions.index("registered")


def test_a_refused_parcel_is_never_registered(busy):
    """
    The defect this ordering fixes. A parcel the facility turns away leaves
    with a reason and no receipt: it was looked at, and the postal system never
    took it on.
    """
    refused = [p for p in busy.env.all_parcels().values()
               if p.status is ParcelStatus.REFUSED]
    assert refused, "the gate never refused anything"
    for parcel in refused:
        actions = [row.get("action") for row in parcel.processing_history]
        assert "validated" in actions, "it was looked at"
        assert "registered" not in actions, \
            f"{parcel.parcel_id} was booked into the system and then turned away"
        assert parcel.timestamps.get("received") is None
        assert parcel.timestamps.get("registered") is None
        assert parcel.due_by is None, "and it was never promised anything"


def test_the_gate_asks_the_two_clerks_in_that_order(eco):
    """
    The same fact seen from the bus: the door's traffic about one parcel is a
    validation request and then, if it was kept, a registration request.
    """
    run(eco, 400)
    booked = [p for p in eco.env.all_parcels().values()
              if p.timestamps.get("registered") is not None]
    assert booked
    parcel_id = booked[0].parcel_id
    asked = [m.receiver for m in eco.bus.log.thread(parcel_id)
             if m.sender == "INTAKE"
             and m.message_type is MessageType.SUBTASK_REQUEST]
    assert asked[:2] == ["SUB-VALIDATION", "SUB-REGISTRATION"]


def test_the_counts_at_the_door_still_add_up(eco):
    run(eco, 400)
    gate = eco.experts["INTAKE"]
    everything = eco.env.all_parcels().values()
    assert gate.accepted == sum(1 for p in everything
                                if p.timestamps.get("registered") is not None)
    assert gate.refused == sum(1 for p in everything
                               if p.status is ParcelStatus.REFUSED)
    # And the base class's own counter is untouched and still means messages.
    assert gate.received >= gate.accepted
