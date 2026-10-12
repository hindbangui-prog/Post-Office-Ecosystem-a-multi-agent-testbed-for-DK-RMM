"""
The DK-RMM operational and early-warning indicators (design of 2026-10-12;
docs/dkrmm-mathematics.md, section 21), one focused test per item of the
brief, on hand-built events and a small fake ecosystem. No simulation runs:
every input is written out in the test and every expected number is worked
out by hand from the formula.

The fake ecosystems: `FakeEco` is the three things DKRMM reads from a run
(logger, roster, clock), copied from tests/test_dkrmm_math.py; `StateEco`
adds the building `operations.snapshot_state` reads (parcels and their zones,
stations, storage, departures, the fleet, the task counts, the generator, the
bus's held list and directory), so the state-read indicators can be driven.
"""

from __future__ import annotations

import copy
from types import MappingProxyType, SimpleNamespace

import pytest

from post_office.api.digest import indicator_rows, monitor_digest
from post_office.communication.topics import REFUSAL_TOPICS, SWITCH_TOPICS
from post_office.dkrmm import monitor as mon
from post_office.dkrmm.indicators import (BASE_INDICATORS, DERIVED_INDICATORS,
                                          INDICATOR_META, INDICATOR_NAMES,
                                          INDICATORS,
                                          INTAKE_REJECTION_TOPICS,
                                          MESSAGE_REFUSAL_TOPICS,
                                          RESOURCE_DENIAL_TOPICS,
                                          compute_indicators, percentile)
from post_office.dkrmm.monitor import DKRMM, deviates, directional
from post_office.dkrmm.operations import snapshot_state
from post_office.dkrmm.states import OperationalState

TWELVE = ("message_frequency", "interaction_density", "delegation_frequency",
          "retry_frequency", "guardrail_events", "tool_call_frequency",
          "task_switching", "execution_latency", "agent_coupling",
          "behavioural_similarity", "persistence_of_deviation",
          "propagation_across_agents")


# ------------------------------------------------------------------ helpers
def ev(tick, topic, actor="", target="", **detail):
    return SimpleNamespace(tick=tick, topic=topic, actor=actor, target=target,
                           detail=detail)


class FakeEco:
    """The three things DKRMM reads from an ecosystem: logger, roster, clock."""

    def __init__(self, roster=4):
        self.agents = {f"A{i}": None for i in range(roster)}
        self.world = SimpleNamespace(tick=0)
        self.listeners = []
        self.emitted = 0
        self.logger = SimpleNamespace(subscribe=self._subscribe, emit=self._emit)

    def _subscribe(self, fn):
        self.listeners.append(fn)
        return lambda: self.listeners.remove(fn)

    def _emit(self, *args, **kwargs):
        self.emitted += 1


class Zone:
    def __init__(self, value):
        self.value = value


def parcel(zone, carried=False):
    """A parcel as the snapshot reads it: a position (None when on a robot) and a zone."""
    return SimpleNamespace(position=None if carried else (1, 1),
                           current_zone=Zone(zone))


class Directory:
    """`all()` records with `agent_id`/`parent_id`, and a pure `may_send`."""

    def __init__(self, records, allowed):
        self._records = tuple(SimpleNamespace(agent_id=a, parent_id=p) for a, p in records)
        self._allowed = frozenset(allowed)

    def all(self):
        return self._records

    def may_send(self, a, b):
        return ((a, b) in self._allowed, "")


class StateEco(FakeEco):
    """
    `FakeEco` plus the building: exactly the attributes
    `operations.snapshot_state` reads, each settable by a test.
    """

    def __init__(self, roster=4, parcels=None, robots=3, available=2, needing=0,
                 stations=None, storage=(2, 10), routes=("R1", "R2"), bay=None,
                 max_on_dock=26, refused=0, held=(), tasks=None,
                 directory=None):
        super().__init__(roster)
        parcels = dict(parcels or {})
        self.env = SimpleNamespace(
            parcels=parcels,
            parcels_in=lambda zone: sum(
                1 for p in parcels.values()
                if p.position is not None and p.current_zone.value == zone),
            stations=dict(stations if stations is not None
                          else {"S1": SimpleNamespace(occupant="R1"),
                                "S2": SimpleNamespace(occupant=None)}),
            storage=SimpleNamespace(used=storage[0], capacity=storage[1]),
            departures=SimpleNamespace(routes=list(routes), _bay=dict(bay or {})))
        self.fleet = _Fleet(robots, available, needing)
        self.world = SimpleNamespace(tick=0, tasks=SimpleNamespace(
            counts=lambda: dict(tasks if tasks is not None
                                else {"PENDING": 2, "COMPLETED": 5, "FAILED": 1})))
        self.generator = SimpleNamespace(refused=refused, max_on_dock=max_on_dock)
        self.bus = SimpleNamespace(
            _held=list(held),
            directory=directory if directory is not None else Directory(
                [("A0", None), ("A1", "A0"), ("A2", "A0"), ("A3", "A1")],
                [("A0", "A1"), ("A1", "A0"), ("A0", "A2"), ("A2", "A0"),
                 ("A1", "A3"), ("A3", "A1"), ("A1", "A2")]))


class _Fleet:
    def __init__(self, roster, available, needing):
        self._roster = roster
        self._available = available
        self._needing = needing

    def __len__(self):
        return self._roster

    def available(self):
        return [f"R{i}" for i in range(self._available)]

    def needing_charge(self):
        return [f"R{i}" for i in range(self._needing)]


def _indicators(events=100, propagation=0.0):
    x = compute_indicators([], ticks=60, roster=28)
    x.events = events
    x.propagation_across_agents = propagation
    return x


def _z(**hot):
    z = {name: 0.0 for name in INDICATOR_NAMES}
    z.update(hot)
    return z


def _fed(eco, events):
    for event in events:
        eco.listeners[0](event)


def _messages(n, sender="A0", receiver="A1", topic="message", ticks=10):
    """`n` messages spread over ticks 1..`ticks`."""
    return [ev(1 + (i % ticks), topic, sender, receiver) for i in range(n)]


# ---------------------------------------------------- 1. message_frequency
def test_message_frequency_counts_attempted_sends_and_a_fall_needs_corroboration():
    assert INDICATOR_META["message_frequency"]["direction"] == "both"
    assert "message_frequency" in mon.CORROBORATED_FALL
    # Attempts of either topic: 20 `message` and 10 `subagent_message`.
    window = _messages(20) + _messages(10, "SUB-X", "A0", "subagent_message")
    x = compute_indicators(window, ticks=10, roster=4)
    assert x.counts["messages"] == 30 == x.counts["attempted"]
    assert x.message_frequency == pytest.approx(30 / 10)

    # Window A: the rate falls from a flat baseline of 10 per tick to 3 per
    # tick (z = -3 on the flat branch, signed by the fall) and nothing
    # operational is off: no chatter kind.
    eco = FakeEco(roster=4)
    m = DKRMM(eco).attach()
    m._series["message_frequency"].extend([10.0] * 4)
    _fed(eco, window)
    a = m.assess(10)
    assert a.z["message_frequency"] == -3.0
    assert a.deviation["message_frequency"] == "down"
    assert "chatter" not in a.kinds and a.kinds == []
    assert a.in_evidence["message_frequency"] is None

    # Window B: the same fall, with ten of the thirty messages dropped
    # (delivery failure from a flat zero baseline): chatter counts.
    eco2 = FakeEco(roster=4)
    m2 = DKRMM(eco2).attach()
    m2._series["message_frequency"].extend([10.0] * 4)
    m2._series["communication_failure_rate"].extend([0.0] * 4)
    _fed(eco2, window + [ev(t, "message_dropped", "A0", "A1") for t in range(1, 11)])
    b = m2.assess(10)
    assert b.z["message_frequency"] == -3.0
    assert b.kinds == ["chatter", "delivery"]
    assert b.in_evidence["message_frequency"] == "chatter"


# -------------------------------------------------- 2. interaction_density
def test_interaction_density_divides_by_active_times_active_minus_one():
    events = [ev(1, "message", "A0", "A1"), ev(1, "message", "A1", "A2"),
              ev(2, "blocked", "A2"),                 # active without messaging
              ev(2, "message", "A0", "A3")]           # A3 only a target: not active
    x = compute_indicators(events, ticks=2, roster=6)
    assert x.active_agents == 3                       # A0, A1, A2 emitted something
    assert x.interaction_density == pytest.approx(3 / (3 * 2))
    assert compute_indicators([ev(1, "message", "A0", "A1")], ticks=1).interaction_density == 0.0


# ----------------------------------------------- 3. delegation vs tool call
def test_delegation_is_down_to_a_sub_agent_and_a_tool_call_is_from_one():
    x = compute_indicators([
        ev(1, "message", "A0", "SUB-X"),                  # delegation
        ev(1, "subagent_message", "SUB-X", "A0"),         # tool call
        ev(1, "subagent_message", "SUB-X", "SUB-Y"),      # sender is a sub-agent: tool call
        ev(1, "message", "A0", "A1"),                     # expert to expert: neither
        ev(1, "message", "A1", "A0"),
    ], ticks=1, roster=4)
    assert x.counts["delegations"] == 1
    assert x.counts["tool_calls"] == 2
    assert x.counts["messages"] == 5
    assert x.delegation_frequency == pytest.approx(1 / 1)
    assert x.tool_call_frequency == pytest.approx(2 / 1)


# ------------------------------------------------------ 4. guardrail split
def test_the_guardrail_split_partitions_the_refusal_topics_and_sums_to_refusals():
    parts = (INTAKE_REJECTION_TOPICS, RESOURCE_DENIAL_TOPICS, MESSAGE_REFUSAL_TOPICS)
    assert frozenset().union(*parts) == REFUSAL_TOPICS
    for topic in REFUSAL_TOPICS:
        assert sum(topic in part for part in parts) == 1, topic
    events = [ev(1, topic, "A0") for topic in sorted(REFUSAL_TOPICS)]
    events += [ev(2, "decision", "A1", validation="policy"),
               ev(2, "decision", "A2", validation="state"),
               ev(2, "decision", "A3", validation="schema"),
               ev(2, "decision", "A3", validation="ok")]
    x = compute_indicators(events, ticks=2, roster=4)
    c = x.counts
    assert c["intake_rejections"] == len(INTAKE_REJECTION_TOPICS)
    assert c["resource_denials"] == len(RESOURCE_DENIAL_TOPICS)
    assert c["message_refusals"] == len(MESSAGE_REFUSAL_TOPICS)
    assert c["gate_rejections"] == 2
    assert "other_refusals" not in c
    assert (c["gate_rejections"] + c["intake_rejections"] + c["resource_denials"]
            + c["message_refusals"]) == c["refusals"] == len(REFUSAL_TOPICS) + 2
    assert c["malformed_decisions"] == 1
    assert x.guardrail_events == pytest.approx(c["refusals"] / 2)


# --------------------------------------------------------- 5. task_switching
def test_task_switching_counts_exactly_the_switch_topics():
    events = [ev(1, topic, "A0") for topic in sorted(SWITCH_TOPICS)]
    events += [ev(1, "blocked", "A0"), ev(1, "message", "A0", "A1"),
               ev(1, "task_completed", "A0")]
    x = compute_indicators(events, ticks=5, roster=2)
    assert x.counts["switches"] == len(SWITCH_TOPICS)
    assert x.task_switching == pytest.approx(len(SWITCH_TOPICS) / 5)
    assert compute_indicators([ev(1, "blocked", "A0")], ticks=5).task_switching == 0.0


# ---------------------------------------------- 6. execution_latency and p95
def test_execution_latency_is_the_mean_wait_and_its_p95_is_nearest_rank():
    created = {f"T{i}": 0 for i in range(1, 21)}
    events = [ev(i, "task_started", "A0", task_id=f"T{i}") for i in range(1, 21)]
    x = compute_indicators(events, ticks=20, roster=1, created=created)
    assert x.detail["waits"] == list(range(1, 21))
    assert x.execution_latency == pytest.approx(sum(range(1, 21)) / 20)      # 10.5
    assert x.detail["execution_latency_p95"] == 19         # ceil(0.95 * 20) = 19th of 20
    assert percentile(list(range(1, 21)), 0.95) == 19
    assert percentile([7.0], 0.95) == 7.0
    assert percentile([], 0.95) is None


# ---------------------------------------------------------- 7. agent_coupling
def test_agent_coupling_is_the_active_agent_fraction_and_says_so():
    events = [ev(1, "message", "A0", "A1"), ev(1, "blocked", "A2")]
    x = compute_indicators(events, ticks=1, roster=8)
    assert x.active_agents == 2
    assert x.agent_coupling == pytest.approx(2 / 8)
    assert "active-agent fraction" in INDICATOR_META["agent_coupling"]["about"]
    assert "not a coupling measure" in INDICATOR_META["agent_coupling"]["about"]


# ----------------------------------------------- 8. behavioural_similarity
def test_behavioural_similarity_is_two_sided_and_its_fall_needs_corroboration():
    assert INDICATOR_META["behavioural_similarity"]["direction"] == "both"
    assert "behavioural_similarity" in mon.CORROBORATED_FALL
    m = DKRMM(FakeEco())
    kinds, _, _, _ = m._evidence(_indicators(), _z(behavioural_similarity=-2.0))
    assert kinds == []
    kinds, _, hits, _ = m._evidence(_indicators(), _z(behavioural_similarity=-2.0,
                                                      communication_failure_rate=2.0))
    assert kinds == ["herding", "delivery"]
    assert hits["behavioural_similarity"] == "herding"
    kinds, _, _, _ = m._evidence(_indicators(), _z(behavioural_similarity=2.0))
    assert kinds == ["herding"]
    assert deviates("behavioural_similarity", -2.0) == "down"
    assert deviates("behavioural_similarity", 2.0) == "up"


# ------------------------------------------------ 9. persistence_of_deviation
def test_persistence_of_deviation_is_the_passed_in_value_and_is_derived():
    x = compute_indicators([ev(1, "blocked", "A0")], ticks=1, persistence=7)
    assert x.persistence_of_deviation == 7.0
    assert compute_indicators([], ticks=1).persistence_of_deviation == 0.0
    assert "persistence_of_deviation" in DERIVED_INDICATORS
    assert INDICATOR_META["persistence_of_deviation"]["kind"] == "derived"


# ------------------------------------------------- 10. propagation population
def test_propagation_divides_by_acting_agents_and_counts_dropped_senders_and_late_receivers():
    events = [
        ev(1, "message", "A0", "A1"),
        ev(2, "message_dropped", "A0", "A1"),                 # A0: acting (not a message topic), affected
        ev(1, "message", "A1", "A0"),                         # A1: message only, not acting
        ev(3, "agent_message_received", "A3", "A2", late_by=5),  # A2 waited: affected if it acted
        ev(3, "task_started", "A2", task_id="T1"),            # A2 acted
        ev(3, "message", "A3", "A2"),                         # A3 also messaged
        ev(4, "task_completed", "A4"),                        # A4: acting, not affected
        ev(4, "agent_message_received", "A3", "A5", late_by=2),  # A5 waited but did nothing: not acting
    ]
    x = compute_indicators(events, ticks=4, roster=6)
    # Acting = actor of any non-message topic: A0 (message_dropped), A2
    # (task_started), A3 (the sender named as actor of the late-delivery
    # events), A4 (task_completed). A1 only sent a message; A5 only waited.
    assert x.acting_agents == 4
    assert x.active_agents == 5                               # A1 too, A5 never an actor
    assert x.propagation_across_agents == pytest.approx(2 / 4)   # A0 and A2 affected
    # A late receiver that is on time is not affected.
    y = compute_indicators([ev(1, "agent_message_received", "A3", "A2", late_by=0),
                            ev(1, "task_started", "A2", task_id="T1")], ticks=1)
    assert y.propagation_across_agents == 0.0


# ------------------------------------------- 11. communication_failure_rate
def test_communication_failure_rate_is_dropped_plus_late_over_attempted_clamped():
    window = _messages(10) + [ev(2, "message_dropped", "A0", "A1")] * 3
    window += [ev(3, "agent_message_received", "A0", "A1", late_by=4),
               ev(3, "agent_message_received", "A0", "A1", late_by=1),
               ev(3, "agent_message_received", "A0", "A1", late_by=0)]   # on time
    x = compute_indicators(window, ticks=10, roster=2)
    assert x.counts["attempted"] == 10 and x.counts["dropped"] == 3 and x.counts["late"] == 2
    assert x.counts["delivered"] == 7
    assert x.communication_failure_rate == pytest.approx((3 + 2) / 10)
    assert x.evaluable["communication_failure_rate"] is True
    assert x.detail["delivery"]["late_by"] == [4, 1]
    # Clamped: three drops against two attempts (a window-edge artefact).
    edge = compute_indicators(_messages(2) + [ev(1, "message_dropped", "A0", "A1")] * 3, ticks=10)
    assert edge.communication_failure_rate == 1.0
    assert edge.detail["delivery"]["raw_rate"] == pytest.approx(1.5)
    assert edge.counts["delivered"] == 0
    # Nothing attempted: not evaluable, value 0 by convention.
    none = compute_indicators([ev(1, "blocked", "A0")], ticks=10)
    assert none.evaluable["communication_failure_rate"] is False
    assert none.communication_failure_rate == 0.0
    assert INDICATOR_META["communication_failure_rate"]["direction"] == "up"


# ---------------------------------------------------------- 12. backlog_growth
def test_backlog_growth_is_the_change_per_tick_since_the_previous_assessment():
    eco = StateEco(parcels={"P1": parcel("INTAKE"), "P2": parcel("SORTING")})
    m = DKRMM(eco).attach()
    assert m.every == mon.EVERY == 20
    first = m.assess(1)
    assert first.evaluable["backlog_growth"] is False
    assert first.indicators.detail["backlog"]["backlog_prev"] is None
    assert first.indicators.detail["backlog"]["backlog_now"] == 2

    for i in range(3, 9):                                     # six more: 8 in the building
        eco.env.parcels[f"P{i}"] = parcel("INTAKE")
    second = m.assess(21)
    assert second.evaluable["backlog_growth"] is True
    assert second.indicators.backlog_growth == pytest.approx((8 - 2) / 20)
    assert second.indicators.detail["backlog"]["increasing_for"] == 1
    assert second.indicators.detail["backlog"]["acceleration"] is None   # no previous growth

    eco.env.parcels["P9"] = parcel("DISPATCH")                # 9: growth 1/20
    third = m.assess(41)
    assert third.indicators.backlog_growth == pytest.approx(1 / 20)
    assert third.indicators.detail["backlog"]["increasing_for"] == 2
    assert third.indicators.detail["backlog"]["acceleration"] == pytest.approx(1 / 20 - 6 / 20)
    assert "backlog_growth" in DERIVED_INDICATORS


# ----------------------------------------------------- 13. task_completion_rate
def test_task_completion_rate_is_parcels_departed_per_tick_and_the_gap_is_demand_minus_it():
    events = [ev(2, "van_departed", "DISPATCH", parcels=3),
              ev(7, "van_departed", "DISPATCH", parcels=2),
              ev(9, "van_departed", "DISPATCH", parcels=0)]
    events += [ev(t, "parcel_arrived", "INTAKE") for t in range(1, 5)]
    events += [ev(5, "arrival_refused", "INTAKE"), ev(6, "arrival_refused", "INTAKE")]
    events += [ev(8, "task_completed", "A0")]
    x = compute_indicators(events, ticks=10, roster=3)
    assert x.counts["parcels_out"] == 5
    assert x.task_completion_rate == pytest.approx(5 / 10)
    assert x.detail["throughput"]["incoming_per_tick"] == pytest.approx((4 + 2) / 10)
    assert x.completion_gap == pytest.approx(6 / 10 - 5 / 10)
    assert x.detail["throughput"]["tasks_completed_per_tick"] == pytest.approx(1 / 10)
    assert x.evaluable["task_completion_rate"] is True
    assert compute_indicators([], ticks=10).evaluable["task_completion_rate"] is True
    assert INDICATOR_META["task_completion_rate"]["direction"] == "down"
    assert INDICATOR_META["completion_gap"]["direction"] == "up"


# ------------------------------------------------------- 14. resource_saturation
def test_resource_saturation_is_the_tightest_category_and_each_is_recorded():
    eco = StateEco(parcels={f"P{i}": parcel("INTAKE") for i in range(13)},   # dock 13 of 26
                   robots=4, available=1,                                     # robots 3/4
                   stations={"S1": SimpleNamespace(occupant="R1"),
                             "S2": SimpleNamespace(occupant=None),
                             "S3": SimpleNamespace(occupant=None),
                             "S4": SimpleNamespace(occupant=None)},           # 1/4
                   storage=(9, 10),                                           # 0.9
                   routes=("R1", "R2"), bay={"R1": "van"})                    # 1 of 2 closed
    snap = snapshot_state(eco)
    res = snap["resources"]
    assert res["robots"]["value"] == pytest.approx(0.75)
    assert res["charge_points"]["value"] == pytest.approx(0.25)
    assert res["routes"]["value"] == pytest.approx(0.5)
    assert res["storage"]["value"] == pytest.approx(0.9)
    assert res["dock"]["value"] == pytest.approx(13 / 26)
    assert snap["resource_saturation"] == pytest.approx(0.9)
    x = compute_indicators([ev(1, "blocked", "A0")], ticks=1, snapshot=snap)
    assert x.resource_saturation == pytest.approx(0.9)
    assert x.evaluable["resource_saturation"] is True
    assert set(x.detail["resources"]) == {"robots", "charge_points", "routes", "storage", "dock"}
    assert all("value" in row for row in x.detail["resources"].values())

    # No fleet: nothing to say.
    empty = snapshot_state(StateEco(robots=0, available=0))
    assert empty["resource_saturation"] is None
    y = compute_indicators([], ticks=1, snapshot=empty)
    assert y.evaluable["resource_saturation"] is False and y.resource_saturation == 0.0

    # No charge point at all and a robot needing one: that category is 1.0.
    starved = snapshot_state(StateEco(stations={}, robots=3, available=3, needing=1))
    assert starved["resources"]["charge_points"]["value"] == 1.0
    assert starved["resource_saturation"] == 1.0
    fine = snapshot_state(StateEco(stations={}, robots=3, available=3, needing=0))
    assert fine["resources"]["charge_points"]["value"] == 0.0


# ------------------------------------------- 15. dependency_graph_divergence
def test_dependency_graph_divergence_is_one_minus_weighted_jaccard_against_the_baseline():
    eco = StateEco()
    m = DKRMM(eco).attach()
    same = [ev(1, "message", "A0", "A1"), ev(1, "message", "A0", "A1"),
            ev(2, "message", "A1", "A0"), ev(3, "blocked", "A2")]
    _fed(eco, same)
    first = m.assess(3)
    assert first.evaluable["dependency_graph_divergence"] is False      # no baseline window yet
    assert first.indicators.detail["structure"]["baseline_windows"] == 0

    _fed(eco, [ev(t + 100, e.topic, e.actor, e.target) for t, e in zip(range(1, 5), same)])
    second = m.assess(104)                                              # identical edge map
    assert second.evaluable["dependency_graph_divergence"] is True
    assert second.indicators.dependency_graph_divergence == pytest.approx(0.0)
    assert second.indicators.detail["structure"]["missing"] == []
    assert second.indicators.detail["structure"]["unexpected"] == []

    # Disjoint: A1 -> A2 is declared, A2 -> A3 is not; both baseline edges are gone.
    _fed(eco, [ev(201, "message", "A1", "A2"), ev(202, "message", "A2", "A3")])
    third = m.assess(202)
    assert third.indicators.dependency_graph_divergence == pytest.approx(1.0)
    assert third.indicators.detail["structure"]["unexpected"] == [["A2", "A3"]]
    assert third.indicators.detail["structure"]["missing"] == [["A0", "A1"], ["A1", "A0"]]
    assert "dependency_graph_divergence" in DERIVED_INDICATORS


# --------------------------------------------- 16. activity_synchronization
def test_activity_synchronization_is_the_mean_pairwise_correlation_of_per_tick_counts():
    def series(agent, counts):
        return [ev(t, "blocked", agent) for t, n in enumerate(counts, start=1) for _ in range(n)]

    identical = series("A0", [1, 2, 1, 2]) + series("A1", [1, 2, 1, 2])
    assert compute_indicators(identical, ticks=4).activity_synchronization == pytest.approx(1.0)
    anti = series("A0", [1, 2, 1, 2]) + series("A1", [2, 1, 2, 1])
    y = compute_indicators(anti, ticks=4)
    assert y.activity_synchronization == pytest.approx(-1.0)
    assert y.evaluable["activity_synchronization"] is True
    alone = compute_indicators(series("A0", [1, 2, 1, 2]), ticks=4)
    assert alone.evaluable["activity_synchronization"] is False
    assert alone.activity_synchronization == 0.0
    assert INDICATOR_META["activity_synchronization"]["direction"] == "both"


# ------------------------------------------------------------ 17. tail_deviation
def test_tail_deviation_is_p95_now_over_the_median_baseline_p95():
    m = DKRMM(FakeEco())
    x = compute_indicators([], ticks=10)
    x.detail["waits"] = [5.0] * 18 + [20.0] * 2                 # p95 = 19th of 20 sorted = 20
    m._tails["task_wait"].extend([8.0, 10.0, 12.0, 100.0])      # median 11, four points
    m._fill_tail_deviation(x, {"by_zone": {}})
    assert x.evaluable["tail_deviation"] is True
    assert x.tail_deviation == pytest.approx(20.0 / 11.0)
    row = x.detail["tail"]["task_wait"]
    assert row["p95_now"] == 20.0 and row["p95_baseline"] == 11.0
    assert row["ratio"] == pytest.approx(20.0 / 11.0)
    assert x.detail["tail"]["message_delay"]["note"] == "no values this window"

    short = DKRMM(FakeEco())
    short._tails["task_wait"].extend([10.0] * (mon.TAIL_MIN_BASELINE - 1))
    y = compute_indicators([], ticks=10)
    y.detail["waits"] = [20.0]
    short._fill_tail_deviation(y, {"by_zone": {}})
    assert y.evaluable["tail_deviation"] is False
    assert y.detail["tail"]["task_wait"]["note"] == "baseline too short"

    zero = DKRMM(FakeEco())
    zero._tails["zone_backlog"].extend([0.0] * mon.TAIL_MIN_BASELINE)
    w = compute_indicators([], ticks=10)
    zero._fill_tail_deviation(w, {"by_zone": {"INTAKE": 3}})
    assert w.detail["tail"]["zone_backlog"]["note"] == "baseline zero"
    assert w.detail["tail"]["zone_backlog"]["ratio"] is None
    assert w.evaluable["tail_deviation"] is False
    assert "tail_deviation" in DERIVED_INDICATORS
    assert "tail_deviation" in mon.EVIDENCE["congestion"] and "tail" not in mon.EVIDENCE


# ----------------------------------------------------------- 18. the registry
def test_base_and_derived_partition_the_registry_and_the_twelve_lead_it():
    assert len(INDICATOR_NAMES) == 20
    assert set(BASE_INDICATORS) | set(DERIVED_INDICATORS) == set(INDICATOR_NAMES)
    assert set(BASE_INDICATORS) & set(DERIVED_INDICATORS) == set()
    assert INDICATOR_NAMES[:12] == TWELVE
    assert tuple(name for name, _about in INDICATORS) == INDICATOR_NAMES
    for name, about in INDICATORS:
        meta = INDICATOR_META[name]
        assert set(meta) == {"kind", "direction", "about"}
        assert meta["kind"] in ("base", "derived")
        assert meta["direction"] in ("up", "down", "both")
        assert meta["about"] == about and about
    assert set(DERIVED_INDICATORS) == {"persistence_of_deviation", "propagation_across_agents",
                                       "backlog_growth", "dependency_graph_divergence",
                                       "tail_deviation"}


# ------------------------------------------------ 19. direction-aware evidence
def test_evidence_is_direction_aware():
    assert INDICATOR_META["retry_frequency"]["direction"] == "up"
    assert deviates("retry_frequency", -3.0) == "none"
    assert deviates("retry_frequency", 3.0) == "up"
    assert deviates("task_completion_rate", -3.0) == "down"
    assert deviates("task_completion_rate", 3.0) == "none"
    assert deviates("activity_synchronization", -3.0) == "down"
    assert deviates("activity_synchronization", 3.0) == "up"
    assert deviates("retry_frequency", mon.DEVIATION_Z - 0.01) == "none"
    m = DKRMM(FakeEco())
    assert m._evidence(_indicators(), _z(retry_frequency=-3.0))[0] == []
    assert m._evidence(_indicators(), _z(task_completion_rate=-3.0))[0] == ["throughput"]
    assert m._evidence(_indicators(), _z(task_completion_rate=3.0))[0] == []
    assert m._evidence(_indicators(), _z(activity_synchronization=-3.0))[0] == ["synchrony"]
    assert m._evidence(_indicators(), _z(activity_synchronization=3.0))[0] == ["synchrony"]


# ------------------------------------------------------ 20. directional severity
def test_severity_counts_a_fall_of_a_down_indicator_over_all_twenty_names():
    assert directional("task_completion_rate", -3.0) == 3.0
    assert directional("task_completion_rate", 3.0) == 0.0
    assert directional("retry_frequency", -3.0) == 0.0
    assert directional("message_frequency", -3.0) == 3.0
    eco = FakeEco(roster=4)
    m = DKRMM(eco).attach()
    m._series["task_completion_rate"].extend([1.0] * 4)   # parcels used to leave
    _fed(eco, [ev(1 + (i % 10), "task_completed", "A0") for i in range(30)])   # none leave now
    a = m.assess(10)
    assert a.z["task_completion_rate"] == -3.0
    assert a.deviation["task_completion_rate"] == "down"
    assert a.kinds == ["throughput"]
    assert len(INDICATOR_NAMES) == 20
    assert a.severity == pytest.approx(3.0 / len(INDICATOR_NAMES))


# ---------------------------------------------------------- 21. baseline learning
def test_a_formed_baseline_learns_from_stable_windows_and_not_from_unstable_ones():
    refusals = [ev(1 + (i % 10), "parcel_refused", "A0") for i in range(30)]
    # Formed (baseline=4 holds four points) and the window is UNSTABLE by
    # persistence: the reading does not enter the series.
    eco = FakeEco(roster=4)
    m = DKRMM(eco, baseline=4).attach()
    m._series["guardrail_events"].extend([0.0] * 4)
    m._persistence = mon.PERSISTENT
    _fed(eco, refusals)
    a = m.assess(10)
    assert a.state is OperationalState.UNSTABLE
    assert list(m._series["guardrail_events"]) == [0.0] * 4
    assert len(m._series["guardrail_events"]) == 4
    # A STABLE window enters it: the value (0.0 refusals) replaces the oldest.
    eco2 = FakeEco(roster=4)
    m2 = DKRMM(eco2, baseline=4).attach()
    m2._series["guardrail_events"].extend([0.1, 0.2, 0.3, 0.4])
    _fed(eco2, [ev(1 + (i % 10), "task_completed", "A0") for i in range(30)])
    b = m2.assess(10)
    assert b.state is OperationalState.STABLE
    assert list(m2._series["guardrail_events"]) == [0.2, 0.3, 0.4, 0.0]
    # Not evaluable values never enter: nothing was attempted on the bus.
    assert b.evaluable["communication_failure_rate"] is False
    assert len(m2._series["communication_failure_rate"]) == 0
    assert len(m._series["communication_failure_rate"]) == 0
    # Until a baseline holds its full complement it learns from every window,
    # UNSTABLE ones included: here the delivery baseline is formed and makes
    # the window UNSTABLE (by persistence), the refusal baseline holds three
    # points and still takes the reading; the formed one does not.
    eco3 = FakeEco(roster=4)
    m3 = DKRMM(eco3, baseline=4).attach()
    m3._series["guardrail_events"].extend([0.0] * 3)
    m3._series["communication_failure_rate"].extend([0.0] * 4)
    m3._persistence = mon.PERSISTENT
    _fed(eco3, refusals + _messages(10) + [ev(t, "message_dropped", "A0", "A1") for t in range(1, 6)])
    c = m3.assess(10)
    assert c.state is OperationalState.UNSTABLE and c.kinds == ["delivery"]
    assert c.z["guardrail_events"] == 0.0                     # three points: no z yet
    assert list(m3._series["guardrail_events"]) == [0.0, 0.0, 0.0, 3.0]
    assert list(m3._series["communication_failure_rate"]) == [0.0] * 4
    assert set(mon.BASELINE_LEARNS_FROM) == {OperationalState.STABLE, OperationalState.DEVIATING,
                                             OperationalState.RECOVERY}


# ------------------------------------------------------------- 22. the quiet rule
def test_below_min_activity_only_the_operational_kinds_are_read():
    quiet = _messages(5)                                         # 5 events: far below 24
    eco = FakeEco(roster=4)
    m = DKRMM(eco).attach()
    m._series["communication_failure_rate"].extend([0.0] * 4)
    m._series["message_frequency"].extend([10.0] * 4)
    _fed(eco, quiet + [ev(t, "message_dropped", "A0", "A1") for t in range(1, 6)])
    a = m.assess(10)
    assert a.indicators.events == 10 < mon.MIN_ACTIVITY
    assert a.enough_activity is False
    assert a.not_evaluated == list(mon.BEHAVIOURAL_KINDS)
    assert a.kinds == ["delivery"]
    assert a.state is OperationalState.DEVIATING
    assert a.evidence[0] == "only 10 events in the window; behavioural kinds not evaluated"
    assert a.in_evidence["message_frequency"] is None          # behavioural: not read

    eco2 = FakeEco(roster=4)
    m2 = DKRMM(eco2).attach()
    m2._series["message_frequency"].extend([10.0] * 4)
    _fed(eco2, quiet)
    b = m2.assess(10)
    assert b.state is OperationalState.STABLE and b.kinds == []
    assert b.evidence == ["only 5 events in the window; behavioural kinds not evaluated"]
    assert set(mon.OPERATIONAL_KINDS) | set(mon.BEHAVIOURAL_KINDS) == set(mon.EVIDENCE)


# --------------------------------- 23. no single indicator makes UNSTABLE or RCT
def test_one_kind_in_one_window_is_deviating_and_rct_keeps_its_four_conditions():
    m = DKRMM(FakeEco())
    for hot in (_z(communication_failure_rate=30.0), _z(backlog_growth=9.0),
                _z(resource_saturation=9.0), _z(task_completion_rate=-9.0)):
        state, kinds, _ = m._classify(_indicators(propagation=1.0), hot)
        assert len(kinds) == 1 and state is OperationalState.DEVIATING
    hot3 = dict(communication_failure_rate=3.0, backlog_growth=3.0, resource_saturation=3.0)
    rct = DKRMM(FakeEco())
    rct._last_kinds = ["delivery"]
    rct._severity.extend([30.0] + [10.0 / r for r in range(2, 13)])     # a dragon king
    state, kinds, _ = rct._classify(_indicators(propagation=mon.RCT_PROPAGATION), _z(**hot3))
    assert len(kinds) == mon.RCT_KINDS and state is OperationalState.RCT
    low, _, _ = rct._classify(_indicators(propagation=mon.RCT_PROPAGATION - 0.01), _z(**hot3))
    assert low is OperationalState.DEVIATING        # one confirmed kind, no persistence: not even UNSTABLE
    rct._last_kinds = []                                                 # nothing confirmed
    state2, _, _ = rct._classify(_indicators(propagation=0.9), _z(**hot3))
    assert state2 is not OperationalState.RCT
    rct._last_kinds = ["delivery"]
    two, kinds2, _ = rct._classify(_indicators(propagation=0.9),
                                   _z(communication_failure_rate=3.0, backlog_growth=3.0))
    assert len(kinds2) == 2 and two is not OperationalState.RCT
    flat = DKRMM(FakeEco())                                              # no statistic
    flat._last_kinds = ["delivery"]
    state3, _, _ = flat._classify(_indicators(propagation=0.9), _z(**hot3))
    assert state3 is not OperationalState.RCT


# ------------------------------------------------------------- 24. the observer
class _Sealed:
    """An object whose attributes cannot be set once sealed."""

    def __init__(self, **fields):
        for key, value in fields.items():
            object.__setattr__(self, key, value)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, key, value):
        raise AttributeError(f"the monitor wrote {key}")

    def __delattr__(self, key):
        raise AttributeError(f"the monitor deleted {key}")


def _sealed_eco():
    parcels = MappingProxyType({"P1": _Sealed(position=(1, 1), current_zone=_Sealed(value="INTAKE")),
                                "P2": _Sealed(position=None, current_zone=_Sealed(value="SORTING"))})
    stations = MappingProxyType({"S1": _Sealed(occupant="R1"), "S2": _Sealed(occupant=None)})
    fleet = _Fleet(3, 2, 1)
    directory = Directory([("A0", None), ("A1", "A0")], [("A0", "A1"), ("A1", "A0")])
    return _Sealed(
        agents=MappingProxyType({"A0": None, "A1": None}),
        world=_Sealed(tick=5, tasks=_Sealed(counts=lambda: {"PENDING": 1, "COMPLETED": 2})),
        env=_Sealed(parcels=parcels, parcels_in=lambda zone: 1, stations=stations,
                    storage=_Sealed(used=2, capacity=10),
                    departures=_Sealed(routes=("R1", "R2"), _bay=MappingProxyType({"R1": "van"}))),
        fleet=fleet, generator=_Sealed(refused=0, max_on_dock=26),
        bus=_Sealed(_held=(), directory=directory),
        logger=_Sealed(subscribe=lambda fn: (lambda: None), emit=lambda *a, **k: None))


def test_the_snapshot_writes_nothing_and_an_assessment_emits_nothing():
    sealed = _sealed_eco()
    snap = snapshot_state(sealed)
    assert snap["errors"] == {}
    assert snap["backlog"] == 2 and snap["by_zone"] == {"INTAKE": 1, "carried": 1}
    assert snap["held_now"] == 0 and snap["unfinished_tasks"] == 1
    assert snap["resources"]["routes"]["value"] == pytest.approx(0.5)
    assert snap["declared_edges"] == [("A0", "A1"), ("A1", "A0")]
    # The same on a mutable fake, compared as a deep copy before and after.
    eco = StateEco(parcels={"P1": parcel("INTAKE")}, held=("m1",))
    before = copy.deepcopy(_plain(eco))
    snapshot_state(eco)
    assert _plain(eco) == before
    # And an assessment emits no event and writes nothing to the building.
    m = DKRMM(eco).attach()
    _fed(eco, _messages(30) + [ev(1, "message_dropped", "A0", "A1")])
    m.assess(10)
    m.assess(30)
    assert eco.emitted == 0
    assert _plain(eco) == before
    assert len(eco.listeners) == 1


def _plain(eco):
    """The fake's state as plain data, for before/after comparison."""
    return {
        "agents": dict(eco.agents), "tick": eco.world.tick,
        "parcels": {k: (p.position, p.current_zone.value) for k, p in eco.env.parcels.items()},
        "stations": {k: s.occupant for k, s in eco.env.stations.items()},
        "storage": (eco.env.storage.used, eco.env.storage.capacity),
        "routes": list(eco.env.departures.routes), "bay": dict(eco.env.departures._bay),
        "fleet": (len(eco.fleet), eco.fleet.available(), eco.fleet.needing_charge()),
        "tasks": eco.world.tasks.counts(),
        "generator": (eco.generator.refused, eco.generator.max_on_dock),
        "held": list(eco.bus._held),
        "directory": [(r.agent_id, r.parent_id) for r in eco.bus.directory.all()],
    }


# ------------------------------------------------------------- 25. state words
def test_the_state_vocabulary_is_unchanged_and_learning_states_are_states():
    assert [s.value for s in OperationalState] == ["STABLE", "DEVIATING", "UNSTABLE", "RCT", "RECOVERY"]
    assert set(mon.BASELINE_LEARNS_FROM) <= set(OperationalState)
    assert OperationalState.UNSTABLE not in mon.BASELINE_LEARNS_FROM
    assert OperationalState.RCT not in mon.BASELINE_LEARNS_FROM


# ---------------------------------------------------------- 26. dashboard rows
def test_the_rows_carry_value_baseline_direction_and_status_and_the_digest_says_what_was_seen():
    eco = FakeEco(roster=4)
    m = DKRMM(eco).attach()
    m._series["communication_failure_rate"].extend([0.0] * 4)
    _fed(eco, _messages(5) + [ev(t, "message_dropped", "A0", "A1") for t in range(1, 6)])
    m.assess(10)
    rows = {row["name"]: row for row in indicator_rows(m)}
    assert list(rows) == list(INDICATOR_NAMES)
    for name, row in rows.items():
        assert {"name", "value", "baseline", "direction", "status"} <= set(row)
        assert row["direction"] == INDICATOR_META[name]["direction"]
        if row["evaluable"]:
            assert isinstance(row["value"], float) and row["status"] != "n/a"
        else:
            assert row["value"] is None and row["status"] == "n/a"
    assert rows["resource_saturation"]["status"] == "n/a"          # no building to read
    assert rows["communication_failure_rate"]["status"] == "deviating up"
    assert rows["communication_failure_rate"]["baseline"] == 0.0
    assert rows["communication_failure_rate"]["value"] == pytest.approx(1.0)
    assert rows["message_frequency"]["baseline"] is None             # fewer than four points
    digest = monitor_digest(m)
    assert digest["observed"] == "delivery observed; behavioural kinds not evaluated"
    assert digest["kinds"] == ["delivery"]
    assert digest["not_evaluated"] == list(mon.BEHAVIOURAL_KINDS)
