"""
The API runner keeps DK-RMM's record and each RCT on disk (trajectory/RCT design, section 4).

Every runner here is rules-only and records to the test's own `tmp_path`, or
nowhere: a test never writes under the project's `results/`. An RCT is forced
the way `tests/test_run_record.py` forces one: the last reading in the
monitor's history is marked RCT and the recorder is asked to update, since the
recorder only reads that history.
"""

from __future__ import annotations

import json

import pytest

from post_office.api.runner import SimulationRunner
from post_office.dkrmm import OperationalState


def _runner(tmp_path=None, **extra):
    return SimulationRunner(rules_only=True, tick_seconds=0,
                            record_dir=tmp_path, **extra)


@pytest.fixture
def recording(tmp_path):
    runner = _runner(tmp_path)
    try:
        runner.eco.start()
        yield runner
    finally:
        runner.close()


def _force_rct(runner):
    reading = runner.monitor.history[-1]
    reading.state = OperationalState.RCT
    runner.recorder.update(runner.monitor, runner.eco)
    return reading


def test_the_record_is_written_as_the_runner_ticks(recording, tmp_path):
    assert recording.recorder is not None
    assert recording.recorder.root == tmp_path
    recording.step(41)                                   # readings at ticks 1, 21 and 41
    path = tmp_path / "dkrmm" / f"{recording.recorder.name}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["app_run"] is True and record["run_id"] == recording.eco.run_id
    assert record["config"] == {"llm_agents": []}        # rules-only: none on the model
    assert [row["tick"] for row in record["readings"]] == [1, 21, 41]
    assert len(recording.monitor.history) == 3
    assert all(row["detected_at"] for row in record["readings"])
    assert recording.record_error == ""


def test_a_forced_rct_is_saved_with_the_reading_as_dkrmm_made_it(recording, tmp_path):
    recording.step(41)
    reading = _force_rct(recording)
    path = tmp_path / "rct" / recording.recorder.name / f"{reading.tick}.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["tick"] == reading.tick and saved["run_id"] == recording.eco.run_id
    assert saved["reading"] == reading.as_dict()
    assert saved["scenario"] == "normal"
    assert {"summary", "discussions", "linked"} <= set(saved["explanation"])


def test_a_gate_verdict_through_the_runner_rewrites_the_rct(recording, tmp_path):
    recording.step(41)
    reading = _force_rct(recording)
    path = tmp_path / "rct" / recording.recorder.name / f"{reading.tick}.json"
    assert json.loads(path.read_text(encoding="utf-8"))["reading"]["status"] == "DISCOVERED"
    recording.monitor.dismiss(by="hind", note="a quiet stretch, then normal work")
    recording.record_gate()
    saved = json.loads(path.read_text(encoding="utf-8"))["reading"]
    assert saved == reading.as_dict()
    assert saved["status"] == "DISMISSED" and saved["decided_by"] == "hind"
    record = json.loads(recording.recorder.record_path.read_text(encoding="utf-8"))
    assert record["readings"][-1]["status"] == "DISMISSED"


def test_a_reset_starts_a_new_recorder_under_a_new_name(recording, tmp_path):
    recording.step(21)
    first = recording.recorder
    recording.reset()
    assert recording.recorder is not None and recording.recorder is not first
    assert recording.recorder.run_id == recording.eco.run_id != first.run_id
    assert recording.recorder.name != first.name
    recording.eco.start()
    recording.step(21)
    assert (tmp_path / "dkrmm" / f"{first.name}.json").exists()
    assert (tmp_path / "dkrmm" / f"{recording.recorder.name}.json").exists()


def test_a_second_runner_with_the_same_run_id_gets_its_own_file(recording, tmp_path):
    recording.step(21)
    again = _runner(tmp_path)
    try:
        assert again.eco.run_id == recording.eco.run_id
        assert again.recorder.name != recording.recorder.name
    finally:
        again.close()


def test_a_recorder_that_raises_never_stops_the_run(recording, monkeypatch):
    def broken(monitor, eco):
        raise OSError("the disk is full")

    monkeypatch.setattr(recording.recorder, "update", broken)
    recording.step(25)
    assert recording.last_frame["tick"] == 25
    assert [a.tick for a in recording.monitor.history] == [1, 21]   # it kept reading
    assert "OSError" in recording.record_error and "disk is full" in recording.record_error


def test_without_a_record_dir_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = _runner()
    try:
        assert runner.recorder is None
        runner.eco.start()
        runner.step(41)
        runner.monitor.history[-1].state = OperationalState.RCT
        runner.record_gate()                             # nothing to write with
        runner.reset()
        assert runner.recorder is None
    finally:
        runner.close()
    assert list(tmp_path.iterdir()) == []


def test_a_recorder_that_cannot_be_built_says_why(tmp_path, monkeypatch):
    from post_office.observability import run_record

    def refused(self, *args, **kwargs):
        raise PermissionError("read-only folder")

    monkeypatch.setattr(run_record.RunRecorder, "__init__", refused)
    runner = _runner(tmp_path)
    try:
        assert runner.recorder is None
        assert runner.record_error == "PermissionError: read-only folder"
        runner.eco.start()
        runner.step(3)                                   # and the run goes on
        assert runner.last_frame["tick"] == 3
    finally:
        runner.close()


def test_no_monitor_means_no_recorder(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationRunner, "_start_monitor",
                        lambda self: setattr(self, "monitor", None))
    runner = _runner(tmp_path)
    try:
        assert runner.monitor is None and runner.recorder is None
    finally:
        runner.close()


def test_the_run_events_come_from_memory_or_from_the_log(tmp_path):
    runner = _runner()
    try:
        runner.eco.start()
        runner.step(5)
        events, source = runner.run_events()
        assert source == "memory"
        assert [e.seq for e in events] == [e.seq for e in runner.eco.logger.recent(100000)]
    finally:
        runner.close()
    logged = _runner(log_path=str(tmp_path / "run.events.jsonl"))
    try:
        logged.eco.start()
        logged.step(5)
        events, source = logged.run_events()
        assert source == "log"
        assert len(events) == logged.eco.logger.total
        assert {e.run_id for e in events} == {logged.eco.run_id}
    finally:
        logged.close()


def test_main_api_records_to_results_live_unless_told_otherwise(monkeypatch, tmp_path):
    import os

    import main
    from post_office.api import server

    served = []
    monkeypatch.setattr(server, "serve", lambda **kwargs: served.append(kwargs))
    assert main.main(["--api", "--rules"]) == 0
    assert served[-1]["record_dir"] == main.RECORD_DIR
    assert main.RECORD_DIR == os.path.join(os.path.dirname(os.path.abspath(main.__file__)),
                                           "results", "live")
    assert main.main(["--api", "--rules", "--record-dir", str(tmp_path)]) == 0
    assert served[-1]["record_dir"] == str(tmp_path)
    assert main.main(["--api", "--rules", "--no-record"]) == 0
    assert served[-1]["record_dir"] is None
    assert list(tmp_path.iterdir()) == []
