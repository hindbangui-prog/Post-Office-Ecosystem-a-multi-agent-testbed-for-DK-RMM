"""
The live runner's experiment recording and its read-only observers.

`--experiment-dir` / `--stop-at` (main.py), `observability/experiment.py`,
`observability/zone_backlog.py`, `observability/decision_trace.py`, the bus's
`watch_inbox`, and the `/zones`, `/decision-traces` and `/summary.kept`
reads. What is checked:

- the observers emit nothing and change nothing: a run's event stream is the
  same with them attached and detached, and with an inbox watcher or without;
- a run stops by itself at its stop tick, a Start after that does not tick,
  and a pause keeps the run `incomplete` until it is resumed and finished;
- a run directory is never written twice (`s<seed>-2`);
- the zone rows sum to the parcels inside, reconcile tick by tick, and agree
  with the study collector's `series.csv`;
- under M-S-DROP the fault fires at 400 and holds: every message sent from
  400 on is dropped and no robot command is applied after it;
- every link a trace makes is backed by the identifiers it names;
- a model-mode run (fake Ollama) records its mode, identity and served models,
  and its consulted decisions carry the consultation and the model calls.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from post_office.api import server
from post_office.api.runner import SimulationRunner
from post_office.config.settings import normal_config
from post_office.crew.console import quiet
from post_office.observability.decision_trace import DecisionTracer
from post_office.observability.zone_backlog import ZONE_COLUMNS, ZoneSeries
from post_office.simulation import build


def _stream(eco, ticks):
    rows = []
    eco.logger.subscribe(lambda e: rows.append(
        (e.tick, e.category, e.topic, e.actor, e.target, e.correlation_id,
         json.dumps(e.detail, sort_keys=True, default=str))))
    eco.start()
    for _ in range(ticks):
        eco.step()
    return rows


def _run_to_end(runner, timeout=600):
    runner.start()
    end = time.time() + timeout
    while runner.is_running and time.time() < end:
        time.sleep(0.05)
    assert not runner.is_running


# ------------------------------------------------------------ no side effects
def test_observers_change_nothing_in_the_event_stream():
    plain = build(3, config=normal_config(), scenario="normal")
    a = _stream(plain, 300)
    plain.close()
    watched = build(3, config=normal_config(), scenario="normal")
    tracer = DecisionTracer(watched)
    zones = ZoneSeries(watched)
    rows = []
    watched.logger.subscribe(lambda e: rows.append(
        (e.tick, e.category, e.topic, e.actor, e.target, e.correlation_id,
         json.dumps(e.detail, sort_keys=True, default=str))))
    watched.start()
    for _ in range(300):
        watched.step()
        zones.sample()
    tracer.close()
    watched.close()
    assert rows == a
    assert tracer.decisions and len(zones.rows) == 301


def test_an_inbox_watcher_sees_every_take_and_alters_none():
    eco = build(5, config=normal_config(), scenario="normal")
    taken = []
    eco.bus.watch_inbox(lambda who, tick, msgs: taken.extend(m.message_id for m in msgs))
    received = []
    eco.logger.subscribe(lambda e: None)
    eco.start()
    for _ in range(80):
        eco.step()
    received = sum(a.received for a in eco.agents.values())
    eco.close()
    assert len(taken) == received > 0
    assert len(set(taken)) == len(taken)


def test_a_runner_without_the_options_never_stops_by_itself_and_writes_nothing(tmp_path):
    runner = SimulationRunner(rules_only=True, tick_seconds=0)
    try:
        assert runner.stop_at is None and runner.experiment_status()["enabled"] is False
        runner.step(30)
        runner.start()
        assert runner.experiment is None
        runner.stop()
    finally:
        runner.close()
    assert not any(tmp_path.iterdir())


# -------------------------------------------------------------- the run's end
def test_a_run_stops_at_its_stop_tick_and_is_kept_complete(tmp_path):
    runner = SimulationRunner(rules_only=True, tick_seconds=0, experiment_dir=tmp_path,
                              stop_at=60)
    try:
        runner.reset(seed=11, preset="ms-drop")
        _run_to_end(runner)
        assert runner.eco.world.tick == 60
        runner.start()                         # over: a Start does not tick on
        time.sleep(0.2)
        assert runner.eco.world.tick == 60 and not runner.is_running
        state = runner.experiment_status()
        assert state["current"] is None and state["last"]["status"] == "complete"
    finally:
        runner.close()
    run = tmp_path / "MS-DROP" / "s11"
    done = json.loads((run / "done.json").read_text())
    assert done["ticks"] == 60 and done["mode"] == "rules" and done["scenario"] == "MS-DROP"
    for name in ("definition.json", "events.jsonl", "series.csv", "measurement.json",
                 "zone_backlog.csv", "dkrmm_assessments.jsonl", "dkrmm.json",
                 "decision_traces.jsonl", "message_traces.jsonl", "trace_summary.json",
                 "summary.json", "verify.json", "status.json"):
        assert (run / name).exists(), name
    with (run / "series.csv").open() as handle:
        assert len(list(csv.DictReader(handle))) == 60
    assert json.loads((run / "status.json").read_text())["status"] == "complete"


def test_a_pause_is_incomplete_and_a_reset_never_overwrites(tmp_path):
    runner = SimulationRunner(rules_only=True, tick_seconds=0.01, experiment_dir=tmp_path,
                              stop_at=80)
    try:
        runner.reset(seed=12, preset="c2near-n")
        runner.start()
        while runner.eco.world.tick < 10:
            time.sleep(0.01)
        runner.stop()
        time.sleep(0.1)
        run = tmp_path / "N" / "s12"
        assert json.loads((run / "status.json").read_text())["status"] == "incomplete"
        assert not (run / "done.json").exists()
        runner.tick_seconds = 0
        _run_to_end(runner)
        assert (run / "done.json").exists()
        runner.reset(seed=12, preset="c2near-n")
        runner.start()
        while runner.eco.world.tick < 5:
            time.sleep(0.01)
        runner.reset(seed=12, preset="c2near-n")       # abandoned: kept as incomplete
    finally:
        runner.close()
    second = tmp_path / "N" / "s12-2"
    status = json.loads((second / "status.json").read_text())
    assert status["status"] == "incomplete" and status["reason"].startswith("reset at tick")
    assert json.loads((tmp_path / "N" / "s12" / "done.json").read_text())["ticks"] == 80


def test_a_preset_that_is_not_an_experiment_is_not_kept(tmp_path):
    runner = SimulationRunner(rules_only=True, tick_seconds=0, experiment_dir=tmp_path,
                              stop_at=20)
    try:
        runner.reset(seed=11, preset="c2near-c0")
        _run_to_end(runner)
        assert "not kept" in runner.experiment_status()["error"]
    finally:
        runner.close()
    assert not any(tmp_path.iterdir())


def test_experiment_dir_needs_a_stop_tick_and_refuses_results_normal():
    with pytest.raises(SystemExit):
        main.parse_args(["--api", "--experiment-dir", "x"])
    with pytest.raises(SystemExit):
        main.parse_args(["--api", "--experiment-dir", "results/normal/x", "--stop-at", "10"])
    args = main.parse_args(["--api", "--experiment-dir", "results/m_s_drop_crewai/live",
                            "--stop-at", "2800"])
    assert args.stop_at == 2800


# ----------------------------------------------------------- M-S-DROP, 450 ticks
@pytest.fixture(scope="module")
def drop_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("exp")
    runner = SimulationRunner(rules_only=True, tick_seconds=0, experiment_dir=root,
                              stop_at=450)
    try:
        runner.reset(seed=11, preset="ms-drop")
        _run_to_end(runner)
        rule = runner.eco.bus.delay_rule
    finally:
        runner.close()
    return root / "MS-DROP" / "s11", rule


def test_the_zone_rows_sum_reconcile_and_agree_with_the_series(drop_run):
    run, _ = drop_run
    zones = list(csv.DictReader((run / "zone_backlog.csv").open()))
    series = {int(r["tick"]): r for r in csv.DictReader((run / "series.csv").open())}
    assert [int(r["tick"]) for r in zones] == list(range(0, 451))
    for row in zones:
        assert sum(int(row[k]) for k in ZONE_COLUMNS) == int(row["total"])
    for row in zones[1:]:
        assert row["reconciled"] == "True"
        mine = series[int(row["tick"])]
        assert int(row["total"]) == int(mine["backlog"])
        assert int(row["arrivals"]) == int(mine["arrivals"])
        assert int(row["dock_refusals"]) == int(mine["arrival_refused"])
        assert int(row["completions"]) == int(mine["dispatched"])
        assert int(row["loaded_on_van"]) <= int(row["dispatch"])


def test_the_fault_fires_at_400_and_holds_to_the_end(drop_run):
    run, rule = drop_run
    assert rule is not None and type(rule).__name__ == "DropAll"
    events = [json.loads(line) for line in (run / "events.jsonl").open()]
    fired = [e for e in events if e["topic"] == "stress_fault_activated"]
    assert [e["tick"] for e in fired] == [400]
    sent = {e["detail"]["message_id"]: e["tick"] for e in events
            if e["topic"] in ("message", "subagent_message")}
    dropped = {e["detail"]["message_id"] for e in events if e["topic"] == "message_dropped"}
    late = [m for m, t in sent.items() if 400 <= t < 450 and m not in dropped]
    assert late == []                                  # every one sent 400..449 dropped
    assert not [e for e in events if e["topic"].startswith("command_") and e["tick"] > 400]
    messages = [json.loads(line) for line in (run / "message_traces.jsonl").open()]
    after = [m for m in messages if m["tick"] >= 400]
    assert after and all(m["outcome"]["state"] in ("dropped", "pending") for m in after)


def test_every_trace_link_is_backed_by_its_identifiers(drop_run):
    run, _ = drop_run
    events = [json.loads(line) for line in (run / "events.jsonl").open()]
    by_seq = {e["seq"]: e for e in events}
    dropped = {e["detail"]["message_id"]: e["tick"] for e in events
               if e["topic"] == "message_dropped"}
    sent = {e["detail"]["message_id"]: e for e in events
            if e["topic"] in ("message", "subagent_message")}
    traces = [json.loads(line) for line in (run / "decision_traces.jsonl").open()]
    assert traces
    linked = applied = 0
    for t in traces:
        decision = by_seq[t["seq"]]
        assert decision["topic"] == "decision" and decision["detail"]["call_id"] == t["decision_id"]
        for m in t["messages"]:
            linked += 1
            ev = sent[m["message_id"]]
            content = ev["detail"].get("content") or {}
            keys = {ev["correlation_id"], content.get("task_id"), content.get("correlation_id")}
            assert t["subject"] in keys
            assert ev["actor"] == t["actor"] and ev["tick"] == t["tick"] and ev["seq"] > t["seq"]
            if m["outcome"]["state"] == "dropped":
                assert dropped[m["message_id"]] == m["outcome"]["tick"]
            if (m.get("applied") or {}).get("state") == "applied":
                applied += 1
                cmd = by_seq[m["applied"]["event_seq"]]
                assert cmd["topic"] == "command_" + m["operation"]
                assert cmd["actor"] == m["sender"] and cmd["target"] == m["receiver"]
                assert cmd["correlation_id"] == m["correlation_id"]
        if t["request"]:
            reply = sent[t["request"]["result_message_id"]]
            assert (reply["detail"].get("content") or {}).get("operation") == t["decision"]
    assert linked > 0 and applied > 0


def test_the_trace_summary_splits_at_the_fault(drop_run):
    run, _ = drop_run
    summary = json.loads((run / "trace_summary.json").read_text())
    assert summary["fault_tick"] == 400
    post = summary["phases"]["post"]
    assert post["robot_commands"]["applied"] == 0
    assert post["eligible"] == 0                 # nothing reaches a message-gated decision


# --------------------------------------------------------------- model mode
@pytest.fixture(scope="module")
def fake():
    from tests.fake_ollama import FakeOllama, deciding_script

    made = FakeOllama()
    made.script(deciding_script("Take the first: its way is clear."))
    try:
        yield made
    finally:
        made.stop()


def test_a_model_mode_run_records_its_identity_and_consultations(fake, tmp_path):
    with quiet():
        runner = SimulationRunner(settings=fake.settings, tick_seconds=0,
                                  experiment_dir=tmp_path, stop_at=70)
        try:
            runner.reset(seed=11, preset="ms-drop")
            _run_to_end(runner, timeout=300)
            traces = runner.decision_traces(limit=2000, eligible_only=True)
        finally:
            runner.close()
    run = tmp_path / "MS-DROP" / "s11"
    definition = json.loads((run / "definition.json").read_text())
    verify = json.loads((run / "verify.json").read_text())
    assert definition["mode"] == "model" and verify["mode"] == "model"
    assert verify["identity"]["model"] == "qwen3:8b"
    assert verify["served_models"] and set(verify["served_models"]) == {"qwen3:8b"}
    consulted = [t for t in traces["traces"] if t["consultation"]]
    assert consulted, "the fake model was consulted at least once in 70 ticks"
    for t in consulted:
        assert t["consultation"]["llm_calls"]
        assert all(c["served_model"] == "qwen3:8b" for c in t["consultation"]["llm_calls"])


# ------------------------------------------------------------------ the API
def test_the_reads_serve_zones_traces_and_the_experiment(tmp_path):
    runner = SimulationRunner(rules_only=True, tick_seconds=0, experiment_dir=tmp_path,
                              stop_at=40)
    previous = server.use(runner)
    try:
        runner.reset(seed=11, preset="ms-drop")
        _run_to_end(runner)
        with TestClient(server.app) as client:
            zones = client.get("/zones?after=30").json()
            assert [r["tick"] for r in zones["rows"]] == list(range(31, 41))
            assert zones["fault_tick"] == 400 and zones["stop_at"] == 40
            body = client.get("/decision-traces?limit=5&eligible=false").json()
            assert len(body["traces"]) == 5 and body["summary"]["fault_tick"] == 400
            exp = client.get("/summary").json()["kept"]
            assert exp["enabled"] and exp["last"]["status"] == "complete"
            page = client.get("/").text
            assert 'id="dk-zones"' in page and 'id="trace-rows"' in page and 'id="c2n-exp"' in page
    finally:
        server.use(previous)
        runner.close()
