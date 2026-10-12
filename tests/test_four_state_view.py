"""
The four-state view of DK-RMM for the study scenarios (`stress/states.py`).

The monitor has five states and keeps them; the study scenarios show four,
with RECOVERY (a window back at baseline right after an escalated one)
shown as STABLE. `four_state` maps one word, `four_state_counts` folds the
monitor's counts, and the places that carry the view (the runner's study
block, the measurement, the results page, the live page's pane) do it
without touching `post_office/dkrmm/`.
"""

from __future__ import annotations

import pathlib

import pytest

from post_office.dkrmm import OperationalState
from post_office.dkrmm.monitor import Assessment
from post_office.stress import measure, report
from post_office.stress.states import FOLDED, FOUR_STATES, four_state, four_state_counts

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIVE = [s.value for s in OperationalState]


# ------------------------------------------------------------------ the map
def test_the_four_states_are_the_monitors_without_recovery():
    assert FOUR_STATES == ("STABLE", "DEVIATING", "UNSTABLE", "RCT")
    assert set(FOUR_STATES) | set(FOLDED) == set(FIVE)
    assert FOLDED == {"RECOVERY": "STABLE"}


@pytest.mark.parametrize("name", FIVE)
def test_four_state_maps_recovery_to_stable_and_passes_the_rest(name):
    assert four_state(name) == ("STABLE" if name == "RECOVERY" else name)
    assert four_state(OperationalState(name)) == four_state(name)   # the enum, too
    assert four_state(name) in FOUR_STATES


def test_four_state_passes_an_absent_reading_through():
    assert four_state(None) is None
    assert four_state("") == ""


def test_four_state_counts_folds_recovery_into_stable_in_order():
    counts = {"STABLE": 41, "DEVIATING": 42, "UNSTABLE": 34, "RCT": 3, "RECOVERY": 20}
    folded = four_state_counts(counts)
    assert folded == {"STABLE": 61, "DEVIATING": 42, "UNSTABLE": 34, "RCT": 3}
    assert list(folded) == list(FOUR_STATES)
    assert sum(folded.values()) == sum(counts.values())
    assert four_state_counts({}) == {s: 0 for s in FOUR_STATES}
    assert four_state_counts(None) == {s: 0 for s in FOUR_STATES}
    # The monitor's own vocabulary is not changed by the view.
    assert FIVE == ["STABLE", "DEVIATING", "UNSTABLE", "RCT", "RECOVERY"]


# ------------------------------------------------------------ the runner
class _Monitor:
    """A monitor with a history containing RECOVERY, for the runner's block."""

    def __init__(self, states):
        self.history = [Assessment(tick=20 * (i + 1), state=OperationalState(s))
                        for i, s in enumerate(states)]


def test_the_runners_study_block_shows_four_states_and_keeps_the_raw_word():
    from post_office.api.runner import SimulationRunner

    states = ["STABLE", "DEVIATING", "UNSTABLE", "RCT", "RECOVERY", "STABLE", "RECOVERY"]
    runner = SimulationRunner.__new__(SimulationRunner)
    runner.monitor = _Monitor(states)
    block = SimulationRunner._dkrmm_block(runner)
    assert block["view"] == "four"
    assert block["attached"] is True and block["assessments"] == 7
    assert block["state"] == "STABLE" and block["raw_state"] == "RECOVERY"
    assert [s for _, s in block["sequence"]] == ["STABLE", "DEVIATING", "UNSTABLE", "RCT",
                                                 "STABLE", "STABLE", "STABLE"]
    assert [t for t, _ in block["sequence"]] == [20, 40, 60, 80, 100, 120, 140]
    assert block["counts"] == {"STABLE": 4, "DEVIATING": 1, "UNSTABLE": 1, "RCT": 1}
    assert block["rct_ticks"] == [80] and block["first_rct_tick"] == 80
    assert "RECOVERY" not in {s for _, s in block["sequence"]}
    assert "RECOVERY" not in block["counts"]
    # The monitor's own history is as it was.
    assert [a.state.value for a in runner.monitor.history] == states


# -------------------------------------------------------- the measurement
def test_the_measurement_columns_carry_both_dkrmm_columns():
    assert measure.COLUMNS[-2:] == ["dkrmm_state", "dkrmm_state_four"]


def test_the_report_sequence_and_counts_are_four_state():
    ticks = list(range(1, 8))
    raw = ["STABLE", "STABLE", "DEVIATING", "RECOVERY", "RECOVERY", "STABLE", "RCT"]
    assert report._state_sequence(ticks, raw) == [[1, "STABLE"], [3, "DEVIATING"],
                                                  [4, "STABLE"], [7, "RCT"]]


def test_the_report_run_maps_a_recovery_final_state(tmp_path):
    import csv
    import json

    run_dir = tmp_path / "C0" / "s11"
    run_dir.mkdir(parents=True)
    with (run_dir / "series.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=measure.COLUMNS, lineterminator="\n")
        writer.writeheader()
        for tick, state in enumerate(["STABLE", "UNSTABLE", "RECOVERY"], start=1):
            row = {key: 0 for key in measure.COLUMNS}
            row.update({"tick": tick, "dkrmm_state": state, "dkrmm_state_four": four_state(state)})
            writer.writerow(row)
    (run_dir / "measurement.json").write_text(json.dumps({
        "totals": {}, "faults_applied": [], "fault_ticks": {}, "per_route": {},
        "dkrmm": {"assessments": 3, "current": {"tick": 3, "state": "RECOVERY"},
                  "counts": {"STABLE": 1, "DEVIATING": 0, "UNSTABLE": 1, "RCT": 0,
                             "RECOVERY": 1}}}), encoding="utf-8")
    (run_dir / "done.json").write_text("{}", encoding="utf-8")
    run = report.collect(tmp_path)["runs"][0]
    dk = run["dkrmm"]
    assert dk["view"] == "four" and dk["states"] == list(FOUR_STATES)
    assert dk["final_state"] == "STABLE" and dk["raw_final_state"] == "RECOVERY"
    assert dk["sequence"] == [[1, "STABLE"], [2, "UNSTABLE"], [3, "STABLE"]]
    assert dk["counts"] == {"STABLE": 2, "DEVIATING": 0, "UNSTABLE": 1, "RCT": 0}


# ---------------------------------------------------------- the live page
def test_the_live_page_maps_only_under_a_study_preset():
    from post_office.ui.live import dk_view_of, shell_html

    class _Runner:
        preset = "default"
        last_frame = {"run_id": "x"}
        settings = None

    assert dk_view_of(None) is None
    assert dk_view_of(_Runner()) is None
    for preset in ("c2near-n", "c2near-c0", "c2near-c2", "ms-drop", "ms-delay",
                   "cs-starve", "cs-partition"):
        made = _Runner()
        made.preset = preset
        assert dk_view_of(made) == "four"
    template = shell_html(None)
    assert 'let STUDY_FOUR = (null) === "four";' in template
    assert 'id="dk-view-note" hidden>' in template
    # The study strip's legend has the four states only.
    key = template.split('id="c2n-key"', 1)[1].split("</span>", 1)[0]
    assert key.count("<i ") == 4 and "RECOVERY" not in key


def test_nothing_under_dkrmm_names_the_view():
    """The monitor is untouched: no file under `post_office/dkrmm/` knows the view."""
    for path in (ROOT / "post_office" / "dkrmm").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "four_state" not in text and "stress.states" not in text, path
