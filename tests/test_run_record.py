"""App runs keep DK-RMM's readings, the RCTs with their cause, and the gate decisions."""
import json

from post_office.config.settings import normal_config, scenario_label
from post_office.dkrmm import DKRMM
from post_office.dkrmm.states import OperationalState
from post_office.observability.run_record import RunRecorder, scenario_of
from post_office.simulation.ecosystem import build


class Recorded:
    """A NORMAL run, its monitor and its recorder, ticked as the runner ticks them."""

    def __init__(self, tmp_path, scenario="default"):
        self.eco = build(seed=3, config=normal_config(), run_id="rec",
                         log_path=str(tmp_path / "run.events.jsonl"), scenario="default")
        self.monitor = DKRMM(self.eco).attach()
        self.recorder = RunRecorder(str(tmp_path / "results"), self.eco.run_id,
                                    scenario=scenario, seed=3, config={"llm_agents": []})

    def step(self, n):
        for _ in range(n):
            self.eco.step()
            self.monitor.tick()
            self.recorder.update(self.monitor, self.eco)

    def close(self):
        self.monitor.close()
        self.eco.close()


def runner_in(tmp_path, **extra):
    return Recorded(tmp_path, **extra)


def test_the_dkrmm_record_is_written_as_the_run_goes(tmp_path):
    runner = runner_in(tmp_path)
    try:
        runner.eco.start()
        runner.step(81)                      # four assessments at 20, 40, 60, 80
        path = tmp_path / "results" / "dkrmm" / f"{runner.eco.run_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["app_run"] is True and record["run_id"] == runner.eco.run_id
        assert record["control"] is True
        readings = record["readings"]
        assert len(readings) == len(runner.monitor.history) >= 3
        assert all(r["detected_at"] for r in readings)          # a clock time each
    finally:
        runner.close()


def test_an_rct_is_saved_with_its_cause_when_it_is_detected(tmp_path):
    runner = runner_in(tmp_path)
    try:
        runner.eco.start()
        runner.step(41)
        # Stand in for DK-RMM calling an RCT: the recorder only reads the history.
        reading = runner.monitor.history[-1]
        reading.state = OperationalState.RCT
        runner.recorder.update(runner.monitor, runner.eco)
        rct = tmp_path / "results" / "rct" / runner.eco.run_id / f"{reading.tick}.json"
        saved = json.loads(rct.read_text(encoding="utf-8"))
        assert saved["tick"] == reading.tick and saved["detected_at"]
        assert saved["reading"]["state"] == "RCT"
        assert "summary" in saved["explanation"] and "discussions" in saved["explanation"]
    finally:
        runner.close()


def test_each_rct_says_which_scenario_it_was_detected_in(tmp_path):
    runner = runner_in(tmp_path)
    try:
        runner.eco.start()
        runner.step(41)
        reading = runner.monitor.history[-1]
        reading.state = OperationalState.RCT
        runner.recorder.update(runner.monitor, runner.eco)
        rct = tmp_path / "results" / "rct" / runner.eco.run_id / f"{reading.tick}.json"
        saved = json.loads(rct.read_text(encoding="utf-8"))
        assert saved["scenario"] == "normal" and saved["scenario_label"] == scenario_label()
        record = json.loads(runner.recorder.record_path.read_text(encoding="utf-8"))
        assert record["scenario_label"] == scenario_label()
        assert record["scenario"] == "default"                 # the preset, as before
    finally:
        runner.close()


def test_an_unknown_preset_is_recorded_under_its_own_name(tmp_path):
    runner = runner_in(tmp_path, scenario="stress")
    try:
        runner.eco.start()
        runner.step(41)
        reading = runner.monitor.history[-1]
        reading.state = OperationalState.RCT
        runner.recorder.update(runner.monitor, runner.eco)
        rct = tmp_path / "results" / "rct" / runner.eco.run_id / f"{reading.tick}.json"
        saved = json.loads(rct.read_text(encoding="utf-8"))
        assert saved["scenario"] == "stress" and saved["scenario_label"] == "stress"
    finally:
        runner.close()


def test_a_gate_decision_is_kept_in_the_record(tmp_path):
    runner = runner_in(tmp_path)
    try:
        runner.eco.start()
        runner.step(41)
        runner.monitor.dismiss(by="hind", note="robot congestion after a quiet stretch")
        runner.recorder.write(runner.monitor)
        path = tmp_path / "results" / "dkrmm" / f"{runner.eco.run_id}.json"
        last = json.loads(path.read_text(encoding="utf-8"))["readings"][-1]
        assert last["status"] == "DISMISSED" and last["decided_by"] == "hind"
        assert "quiet stretch" in last["note"]
    finally:
        runner.close()



def test_the_normal_label_names_the_model_it_is_given(tmp_path):
    assert scenario_of("default", model="m:1")["scenario_label"] == scenario_label("m:1")
    assert scenario_of("default")["scenario_label"] == scenario_label()
    recorder = RunRecorder(str(tmp_path / "results"), "rec", scenario="default", model="m:1")
    assert recorder.scenario_tag == {"scenario": "normal",
                                     "scenario_label": scenario_label("m:1")}
