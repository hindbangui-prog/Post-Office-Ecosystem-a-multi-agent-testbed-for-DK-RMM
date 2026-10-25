"""
P7-ONOFF: the Phase 7 ON-OFF agent misbehaviour as a scenario of the live app.

The scenario is registered after the collapse scenarios (tenth option, its own
label, `normal_config()` byte for byte); its schedule is the frozen one
(ON 1200-1500, 1800-2200, 2500-3000, 3300-3800; OFF 300 between; id
`A[ROUTING!+SCHEDULING!]on300off300d100p100@1200to3800`); its arrival schedule
for seed 11977 is the frozen run's (same consignment ids, same schedule
hash); the live runner carries it from tick 0, displaces ROUTING's and
SCHEDULING's decisions in ON phases only and never in OFF, reports it under
`family: "onoff"`, stops by itself at 4400, and starts on seed 11977 when the
preset is chosen from Normal. The run of seed 11977 reproduces the frozen
Phase 7 confirmation run event for event (the sha256 of the first 1700
ticks' events, without wall clock, run id and sequence number, is the archived
run's), and its robot trap is the frozen one: R1 and R2, no errand, in the
charging zone, from tick 1211, through the first OFF phase. The existing
scenarios and the Normal page are what they were: nothing is displaced on any
other preset, and the page's source names no removed family.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from post_office.api.runner import SimulationRunner
from post_office.config.settings import (COLLAPSE_PRESETS, ONOFF_PRESETS, config, known_presets,
                                         normal_config, scenario_meta, scenario_name, scenarios)
from post_office.crew.console import quiet
from post_office.stress import onoff_attack as spec

#: The frozen run of seed 11977 (exp_cascade phase7, runs_C, meta_p7.json): its
#: consignment ids, its arrival schedule's hash, and the sha256 of its event
#: stream for ticks 1 to 1700 and 1 to 4400 (events without wall_clock, run_id
#: and seq, one JSON object per line, sorted keys, compact separators).
FROZEN_CONSIGNMENT = ["P-0058", "P-0060", "P-0064", "P-0071", "P-0074", "P-0079", "P-0083", "P-0087",
                      "P-0089", "P-0094", "P-0095", "P-0096", "P-0100", "P-0101", "P-0102", "P-0103",
                      "P-0111", "P-0113", "P-0114", "P-0116"]
FROZEN_SCHEDULE_SHA256 = "60547ba407c34d2e61b2c7fd0fc5cb137d15f927f75ecf43a24bfff921a722b6"
FROZEN_EVENTS_SHA256_1700 = "d5c2edc19ddb5bd0ff2cb92d2042b73fe803f6dad6d6fe7b03f0a0962b6bc5ac"
FROZEN_EVENTS_SHA256_4400 = "f70f84e795f8325164b490493b526afb13f3b764d0042d34b1844928e440ec5e"
FORBIDDEN = ("attack", "perturb", "stress", "inject", "experiment", "autodk", "openrt")


def _events_sha(log_path: str, upto: int) -> str:
    rows = []
    for line in open(log_path, encoding="utf-8"):
        event = json.loads(line)
        if not 1 <= int(event.get("tick", 0)) <= upto:
            continue
        for key in ("wall_clock", "run_id", "seq"):
            event.pop(key, None)
        # `handling`, the label every decision now carries for how it was
        # handled, did not exist when the run was frozen; it is derived from
        # the record's own fields, so the frozen stream is compared without it.
        if event.get("topic") == "decision":
            event.get("detail", {}).pop("handling", None)
        rows.append(json.dumps(event, sort_keys=True, separators=(",", ":")))
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


# ------------------------------------------------------------- registration
def test_the_scenario_is_the_tenth_option_and_normal_config():
    presets = [preset for preset, _ in scenarios("qwen3:8b")]
    # The tenth option; the model variant (`tests/test_p7_onoff_model.py`) follows it.
    assert presets[:10] == ["default", "c2near-n", "c2near-c0", "c2near-c2", "ms-drop", "ms-delay",
                            "cs-starve", "cs-partition", "ms-stall", "p7-onoff"]
    assert dict(scenarios("qwen3:8b"))["p7-onoff"] == spec.LABEL
    assert known_presets()[9] == "p7-onoff" and ONOFF_PRESETS["p7-onoff"] == "P7-ONOFF"
    assert list(ONOFF_PRESETS)[0] == "p7-onoff"
    assert "p7-onoff" not in COLLAPSE_PRESETS
    assert scenario_name("p7-onoff") == "p7-onoff"
    meta = scenario_meta("p7-onoff")
    assert meta["label"] == spec.LABEL and meta["monitoring"] == "Monitoring (observe only)"
    assert "not a confirmed Dragon-King" in meta["about"]
    assert config("p7-onoff") == normal_config() == spec.config()
    low = (spec.LABEL + meta["purpose"] + meta["about"]).lower()
    assert not [w for w in FORBIDDEN if w in low]


def test_the_schedule_and_the_id_are_the_frozen_ones():
    assert spec.frozen_spec().id == spec.ATTACK_ID
    assert spec.ATTACK_ID == "A[ROUTING!+SCHEDULING!]on300off300d100p100@1200to3800"
    assert spec.SCENARIO6_ID == "L40S20@1400to3400-none-none-T4400" and spec.RUN_TICKS == 4400
    assert [(p["on_from"], p["on_to"], p["off_to"]) for p in spec.PHASES] == [
        (1200, 1500, 1800), (1800, 2200, 2500), (2500, 3000, 3300), (3300, 3800, 3800)]
    on = [t for t in range(0, 4401) if spec.is_on(t)]
    assert len(on) == 300 + 400 + 500 + 500 and on[0] == 1200 and on[-1] == 3799
    assert not spec.is_on(1199) and spec.is_on(1200) and not spec.is_on(1500) and spec.is_on(1800)
    assert not spec.is_on(3800) and not spec.is_on(4400)
    assert spec.phase_at(1000) == {"phase": "OFF", "since": 0, "until": 1200, "k": None, "before_window": True}
    assert spec.phase_at(1250) == {"phase": "ON", "since": 1200, "until": 1500, "k": 0}
    assert spec.phase_at(1600) == {"phase": "OFF", "since": 1500, "until": 1800, "k": 0}
    assert spec.phase_at(3900)["after_window"] is True
    assert [row["tick"] for row in spec.schedule_rows()] == [1200, 1800, 2500, 3300]
    assert spec.AGENTS == ("ROUTING", "SCHEDULING") and spec.frozen_spec().floor_targets == {"ROUTING", "SCHEDULING"}
    assert spec.DEMO_SEED == 11977 and spec.DEMO_SEED in spec.TRAPPED_SEEDS and len(spec.TRAPPED_SEEDS) == 7


def test_the_arrival_schedule_of_seed_11977_is_the_frozen_runs():
    cfg = normal_config()
    arrivals = spec.ConsignmentArrivals(11977, spec.RUN_TICKS, float(cfg["arrival_interval"]),
                                        int(cfg["initial_parcels"]))
    assert arrivals.consignment == FROZEN_CONSIGNMENT
    assert spec.schedule_hash(arrivals.schedule) == FROZEN_SCHEDULE_SHA256
    ticks = spec.consignment_ticks(11977)
    assert len(ticks) == 20 and all(1400 <= t <= 3400 for t in ticks) and ticks == sorted(ticks)
    assert all(arrivals.routes[pid] == "HRADEC" for pid in arrivals.consignment)
    # The same seed on a different mean interval or dock is a different schedule, so the
    # configuration is what the run's parcels follow from.
    other = spec.ConsignmentArrivals(11977, spec.RUN_TICKS, 30.0, int(cfg["initial_parcels"]))
    assert spec.schedule_hash(other.schedule) != FROZEN_SCHEDULE_SHA256


# -------------------------------------------------------------- the runner
@pytest.fixture(scope="module")
def demo_run(tmp_path_factory):
    """The live runner on seed 11977, stepped to tick 1700 with its event log on disk."""
    log = str(tmp_path_factory.mktemp("p7") / "events.jsonl")
    with quiet():
        runner = SimulationRunner(seed=11977, preset="p7-onoff", rules_only=True, verify_model=False,
                                  tick_seconds=0.0, run_id="p7", log_path=log)
        try:
            runner.eco.start()
            for _ in range(1700):
                assert runner._tick()
            runner._logger.flush()
            yield runner, log
        finally:
            runner.close()


@pytest.mark.slow
def test_seed_11977_reproduces_the_frozen_run_and_its_trap(demo_run):
    runner, log = demo_run
    assert runner.eco.world.tick == 1700
    assert _events_sha(log, 1700) == FROZEN_EVENTS_SHA256_1700
    study = runner.study_status()
    assert study["family"] == "onoff" and study["seed"] == 11977 and study["run_ticks"] == 4400
    assert study["pressure_from"] == 1200 and study["complete"] is False and study["summary"] is None
    assert [row["applied_at"] for row in study["schedule"]] == [1200, None, None, None]
    st = study["status"]
    assert st["phase"] == {"phase": "OFF", "since": 1500, "until": 1800, "k": 0, "remaining": 100, "tick": 1700}
    assert st["is_demo_seed"] is True and st["consignment_ids"] == FROZEN_CONSIGNMENT
    d = st["displacement"]
    assert d["attack"] == spec.ATTACK_ID and d["on_ticks"] == 300 and d["displaced"] > 0
    assert set(d["by_agent"]) == {"ROUTING", "SCHEDULING"} and d["by_agent"]["ROUTING"] > d["by_agent"]["SCHEDULING"]
    assert d["phases"] == [{"tick": 1, "phase": "OFF"}, {"tick": 1200, "phase": "ON"}, {"tick": 1500, "phase": "OFF"}]
    trap = st["trap"]
    assert trap["occurred"] and trap["persistent"] and trap["robots"] == ["R1", "R2"]
    assert trap["started"] == 1211 and trap["no_errand"] is True and trap["zone"] == "CHARGING"
    assert trap["formed_in"]["phase"] == "ON" and trap["off_phases_crossed"] == [1] and trap["survived_off_phase"]
    assert st["head_to_head"] == [["R1", "R2"]]
    robots = {r["robot"]: r for r in st["robots"]}
    assert robots["R1"]["cell"] == [14, 12] and robots["R2"]["cell"] == [13, 12]
    assert robots["R1"]["trapped_since"] == 1510 and robots["R2"]["trapped_since"] == 1630
    assert robots["R1"]["task"] is None and robots["R2"]["task"] is None
    assert robots["R1"]["routing_choices_in_streak"]["ABANDON"] > 100
    imp = st["impact"]
    assert imp["robots_blocked"] == 2 and imp["robots_trapped"] == 2 and imp["robots_available"] == 3
    assert imp["hospital_total"] == 20 and imp["hospital_not_yet"] == 20     # the first arrives at 2013
    assert len(st["hospital"]) == 20 and all(h["state"] == "NOT_YET_ARRIVED" for h in st["hospital"])


@pytest.mark.slow
def test_the_events_say_what_was_displaced_and_when(demo_run):
    runner, log = demo_run
    events = [json.loads(line) for line in open(log, encoding="utf-8")]
    phases = [(e["tick"], e["detail"]["phase"]) for e in events if e["topic"] == "attack_phase"]
    assert phases == [(1, "OFF"), (1200, "ON"), (1500, "OFF")]
    displaced = [e for e in events if e["topic"] == "attack_displaced"]
    assert displaced and all(1200 <= e["tick"] < 1500 for e in displaced), "ON phases only"
    assert all(e["detail"]["honest"] != e["detail"]["displaced"] for e in displaced)
    routing = [e for e in displaced if e["actor"] == "ROUTING"]
    assert routing and all(e["detail"]["decision"] == "resolve_block" and e["detail"]["displaced"] == "WAIT"
                           for e in routing)
    sched = [e for e in displaced if e["actor"] == "SCHEDULING"]
    assert sched and {e["detail"]["decision"] for e in sched} <= {"choose_robot", "choose_next_task"}
    # Every displaced decision follows its honest decision event, which was recorded as always.
    decisions = {(e["tick"], e["actor"], e["detail"].get("decision")) for e in events if e["topic"] == "decision"}
    assert all((e["tick"], e["actor"], e["detail"]["decision"]) in decisions for e in displaced)
    # The page's words for them, through the server's describe.
    from post_office.ui.views import describe

    assert describe(routing[0]).startswith("ON phase: resolve_block ") and describe(routing[0]).endswith("-> WAIT (displaced)")
    assert describe([e for e in events if e["topic"] == "attack_phase"][1]) == "phase ON: ROUTING, SCHEDULING"


def test_the_runner_starts_on_the_demonstration_seed_and_leaves_the_other_presets_alone():
    with quiet():
        runner = SimulationRunner(seed=1, preset="default", rules_only=True, verify_model=False, tick_seconds=0.0)
        try:
            assert runner.faults is None and runner.study_status() is None
            runner.reset(preset="p7-onoff")
            assert runner._seed == 11977 and runner.eco.seed == 11977
            assert type(runner.faults).__name__ == "OnOffFaults" and runner.reached_stop() is False
            assert runner.study_status()["family"] == "onoff"
            assert [s for s, _ in runner.study_status()["seed_options"]][0] == 11977
            # Its arrivals and its wrap are on this ecosystem only, and inert until tick 1200.
            assert runner.eco.generator.step.__self__ is runner.faults.arrivals
            runner.eco.start()
            for _ in range(60):
                runner._tick()
            assert runner.faults.attack.displaced == 0 and runner.faults.attack.phase_log == [{"tick": 1, "phase": "OFF"}]
            runner.reset(preset="ms-drop")
            assert runner._seed == 11 and type(runner.faults).__name__ == "CollapseFaults"
            assert "step" not in vars(runner.eco.generator), "the generator's own step on a collapse scenario"
            runner.reset(preset="default")
            assert runner.faults is None and runner.study_status() is None
            assert "step" not in vars(runner.eco.generator)
            assert all("decide" not in vars(agent) for agent in runner.eco.agents.values()), "no wrapped decide on Normal"
            runner.reset(preset="p7-onoff", seed=12070)
            assert runner.eco.seed == 12070 and runner.study_status()["status"]["is_demo_seed"] is False
        finally:
            runner.close()


def test_the_run_stops_by_itself_at_the_horizon_only_on_this_preset():
    with quiet():
        runner = SimulationRunner(seed=11977, preset="p7-onoff", rules_only=True, verify_model=False, tick_seconds=0.0)
        try:
            assert runner.faults.horizon == 4400 and runner.stop_at is None
            runner.eco.world.tick = 4399          # the clock only: enough to see the stop rule act
            assert runner.reached_stop() is False
            runner.eco.world.tick = 4400
            assert runner.reached_stop() is True
            runner.reset(preset="ms-stall", seed=13)
            runner.eco.world.tick = 4400
            assert runner.reached_stop() is False, "a collapse scenario has no horizon of its own"
        finally:
            runner.close()


def test_the_pages_source_names_no_removed_family():
    from pathlib import Path

    here = Path(__file__).resolve().parent.parent / "post_office" / "ui"
    for name in ("live.html", "floor.html"):
        low = (here / name).read_text(encoding="utf-8").lower()
        found = [w for w in FORBIDDEN if w in low]
        assert not found, f"{name} says {found}"


def test_the_page_has_the_dk_alert_and_the_sound_switch():
    """The DK alert chip (tick, the extreme event's short name, a details button) and the beep's switch."""
    from pathlib import Path

    page = (Path(__file__).resolve().parent.parent / "post_office" / "ui" / "live.html").read_text(encoding="utf-8")
    for needle in ('id="dk-alert"', 'id="dk-alert-tick"', 'id="dk-alert-event"', 'id="dk-alert-more"',
                   'id="sound"', "function beep()", "function paintDkAlert(", "function extremeEventName(",
                   "paintDkAlert(s);"):
        assert needle in page, needle
    # The chip reads the study's DK readings, never the five-state digest of Normal.
    assert "s.study && s.study.dkrmm" in page
    # The event's name on the ON-OFF preset comes from the trap as observed; no verdict word.
    assert "orphaned-robot trap:" in page and "not a verdict" in page

