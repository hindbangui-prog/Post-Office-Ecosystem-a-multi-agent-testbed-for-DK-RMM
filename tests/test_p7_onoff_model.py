"""
P7-ONOFF-MODEL (`stress/onoff_model.py`, preset `p7-onoff-model`): the Phase 7
ON-OFF misbehaviour on experts that decide by their rules first and consult the
model when a rule is insufficient.

What is checked: the scenario is the eleventh option and shares `p7-onoff`'s
configuration, schedule and seeds; a rules-only runner refuses it the way it
refuses the C2 condition, before anything is touched; on the fake Ollama it
launches, runs, and its status carries the model's part per phase and the
blocked streaks ROUTING was asked about, with consistent counts; the rules-only
reference file holds the seed picker's six seeds and seed 11977's run is the
frozen Phase 7 confirmation run; the live page carries the two new cards and
none of the words the Normal page may not carry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from post_office.api.runner import SimulationRunner
from post_office.config.settings import (ONOFF_MODEL_PRESETS, ONOFF_PRESETS, config, known_presets,
                                         normal_config, scenario_meta, scenarios)
from post_office.crew.console import quiet
from post_office.stress import onoff_attack as rules_spec
from post_office.stress import onoff_model as spec
from post_office.stress.onoff_model import OnOffModelFaults, PHASE_KEYS, phase_key, reference
from tests.fake_ollama import deciding_script

ROOT = Path(__file__).resolve().parents[1]
FROZEN_EVENTS_SHA256_4400 = "f70f84e795f8325164b490493b526afb13f3b764d0042d34b1844928e440ec5e"
FORBIDDEN = ("attack", "perturb", "stress", "inject", "experiment", "autodk", "openrt")


# ------------------------------------------------------------- registration
def test_the_scenario_is_the_eleventh_option_and_shares_the_frozen_configuration():
    presets = [preset for preset, _ in scenarios("qwen3:8b")]
    assert presets == ["default", "c2near-n", "c2near-c0", "c2near-c2", "ms-drop", "ms-delay",
                       "cs-starve", "cs-partition", "ms-stall", "p7-onoff", "p7-onoff-model"]
    labels = dict(scenarios("qwen3:8b"))
    assert labels["p7-onoff"] == rules_spec.LABEL                 # the tenth option is as it was
    assert labels["p7-onoff-model"] == spec.label("qwen3:8b")
    assert labels["p7-onoff-model"] == "ON-OFF, model"          # names no model since 2026-10-23
    assert known_presets()[-2:] == ["p7-onoff", "p7-onoff-model"]
    assert ONOFF_MODEL_PRESETS == ("p7-onoff-model",) and set(ONOFF_MODEL_PRESETS) < set(ONOFF_PRESETS)
    assert config("p7-onoff-model") == config("p7-onoff") == normal_config()
    meta = scenario_meta("p7-onoff-model")
    assert meta["scenario"] == "p7-onoff-model" and "model" in meta["purpose"]
    assert "labelled a confirmed Dragon-King" in meta["about"] and "no run is" in meta["about"]
    for text in (meta["label"], meta["purpose"], meta["about"], spec.label("qwen3:8b")):
        assert not any(word in text.lower() for word in FORBIDDEN), text


def test_the_schedule_the_seeds_and_the_phase_keys_are_the_frozen_ones():
    assert spec.ATTACK_START == 1200 and spec.ATTACK_END == 3800 and spec.RUN_TICKS == 4400
    assert spec.DEMO_SEED == rules_spec.DEMO_SEED == 11977
    assert spec.SEED_OPTIONS is rules_spec.SEED_OPTIONS and spec.TRAPPED_SEEDS is rules_spec.TRAPPED_SEEDS
    assert spec.TARGETED == {"ROUTING": ["resolve_block"], "SCHEDULING": ["choose_next_task", "choose_robot"]}
    assert PHASE_KEYS == ["before", "ON1", "OFF1", "ON2", "OFF2", "ON3", "OFF3", "ON4", "after"]
    assert [phase_key(t) for t in (0, 1199, 1200, 1499, 1500, 1799, 1800, 2200, 2500, 3000, 3300, 3799, 3800, 4399)] == \
        ["before", "before", "ON1", "ON1", "OFF1", "OFF1", "ON2", "OFF2", "ON3", "OFF3", "ON4", "ON4", "after", "after"]


# ----------------------------------------------------------------- refusal
def test_a_rules_only_runner_refuses_the_scenario_before_anything_is_touched():
    with pytest.raises(ValueError) as refused:
        SimulationRunner(seed=11977, preset="p7-onoff-model", rules_only=True, verify_model=False, tick_seconds=0.0)
    assert "p7-onoff-model" in str(refused.value) and "rules-only ON-OFF scenario is p7-onoff" in str(refused.value)
    with quiet():
        runner = SimulationRunner(seed=11977, preset="p7-onoff", rules_only=True, verify_model=False, tick_seconds=0.0)
        try:
            runner.eco.start()
            for _ in range(5):
                assert runner._tick()
            with pytest.raises(ValueError):
                runner.reset(preset="p7-onoff-model")
            # The run goes on as it was: same preset, same seed, same tick, its faults in place.
            assert runner.preset == "p7-onoff" and runner._seed == 11977 and runner.eco.world.tick == 5
            assert runner.study_status()["preset"] == "p7-onoff"
            assert type(runner.faults).__name__ == "OnOffFaults"
        finally:
            runner.close()


# ------------------------------------------------------------- the model run
@pytest.fixture(scope="module")
def model_run(fake_ollama_module):
    fake_ollama_module.script(deciding_script("I would take the first option."))
    with quiet():
        runner = SimulationRunner(seed=11977, preset="p7-onoff-model", settings=fake_ollama_module.settings,
                                  tick_seconds=0.0, run_id="p7m")
        try:
            assert runner.llm_error == "" and "ROUTING" in runner.llm_agents and "SCHEDULING" in runner.llm_agents
            runner.eco.start()
            for _ in range(320):
                assert runner._tick()
            yield runner, fake_ollama_module
        finally:
            runner.close()


@pytest.fixture(scope="module")
def fake_ollama_module():
    from tests.fake_ollama import FakeOllama

    fake = FakeOllama()
    try:
        yield fake
    finally:
        fake.stop()


def test_the_scenario_launches_on_the_model_and_reports_the_models_part(model_run):
    runner, fake = model_run
    assert isinstance(runner.faults, OnOffModelFaults)
    assert runner.eco.world.tick == 320 and len(fake.requests) > 0
    study = runner.study_status()
    assert study["family"] == "onoff" and study["preset"] == "p7-onoff-model"
    assert study["scenario"] == "P7-ONOFF-MODEL" and study["label"] == spec.label("qwen3:8b")
    assert study["seed"] == 11977 and study["run_ticks"] == 4400 and study["complete"] is False
    assert [row["tick"] for row in study["schedule"]] == [1200, 1800, 2500, 3300]
    st = study["status"]
    assert st["variant"] == "model" and st["rules_preset"] == "p7-onoff" and st["model"]["model"] == "qwen3:8b"
    # Everything the rules-only status carries is still there, the same shape.
    for key in ("phase", "phases", "displacement", "robots", "head_to_head", "trap", "impact", "hospital",
                "consignment_ids", "demo_seed", "is_demo_seed"):
        assert key in st, key
    assert st["phase"]["before_window"] is True and st["displacement"]["displaced"] == 0   # before the window
    m = st["model"]
    assert m["phase_keys"] == PHASE_KEYS and m["phase_now"] == "before"
    tot = m["total"]
    assert tot["decisions"] > 0 and tot["model_asked"] > 0, "the fake model was consulted"
    assert tot["rule"] + tot["model_asked"] == tot["decisions"]
    assert tot["model_accepted"] + tot["model_rejected"] + tot["model_failed"] == tot["model_asked"]
    assert tot["displaced"] == 0 and tot["llm_calls"] >= tot["model_asked"]
    assert set(tot["by_agent"]) <= {"ROUTING", "SCHEDULING"} and sum(tot["by_trigger"].values()) == tot["model_asked"]
    assert m["by_phase"]["before"]["decisions"] == tot["decisions"]
    assert all(m["by_phase"][k]["decisions"] == 0 for k in PHASE_KEYS if k != "before")
    for row in m["resolutions"]:
        assert row["ended_on"] in ("rule", "model", "displaced", "none")
        assert row["answers"]["rule"] + row["answers"]["model"] + row["answers"]["displaced"] >= 1
        assert row["end"] > row["start"] and row["phase"] == "before"
    assert sum(m["resolution_counts"].values()) >= len(m["resolutions"])
    assert "not proof" in m["note"]
    # The rules-only run of the same seed, for the side-by-side column.
    ref = st["reference"]
    assert ref["available"] is True and ref["seed"] == 11977 and ref["preset"] == "p7-onoff"
    assert ref["trap"]["occurred"] is True and ref["trap"]["robots"] == ["R1", "R2"] and ref["trap"]["started"] == 1211
    assert ref["events_sha256"] == FROZEN_EVENTS_SHA256_4400


def test_entering_the_scenario_from_normal_starts_on_the_demonstration_seed(fake_ollama_module):
    fake_ollama_module.script(deciding_script("I would take the first option."))
    with quiet():
        runner = SimulationRunner(seed=3, settings=fake_ollama_module.settings, tick_seconds=0.0, run_id="p7m2")
        try:
            runner.reset(preset="p7-onoff-model")
            assert runner.preset == "p7-onoff-model" and runner._seed == 11977
            assert isinstance(runner.faults, OnOffModelFaults)
            runner.reset(preset="p7-onoff")                          # the rules-only one keeps the seed
            assert runner.preset == "p7-onoff" and runner._seed == 11977
            assert type(runner.faults).__name__ == "OnOffFaults"
            runner.reset(preset="p7-onoff-model", seed=11996)
            assert runner._seed == 11996 and runner.study_status()["status"]["reference"]["available"] is True
            runner.reset(preset="p7-onoff-model", seed=5)
            assert runner.study_status()["status"]["reference"] == {
                "available": False, "seed": 5, "seeds": [11322, 11977, 11996, 12057, 12070, 12196],
                "preset": "p7-onoff", "source": reference(11977)["source"]}
        finally:
            runner.close()


# ------------------------------------------------------------ the reference
def test_the_rules_only_reference_holds_the_picker_seeds_and_the_frozen_run():
    data = json.loads(spec.REFERENCE_PATH.read_text(encoding="utf-8"))
    assert data["preset"] == "p7-onoff" and data["horizon"] == 4400
    assert sorted(int(s) for s in data["runs"]) == sorted(seed for seed, _ in rules_spec.SEED_OPTIONS)
    demo = data["runs"]["11977"]
    assert demo["events_sha256"] == FROZEN_EVENTS_SHA256_4400 and demo["complete"] is True and demo["tick"] == 4400
    assert demo["trap"] == {**demo["trap"], "occurred": True, "persistent": True, "started": 1211,
                            "robots": ["R1", "R2"], "no_errand": True, "zone": "CHARGING"}
    assert demo["impact"]["robots_trapped"] == 2 and demo["dkrmm"]["first_dk_tick"] == 1341
    for row in data["runs"].values():
        assert set(row) >= {"trap", "impact", "dkrmm", "displaced", "events_sha256"}
        assert row["impact"]["hospital_total"] == 20


# --------------------------------------------------------------- the page
def test_the_live_page_carries_the_two_cards_and_none_of_the_words():
    page = (ROOT / "post_office" / "ui" / "live.html").read_text(encoding="utf-8")
    for word in FORBIDDEN:
        assert word not in page.lower(), word
    for marker in ('id="p7-model"', 'id="p7-compare"', 'id="p7-variant"', "function paintP7Model", "function paintP7Compare"):
        assert marker in page, marker
    assert re.search(r"not proof that it cleared the block", page)
    assert "no frozen artifacts for the rules-first, model-when-insufficient path" in page
    for name in ("onoff_model.py", "p7_rules_reference.json"):
        assert (ROOT / "post_office" / "stress" / name).exists()


# ------------------------------------------------ the rules-only scenario on a model-mode app
def test_the_rules_only_scenario_runs_on_rules_in_a_model_mode_app(fake_ollama_module):
    """`p7-onoff` builds no brains whatever mode the app is in; its label says "rules only"."""
    from post_office.config.settings import RULES_ONLY_PRESETS

    assert RULES_ONLY_PRESETS == ("p7-onoff",) and rules_spec.LABEL == "ON-OFF, rules only"
    assert dict(scenarios("qwen3:8b"))["p7-onoff"] == "ON-OFF, rules only"
    assert dict(scenarios("qwen3:8b"))["p7-onoff-model"] == "ON-OFF, model"
    fake_ollama_module.script(deciding_script("I would take the first option."))
    before = len(fake_ollama_module.requests)
    with quiet():
        runner = SimulationRunner(seed=11977, preset="p7-onoff", settings=fake_ollama_module.settings,
                                  tick_seconds=0.0, run_id="p7r")
        try:
            assert runner._brains == {} and runner.llm_agents == [] and runner.llm_wanted == []
            assert runner.settings is not None                      # the Ollama settings stay in force
            assert "runs every expert on its rules" in runner.llm_error and "p7-onoff-model" in runner.llm_error
            runner.eco.start()
            for _ in range(60):
                assert runner._tick()
            assert len(fake_ollama_module.requests) == before, "no model call on the rules-only scenario"
            assert runner.study_status()["label"] == rules_spec.LABEL
            runner.reset(preset="p7-onoff-model")                  # the model one gets its brains
            assert sorted(runner.llm_agents) == sorted(runner.llm_wanted) and runner.llm_error == ""
            runner.reset(preset="p7-onoff")
            assert runner.llm_agents == [] and runner._brains == {}
            runner.reset(preset="default")                          # Normal gets them back
            assert len(runner.llm_agents) == 7 and runner.llm_error == ""
        finally:
            runner.close()


def test_the_rules_only_scenario_gives_the_same_events_with_or_without_the_model_served(fake_ollama_module, tmp_path):
    import hashlib

    def sha(log: Path) -> str:
        rows = []
        for line in log.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if not 1 <= int(event.get("tick", 0)) <= 200:
                continue
            for key in ("wall_clock", "run_id", "seq"):
                event.pop(key, None)
            rows.append(json.dumps(event, sort_keys=True, separators=(",", ":")))
        return hashlib.sha256("\n".join(rows).encode()).hexdigest()

    hashes = []
    for name, kwargs in (("rules", {"rules_only": True, "verify_model": False}),
                         ("model-mode app", {"settings": fake_ollama_module.settings})):
        log = tmp_path / f"{name}.jsonl"
        with quiet():
            runner = SimulationRunner(seed=11977, preset="p7-onoff", tick_seconds=0.0, run_id="p7e",
                                      log_path=str(log), **kwargs)
            try:
                runner.eco.start()
                for _ in range(200):
                    assert runner._tick()
                runner._logger.flush()
            finally:
                runner.close()
        hashes.append(sha(log))
    assert hashes[0] == hashes[1]
