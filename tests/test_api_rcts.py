"""
The DK-RMM routes of the trajectory/RCT design, section 5 (the /ui/* ones aside).

    GET  /dkrmm/rcts                         the current run's RCTs, newest first
    GET  /dkrmm/explain?tick=                what drove one reading, from the run's events
    GET  /dkrmm/rct-log                      every saved RCT, with the scenarios
    GET  /dkrmm/rct-log/item?run=&tick=      one saved RCT whole
    POST /dkrmm/validate|activate|dismiss    a person's verdict on the current reading

Each runner is rules-only. `recording` records to the test's `tmp_path`;
`unrecorded` records nowhere. An RCT is forced as `tests/test_recording.py`
forces one. DK-RMM's code is pinned by its tree hash (and, where git and a
`main` other than HEAD are at hand, by `git diff main`).
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
from post_office.config.settings import scenario_label, scenarios
from post_office.dkrmm import OperationalState
from tools.provenance import tree_sha

ROOT = Path(__file__).resolve().parent.parent

#: `tools.provenance.tree_sha` of `post_office/dkrmm/`: the trajectory/RCT design
#: changes no DK-RMM code (its invariant 1), so this pins the tree. Re-pinned on
#: 2026-10-12 for the operational and early-warning extension of DK-RMM itself
#: (docs/dkrmm-mathematics.md, section 21), which is the one change the pin is
#: meant to admit; it was 5eb100c6...ab58b as on `main` (95d7109) before that.
DKRMM_TREE_SHA = "a98b1a2da004b54a98732e3a920f7d13082815172609099ae4274a4ca19eb3ca"

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


def test_without_an_rct_the_log_is_not_read(unrecorded, monkeypatch):
    client, runner = unrecorded
    runner.step(41)

    def unread():
        raise AssertionError("the run's events were read with no RCT to date")

    monkeypatch.setattr(runner, "run_events", unread)
    body = client.get("/dkrmm/rcts").json()
    assert body["rcts"] == [] and body["assessments"] == 3


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
    assert body["tick"] == 40 and body["window"] == [0, 40]
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


def test_a_saved_rct_is_explained_from_the_log_once_while_the_pane_polls(tmp_path):
    # The tick thread saves RCTs from the log while open DK-RMM panes poll
    # /dkrmm/rcts, which reads the same log: each saved explanation must equal
    # a fresh, single-threaded one over the log as written.
    from types import SimpleNamespace

    from post_office.observability import rct_explain

    rct_explain._CACHE.clear()
    runner = SimulationRunner(rules_only=True, tick_seconds=0, record_dir=tmp_path,
                              log_path=str(tmp_path / "run.events.jsonl"))
    client, done = _serve(runner)
    stop = threading.Event()

    def poll():                                      # what an open DK-RMM pane does
        while not stop.is_set():
            client.get("/dkrmm/rcts")

    pollers = [threading.Thread(target=poll) for _ in range(2)]
    wrong = []
    try:
        runner.eco.start()
        runner.step(21)
        with runner._record_lock:
            _force_rct(runner)                       # an RCT on record: the polls read the log
        for t in pollers:
            t.start()
        for _ in range(8):
            runner.step(20)
            with runner._record_lock:
                reading = _force_rct(runner)
            saved = json.loads((tmp_path / "rct" / runner.recorder.name
                                / f"{reading.tick}.json").read_text(encoding="utf-8"))
            runner._logger.flush()
            mine = []
            for line in Path(runner._logger.path).read_bytes().splitlines():
                raw = json.loads(line)
                raw["detail"] = raw.get("detail") or {}
                mine.append(SimpleNamespace(**raw))
            truth = json.loads(json.dumps(rct_explain.explain(mine, reading.tick)))
            if saved["explanation"] != truth:
                wrong.append((reading.tick, saved["explanation"]["events"], truth["events"]))
    finally:
        stop.set()
        for t in pollers:
            if t.is_alive():
                t.join()
        done()
    assert wrong == []


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
    # Normal first with no RCT, then the C2-NEAR conditions, each listed under
    # its own name with no RCT either.
    model = getattr(runner.settings, "model", None)
    offered = [{"scenario": "normal" if preset == "default" else preset,
                "scenario_label": shown, "count": 0} for preset, shown in scenarios(model)]
    assert body["scenarios"][0] == {"scenario": "normal", "scenario_label": label, "count": 0}
    assert body["scenarios"] == offered
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
    assert body["scenarios"][0] == {"scenario": "normal", "scenario_label": label, "count": 1}
    assert body["scenarios"][1:8] == [row for row in offered if row["scenario"] != "normal"]
    assert body["scenarios"][8:] == [{"scenario": "stress", "scenario_label": "stress", "count": 1}]


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
    assert [row["count"] for row in body["scenarios"]] == [0] * 8
    assert body["scenarios"][0]["scenario"] == "normal"
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


def _hold_the_step_lock(runner, seconds):
    held = threading.Event()

    def hold():
        with runner._lock:
            held.set()
            time.sleep(seconds)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(5)
    return holder


def test_a_verdict_does_not_wait_for_the_tick_in_progress(unrecorded):
    client, runner = unrecorded
    runner.step(21)
    holder = _hold_the_step_lock(runner, 2.0)
    try:
        started = time.perf_counter()
        response = client.post("/dkrmm/validate", json={"by": "hind"})
        took = time.perf_counter() - started
    finally:
        holder.join()
    assert response.status_code == 200 and response.json()["status"] == "VALIDATED"
    assert took < 1.0, f"the verdict took {took:.2f} s while a tick held the lock"


def test_a_verdict_after_a_reset_answers_on_the_new_monitor(unrecorded):
    client, runner = unrecorded
    runner.step(21)
    old = runner.monitor
    runner.reset()
    assert runner.monitor is not old and runner.monitor.current is None
    assert client.post("/dkrmm/validate", json={"by": "hind"}).status_code == 409
    assert old.current.status.value == "DISCOVERED"


def test_a_reset_during_a_verdict_leaves_the_verdict_on_the_new_run(unrecorded, monkeypatch):
    """A reset that lands between resolving the monitor and deciding: the live
    run's monitor answers (409, nothing assessed yet), not the discarded one."""
    client, runner = unrecorded
    runner.step(21)
    old = runner.monitor
    decide = old.validate

    def reset_first(**kwargs):
        runner.reset()
        return decide(**kwargs)

    monkeypatch.setattr(old, "validate", reset_first)
    response = client.post("/dkrmm/validate", json={"by": "hind"})
    assert response.status_code == 409
    assert runner.monitor is not old and runner.monitor.current is None


def test_the_recorder_writes_one_at_a_time(recording, monkeypatch):
    client, runner = recording
    seen = []
    update, write = runner.recorder.update, runner.recorder.write

    def watched_update(monitor, eco):
        seen.append(("update", runner._record_lock.locked()))
        return update(monitor, eco)

    def watched_write(monitor):
        seen.append(("write", runner._record_lock.locked()))
        return write(monitor)

    monkeypatch.setattr(runner.recorder, "update", watched_update)
    monkeypatch.setattr(runner.recorder, "write", watched_write)
    runner.step(21)
    assert client.post("/dkrmm/dismiss", json={"by": "hind"}).status_code == 200
    assert ("write", True) in seen and ("update", True) in seen
    assert all(locked for _, locked in seen)


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
def test_dkrmm_is_unchanged():
    assert tree_sha(ROOT / "post_office" / "dkrmm") == DKRMM_TREE_SHA


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def test_dkrmm_is_unchanged_against_main_when_git_can_say():
    """An extra, where git is at hand and `main` is not this very commit."""
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    main, head = _git("rev-parse", "--verify", "--quiet", "main"), _git("rev-parse", "HEAD")
    if main.returncode != 0 or head.returncode != 0:
        pytest.skip("no main branch to compare with")
    if main.stdout == head.stdout:
        pytest.skip("main is HEAD: nothing to compare")
    diff = _git("diff", "main", "--", "post_office/dkrmm")
    assert diff.returncode == 0 and diff.stdout == ""
