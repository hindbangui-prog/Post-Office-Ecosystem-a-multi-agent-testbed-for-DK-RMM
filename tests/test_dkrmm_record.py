"""
The run-level DK-RMM artifact.

What is being pinned here is a reading, not a calculation: `record.py` computes
no indicator and decides no state. It transposes what the monitor already
produced and writes down the order things happened in, because the order is
what a Dragon-King reading turns on and the order is the part that is easy to
lose when a run is summarised.

The one test that matters most is the last section's: two runs of one
configuration, one perturbed and one not, both reaching UNSTABLE on their own.
That is what the facility does under load, and it is why a state reached in a
single run is not a finding.
"""

from __future__ import annotations

import json
import os
import tempfile

from post_office.dkrmm import (build_record, compare_records, series_of,
                               states_of, transitions_of, write_record)
from post_office.dkrmm.indicators import BehaviouralIndicators, INDICATOR_NAMES
from post_office.dkrmm.monitor import Assessment
from post_office.dkrmm.signals import DragonKing, Precursors
from post_office.dkrmm.states import OperationalState


def an_assessment(tick, state=OperationalState.STABLE, severity=0.0,
                  z=None, kinds=(), counts=None, slowing=False,
                  dragon=False, events=100):
    indicators = BehaviouralIndicators(
        ticks=60, events=events, counts=dict(counts or {}))
    for index, name in enumerate(INDICATOR_NAMES):
        setattr(indicators, name, float(index) / 10.0)
    return Assessment(
        tick=tick, state=state, severity=severity,
        indicators=indicators,
        z={name: float((z or {}).get(name, 0.0)) for name in INDICATOR_NAMES},
        kinds=list(kinds),
        precursors=Precursors(points=30, enough=True,
                              variance_rising=slowing,
                              autocorrelation_rising=slowing),
        dragon=DragonKing(points=30, enough=True, is_dragon=dragon,
                          ratio=3.0 if dragon else 1.0),
    )


def a_history():
    hot = {"guardrail_events": 3.1}
    hotter = {"guardrail_events": 3.1, "task_switching": 2.6}
    return [
        an_assessment(20),
        an_assessment(40, severity=0.2),
        an_assessment(60, OperationalState.DEVIATING, 0.9, hot, ["refusal"]),
        an_assessment(80, OperationalState.UNSTABLE, 1.4, hotter,
                      ["refusal", "congestion"], slowing=True),
        an_assessment(100, OperationalState.RECOVERY, 0.3),
    ]


# ------------------------------------------------------------------ series
def test_the_series_share_one_spine():
    series = series_of(a_history())
    length = len(series["ticks"])
    assert series["ticks"] == [20, 40, 60, 80, 100]
    for name in INDICATOR_NAMES:
        assert len(series["indicator_series"][name]) == length
        assert len(series["z_series"][name]) == length
    assert len(series["severity_series"]) == length
    assert len(series["events_series"]) == length


def test_the_z_scores_are_kept_beside_the_values():
    """
    Not recoverable from the values alone. "Off baseline" is measured against a
    baseline that moves, so a reader given only the raw indicator cannot work
    out what the monitor saw.
    """
    series = series_of(a_history())
    assert series["z_series"]["guardrail_events"] == [0.0, 0.0, 3.1, 3.1, 0.0]


def test_the_counts_behind_the_rates_survive():
    history = [an_assessment(20, counts={"refusals": 2, "retries": 1}),
               an_assessment(40, counts={"refusals": 5, "retries": 0})]
    series = series_of(history)
    assert series["count_series"]["refusals"] == [2, 5]
    assert series["count_series"]["retries"] == [1, 0]


# ------------------------------------------------------------------ states
def test_each_state_row_carries_its_precursor_and_dragon_reading():
    rows = states_of(a_history())
    assert rows[3]["state"] == "UNSTABLE"
    assert rows[3]["precursors"]["slowing_down"] is True
    assert rows[0]["dragon"]["is_dragon"] is False


def test_transitions_are_the_changes_not_the_windows():
    rows = transitions_of(states_of(a_history()))
    assert [(t["tick"], t["from"], t["to"]) for t in rows] == [
        (60, "STABLE", "DEVIATING"),
        (80, "DEVIATING", "UNSTABLE"),
        (100, "UNSTABLE", "RECOVERY"),
    ]
    assert rows[0]["escalation"] is True       # STABLE -> DEVIATING
    assert rows[1]["escalation"] is False      # already escalated


# ---------------------------------------------------------------- timeline
def test_the_timeline_records_firsts_in_tick_order():
    record = build_record("r", _monitor(a_history()), seed=1, target="ROUTING",
                          perturbation={"start_tick": 40, "end_tick": 90},
                          changes=[{"tick": 55}, {"tick": 70}])
    line = record["timeline"]
    assert line["perturbation_start"] == 40
    assert line["first_changed_decision"] == 55
    assert line["last_changed_decision"] == 70
    assert line["first_indicator_deviation"] == 60
    assert line["first_multi_indicator_deviation"] == 80
    assert line["first_escalation"] == 60
    assert line["first_unstable"] == 80
    assert line["first_slowing_down"] == 80
    assert line["recovery"] == 100


def test_a_first_that_never_happened_is_none_not_zero():
    """
    None means "not observed in this window", which is not the same claim as
    "did not happen" and must not be read as a negative finding.
    """
    record = build_record("r", _monitor(a_history()))
    assert record["timeline"]["first_rct"] is None
    assert record["timeline"]["first_dragon_flag"] is None
    assert record["rct_events"] == []


class _monitor:
    """The two attributes `build_record` reads off a monitor."""

    every, window, baseline = 20, 60, 24

    def __init__(self, history):
        self.history = list(history)


# ------------------------------------------------------------------ record
def test_the_artifact_carries_the_schema_the_analysis_asks_for():
    record = build_record("run-7", _monitor(a_history()), scenario="rainbow",
                          seed=11, target="ROUTING",
                          attack={"method": "rainbow_teaming"},
                          uptake={"decision_changed": 5},
                          propagation={"count": 2, "deepest": 3})
    for key in ("run_id", "scenario", "seed", "target", "attack", "uptake",
                "indicator_series", "state_series", "rct_events",
                "propagation", "timeline", "transitions", "control"):
        assert key in record, key
    assert record["run_id"] == "run-7"
    assert record["uptake"]["decision_changed"] == 5
    assert record["control"] is False


def test_a_control_says_so_rather_than_being_inferred():
    """
    "No perturbation" and "a perturbation that did nothing" are different runs.
    An empty uptake cannot tell them apart, so the record states which it is.
    """
    record = build_record("c", _monitor(a_history()), control=True)
    assert record["control"] is True
    assert record["uptake"] is None


def test_the_artifact_is_json_and_makes_its_own_directory():
    record = build_record("r", _monitor(a_history()))
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "dkrmm", "r.json")
        write_record(record, path)
        assert json.loads(open(path, encoding="utf-8").read())["run_id"] == "r"


# --------------------------------------------------------------- comparison
def test_a_state_both_runs_reach_is_not_a_finding():
    """
    The reason the matched control is not optional. In validation a perturbed
    run and its control both went DEVIATING and then UNSTABLE well before
    anything was injected, from the load the facility starts under. Read alone,
    either one looks like it went unstable.
    """
    shared = a_history()
    perturbed = build_record("p", _monitor(shared))
    control = build_record("c", _monitor(shared), control=True)
    out = compare_records(perturbed, control)
    assert out["first_divergence"] is None
    assert out["states_only_in_perturbed"] == []
    assert out["divergent_windows"] == 0


def test_the_comparison_finds_the_tick_the_two_runs_stop_agreeing():
    control = build_record("c", _monitor([
        an_assessment(20), an_assessment(40), an_assessment(60),
        an_assessment(80), an_assessment(100)]), control=True)
    perturbed = build_record("p", _monitor(a_history()))
    out = compare_records(perturbed, control)
    assert out["first_divergence"] == 60
    assert out["divergent_windows"] == 3
    assert "UNSTABLE" in out["states_only_in_perturbed"]


def test_a_configuration_mismatch_is_reported_rather_than_swallowed():
    perturbed = build_record("p", _monitor(a_history()), seed=1, target="ROUTING")
    control = build_record("c", _monitor(a_history()), seed=2, target="SORTING",
                           control=True)
    out = compare_records(perturbed, control)
    assert set(out["configuration_mismatch"]) == {"seed", "target"}
