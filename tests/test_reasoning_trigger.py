"""
When an agent thinks, and when it just acts.

An LLM agent that calls its model on every decision is not a model of an
operator, it is a model of somebody who has never done the job before. A real
sorter does not deliberate over a legible label for Brno; they read it, they
throw it in the Brno cage, and they think only when something is wrong --
smudged, contradictory, or the cage is already full.

So a decision has two paths, and which one it takes is itself a small, visible
piece of state. The trigger says *why* the agent stopped to think, in a word
that can be counted across a run:

    routine        no trigger fired; the rule answers
    non-routine    a named trigger fired; the brain answers

The vocabulary is fixed and shared, because the point of the exercise is to
count reasoning invocations by cause under stress. A trigger named per agent
would make that impossible.
"""

from __future__ import annotations

import pytest

from post_office.agents.reasoning import REASONS, Trigger, TriggerSet


def test_a_trigger_set_with_nothing_registered_calls_everything_routine():
    triggers = TriggerSet()
    assert triggers.check("anything", {}) is None


def test_a_condition_that_does_not_fire_leaves_the_decision_routine():
    triggers = TriggerSet()
    triggers.register(
        "release_work",
        lambda facts: (Trigger(REASONS.CONTENTION, "more waiting than headroom")
                       if facts["waiting"] > facts["headroom"] else None))

    assert triggers.check("release_work", {"waiting": 2, "headroom": 8}) is None


def test_a_condition_that_fires_names_the_reason_and_the_detail():
    triggers = TriggerSet()
    triggers.register(
        "release_work",
        lambda facts: (Trigger(REASONS.CONTENTION, "more waiting than headroom")
                       if facts["waiting"] > facts["headroom"] else None))

    fired = triggers.check("release_work", {"waiting": 12, "headroom": 3})
    assert fired is not None
    assert fired.reason == REASONS.CONTENTION
    assert "headroom" in fired.detail


def test_the_first_condition_to_fire_is_the_one_reported():
    """
    Several conditions can be true at once. One reason per decision, in the
    order the agent registered them, so a run can be counted without
    double-counting.
    """
    triggers = TriggerSet()
    triggers.register("choose_robot",
                      lambda facts: Trigger(REASONS.CONTENTION, "two robots"))
    triggers.register("choose_robot",
                      lambda facts: Trigger(REASONS.DEADLINE, "also late"))

    assert triggers.check("choose_robot", {}).reason == REASONS.CONTENTION


def test_a_condition_that_raises_is_not_allowed_to_stop_the_decision():
    """
    A trigger is an optimisation, not a gate. If the condition itself is
    broken -- a fact missing after a perturbation, say -- the decision must
    still happen, and it goes the safe way: to reasoning.
    """
    triggers = TriggerSet()
    triggers.register("choose_robot",
                      lambda facts: facts["missing_key"] and None)

    fired = triggers.check("choose_robot", {})
    assert fired is not None
    assert fired.reason == REASONS.UNKNOWN, "a broken condition reasons anyway"


def test_every_reason_is_a_plain_countable_word():
    """The whole vocabulary, so a run can be tallied by cause."""
    words = REASONS.all()
    assert len(words) == len(set(words)), "duplicated reason"
    for word in words:
        assert word.islower() and " " not in word, word
