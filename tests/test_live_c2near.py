"""
The C2-NEAR collapse study in the live app, at the API level (no browser).

The scenario registry offers Normal first, unchanged, and the three C2-NEAR
conditions after it, in words the Normal page may not show (the live UI
test's FORBIDDEN list). `config()` resolves the new presets through the
study's own module: N and C0 are `normal_config()` byte for byte, C2 carries
the campaign block. The runner applies the schedule beside the run
(OP-SURGE at tick 400 on a rules-only C0 run), reports it through
`c2near_status()` and `/summary`'s `c2near`, refuses C2 on a rules-only
runner without touching the run, binds the campaign on a model-mode (fake
Ollama) runner, and restores `normal_config()` with `c2near: null` when
switched back to `default`.
"""

from __future__ import annotations

import pytest

from post_office.api.runner import SimulationRunner
from post_office.config.settings import (C2NEAR_PRESETS, DEFAULT_CONFIG, PRESETS, config,
                                         known_presets, normal_config, scenario_label,
                                         scenario_meta, scenario_name, scenarios)
from post_office.crew.console import quiet
from post_office.stress import c2near_system_override as spec

fastapi = pytest.importorskip("fastapi", reason="the API is optional")
from fastapi.testclient import TestClient  # noqa: E402

from post_office.api import server  # noqa: E402

#: As `tests/test_live_ui.py::FORBIDDEN`: words the Normal page must not show,
#: and the scenario selector's options are part of that page's text.
FORBIDDEN = ("attack", "perturb", "stress", "inject", "experiment", "autodk", "openrt")
NORMAL_LABEL = "NORMAL · CrewAI · Ollama/qwen3:8b · DK-RMM"


def _clean(text: str) -> None:
    low = text.lower()
    found = [word for word in FORBIDDEN if word in low]
    assert not found, f"{text!r} says {found}"


# ------------------------------------------------------------- the registry
def test_scenarios_lists_normal_first_unchanged_and_the_three_conditions():
    rows = scenarios("qwen3:8b")[:4]            # the collapse scenarios follow these
    assert len(rows) == 4
    assert rows[0] == ("default", NORMAL_LABEL)
    assert rows[0][1] == scenario_label("qwen3:8b")
    assert [preset for preset, _ in rows] == ["default", "c2near-n", "c2near-c0", "c2near-c2"]
    assert rows[1][1].startswith("C2-NEAR · N control")
    assert rows[2][1].startswith("C2-NEAR · C0 operational pressure")
    assert rows[3][1].startswith("C2-NEAR · C2 System Override + operational pressure")
    assert all(label.endswith("Ollama/qwen3:8b") for _, label in rows[1:])
    assert known_presets()[:4] == ["default", "c2near-n", "c2near-c0", "c2near-c2"]
    assert list(C2NEAR_PRESETS) == known_presets()[1:4]


def test_the_new_labels_and_meta_carry_no_forbidden_word():
    for preset, label in scenarios("qwen3:8b")[1:]:
        _clean(label)
        meta = scenario_meta(preset)
        assert meta["scenario"] == preset == scenario_name(preset)
        assert meta["monitoring"] == "Monitoring (observe only)"
        for key in ("label", "monitoring", "purpose", "about"):
            _clean(meta[key])
        if preset in C2NEAR_PRESETS:
            assert "Schedule" in meta["purpose"]
    # The Normal entry is what it was.
    assert scenario_meta("default") == {"scenario": "normal", "label": "Normal Ecosystem",
                                        "monitoring": "Monitoring", "purpose": "No Perturbation",
                                        "about": "the facility under ordinary operating "
                                                 "conditions, with its own variability and "
                                                 "its own naturally occurring deviations"}
    with pytest.raises(ValueError):
        scenario_meta("c2near-c9")


def test_config_resolves_the_conditions_and_leaves_default_alone():
    assert PRESETS == {"default": DEFAULT_CONFIG}
    assert config() == DEFAULT_CONFIG and config("default") == DEFAULT_CONFIG
    assert config("c2near-n") == normal_config()
    assert config("c2near-c0") == normal_config()
    c2 = config("c2near-c2")
    assert c2["c2near_system_override"] == {"targets": list(spec.TARGETS), "start_tick": 400,
                                            "exhaustion": "repeat_final"}
    assert {k: v for k, v in c2.items() if k != "c2near_system_override"} == normal_config()
    assert c2 == spec.config(spec.condition("C2"))
    assert "c2near_system_override" not in normal_config()
    with pytest.raises(ValueError):
        config("c2near-c9")


# ---------------------------------------------------------------- the runner
@pytest.fixture
def rules():
    runner = SimulationRunner(seed=2, run_id="c2n", tick_seconds=0.0, rules_only=True)
    try:
        yield runner
    finally:
        runner.close()


def test_a_normal_runner_has_no_schedule_and_the_summary_says_null(rules):
    assert rules.faults is None and rules.c2near_status() is None
    previous = server.use(rules)
    try:
        rules.eco.start()
        rules.step(25)
        with TestClient(server.app) as client:
            body = client.get("/summary").json()
            assert body["preset"] == "default" and body["c2near"] is None
            assert body["scenario_label"] == NORMAL_LABEL
            # Normal's monitor digest is the monitor's own: five states, no view.
            assert body["study"] is None
            assert "view" not in body["dkrmm"] and "raw_state" not in body["dkrmm"]
            assert set(body["dkrmm"]["counts"]) == {"STABLE", "DEVIATING", "UNSTABLE",
                                                    "RCT", "RECOVERY"}
            assert set(client.get("/dkrmm/state").json()["counts"]) == set(body["dkrmm"]["counts"])
    finally:
        server.use(previous)


def test_c0_on_rules_applies_the_surge_at_tick_400_and_reports_it(rules):
    rules.reset(preset="c2near-c0")
    assert rules.preset == "c2near-c0" and rules.eco.seed == 11      # the study's first seed
    assert rules._config == normal_config() and rules.eco.config == normal_config()
    assert rules.faults is not None and rules.faults.cond.id == "C0"
    rules.eco.start()
    rules.step(399)
    assert rules.eco.generator.mean_interval == 40.0
    before = rules.c2near_status()
    assert before["schedule"][0] == {"tick": 400, "mechanism": "arrival_surge",
                                     "fault_id": "OP-SURGE", "label": "arrivals x3",
                                     "applied_at": None}
    rules.step(1)
    assert rules.eco.world.tick == 400
    assert rules.eco.generator.mean_interval == pytest.approx(40.0 / 3.0)
    status = rules.c2near_status()
    assert status["condition"] == "C0" and status["seed"] == 11
    assert status["run_ticks"] == 2800 and status["pressure_from"] == 400
    assert [row["fault_id"] for row in status["schedule"]] == ["OP-SURGE", "OP-ROUTE-1",
                                                               "OP-ROUTE-2", "OP-CHARGE"]
    assert status["schedule"][0]["applied_at"] == 400
    assert all(row["applied_at"] is None for row in status["schedule"][1:])
    assert status["routes_open"] == ["BRNO", "OSTRAVA", "PLZEN", "OLOMOUC", "LIBEREC", "HRADEC"]
    assert status["stations"] == ["CS-1", "CS-2", "CS-3", "CS-4"]
    assert status["arrival_interval"] == pytest.approx(40.0 / 3.0)
    assert status["arrival_interval_normal"] == 40.0
    assert status["campaign"] is None
    dk = status["dkrmm"]
    assert dk["attached"] is True and dk["assessments"] == len(dk["sequence"]) >= 19
    # The study's four-state view: no RECOVERY anywhere in it, the monitor's
    # own word kept beside the current state, its history untouched.
    assert dk["view"] == "four"
    words = ("STABLE", "DEVIATING", "UNSTABLE", "RCT", "DK")
    assert all(state in words for _, state in dk["sequence"])
    assert dk["state"] in words
    assert set(dk["counts"]) == set(words)
    assert sum(dk["counts"].values()) == dk["assessments"]
    raw = [a.state.value for a in rules.monitor.history]
    assert dk["raw_state"] == raw[-1]
    assert [s for _, s in dk["sequence"]] == [("STABLE" if r == "RECOVERY" else r) for r in raw]
    assert dk["rct_ticks"] == [t for t, s in dk["sequence"] if s == "RCT"]
    assert dk["first_rct_tick"] == (dk["rct_ticks"][0] if dk["rct_ticks"] else None)
    # The activation is in the run's event log, as the study's driver writes it.
    fired = [e for e in rules.eco.logger.recent(limit=100000)
             if e.topic == "stress_fault_activated"]
    assert [e.detail["fault_id"] for e in fired] == ["OP-SURGE"] and fired[0].tick == 400
    # Route LIBEREC closes at 500, and the status follows.
    rules.step(100)
    status = rules.c2near_status()
    assert status["schedule"][1]["applied_at"] == 500
    assert "LIBEREC" not in status["routes_open"] and status["routes_closed"] == ["LIBEREC"]


def test_an_explicit_seed_is_kept_and_n_has_an_empty_schedule(rules):
    rules.reset(preset="c2near-n", seed=13)
    status = rules.c2near_status()
    assert status["condition"] == "N" and status["seed"] == 13 and rules.eco.seed == 13
    assert status["schedule"] == [] and status["campaign"] is None
    rules.eco.start()
    rules.step(401)
    assert rules.eco.generator.mean_interval == 40.0
    # Moving between the study's presets keeps the seed; only a switch from
    # Normal without a seed takes 11.
    rules.reset(preset="c2near-c0")
    assert rules.eco.seed == 13


def test_c2_is_refused_on_a_rules_only_runner_and_the_run_is_untouched(rules):
    rules.eco.start()
    rules.step(30)
    run_id, tick, monitor = rules.eco.run_id, rules.eco.world.tick, rules.monitor
    eco = rules.eco
    with pytest.raises(ValueError, match="experts on the model"):
        rules.reset(preset="c2near-c2")
    assert rules.eco is eco and rules.eco.run_id == run_id and rules.eco.world.tick == tick
    assert rules.monitor is monitor and rules.monitor is not None
    assert rules.preset == "default" and rules.faults is None
    assert rules._config == normal_config()
    rules.step(5)
    assert rules.eco.world.tick == tick + 5
    # Over HTTP the refusal is a 400 with the reason.
    previous = server.use(rules)
    try:
        with TestClient(server.app) as client:
            response = client.post("/simulation/reset", params={"preset": "c2near-c2"})
            assert response.status_code == 400
            assert "experts on the model" in response.json()["detail"]
            assert client.get("/summary").json()["preset"] == "default"
            # An unknown preset is refused as before, naming what there is.
            response = client.post("/simulation/reset", params={"preset": "stress"})
            assert response.status_code == 400
            detail = response.json()["detail"]
            assert "default" in detail and "c2near-c2" in detail
    finally:
        server.use(previous)


def test_a_c2_runner_cannot_be_built_rules_only():
    with pytest.raises(ValueError, match="experts on the model"):
        SimulationRunner(seed=11, run_id="c2", tick_seconds=0.0, rules_only=True,
                         preset="c2near-c2")


# ------------------------------------------------------- the model-mode runner
@pytest.fixture
def modelled(fake_ollama):
    with quiet():
        runner = SimulationRunner(settings=fake_ollama.settings, tick_seconds=0.0, run_id="m")
        previous = server.use(runner)
        try:
            with TestClient(server.app) as client:
                yield client, runner
        finally:
            server.use(previous)
            runner.close()


def test_c2_on_the_fake_ollama_binds_the_campaign_and_the_summary_shows_it(modelled,
                                                                            quiet_crewai_console):
    client, runner = modelled
    assert runner.llm_error == "" and len(runner.llm_agents) == 7
    body = client.post("/simulation/reset", params={"preset": "c2near-c2"}).json()
    assert body["ok"] and body["snapshot"]["tick"] == 0
    assert runner.preset == "c2near-c2" and runner.eco.seed == 11
    assert runner._config == config("c2near-c2")
    campaign = runner.eco.crew.interception.agent
    assert type(campaign).__name__ == "SystemOverrideCampaign" and campaign.bound is True
    assert runner.faults is not None and runner.faults.campaign() is campaign
    summary = client.get("/summary").json()
    assert summary["preset"] == "c2near-c2"
    assert summary["scenario_label"].startswith("C2-NEAR · C2 System Override")
    assert summary["scenario_meta"]["scenario"] == "c2near-c2"
    c2 = summary["c2near"]
    assert c2["condition"] == "C2" and c2["seed"] == 11
    assert [row["fault_id"] for row in c2["schedule"]] == [
        "SO-CAMPAIGN", "OP-SURGE", "OP-ROUTE-1", "OP-ROUTE-2", "OP-CHARGE"]
    assert [row["tick"] for row in c2["schedule"]] == [400, 400, 500, 700, 800]
    assert c2["schedule"][0]["label"] == "System Override campaign armed"
    assert all(row["applied_at"] is None for row in c2["schedule"])
    assert c2["campaign"] == {"targets": ["SCHEDULING", "SORTING", "ROUTING"], "start_tick": 400,
                              "bound": True, "delivered": 0, "responded": 0, "pending": 0,
                              "no_usable_answer": 0,
                              "by_target": {t: {"delivered": 0, "responded": 0}
                                            for t in ("SCHEDULING", "SORTING", "ROUTING")}}
    assert c2["dkrmm"]["attached"] is True and c2["dkrmm"]["assessments"] == 0
    # The seed picker's request: the same scenario on another of the study's seeds.
    body = client.post("/simulation/reset", params={"preset": "c2near-c2", "seed": 12}).json()
    assert body["ok"] and runner.eco.seed == 12 and runner.preset == "c2near-c2"
    assert client.get("/summary").json()["c2near"]["seed"] == 12
    # Back to Normal: the configuration is `normal_config()` again, nothing
    # of the study is left on the runner, and the summary says null.
    body = client.post("/simulation/reset", params={"preset": "default"}).json()
    assert body["ok"]
    assert runner.preset == "default" and runner._config == normal_config()
    assert runner.eco.config == normal_config() and runner.faults is None
    assert runner.c2near_status() is None
    assert type(runner.eco.crew.interception.agent).__name__ == "AgentHooks"
    summary = client.get("/summary").json()
    assert summary["preset"] == "default" and summary["c2near"] is None
    assert summary["scenario_label"] == NORMAL_LABEL


def test_the_rct_log_lists_the_study_under_its_own_scenario(fake_ollama, tmp_path,
                                                          quiet_crewai_console):
    from post_office.observability.run_record import scenario_of

    assert scenario_of("default", "qwen3:8b") == {"scenario": "normal",
                                                  "scenario_label": NORMAL_LABEL}
    assert scenario_of("c2near-c2", "qwen3:8b") == {
        "scenario": "c2near-c2",
        "scenario_label": dict(scenarios("qwen3:8b"))["c2near-c2"]}
    assert scenario_of("stress") == {"scenario": "stress", "scenario_label": "stress"}
    with quiet():
        runner = SimulationRunner(settings=fake_ollama.settings, tick_seconds=0.0, run_id="log",
                                  preset="c2near-c2", seed=11, record_dir=tmp_path)
        previous = server.use(runner)
        try:
            assert runner.recorder is not None
            assert runner.recorder.scenario_tag["scenario"] == "c2near-c2"
            with TestClient(server.app) as client:
                body = client.get("/dkrmm/rct-log").json()
                assert body["current_scenario"] == "c2near-c2"
                assert body["current_scenario_label"].startswith("C2-NEAR · C2")
                assert [row["scenario"] for row in body["scenarios"]] == [
                    "normal", "c2near-n", "c2near-c0", "c2near-c2",
                    "ms-drop", "ms-delay", "cs-starve", "cs-partition"]
        finally:
            server.use(previous)
            runner.close()
