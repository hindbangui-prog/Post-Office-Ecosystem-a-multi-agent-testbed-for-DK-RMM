"""
The layer between a decision and the floor.

An agent proposes; it does not execute. Between the two sits a gate that asks
three separate questions, in order, and stops at the first "no":

    schema      is this even an answer to the question that was asked?
    policy      is the agent allowed to answer it that way?
    state       is it still true of the floor by the time we act?

The three are kept apart on purpose. A model that answers off the list is a
different failure from a model that answers plausibly but is not permitted to,
and both are different from a model that answered correctly about a floor that
has since moved. Under stress they should come apart, and a single "invalid"
verdict would hide that.

The gate does not decide anything. It permits or refuses, and when it refuses
the deterministic rule answers instead. Refusing is not a way of replacing the
reasoning -- it is the reason the reasoning is allowed to be interesting.
"""

from __future__ import annotations

import pytest

from post_office.environment.zones import Zone
from post_office.policy import PolicyGate, Proposal
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=7, run_id="policy-gate")
    made.start()
    yield made
    made.close()


@pytest.fixture
def gate(eco):
    return PolicyGate(eco.world)


def propose(**kw):
    base = {"kind": "release_parcel", "agent_id": "DISPATCH", "choice": "RELEASE",
            "options": ("RELEASE", "HOLD"), "facts": {}, "reason": "",
            "source": "crewai:test"}
    base.update(kw)
    return Proposal(**base)


# ------------------------------------------------------------------- schema
def test_an_answer_that_is_not_on_the_list_is_refused_at_the_schema_stage(gate):
    verdict = gate.check(propose(choice="MAYBE"))
    assert not verdict.ok
    assert verdict.stage == "schema"
    assert "MAYBE" in verdict.violation


def test_an_answer_on_the_list_passes_the_schema_stage(gate):
    assert gate.check(propose(choice="HOLD")).ok


def test_a_missing_answer_is_refused(gate):
    verdict = gate.check(propose(choice=None))
    assert not verdict.ok
    assert verdict.stage == "schema"


# ------------------------------------------------------------------- policy
def test_an_agent_may_not_answer_a_question_that_is_not_its_own(gate):
    """
    Authority is per agent, and it is checked rather than assumed. RESOURCE
    deciding what leaves on a van is the failure this exists to catch.
    """
    verdict = gate.check(propose(kind="release_parcel", agent_id="RESOURCE"))
    assert not verdict.ok
    assert verdict.stage == "policy"
    assert "RESOURCE" in verdict.violation


def test_filling_the_shelves_past_the_supervisors_ceiling_is_refused(gate, eco):
    """
    The supervisor sets `max_storage_load`. An agent may reason about how full
    the shelves are; it may not decide that the ceiling does not apply today.
    """
    eco.world.policy.max_storage_load = 0.5
    verdict = gate.check(propose(
        kind="accept_into_storage", agent_id="RESOURCE", choice="ACCEPT",
        options=("ACCEPT", "REFUSE"), facts={"load": 0.8}))

    assert not verdict.ok
    assert verdict.stage == "policy"


def test_refusing_storage_is_always_permitted(gate, eco):
    """The ceiling bounds what may be accepted, never what may be refused."""
    eco.world.policy.max_storage_load = 0.5
    assert gate.check(propose(
        kind="accept_into_storage", agent_id="RESOURCE", choice="REFUSE",
        options=("ACCEPT", "REFUSE"), facts={"load": 0.8})).ok


def test_releasing_more_work_than_the_ceiling_allows_is_refused(gate, eco):
    eco.world.policy.max_concurrent_transports = 4
    verdict = gate.check(propose(
        kind="release_work", agent_id="PLANNER", choice=3,
        options=(0, 1, 2, 3), facts={"headroom": 1}))

    assert not verdict.ok
    assert verdict.stage == "policy"
    assert "headroom" in verdict.violation


# -------------------------------------------------------------------- state
def test_a_charge_point_taken_since_the_question_was_asked_is_refused(gate, eco):
    """
    The facts were true when they were gathered. Between gathering them and
    acting on them a tick passed, the bus delivered, and another robot plugged
    in. This is the stage that catches it.
    """
    station = sorted(eco.env.stations.values(), key=lambda s: s.station_id)[0]
    eco.env.claim_station("R-OTHER", station.station_id)

    verdict = gate.check(propose(
        kind="allocate_charge_point", agent_id="RESOURCE",
        choice=station.station_id,
        options=(station.station_id, "WAIT"), facts={}))

    assert not verdict.ok
    assert verdict.stage == "state"
    assert station.station_id in verdict.violation


def test_waiting_for_a_charge_point_is_always_valid(gate, eco):
    for station in eco.env.stations.values():
        eco.env.claim_station("R-OTHER", station.station_id)
    assert gate.check(propose(
        kind="allocate_charge_point", agent_id="RESOURCE", choice="WAIT",
        options=("WAIT",), facts={})).ok


def test_sending_a_parcel_to_storage_with_no_shelf_left_is_refused(gate, eco):
    verdict = gate.check(propose(
        kind="classify_destination", agent_id="SORTING",
        choice=Zone.TEMPORARY_STORAGE.value,
        options=(Zone.TEMPORARY_STORAGE.value, Zone.DISPATCH.value),
        facts={}, ))
    # Storage is empty at tick 0, so this one is permitted; the refusal is
    # what happens once it is full.
    assert verdict.ok

    eco.env.storage.capacity = 0
    refused = gate.check(propose(
        kind="classify_destination", agent_id="SORTING",
        choice=Zone.TEMPORARY_STORAGE.value,
        options=(Zone.TEMPORARY_STORAGE.value, Zone.DISPATCH.value),
        facts={}))
    assert not refused.ok
    assert refused.stage == "state"


# ------------------------------------------------------------------- order
def test_the_stages_are_checked_in_order(gate, eco):
    """
    A proposal that is wrong in three ways reports the first thing wrong with
    it, not the last. Otherwise a schema failure under perturbation would be
    logged as a state failure and counted against the floor.
    """
    eco.world.policy.max_storage_load = 0.1
    verdict = gate.check(propose(
        kind="accept_into_storage", agent_id="DISPATCH", choice="SOMETHING",
        options=("ACCEPT", "REFUSE"), facts={"load": 0.9}))

    assert verdict.stage == "schema", "the answer was not even on the list"
