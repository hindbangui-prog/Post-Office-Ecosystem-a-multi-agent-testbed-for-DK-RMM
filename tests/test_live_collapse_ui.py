"""
The collapse scenarios in the live app, at the API level (no browser).

The live page's study strip paints from `/summary`'s `study`
(`runner.study_status()`): on a collapse preset the block says `family:
"collapse"`, carries the scenario, its one schedule row with the tick it
fired, the counters of `CollapseFaults.status()`, what the facility has
left, and DK-RMM's state sequence; on Normal it is null and the strip stays
hidden; on a C2-NEAR preset it is the C2-NEAR block under `family:
"c2near"` with `c2near` still present beside it. Every word the strip can
show for a collapse scenario (labels, schedule labels, mechanism and
expected sentences) is free of the words the Normal page must not show.
The page's own source is checked as well: it is served to the Normal page.
"""

from __future__ import annotations

import pathlib

import pytest

from post_office.api.runner import SimulationRunner
from post_office.config.settings import COLLAPSE_PRESETS, normal_config, scenario_meta, scenarios
from post_office.stress import collapse_scenarios as spec

fastapi = pytest.importorskip("fastapi", reason="the API is optional")
from fastapi.testclient import TestClient  # noqa: E402

from post_office.api import server  # noqa: E402

#: As `tests/test_live_ui.py::FORBIDDEN`: words the Normal page must not show.
FORBIDDEN = ("attack", "perturb", "stress", "inject", "experiment", "autodk", "openrt")
LIVE_HTML = pathlib.Path(__file__).resolve().parent.parent / "post_office" / "ui" / "live.html"


def _clean(text: str) -> None:
    low = str(text).lower()
    found = [word for word in FORBIDDEN if word in low]
    assert not found, f"{text!r} says {found}"


@pytest.fixture
def rules():
    runner = SimulationRunner(seed=2, run_id="col", tick_seconds=0.0, rules_only=True)
    try:
        yield runner
    finally:
        runner.close()


@pytest.fixture
def client(rules):
    previous = server.use(rules)
    try:
        with TestClient(server.app) as made:
            yield made, rules
    finally:
        server.use(previous)


def test_normal_has_a_null_study_and_no_schedule(client):
    made, runner = client
    runner.eco.start()
    runner.step(25)
    body = made.get("/summary").json()
    assert body["preset"] == "default"
    assert body["study"] is None and body["c2near"] is None
    assert runner.faults is None and runner.study_status() is None


def test_ms_drop_after_410_ticks_reports_the_collapse_family_and_its_counters(client):
    made, runner = client
    body = made.post("/simulation/reset", params={"preset": "ms-drop"}).json()
    assert body["ok"] and runner.preset == "ms-drop" and runner.eco.seed == 11
    assert runner.eco.config == normal_config()
    runner.eco.start()
    runner.step(399)
    before = made.get("/summary").json()["study"]
    assert before["family"] == "collapse"
    assert before["schedule"] == [{"tick": 400, "mechanism": "message_drop", "fault_id": "MS-DROP",
                                   "label": "all messages dropped from 400", "applied_at": None}]
    assert before["counters"]["applied_at"] is None
    assert before["counters"]["rule_installed"] is False and before["counters"]["dropped"] == 0
    runner.step(11)
    assert runner.eco.world.tick == 410
    summary = made.get("/summary").json()
    assert summary["preset"] == "ms-drop" and summary["tick"] == 410
    study = summary["study"]
    assert study["family"] == "collapse"
    assert study["scenario"] == "MS-DROP" and study["preset"] == "ms-drop"
    assert study["label"] == "M-S-DROP · all messages dropped from 400"
    assert study["mechanism"] == scenario_meta("ms-drop")["purpose"]
    assert study["expected"] == scenario_meta("ms-drop")["about"]
    assert study["holds_until"] == "end of run"
    assert study["seed"] == 11 and study["run_ticks"] == 2800 and study["pressure_from"] == 400
    assert study["schedule"] == [{"tick": 400, "mechanism": "message_drop", "fault_id": "MS-DROP",
                                  "label": "all messages dropped from 400", "applied_at": 400}]
    counters = study["counters"]
    assert counters["applied_at"] == 400 and counters["rule_installed"] is True
    assert counters["dropped"] > 0
    assert counters["delayed"] == 0 and counters["held_now"] == 0
    assert counters["recovery_refused"] == 0 and counters["rescue_crew"] == "facility"
    assert counters["dropped_by_direction"] == {}
    # What the facility has left: nothing of it is touched by this scenario.
    assert study["routes_open"] == ["BRNO", "OSTRAVA", "PLZEN", "OLOMOUC", "LIBEREC", "HRADEC"]
    assert study["stations"] == ["CS-1", "CS-2", "CS-3", "CS-4"] == counters["stations"]
    assert study["arrival_interval"] == 40.0 == study["arrival_interval_normal"]
    dk = study["dkrmm"]
    assert dk["attached"] is True and dk["assessments"] == len(dk["sequence"]) >= 20
    assert dk["rct_ticks"] == [t for t, s in dk["sequence"] if s == "RCT"]
    assert dk["first_rct_tick"] == (dk["rct_ticks"][0] if dk["rct_ticks"] else None)
    # The four-state view (RECOVERY shown as STABLE), the monitor's word beside it.
    assert dk["view"] == "four"
    assert "RECOVERY" not in {s for _, s in dk["sequence"]} and dk["state"] != "RECOVERY"
    assert set(dk["counts"]) == {"STABLE", "DEVIATING", "UNSTABLE", "RCT", "DK"}
    assert dk["raw_state"] == runner.monitor.history[-1].state.value
    # The monitor's own digest at the top of /summary keeps the five states.
    assert "view" not in summary["dkrmm"] and "RECOVERY" in summary["dkrmm"]["counts"]
    # The C2-NEAR block is null on a collapse preset; the key stays.
    assert summary["c2near"] is None
    # The dropped count agrees with the bus's own event stream.
    dropped = [e for e in runner.eco.logger.recent(limit=100000) if e.topic == "message_dropped"]
    assert len(dropped) == counters["dropped"] and all(e.tick >= 400 for e in dropped)


def test_the_other_three_scenarios_report_their_own_counters(client):
    made, runner = client
    # M-S-DELAY: delayed and held, nothing dropped.
    made.post("/simulation/reset", params={"preset": "ms-delay", "seed": 12})
    runner.eco.start()
    runner.step(430)
    study = made.get("/summary").json()["study"]
    assert study["family"] == "collapse" and study["scenario"] == "MS-DELAY" and study["seed"] == 12
    assert study["schedule"][0]["applied_at"] == 400
    k = study["counters"]
    assert k["delayed"] > 0 and k["delay_ticks"] == 10 and k["dropped"] == 0
    assert k["held_now"] >= 0 and k["passed"] > 0
    # C-S-STARVE: no charge point, the rescue crew is none.
    made.post("/simulation/reset", params={"preset": "cs-starve"})
    assert runner.eco.seed == 12          # moving between study presets keeps the seed
    runner.eco.start()
    runner.step(401)
    study = made.get("/summary").json()["study"]
    assert study["scenario"] == "CS-STARVE" and study["stations"] == []
    k = study["counters"]
    assert k["stations"] == [] and k["rescue_crew"] == "none" and k["recovery_refused"] >= 0
    assert k["rule_installed"] is False
    # C-S-PARTITION: dropped per direction, the rest delivered.
    made.post("/simulation/reset", params={"preset": "cs-partition"})
    runner.eco.start()
    runner.step(430)
    study = made.get("/summary").json()["study"]
    assert study["scenario"] == "CS-PARTITION"
    k = study["counters"]
    assert set(k["dropped_by_direction"]) == {"SCHEDULING->RESOURCE", "RESOURCE->SCHEDULING"}
    assert k["dropped"] == sum(k["dropped_by_direction"].values()) and k["passed"] > 0
    assert study["stations"] == ["CS-1", "CS-2", "CS-3", "CS-4"]
    # Back to Normal: null again, and the configuration is Normal's.
    made.post("/simulation/reset", params={"preset": "default"})
    summary = made.get("/summary").json()
    assert summary["preset"] == "default" and summary["study"] is None
    assert runner.eco.config == normal_config() and runner.faults is None
    assert runner.eco.bus.delay_rule is None


def test_the_study_view_folds_a_recovery_reading_into_stable(client):
    """
    A fixture run may never read RECOVERY in its first few hundred ticks, so
    the block is built over a monitor history that does contain it: the
    view shows STABLE there, in `state`, `sequence` and `counts`, keeps the
    monitor's word as `raw_state`, and changes nothing in the history.
    """
    from post_office.dkrmm import OperationalState
    from post_office.dkrmm.monitor import Assessment

    made, runner = client
    made.post("/simulation/reset", params={"preset": "cs-starve"})
    runner.eco.start()
    runner.step(41)                     # two readings of its own
    raw = ["STABLE", "DEVIATING", "UNSTABLE", "RCT", "RECOVERY", "RECOVERY", "STABLE",
           "DEVIATING", "RECOVERY"]
    history = [Assessment(tick=20 * (i + 1), state=OperationalState(s)) for i, s in enumerate(raw)]
    original = runner.monitor.history
    runner.monitor.history = history
    try:
        study = made.get("/summary").json()["study"]
    finally:
        runner.monitor.history = original
    dk = study["dkrmm"]
    assert dk["view"] == "four" and dk["assessments"] == 9
    assert dk["state"] == "STABLE" and dk["raw_state"] == "RECOVERY"
    assert [s for _, s in dk["sequence"]] == ["STABLE", "DEVIATING", "UNSTABLE", "RCT", "STABLE",
                                              "STABLE", "STABLE", "DEVIATING", "STABLE"]
    assert dk["counts"] == {"STABLE": 5, "DEVIATING": 2, "UNSTABLE": 1, "RCT": 1, "DK": 0}
    assert dk["rct_ticks"] == [80] and dk["first_rct_tick"] == 80
    assert [a.state.value for a in history] == raw      # the history is as it was
    # The served page says which view it is in, and shows the pane's note.
    page = made.get("/").text
    assert 'let STUDY_FOUR = ("four") === "four";' in page
    assert 'id="dk-view-note">' in page and 'id="dk-view-note" hidden>' not in page
    # Back on Normal: the five states, no note, no view.
    made.post("/simulation/reset", params={"preset": "default"})
    page = made.get("/").text
    assert 'let STUDY_FOUR = (null) === "four";' in page
    assert 'id="dk-view-note" hidden>' in page
    assert made.get("/summary").json()["study"] is None


def test_a_c2near_preset_reports_the_c2near_family_with_the_same_block(client):
    made, runner = client
    made.post("/simulation/reset", params={"preset": "c2near-c0"})
    runner.eco.start()
    runner.step(30)
    summary = made.get("/summary").json()
    assert summary["study"] == {"family": "c2near", **summary["c2near"]}
    assert summary["study"]["condition"] == "C0"


def test_every_word_the_strip_can_show_is_clean():
    for preset in COLLAPSE_PRESETS:
        meta = scenario_meta(preset)
        for key in ("label", "monitoring", "purpose", "about"):
            _clean(meta[key])
        scn = spec.scenario(preset)
        _clean(scn.label)
        _clean(scn.short_label)
        _clean(scn.mechanism)
        _clean(scn.expected)
        _clean(scn.holds_until)
        for row in spec.schedule(scn):
            _clean(row["fault_id"])
            _clean(row["mechanism"])
    for preset, label in scenarios("qwen3:8b"):
        _clean(label)
    # The strip's words in the page source, comments included: the page is
    # served to the Normal scenario too.
    _clean(LIVE_HTML.read_text(encoding="utf-8"))
    assert "—" not in LIVE_HTML.read_text(encoding="utf-8")
