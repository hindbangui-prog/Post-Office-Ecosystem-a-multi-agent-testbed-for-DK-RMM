"""
The Dragon-King Runtime Monitoring Model, and the constraint it lives under.

Two things are being tested here and they are not the same thing.

The first is arithmetic: that the twelve indicators measure what they say, that
a rank-ordering test can tell an extreme that belongs to a tail from one that
does not, and that the state rules fire on the evidence they claim to.

The second is the constraint, and it is the more important of the two. This
monitor watches a system it must not touch. If it could act -- send a message,
nudge a robot, hold a task back -- its readings would partly be readings of its
own influence, and a model whose measurements include its own footprint cannot
be used to argue anything about the system it is measuring. So the tests below
hold that in the strongest form available: the same seed, with and without the
monitor attached, produces an identical run.
"""

from __future__ import annotations

import math

import pytest

from post_office.config.settings import config
from post_office.dkrmm import (DKRMM, DiscoveryStatus, OperationalState,
                               compute_indicators, dragon_king, precursors,
                               zscore)
from post_office.dkrmm.indicators import INDICATOR_NAMES
from post_office.simulation import build
from tests.presets import busy_config


def watched(seed=1, preset="busy", ticks=400, **kw):
    eco = build(seed=seed, run_id="dk",
                config=busy_config() if preset == "busy" else config(preset))
    monitor = DKRMM(eco, **kw).attach()
    eco.start()
    for _ in range(ticks):
        eco.step()
        monitor.tick()
    return eco, monitor


# ------------------------------------------------------------- independence
def test_watching_a_run_does_not_change_it():
    """
    The constraint the whole design answers to, held in the only form that
    settles it: run the same seed twice, once watched and once not, and every
    number the facility reports must be identical.
    """
    plain = build(seed=3, run_id="plain", config=busy_config())
    plain.start()
    for _ in range(300):
        plain.step()
    before = plain.summary()
    plain.close()

    eco, monitor = watched(seed=3, ticks=300)
    after = eco.summary()
    assert monitor.history, "the monitor never assessed anything"
    eco.close()

    ignore = {"run_id"}
    assert {k: v for k, v in after.items() if k not in ignore} == \
           {k: v for k, v in before.items() if k not in ignore}, \
        "the run went differently while it was being watched"


def test_the_monitor_is_not_an_agent_and_not_on_the_bus():
    eco, monitor = watched(ticks=60)
    try:
        assert "DK-RMM" not in eco.agents
        assert not any("DK" in str(name).upper() for name in eco.agents)
        # Nothing it could send a message through, and nothing it could write
        # to an agent with.
        assert not hasattr(monitor, "bus")
        assert not hasattr(monitor, "send")
        registered = {entry for entry in eco.directory.everyone()} \
            if hasattr(eco.directory, "everyone") else set()
        assert not any("DK" in str(entry).upper() for entry in registered)
    finally:
        eco.close()


def test_assessing_changes_nothing_it_is_assessing():
    """
    Belt and braces around the run-equality test above, and a tighter target:
    making an assessment is itself a read. The facility is photographed, the
    monitor is asked for its verdict several times over, and the photograph
    has to still match.
    """
    eco, monitor = watched(ticks=200)
    try:
        def photograph():
            return {
                "robots": [(r.robot_id, r.current_position, r.battery_level,
                            r.status, r.carrying, r.current_task)
                           for r in eco.fleet.all()],
                "tasks": sorted((t.task_id, t.status.value)
                                for t in eco.tasks.all()),
                "parcels": sorted((p.parcel_id, p.status.value)
                                  for p in eco.env.parcels.values()),
                "tick": eco.world.tick,
                "events": len(eco.logger.recent(100000)),
            }

        before = photograph()
        for extra in range(1, 4):
            monitor.assess(eco.world.tick + extra)
        assert photograph() == before, \
            "the monitor moved something by looking at it"
    finally:
        eco.close()


# --------------------------------------------------------------- indicators
def test_the_twelve_are_all_computed_and_all_finite():
    eco, monitor = watched(ticks=300)
    try:
        assert monitor.current is not None
        values = monitor.current.indicators.values()
        assert set(values) == set(INDICATOR_NAMES), "an indicator is missing"
        for name, value in values.items():
            assert math.isfinite(value), f"{name} is not a number"
            assert value >= 0.0, f"{name} went negative"
    finally:
        eco.close()


def test_rates_do_not_grow_with_the_length_of_the_window():
    """
    Everything countable is divided by the ticks it was counted over, so that
    watching for longer does not look like doing more. Without this the window
    length is itself an indicator, and the busiest thing in the facility is
    whoever set it.
    """
    eco, monitor = watched(ticks=400, window=60)
    events = monitor._window(eco.world.tick)
    try:
        short = compute_indicators(events, ticks=60, roster=28)
        long = compute_indicators(events, ticks=120, roster=28)
        assert long.message_frequency == pytest.approx(
            short.message_frequency / 2, rel=1e-6)
    finally:
        eco.close()


def test_work_handed_down_and_answers_coming_back_up_roughly_balance():
    """
    A sanity check on the direction of the two message indicators, and the
    reason it is here: the log files a message by who *sent* it, not by which
    way it was going, so reading direction off the topic made delegation a
    flat zero for a whole run while answers streamed in. In a facility that is
    keeping up, questions and answers are within a few of each other.
    """
    eco, monitor = watched(ticks=600)
    try:
        counts = monitor.current.indicators.counts
        down, up = counts["delegations"], counts["tool_calls"]
        assert down > 0 and up > 0, "one direction was never counted at all"
        assert abs(down - up) / max(down, up) < 0.25, (
            f"{down} questions and {up} answers is not a facility keeping up")
    finally:
        eco.close()


def test_a_busy_facility_talks_more_than_a_nearly_empty_one():
    """
    The indicators have to track the thing they name, or they are decoration.

    The contrast is drawn against a nearly empty facility rather than against
    the ordinary one, because between `default` and `busy` the conversation
    barely differs: the hierarchy talks about the work it has, and at both
    those loads it has plenty. That is a fact about the facility worth knowing
    -- message volume saturates long before the floor does -- and it makes the
    ordinary preset useless as the calm half of this comparison.

    Measured over every window rather than the last one, because a single
    window is one minute of an afternoon.
    """
    light = {"arrival_interval": 150.0, "initial_parcels": 1}

    def talking(cfg, ticks=500):
        eco = build(seed=1, run_id="dk", config=cfg)
        monitor = DKRMM(eco).attach()
        eco.start()
        for _ in range(ticks):
            eco.step()
            monitor.tick()
        rows = monitor.history
        out = (sum(r.indicators.message_frequency for r in rows) / len(rows),
               sum(r.indicators.agent_coupling for r in rows) / len(rows))
        eco.close()
        return out

    quiet_messages, quiet_coupling = talking({**config("default"), **light})
    busy_messages, busy_coupling = talking(busy_config())

    assert busy_messages > quiet_messages, (
        f"a busy facility averaged {busy_messages:.2f} messages a tick "
        f"against {quiet_messages:.2f} in a nearly empty one")
    assert busy_coupling > quiet_coupling


# --------------------------------------------------------------- statistics
def test_a_tail_explains_its_own_largest_value():
    """
    The distinction the model is named for. A power-law sample has extremes --
    that is what a heavy tail means -- and none of them is a dragon king,
    because the tail already accounts for them.
    """
    sample = [1.0 / (rank ** 0.8) for rank in range(1, 60)]
    verdict = dragon_king(sample)
    assert verdict.enough
    assert not verdict.is_dragon, (
        f"an ordinary tail was called a dragon king at ratio {verdict.ratio}")


def test_a_value_above_the_tail_is_a_dragon_king():
    sample = [1.0 / (rank ** 0.8) for rank in range(1, 60)]
    sample[0] = sample[0] * 6.0
    verdict = dragon_king(sample)
    assert verdict.enough and verdict.is_dragon
    assert verdict.ratio > 2.0
    assert verdict.expected > 0.0


def test_critical_slowing_down_is_visible_before_the_transition():
    """
    Variance and memory both climbing is the classical early warning. Built
    here rather than found in a run, because the point of the test is that the
    statistic reads the pattern, not that this facility produces it.
    """
    calm = [0.1, 0.12, 0.09, 0.11, 0.1, 0.12, 0.08, 0.11, 0.1, 0.09, 0.11, 0.1]
    # A series that wanders further and further and keeps its direction.
    creeping = list(calm) + [0.2, 0.35, 0.3, 0.5, 0.45, 0.7, 0.65, 0.95,
                             0.9, 1.3, 1.2, 1.8]
    assert not precursors(calm).slowing_down
    warning = precursors(creeping)
    assert warning.enough
    assert warning.slowing_down, "a series heading for a transition read as calm"
    assert warning.rising >= 2


def test_a_statistic_says_so_rather_than_guessing_on_thin_evidence():
    assert not precursors([0.1, 0.2, 0.3]).enough
    assert not dragon_king([5.0, 1.0, 0.5]).enough


def test_a_flat_baseline_is_not_a_standard_deviation_of_nothing():
    assert zscore(1.0, [1.0, 1.0, 1.0, 1.0]) == 0.0
    assert zscore(9.0, [1.0, 1.0, 1.0, 1.0]) == 3.0


# ------------------------------------------------------------------- states
def test_a_facility_going_about_its_business_is_stable():
    eco, monitor = watched(seed=1, preset="default", ticks=500)
    try:
        states = [row.state for row in monitor.history]
        assert states, "nothing was assessed"
        calm = sum(1 for s in states if s is OperationalState.STABLE)
        assert calm / len(states) > 0.5, (
            "an ordinary run spent most of it off baseline, which means the "
            f"baseline is wrong: {[s.value for s in states]}")
    finally:
        eco.close()


def test_one_kind_of_evidence_is_a_deviation_and_two_are_instability():
    """The rule, tested directly: kinds of evidence, not counts of events."""
    eco, monitor = watched(seed=1, preset="default", ticks=200)
    try:
        indicators = monitor.current.indicators
        one = {name: 0.0 for name in INDICATOR_NAMES}
        one["guardrail_events"] = 3.0
        monitor._last_kinds = ["refusal"]
        state, kinds, evidence = monitor._classify(indicators, one)
        assert state is OperationalState.DEVIATING and kinds == ["refusal"]
        assert evidence, "a state was returned with nothing to justify it"

        two = dict(one)
        two["retry_frequency"] = 2.5
        monitor._last_kinds = ["refusal", "retry"]
        state, kinds, _ = monitor._classify(indicators, two)
        assert state is OperationalState.UNSTABLE
        assert set(kinds) == {"refusal", "retry"}
    finally:
        eco.close()


def test_a_burst_that_lasts_one_window_is_not_instability():
    """
    A single parcel arriving into a quiet facility moves chatter, switching
    and coupling in the same breath. Counting that as independent evidence is
    how a monitor reports a crisis over one parcel, so a kind has to survive
    into a second window before it counts for anything above DEVIATING.
    """
    eco, monitor = watched(seed=1, preset="default", ticks=200)
    try:
        z = {name: 0.0 for name in INDICATOR_NAMES}
        z["guardrail_events"] = 3.0
        z["retry_frequency"] = 3.0

        monitor._last_kinds = []                      # nothing before this
        state, kinds, _ = monitor._classify(monitor.current.indicators, z)
        assert set(kinds) == {"refusal", "retry"}
        assert state is OperationalState.DEVIATING, \
            "two kinds in a single window were read as instability"

        monitor._last_kinds = ["refusal", "retry"]    # and now they have held
        state, _, _ = monitor._classify(monitor.current.indicators, z)
        assert state is OperationalState.UNSTABLE
    finally:
        eco.close()


def test_several_indicators_of_one_kind_are_still_one_kind():
    """
    The mistake this prevents: chatter pushes four indicators at once, and a
    monitor that counted indicators rather than kinds would read a busy minute
    as a crisis with four independent witnesses.
    """
    eco, monitor = watched(seed=1, preset="default", ticks=200)
    try:
        z = {name: 0.0 for name in INDICATOR_NAMES}
        for name in ("message_frequency", "delegation_frequency",
                     "tool_call_frequency", "interaction_density"):
            z[name] = 4.0
        monitor._last_kinds = ["chatter"]
        state, kinds, _ = monitor._classify(monitor.current.indicators, z)
        assert kinds == ["chatter"]
        assert state is OperationalState.DEVIATING
    finally:
        eco.close()


def test_an_rct_needs_spread_and_the_statistics_as_well_as_evidence():
    """
    Three kinds of evidence is not a Runtime Critical Transition. The model's
    claim is stronger: independent evidence, spread across the population, and
    the statistics of a system changing regime rather than having a bad minute.
    """
    eco, monitor = watched(seed=1, preset="busy", ticks=300)
    try:
        z = {name: 0.0 for name in INDICATOR_NAMES}
        for name in ("guardrail_events", "retry_frequency",
                     "execution_latency"):
            z[name] = 4.0

        indicators = monitor.current.indicators
        indicators.propagation_across_agents = 0.05      # nobody else affected
        monitor._last_kinds = ["guardrail", "refusal", "retry", "congestion"]
        state, kinds, _ = monitor._classify(indicators, z)
        assert len(kinds) >= 3
        assert state is OperationalState.UNSTABLE, \
            "an RCT was declared without the trouble having spread"

        # A heavy tail, and then one value far above where that tail says the
        # largest should be. The shape the model is named for.
        tail = [1.0 / (rank ** 0.8) for rank in range(1, 26)]
        indicators.propagation_across_agents = 0.8
        monitor._severity.clear()
        monitor._severity.extend(tail[1:] + [tail[0] * 6.0])
        state, _, evidence = monitor._classify(indicators, z)
        assert state is OperationalState.RCT
        assert any("tail" in line or "climbing" in line for line in evidence)
    finally:
        eco.close()


def test_coming_back_is_itself_reported():
    eco, monitor = watched(seed=1, preset="default", ticks=200)
    try:
        monitor.current.state = OperationalState.UNSTABLE
        after = monitor.assess(eco.world.tick + 1)
        if after.state is not OperationalState.RECOVERY:
            pytest.skip("the facility was not calm on the next window")
        assert after.previous is OperationalState.UNSTABLE
        assert any("back to baseline" in line for line in after.evidence)
    finally:
        eco.close()


# ----------------------------------------------------------- the human gate
def test_every_finding_starts_unconfirmed():
    eco, monitor = watched(ticks=200)
    try:
        assert all(row.status is DiscoveryStatus.DISCOVERED
                   for row in monitor.history), \
            "something validated itself"
    finally:
        eco.close()


def test_a_person_validates_activates_or_dismisses():
    eco, monitor = watched(ticks=200)
    try:
        assert monitor.activate() is None, \
            "a finding was activated without being validated first"

        validated = monitor.validate(by="hind", note="looks right")
        assert validated.status is DiscoveryStatus.VALIDATED
        assert validated.decided_by == "hind" and validated.decided_at
        assert monitor.state()["validated"] == 1

        active = monitor.activate(by="hind")
        assert active.status is DiscoveryStatus.ACTIVE

        monitor.assess(eco.world.tick + 1)
        dismissed = monitor.dismiss(by="hind", note="a van, not a crisis")
        assert dismissed.status is DiscoveryStatus.DISMISSED
        assert monitor.state()["dismissed"] == 1
    finally:
        eco.close()


def test_a_dismissal_is_kept():
    """A monitor whose false positives are deleted can never be shown to have any."""
    eco, monitor = watched(ticks=200)
    try:
        before = len(monitor.history)
        monitor.dismiss(by="hind")
        assert len(monitor.history) == before
        assert monitor.history[-1].status is DiscoveryStatus.DISMISSED
    finally:
        eco.close()


# ------------------------------------------------------------------ reading
def test_the_series_is_drawable_and_json_safe():
    import json

    eco, monitor = watched(ticks=400)
    try:
        series = monitor.series()
        assert len(series["ticks"]) == len(series["severity"])
        for name in INDICATOR_NAMES:
            assert len(series["indicators"][name]) == len(series["ticks"])
        json.dumps(series)
        json.dumps(monitor.state())
    finally:
        eco.close()


# ------------------------------------------------------------ over the wire
# --------------------------------------------------------------------------
# What the monitor makes of a refused decision.
#
# The gate records the *stage* that refused -- "schema", "policy" or "state",
# and "ok" when it passed. `compute_indicators` used to look for the literal
# string "refused", which `BaseAgent.decide` has never written, so the
# comparison was always false and every gate refusal by an expert was invisible
# to the monitor. These pin the corrected mapping, and the distinction the
# correction had to make: a schema refusal is a malformed proposal, not the
# guardrail exercising authority, and counting the two together would let a
# parser failure read as containment.
# --------------------------------------------------------------------------

class _Ev:
    """One log line, with only the fields the indicators read."""

    def __init__(self, topic, actor="ROUTING", target="", tick=1, **detail):
        self.topic = topic
        self.actor = actor
        self.target = target
        self.tick = tick
        self.detail = detail


def _indicators_for(*events):
    return compute_indicators(list(events), ticks=10, roster=4)


def test_a_policy_refusal_is_a_guardrail_event():
    out = _indicators_for(_Ev("decision", validation="policy"))
    assert out.counts["refusals"] == 1
    assert out.counts["malformed_decisions"] == 0
    assert out.guardrail_events > 0


def test_a_state_refusal_is_a_guardrail_event():
    out = _indicators_for(_Ev("decision", validation="state"))
    assert out.counts["refusals"] == 1


def test_a_schema_refusal_is_counted_apart_from_the_guardrail():
    """
    Not governance. The answer was not one of the options, which says the
    proposer malfunctioned -- a model answering off-list, or a rule offering an
    action the situation did not have.
    """
    out = _indicators_for(_Ev("decision", validation="schema"))
    assert out.counts["refusals"] == 0
    assert out.counts["malformed_decisions"] == 1


def test_a_permitted_decision_is_neither():
    out = _indicators_for(_Ev("decision", validation="ok"))
    assert out.counts["refusals"] == 0
    assert out.counts["malformed_decisions"] == 0


def test_the_string_the_gate_never_writes_is_not_what_is_looked_for():
    """
    The regression this whole section exists for. `verdict.stage` is one of
    "schema" | "policy" | "state" | "ok" and never the word "refused", so a
    reader keyed to "refused" counts nothing however many refusals there were.
    """
    real = _indicators_for(_Ev("decision", validation="policy"))
    assert real.counts["refusals"] == 1


def test_a_refused_decision_puts_its_agent_in_trouble_only_for_policy_or_state():
    governed = _indicators_for(_Ev("decision", actor="ROUTING",
                                   validation="state"))
    assert governed.propagation_across_agents > 0

    malformed = _indicators_for(_Ev("decision", actor="ROUTING",
                                    validation="schema"))
    assert malformed.propagation_across_agents == 0


def test_door_refusals_still_count_as_they_did():
    """The other guardrails are untouched by the decision-stage change."""
    out = _indicators_for(_Ev("storage_refused", actor="SORTING"))
    assert out.counts["refusals"] == 1
