"""
The formulas of docs/dkrmm-mathematics.md, checked against hand-computed values.

Each test feeds a small, fully known input to the DK-RMM code and compares the
result with a number worked out by hand in the test itself (from the formula
the document states), not with a value copied from a previous run of the code.
Production code is not modified; private helpers are reached only where the
document names them as the implementation of a formula.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from post_office.dkrmm import monitor as mon
from post_office.dkrmm.indicators import INDICATOR_NAMES, compute_indicators
from post_office.dkrmm.monitor import DKRMM
from post_office.dkrmm.signals import dragon_king, precursors, zscore
from post_office.dkrmm.states import OperationalState


def ev(tick, topic, actor="", target="", **detail):
    return SimpleNamespace(tick=tick, topic=topic, actor=actor, target=target,
                           detail=detail)


class FakeEco:
    """The three things DKRMM reads from an ecosystem: logger, roster, clock."""

    def __init__(self, roster=4):
        self.agents = {f"A{i}": None for i in range(roster)}
        self.world = SimpleNamespace(tick=0)
        self.listeners = []
        self.logger = SimpleNamespace(subscribe=self._subscribe)

    def _subscribe(self, fn):
        self.listeners.append(fn)
        return lambda: self.listeners.remove(fn)


# ----------------------------------------------------------- equation (Z)
def test_zscore_is_population_standardisation_against_the_baseline():
    history = [1.0, 2.0, 3.0, 4.0]
    mu = 2.5
    sigma = math.sqrt(((1.5 ** 2) * 2 + (0.5 ** 2) * 2) / 4)     # population sd
    assert zscore(5.0, history) == pytest.approx((5.0 - mu) / sigma)


def test_zscore_needs_four_baseline_points():
    assert zscore(100.0, [1.0, 2.0, 3.0]) == 0.0


def test_zscore_on_a_flat_baseline_is_zero_or_plus_three_whatever_the_direction():
    flat = [2.0, 2.0, 2.0, 2.0]
    assert zscore(2.0, flat) == 0.0
    assert zscore(2.5, flat) == 3.0
    assert zscore(1.0, flat) == 3.0          # a drop also reads +3 (documented edge case)


# ----------------------------------------------- equations (I1)-(I12)
def test_the_twelve_indicators_on_a_hand_built_window():
    events = [
        ev(10, "message", "A0", "A1"),
        ev(10, "message", "A1", "A0"),
        ev(11, "message", "A0", "SUB-X"),             # delegation
        ev(11, "subagent_message", "SUB-X", "A0"),    # tool call (answer back up)
        ev(12, "task_released", "A1"),                # retry and switch
        ev(12, "parcel_refused", "A0"),               # refusal, trouble
        ev(13, "decision", "A2", validation="policy"),  # governed refusal, trouble
        ev(13, "decision", "A3", validation="schema"),  # malformed only
        ev(14, "task_started", "A1", task_id="T1"),
        ev(15, "task_started", "A2", task_id="T2"),
        ev(15, "task_started", "A3", task_id="T9"),     # created unknown: skipped
        ev(16, "blocked", "A3"),                        # trouble, counted as blocked
    ]
    created = {"T1": 4, "T2": 13}
    span = 10
    x = compute_indicators(events, ticks=span, roster=8, created=created, persistence=2)

    # actors with a non-empty id: A0, A1, SUB-X, A2, A3
    active = 5
    assert x.active_agents == active
    assert x.message_frequency == pytest.approx(4 / span)
    pairs = {("A0", "A1"), ("A1", "A0"), ("A0", "SUB-X"), ("SUB-X", "A0")}
    assert x.interaction_density == pytest.approx(len(pairs) / (active * (active - 1)))
    assert x.delegation_frequency == pytest.approx(1 / span)
    assert x.tool_call_frequency == pytest.approx(1 / span)
    assert x.retry_frequency == pytest.approx(1 / span)        # task_released
    assert x.task_switching == pytest.approx(1 / span)         # task_released
    assert x.guardrail_events == pytest.approx(2 / span)       # parcel_refused + policy
    assert x.counts["malformed_decisions"] == 1
    assert x.counts["blocked"] == 1
    assert x.execution_latency == pytest.approx(((14 - 4) + (15 - 13)) / 2)
    assert x.agent_coupling == pytest.approx(active / 8)
    assert x.persistence_of_deviation == 2.0
    # acting = actors of a non-message event: A1, A0, A2, A3 (SUB-X only messaged)
    # trouble = A1 (task_released), A0 (parcel_refused), A2 (policy), A3 (blocked)
    assert x.acting_agents == 4
    assert x.propagation_across_agents == pytest.approx(4 / 4)


def test_behavioural_similarity_is_the_mean_pairwise_cosine_of_topic_profiles():
    events = [ev(1, "a", "X"), ev(1, "a", "X"), ev(1, "b", "X"),     # X = (a:2, b:1)
              ev(1, "a", "Y"), ev(1, "c", "Y"),                      # Y = (a:1, c:1)
              ev(1, "d", "Z")]                                       # Z = (d:1)
    x = compute_indicators(events, ticks=1, roster=3)
    cos_xy = (2 * 1) / (math.sqrt(4 + 1) * math.sqrt(1 + 1))
    cos_xz = 0.0                                                     # no shared topic
    cos_yz = 0.0
    assert x.behavioural_similarity == pytest.approx((cos_xy + cos_xz + cos_yz) / 3)


def test_density_and_similarity_are_zero_with_fewer_than_two_actors():
    x = compute_indicators([ev(1, "message", "A0", "A1")], ticks=1, roster=2)
    assert x.active_agents == 1
    assert x.interaction_density == 0.0
    assert x.behavioural_similarity == 0.0


def test_an_empty_window_gives_all_zero_indicators():
    x = compute_indicators([], ticks=60, roster=28)
    assert all(v == 0.0 for v in x.values().values())


# ----------------------------------------------- equations (V), (AC), (SK)
def test_precursor_statistics_by_hand():
    p = precursors([1.0, 2.0, 3.0, 4.0])          # fewer than 12: values but not enough
    assert p.enough is False and p.slowing_down is False
    assert p.variance == pytest.approx(1.25)                    # population variance
    # lag-1: deviations -1.5,-0.5,0.5,1.5; top = 0.75-0.25+0.75; bottom = 5
    assert p.autocorrelation == pytest.approx(1.25 / 5.0)
    q = precursors([0.0, 0.0, 3.0])
    sd = math.sqrt((1 + 1 + 4) / 3)
    expected = ((-1 / sd) ** 3 * 2 + (2 / sd) ** 3) / 3
    assert q.skewness == pytest.approx(expected)


def test_the_rising_flags_compare_the_later_half_with_the_earlier_half():
    early = [1.0, 1.1, 0.9, 1.0, 1.05, 0.95]       # low variance, alternating
    late = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]          # high variance, trending
    p = precursors(early + late)
    assert p.enough is True
    var = lambda s: sum((v - sum(s) / len(s)) ** 2 for v in s) / len(s)  # noqa: E731
    assert p.variance_rising == (var(late) > var(early))
    assert p.variance_rising is True and p.autocorrelation_rising is True
    assert p.slowing_down is True


def test_an_odd_length_series_gives_the_extra_point_to_the_later_half():
    # 13 points, h = floor(13/2) = 6: early = six zeros (variance 0),
    # late = [1, 0, 0, 0, 0, 0, 0] (variance 6/49 > 0). A ceil split would put
    # the 1 in the early half and make the late half flat.
    p = precursors([0.0] * 6 + [1.0] + [0.0] * 6)
    assert p.enough is True
    assert p.variance_rising is True


# ---------------------------------------------------------- equation (DK)
def test_a_power_law_tail_explains_its_own_largest_value():
    series = [10.0 / r for r in range(1, 13)]       # v_r = 10 r^-1 exactly
    d = dragon_king(series)
    assert d.enough is True
    assert d.slope == pytest.approx(-1.0)
    assert d.expected == pytest.approx(10.0)        # exp(intercept) = 10
    assert d.ratio == pytest.approx(1.0)
    assert d.fit_quality == pytest.approx(1.0)
    assert d.is_dragon is False


def test_a_point_three_times_above_the_tail_is_flagged():
    series = [30.0] + [10.0 / r for r in range(2, 13)]
    d = dragon_king(series)
    assert d.expected == pytest.approx(10.0)        # the fit excludes rank 1
    assert d.ratio == pytest.approx(3.0)
    assert d.is_dragon is True


def test_the_dragon_threshold_is_a_ratio_of_two():
    tail = [10.0 / r for r in range(2, 13)]          # predicts 10 at rank 1
    assert dragon_king([20.01] + tail).is_dragon is True
    assert dragon_king([19.99] + tail).is_dragon is False


def test_only_positive_values_enter_and_twelve_are_needed():
    d = dragon_king([0.0] * 50 + [1.0] * 11)
    assert d.points == 11 and d.enough is False


# ------------------------------------------- windows and scheduling (W)
def test_assessments_happen_at_the_first_call_then_every_twenty_ticks():
    eco = FakeEco()
    m = DKRMM(eco)
    made = []
    for t in range(1, 70):
        eco.world.tick = t
        if m.tick() is not None:
            made.append(t)
    assert made == [1, 21, 41, 61]


def test_the_window_is_the_closed_interval_and_the_span_is_capped_at_sixty():
    eco = FakeEco()
    m = DKRMM(eco).attach()
    for t in (39, 40, 41, 100):
        eco.listeners[0](ev(t, "x", "A0"))
    assert [e.tick for e in m._window(100)] == [40, 41, 100]   # 100-60 <= tau <= 100
    a = m.assess(100)
    assert a.indicators.ticks == 60
    b = DKRMM(FakeEco()).assess(7)
    assert b.indicators.ticks == 7                              # min(60, max(1, t))


# ---------------------------------------- severity (S) and state rules (R)
def _monitor_with_baseline(values_by_name):
    m = DKRMM(FakeEco())
    for name, values in values_by_name.items():
        m._series[name].extend(values)
    return m


def test_severity_is_the_mean_positive_z_over_the_twelve():
    eco = FakeEco(roster=4)
    m = DKRMM(eco).attach()
    # Every baseline flat at zero (four points), so a non-zero reading is z = +3
    # and an unchanged one is z = 0 (equation Z, flat case).
    for name in INDICATOR_NAMES:
        m._series[name].extend([0.0, 0.0, 0.0, 0.0])
    # Except retry_frequency: a baseline of 1, 2, 3, 4 with a reading of 0 gives
    # z = (0 - 2.5) / sqrt(1.25) < 0, which the positive part must ignore.
    m._series["retry_frequency"].clear()
    m._series["retry_frequency"].extend([1.0, 2.0, 3.0, 4.0])
    # 30 messages A0 -> A1: only A0 is an actor, so message_frequency and
    # agent_coupling move; density needs two actors and stays 0; no acting agent.
    for _ in range(30):
        eco.listeners[0](ev(10, "message", "A0", "A1"))
    a = m.assess(10)
    assert a.z["retry_frequency"] == pytest.approx(-2.5 / math.sqrt(1.25))
    moved = [n for n in INDICATOR_NAMES if a.z[n] > 0.0]
    assert sorted(moved) == ["agent_coupling", "message_frequency"]
    assert all(a.z[n] == 3.0 for n in moved)
    assert a.severity == pytest.approx((3.0 + 3.0) / 12)     # the negative z adds nothing
    assert list(m._severity) == [pytest.approx(0.5)]
    # the reading joins the baseline after it was scored
    assert list(m._series["message_frequency"])[-1] == pytest.approx(30 / 10)


def _indicators(events=100, propagation=0.0):
    x = compute_indicators([], ticks=60, roster=28)
    x.events = events
    x.propagation_across_agents = propagation
    return x


def _z(**hot):
    z = {name: 0.0 for name in INDICATOR_NAMES}
    z.update(hot)
    return z


def test_low_activity_is_stable_with_no_kinds():
    m = DKRMM(FakeEco())
    state, kinds, _ = m._classify(_indicators(events=mon.MIN_ACTIVITY - 1),
                                  _z(guardrail_events=9.0))
    assert state is OperationalState.STABLE and kinds == []


def test_kinds_are_groups_with_a_member_at_or_above_two():
    m = DKRMM(FakeEco())
    state, kinds, _ = m._classify(_indicators(),
                                  _z(execution_latency=2.0, task_switching=5.0,
                                     message_frequency=1.99))
    assert kinds == ["congestion"]                       # one kind, two members
    assert state is OperationalState.DEVIATING


def test_two_confirmed_kinds_are_unstable_and_persistence_alone_also_is():
    m = DKRMM(FakeEco())
    m._last_kinds = ["refusal", "retry"]
    state, _, _ = m._classify(_indicators(), _z(guardrail_events=2.0, retry_frequency=2.0))
    assert state is OperationalState.UNSTABLE
    m2 = DKRMM(FakeEco())
    m2._persistence = mon.PERSISTENT                     # value before this assessment
    state2, _, _ = m2._classify(_indicators(), _z(guardrail_events=2.0))
    assert state2 is OperationalState.UNSTABLE


def test_rct_needs_three_kinds_one_confirmed_spread_and_a_statistic():
    hot = dict(guardrail_events=3.0, retry_frequency=3.0, task_switching=3.0)
    m = DKRMM(FakeEco())
    m._last_kinds = ["refusal"]
    m._severity.extend([30.0] + [10.0 / r for r in range(2, 13)])   # a dragon king
    state, kinds, _ = m._classify(_indicators(propagation=0.5), _z(**hot))
    assert len(kinds) == 3 and state is OperationalState.RCT
    # the same with spread just below one half is not an RCT
    state_low, _, _ = m._classify(_indicators(propagation=0.49), _z(**hot))
    assert state_low is not OperationalState.RCT
    # and without either statistic it is not an RCT either
    m3 = DKRMM(FakeEco())
    m3._last_kinds = ["refusal"]
    state_no_stat, _, _ = m3._classify(_indicators(propagation=0.9), _z(**hot))
    assert state_no_stat is not OperationalState.RCT


def test_stable_after_an_escalated_state_is_recovery_and_resets_persistence():
    m = DKRMM(FakeEco())
    m.assess(1)
    m.current.state = OperationalState.UNSTABLE
    m._persistence = 5
    a = m.assess(21)                 # empty window: low activity, computed STABLE
    assert a.state is OperationalState.RECOVERY
    assert m._persistence == 0
    b = m.assess(41)
    assert b.state is OperationalState.STABLE            # RECOVERY is not escalated


def test_persistence_counts_non_stable_assessments_and_feeds_the_next_window():
    m = DKRMM(FakeEco())
    m._persistence = 2
    a = m.assess(1)                                      # computed STABLE (empty)
    assert a.indicators.persistence_of_deviation == 2.0  # value passed in: before update
    assert m._persistence == 0


def test_persistence_increments_on_each_non_stable_assessment():
    # a deviating window twice in a row, through assess
    eco = FakeEco(roster=4)
    m2 = DKRMM(eco).attach()
    for name in INDICATOR_NAMES:
        m2._series[name].extend([0.0] * 4)
    for t in (1, 21):
        for _ in range(30):
            eco.listeners[0](ev(t, "parcel_refused", "A0"))
        m2.assess(t)
    assert m2.history[0].state is not OperationalState.STABLE
    assert m2._persistence == 2


def test_rct_is_refused_without_a_confirmed_kind_or_with_only_two_kinds():
    hot3 = dict(guardrail_events=3.0, retry_frequency=3.0, task_switching=3.0)
    m = DKRMM(FakeEco())
    m._last_kinds = []                                   # nothing to confirm
    m._severity.extend([30.0] + [10.0 / r for r in range(2, 13)])
    state, kinds, _ = m._classify(_indicators(propagation=0.9), _z(**hot3))
    assert len(kinds) == 3 and state is not OperationalState.RCT
    m._last_kinds = ["refusal", "retry"]
    state2, kinds2, _ = m._classify(_indicators(propagation=0.9),
                                    _z(guardrail_events=3.0, retry_frequency=3.0))
    assert len(kinds2) == 2 and state2 is OperationalState.UNSTABLE   # not RCT


def test_no_kind_with_enough_activity_is_stable_and_the_activity_boundary_is_24():
    m = DKRMM(FakeEco())
    state, kinds, _ = m._classify(_indicators(events=100), _z())
    assert state is OperationalState.STABLE and kinds == []
    hot = _z(guardrail_events=5.0)
    assert m._classify(_indicators(events=23), hot)[0] is OperationalState.STABLE
    assert m._classify(_indicators(events=24), hot)[0] is OperationalState.DEVIATING


def test_the_previous_kind_set_is_the_last_assessment_s():
    eco = FakeEco(roster=4)
    m = DKRMM(eco).attach()
    for name in INDICATOR_NAMES:
        m._series[name].extend([0.0] * 4)
    for _ in range(30):
        eco.listeners[0](ev(1, "parcel_refused", "A0"))
    a = m.assess(1)
    assert "refusal" in a.kinds and m._last_kinds == a.kinds
    b = m.assess(200)                                    # empty window: low activity
    assert b.kinds == [] and m._last_kinds == []


def test_task_creation_keeps_the_first_tick_and_prunes_the_oldest_half():
    eco = FakeEco()
    m = DKRMM(eco).attach()
    observe = eco.listeners[0]
    observe(ev(5, "task_created", task_id="T1"))
    observe(ev(9, "task_created", task_id="T1"))         # second sighting ignored
    observe(ev(7, "task_created", task_id=""))           # empty id ignored
    assert m._created == {"T1": 5}
    for i in range(2, 4002):                             # 4001 keys in total
        observe(ev(10, "task_created", task_id=f"T{i}"))
    # the 4001st key pushed the map over 4000: the 2000 earliest-inserted went
    assert len(m._created) == 2001
    # keys T1..T4001 were inserted in order; T1..T2000 are the earliest 2000
    assert "T1" not in m._created and "T2000" not in m._created
    assert "T2001" in m._created and "T4001" in m._created
