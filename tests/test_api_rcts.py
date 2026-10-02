"""
The DK-RMM routes of the trajectory/RCT design, section 5 (the /ui/* ones aside).

    GET  /dkrmm/rcts                         the current run's RCTs, newest first
    GET  /dkrmm/explain?tick=                what drove one reading, from the run's events
    GET  /dkrmm/rct-log                      every saved RCT, with the scenarios
    GET  /dkrmm/rct-log/item?run=&tick=      one saved RCT whole
    POST /dkrmm/validate|activate|dismiss    a person's verdict on the current reading

Each runner is rules-only. `recording` records to the test's `tmp_path`;
`unrecorded` records nowhere. An RCT is forced as `tests/test_recording.py`
forces one. DK-RMM's code is checked unchanged against `main`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from post_office.api import server
from post_office.api.runner import SimulationRunner
from post_office.config.settings import scenario_label
from post_office.dkrmm import OperationalState

ROOT = Path(__file__).resolve().parent.parent

EXPLAIN_KEYS = {"tick", "window", "events", "trouble", "kinds", "messages",
                "discussion_messages", "discussions", "linked", "baseline", "summary",
                "source"}
RCT_KEYS = {"tick", "detected_at", "severity", "kinds", "evidence", "status"}
LOG_KEYS = {"rcts", "current_run", "recording", "folder", "current_scenario",
            "current_scenario_label", "scenarios", "record_error"}


def _serve(runner):
    previous = server.use(runner)
    client = TestClient(server.app)
    client.__enter__()

    def done():
        client.__exit__(None, None, None)
        server.use(previous)
        runner.close()
    return client, done


@pytest.fixture
def recording(tmp_path):
    runner = SimulationRunner(rules_only=True, tick_seconds=0, record_dir=tmp_path)
    client, done = _serve(runner)
    try:
        runner.eco.start()
        yield client, runner
    finally:
        done()


@pytest.fixture
def unrecorded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = SimulationRunner(rules_only=True, tick_seconds=0)
    client, done = _serve(runner)
    try:
        runner.eco.start()
        yield client, runner
    finally:
        done()
    assert list(tmp_path.iterdir()) == []


def _force_rct(runner):
    reading = runner.monitor.history[-1]
    reading.state = OperationalState.RCT
    if runner.recorder is not None:
        runner.recorder.update(runner.monitor, runner.eco)
    return reading


# ------------------------------------------------------------- /dkrmm/rcts
def test_the_current_runs_rcts_are_listed_newest_first(recording):
    client, runner = recording
    runner.step(41)
    body = client.get("/dkrmm/rcts").json()
    assert body == {"rcts": [], "assessments": 3, "run_id": runner.eco.run_id}
    first = runner.monitor.history[-2]
    first.state = OperationalState.RCT
    second = _force_rct(runner)
    rows = client.get("/dkrmm/rcts").json()["rcts"]
    assert [row["tick"] for row in rows] == [second.tick, first.tick] == [41, 21]
    for row in rows:
        assert set(row) == RCT_KEYS
        assert row["detected_at"] and row["status"] == "DISCOVERED"


def test_the_rcts_are_listed_without_a_recorder_too(unrecorded):
    client, runner = unrecorded
    runner.step(21)
    reading = _force_rct(runner)
    rows = client.get("/dkrmm/rcts").json()["rcts"]
    assert [row["tick"] for row in rows] == [reading.tick]


# ----------------------------------------------------------- /dkrmm/explain
def test_a_reading_is_explained_from_the_runs_own_events(unrecorded):
    client, runner = unrecorded
    runner.step(41)
    body = client.get("/dkrmm/explain", params={"tick": 40}).json()
    assert set(body) == EXPLAIN_KEYS
    assert body["tick"] == 40 and body["window"] == [-19, 40]
    assert body["events"] > 0 and isinstance(body["summary"], str) and body["summary"]
    assert body["source"] == "memory"
    assert client.get("/dkrmm/explain").status_code == 422              # a tick is required
    assert client.get("/dkrmm/explain", params={"tick": -1}).status_code == 422


def test_the_explanation_reads_the_log_file_when_there_is_one(tmp_path):
    runner = SimulationRunner(rules_only=True, tick_seconds=0,
                              log_path=str(tmp_path / "run.events.jsonl"))
    client, done = _serve(runner)
    try:
        runner.eco.start()
        runner.step(21)
        body = client.get("/dkrmm/explain", params={"tick": 20}).json()
        assert body["source"] == "log" and body["events"] > 0
    finally:
        done()


# ----------------------------------------------------------- /dkrmm/rct-log
def test_the_rct_log_lists_what_was_saved_with_the_scenarios(recording, tmp_path):
    client, runner = recording
    runner.step(41)
    label = scenario_label(getattr(runner.settings, "model", None))
    body = client.get("/dkrmm/rct-log").json()
    assert set(body) == LOG_KEYS
    assert body["recording"] is True and body["folder"] == str(tmp_path)
    assert body["current_run"] == runner.recorder.name and body["rcts"] == []
    assert body["current_scenario"] == "normal"
    assert body["current_scenario_label"] == label
    assert body["scenarios"] == [{"scenario": "normal", "scenario_label": label, "count": 0}]
    assert body["record_error"] == ""

    reading = _force_rct(runner)
    older = tmp_path / "rct" / "older-run"
    older.mkdir(parents=True)
    (older / "7.json").write_text(json.dumps({
        "run_id": "older", "scenario": "stress", "scenario_label": "stress", "tick": 7,
        "detected_at": "2026-01-01T00:00:00.000+00:00",
        "reading": {"severity": 1.0, "kinds": ["retry"], "status": "DISMISSED"},
        "explanation": {"summary": "an older run"}}), encoding="utf-8")
    body = client.get("/dkrmm/rct-log").json()
    rows = {(row["run"], row["tick"]): row for row in body["rcts"]}
    assert set(rows) == {(runner.recorder.name, reading.tick), ("older-run", 7)}
    assert rows[(runner.recorder.name, reading.tick)]["current"] is True
    assert rows[("older-run", 7)]["current"] is False
    assert body["rcts"][0]["run"] == runner.recorder.name                # newest first
    assert body["scenarios"] == [
        {"scenario": "normal", "scenario_label": label, "count": 1},
        {"scenario": "stress", "scenario_label": "stress", "count": 1}]


def test_one_saved_rct_is_served_whole(recording):
    client, runner = recording
    runner.step(41)
    reading = _force_rct(runner)
    name = runner.recorder.name
    body = client.get("/dkrmm/rct-log/item", params={"run": name, "tick": reading.tick})
    assert body.status_code == 200
    saved = body.json()
    assert saved["reading"] == reading.as_dict() and saved["tick"] == reading.tick
    assert {"summary", "discussions"} <= set(saved["explanation"])
    missing = client.get("/dkrmm/rct-log/item", params={"run": name, "tick": 999})
    assert missing.status_code == 404
    assert client.get("/dkrmm/rct-log/item",
                      params={"run": "older-run", "tick": 1}).status_code == 404
    for bad in ("..", ".hidden", "a/b"):
        assert client.get("/dkrmm/rct-log/item",
                          params={"run": bad, "tick": 1}).status_code == 400, bad
    assert client.get("/dkrmm/rct-log/item", params={"run": name}).status_code == 422


def test_without_a_recorder_the_log_is_empty_and_items_are_absent(unrecorded):
    client, runner = unrecorded
    runner.step(41)
    reading = _force_rct(runner)
    body = client.get("/dkrmm/rct-log").json()
    assert set(body) == LOG_KEYS
    assert body["recording"] is False and body["rcts"] == []
    assert body["folder"] == "" and body["current_run"] == ""
    assert body["current_scenario"] == "normal"
    assert [row["count"] for row in body["scenarios"]] == [0]
    item = client.get("/dkrmm/rct-log/item", params={"run": "api", "tick": reading.tick})
    assert item.status_code == 404


def test_a_failing_recorder_is_reported_in_the_log(recording, monkeypatch):
    client, runner = recording

    def broken(monitor, eco):
        raise OSError("the disk is full")

    monkeypatch.setattr(runner.recorder, "update", broken)
    runner.step(3)
    assert "disk is full" in client.get("/dkrmm/rct-log").json()["record_error"]


# -------------------------------------------------------------- the gate
def test_there_is_nothing_to_decide_before_the_first_reading(unrecorded):
    client, _ = unrecorded
    for verdict in ("validate", "activate", "dismiss"):
        response = client.post(f"/dkrmm/{verdict}", json={"by": "hind"})
        assert response.status_code == 409, verdict
        assert response.json()["detail"]


def test_a_verdict_is_recorded_on_the_reading_and_returned(unrecorded):
    client, runner = unrecorded
    runner.step(21)
    assert client.post("/dkrmm/activate", json={}).status_code == 409   # not validated yet
    validated = client.post("/dkrmm/validate", json={"by": "hind", "note": "seen it"})
    assert validated.status_code == 200
    body = validated.json()
    assert body == runner.monitor.current.as_dict()
    assert body["status"] == "VALIDATED" and body["decided_by"] == "hind"
    assert body["note"] == "seen it" and body["decided_at"]
    active = client.post("/dkrmm/activate", json={}).json()
    assert active["status"] == "ACTIVE" and active["decided_by"] == "operator"
    dismissed = client.post("/dkrmm/dismiss", json={"by": "hind", "note": "after all, no"})
    assert dismissed.json()["status"] == "DISMISSED"
    assert dismissed.json()["decided_by"] == "hind"


def test_a_verdict_rewrites_the_saved_rct(recording, tmp_path):
    client, runner = recording
    runner.step(41)
    reading = _force_rct(runner)
    body = client.post("/dkrmm/dismiss", json={"by": "hind", "note": "a quiet stretch"}).json()
    assert body["status"] == "DISMISSED" and body["decided_by"] == "hind"
    path = tmp_path / "rct" / runner.recorder.name / f"{reading.tick}.json"
    assert json.loads(path.read_text(encoding="utf-8"))["reading"] == body
    item = client.get("/dkrmm/rct-log/item",
                      params={"run": runner.recorder.name, "tick": reading.tick}).json()
    assert item["reading"]["status"] == "DISMISSED"


def test_a_verdict_is_bounded(unrecorded):
    client, runner = unrecorded
    runner.step(21)
    assert client.post("/dkrmm/validate", json={"by": "x" * 81}).status_code == 422
    assert client.post("/dkrmm/validate", json={"note": "x" * 501}).status_code == 422
    assert runner.monitor.current.status.value == "DISCOVERED"


def test_without_a_monitor_the_routes_say_so(unrecorded, monkeypatch):
    client, runner = unrecorded
    monkeypatch.setattr(runner, "monitor", None)
    for path in ("/dkrmm/rcts", "/dkrmm/explain?tick=1"):
        assert client.get(path).status_code == 503, path
    assert client.post("/dkrmm/validate", json={}).status_code == 503


# ----------------------------------------------------- reads take no lock
def test_the_reads_do_not_wait_for_the_step_lock(recording):
    client, runner = recording
    runner.step(41)
    reading = _force_rct(runner)
    held, release = threading.Event(), threading.Event()

    def hold():
        with runner._lock:
            held.set()
            release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert held.wait(5)
        for path, params in (("/dkrmm/rcts", None), ("/dkrmm/explain", {"tick": 40}),
                             ("/dkrmm/rct-log", None),
                             ("/dkrmm/rct-log/item",
                              {"run": runner.recorder.name, "tick": reading.tick})):
            started = time.perf_counter()
            response = client.get(path, params=params)
            assert response.status_code == 200, path
            assert time.perf_counter() - started < 2.0, path
    finally:
        release.set()
        holder.join()


# ---------------------------------------------------------- DK-RMM as is
def test_dkrmm_is_unchanged_against_main():
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    known = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "main"], cwd=ROOT,
                           capture_output=True, text=True)
    if known.returncode != 0:
        pytest.skip("no main branch to compare with")
    diff = subprocess.run(["git", "diff", "main", "--", "post_office/dkrmm"], cwd=ROOT,
                          capture_output=True, text=True)
    assert diff.returncode == 0 and diff.stdout == ""
