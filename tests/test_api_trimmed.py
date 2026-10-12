"""
The trimmed API (spec 16) over a runner whose seven experts are on the fake Ollama.

Every route spec 16 names answers, plus `GET /taxonomy` (the taxonomy design of
2026-10-02, section 5, and its amendment under section 11), plus the DK-RMM
and page routes of the trajectory and RCT log design of 2026-10-02, section 5
(their shapes are in `tests/test_api_rcts.py` and `tests/test_trajectory.py`);
every route the source served for its removed scenarios, settings panel, trace
and history is gone (404, no stub); `/settings` names the model; and the reads
answer while a tick is blocked in a consultation, because they come from the
published frame and the lock-free accessors, never from the step lock.
"""

from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from post_office.api import server
from post_office.api.runner import SimulationRunner
from post_office.config.settings import EXPERTS, LLM_CANDIDATES
from post_office.crew.console import quiet
from post_office.dkrmm import OperationalState
from post_office.dkrmm.indicators import INDICATOR_NAMES
from tests.fake_ollama import FakeOllama, deciding_script

STATES = {s.value for s in OperationalState}

#: Spec 16 of 2026-10-01 plus `GET /taxonomy` (taxonomy design, 2026-10-02) plus
#: the DK-RMM and page routes of the trajectory and RCT log design (2026-10-02,
#: section 5), as (method, path).
SPEC_ROUTES = {
    ("GET", "/"), ("GET", "/state"), ("GET", "/frame"), ("GET", "/summary"),
    ("GET", "/events"), ("GET", "/consultations"), ("GET", "/llm/calls"),
    ("GET", "/settings"), ("GET", "/taxonomy"),
    ("GET", "/dkrmm/state"), ("GET", "/dkrmm/series"),
    ("GET", "/dkrmm/indicators"), ("POST", "/simulation/start"),
    ("POST", "/simulation/stop"), ("POST", "/simulation/reset"),
    ("POST", "/simulation/speed"), ("WS", "/ws"),
    ("GET", "/dkrmm/rcts"), ("GET", "/dkrmm/explain"), ("GET", "/dkrmm/rct-log"),
    ("GET", "/dkrmm/rct-log/item"), ("POST", "/dkrmm/validate"),
    ("POST", "/dkrmm/activate"), ("POST", "/dkrmm/dismiss"),
    ("GET", "/ui/trajectory"), ("GET", "/ui/trajectory/tail"), ("GET", "/ui/rcts"),
}

READS = ["/state", "/frame", "/summary", "/events", "/events?after=0&limit=5",
         "/consultations?limit=5", "/llm/calls?limit=5", "/settings", "/dkrmm/state",
         "/dkrmm/series", "/dkrmm/series?limit=5", "/dkrmm/indicators"]

REMOVED = ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect",
           "/experiments", "/perturbation", "/perturbations", "/injections", "/stress",
           "/stress/experiments", "/stress/state", "/autodk/experiments", "/trace",
           "/trace/models", "/settings/ui", "/settings/providers", "/rcts",
           "/dkrmm/history", "/dkrmm", "/sessions",
           "/runs", "/actions", "/tools", "/discussions", "/ui", "/ui/robots", "/ui/dkrmm",
           "/ui/trace", "/ui/history", "/ui/frame", "/agents",
           "/robots", "/parcels", "/tasks", "/hierarchy", "/environment"]


@pytest.fixture(scope="module")
def fake():
    made = FakeOllama()
    made.script(deciding_script("Take the first: its way is clear."))
    try:
        yield made
    finally:
        made.stop()


@pytest.fixture(scope="module")
def client(fake):
    """A model-mode runner stepped past the first consultations and DK-RMM reading."""
    with quiet():
        runner = SimulationRunner(settings=fake.settings, tick_seconds=0)
        previous = server.use(runner)
        try:
            runner.eco.start()
            runner.step(25)
            with TestClient(server.app) as test_client:
                yield test_client
        finally:
            server.use(previous)
            runner.close()


# ---------------------------------------------------------------- the routes
def test_the_route_table_is_spec_16_and_nothing_else():
    from starlette.routing import WebSocketRoute

    served = set()
    assert (server.app.docs_url, server.app.redoc_url, server.app.openapi_url) == (
        None, None, None)
    for route in server.app.routes:
        if isinstance(route, WebSocketRoute):
            served.add(("WS", route.path))
            continue
        for method in route.methods - {"HEAD"}:
            served.add((method, route.path))
    assert served == SPEC_ROUTES


def test_the_page_is_served_at_the_root(client):
    page = client.get("/")
    assert page.status_code == 200
    assert page.text.lower().startswith("<!doctype html>")
    assert page.headers.get("cache-control") == "no-store"


@pytest.mark.parametrize("path", READS)
def test_every_read_route_answers_with_json(client, path):
    response = client.get(path)
    assert response.status_code == 200, response.text
    json.dumps(response.json())


@pytest.mark.parametrize("path", REMOVED)
def test_a_removed_route_is_gone(client, path):
    assert client.get(path).status_code == 404, path


@pytest.mark.parametrize("path", ["/settings", "/settings/agents", "/settings/probe",
                                  "/settings/reset", "/simulation/step",
                                  "/simulation/policy", "/tasks", "/robots/R1/command",
                                  "/sessions"])
def test_no_removed_write_is_accepted(client, path):
    # 405 where a GET of the same path is served (`/settings`), 404 otherwise.
    assert client.post(path, json={}).status_code in (404, 405), path


# ------------------------------------------------------------- the readings
def test_the_settings_name_the_model_and_the_experts_on_it(client):
    body = client.get("/settings").json()
    assert set(body) == {"ollama", "identity", "llm_agents", "llm_candidates",
                         "llm_error", "llm_stats"}
    assert body["ollama"]["model"] == "qwen3:8b"
    assert body["identity"]["model"] == "qwen3:8b" and body["identity"]["ok"] is True
    assert body["llm_agents"] == sorted(EXPERTS)
    assert body["llm_candidates"] == list(LLM_CANDIDATES)
    assert body["llm_error"] == ""
    assert set(body["llm_stats"]["agents"]) == set(EXPERTS)
    assert body["llm_stats"]["calls"] > 0


def test_consultations_and_model_calls_are_served_newest_last(client):
    rows = client.get("/consultations", params={"limit": 50}).json()["consultations"]
    assert rows and rows[0]["tick"] == 17
    for key in ("id", "tick", "owner", "peer", "kind", "condition", "request", "response",
                "decision", "outcome", "latency_ms", "model"):
        assert key in rows[0], key
    assert len(client.get("/consultations", params={"limit": 1}).json()["consultations"]) == 1
    calls = client.get("/llm/calls", params={"limit": 50}).json()["calls"]
    assert calls and {c["served_model"] for c in calls} == {"qwen3:8b"}
    for key in ("agent_id", "phase", "served_model", "latency_ms", "prompt_tokens",
                "completion_tokens", "consultation_id", "tick"):
        assert key in calls[0], key


def test_events_are_read_after_a_sequence_number(client):
    first = client.get("/events", params={"limit": 10}).json()
    assert len(first["events"]) == 10 and first["total"] > 10
    after = first["events"][4]["seq"]
    rest = client.get("/events", params={"after": after, "limit": 3}).json()["events"]
    assert [e["seq"] for e in rest] == [after + 1, after + 2, after + 3]


def test_the_frame_is_the_floor_plus_who_is_inside_a_model_call(client):
    frame = client.get("/frame").json()
    assert {"t", "r", "p", "m", "c", "v", "g", "d"} <= set(frame)
    assert frame["t"] == 25 and len(frame["r"]) == 5
    assert frame["busy"] == [] and frame["in_flight"] == []
    assert {row["agent_id"] for row in frame["roster"]} >= set(EXPERTS)


def test_the_monitor_is_served_three_ways(client):
    state = client.get("/dkrmm/state").json()
    assert state["current"]["state"] in STATES and state["assessments"] >= 1
    series = client.get("/dkrmm/series", params={"limit": 5}).json()
    assert len(series["ticks"]) == len(series["states"]) >= 1
    body = client.get("/dkrmm/indicators").json()
    assert body["attached"] is True and body["state"] in STATES
    assert [row["name"] for row in body["indicators"]] == list(INDICATOR_NAMES)
    for row in body["indicators"]:
        # A value is a number when the indicator could be read this window
        # and None when it could not (shown as "n/a"), never a stand-in 0.
        assert row["about"]
        if row["evaluable"]:
            assert isinstance(row["value"], (int, float))
        else:
            assert row["value"] is None and row["status"] == "n/a"


def test_the_summary_carries_the_digest_and_the_run(client):
    body = client.get("/summary").json()
    assert body["tick"] == 25 and body["preset"] == "default"
    assert body["dkrmm"]["attached"] is True
    assert body["llm_agents"] == sorted(EXPERTS)
    assert body["scenario_label"] == "NORMAL · CrewAI · Ollama/qwen3:8b · DK-RMM"


def test_the_scenario_label_names_the_configured_model(monkeypatch):
    import types

    from post_office.config.settings import scenario_label, scenarios
    from post_office.ui import live

    baseline = "NORMAL · CrewAI · Ollama/qwen3:8b · DK-RMM"
    assert scenario_label("qwen3:8b") == baseline
    assert scenario_label("gemma4:26b") == "NORMAL · CrewAI · Ollama/gemma4:26b · DK-RMM"
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:26b")
    # Normal first, as it always was; the C2-NEAR conditions follow it.
    assert scenarios()[0] == ("default", "NORMAL · CrewAI · Ollama/gemma4:26b · DK-RMM")
    assert [preset for preset, _ in scenarios()] == ["default", "c2near-n", "c2near-c0", "c2near-c2",
                                                     "ms-drop", "ms-delay", "cs-starve",
                                                     "cs-partition"]
    assert all("Ollama/gemma4:26b" in label for _, label in scenarios()[:4])
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    assert scenario_label() == baseline
    on_gemma = types.SimpleNamespace(settings=types.SimpleNamespace(model="gemma4:26b"))
    assert live.scenario_options(on_gemma).startswith(
        '<option value="default">NORMAL · CrewAI · Ollama/gemma4:26b · DK-RMM</option>')
    assert live.scenario_options(on_gemma).count("<option") == 8


def test_the_socket_says_hello_with_the_published_state(client):
    with client.websocket_connect("/ws") as socket:
        hello = socket.receive_json()
        assert hello["type"] == "hello"
        assert hello["state"]["run"]["tick"] == 25


# --------------------------------------------------------------- the writes
@pytest.fixture
def fresh(fake_ollama):
    fake_ollama.script(deciding_script("Take the first: its way is clear."))
    runner = SimulationRunner(settings=fake_ollama.settings, tick_seconds=0.25)
    previous = server.use(runner)
    try:
        with TestClient(server.app) as test_client:
            yield test_client, runner
    finally:
        server.use(previous)
        runner.close()


def test_the_controls_start_stop_pace_and_reset(fresh, quiet_crewai_console):
    client, runner = fresh
    assert client.post("/simulation/speed", json={"tick_seconds": 1.0}).json()["ok"]
    assert runner.tick_seconds == 1.0
    assert client.post("/simulation/start").json()["ok"]
    assert client.get("/summary").json()["running"] is True
    assert client.post("/simulation/stop").json()["ok"]
    deadline = time.monotonic() + 30
    while client.get("/summary").json()["running"]:
        assert time.monotonic() < deadline, "the run did not stop"
        time.sleep(0.05)
    before = runner.eco.run_id
    body = client.post("/simulation/reset", params={"seed": 7, "preset": "default"}).json()
    assert body["ok"] and body["snapshot"]["tick"] == 0
    summary = client.get("/summary").json()
    assert summary["seed"] == 7 and summary["run_id"] != before
    assert client.get("/settings").json()["llm_agents"] == sorted(EXPERTS)


@pytest.mark.parametrize("preset", ["busy", "stress", "normal_llm", "exp:anything"])
def test_only_the_default_scenario_can_be_chosen(fresh, preset):
    client, _ = fresh
    response = client.post("/simulation/reset", params={"preset": preset})
    assert response.status_code == 400
    assert "default" in response.json()["detail"]


# ------------------------------------------------- reads during a consultation
def test_reads_do_not_block_on_consultation(fake_ollama, quiet_crewai_console):
    """
    With every model call taking two seconds, the tick that consults holds the
    step lock for seconds; `/frame` and `/dkrmm/state` (and every other read)
    still answer at once, and `/frame` names the expert inside the call.
    """
    fake_ollama.script(deciding_script("Take the first: its way is clear."))
    fake_ollama.delay(2)
    runner = SimulationRunner(settings=fake_ollama.settings, tick_seconds=0)
    previous = server.use(runner)
    try:
        with TestClient(server.app) as client:
            runner.start()
            deadline = time.monotonic() + 30
            while not fake_ollama.requests:
                assert time.monotonic() < deadline, "no consultation began"
                time.sleep(0.01)
            got = threading.Event()

            def probe():  # the step lock is an RLock: only another thread can tell it is held
                if runner._lock.acquire(timeout=0):
                    runner._lock.release()
                else:
                    got.set()

            def lock_is_held():
                got.clear()
                prober = threading.Thread(target=probe)
                prober.start()
                prober.join()
                return got.is_set()

            assert lock_is_held(), "the tick is not inside the consultation"
            seen = len(fake_ollama.requests)
            for path in ("/", "/frame", "/dkrmm/state", "/summary", "/state", "/events",
                         "/consultations", "/llm/calls", "/settings", "/dkrmm/series",
                         "/dkrmm/indicators"):
                started = time.perf_counter()
                response = client.get(path)
                took = time.perf_counter() - started
                assert response.status_code == 200, path
                assert took < 0.5, f"{path} took {took:.2f} s during a consultation"
            frame = client.get("/frame").json()
            assert frame["busy"] and frame["busy"][0] in EXPERTS
            assert frame["in_flight"][0]["tick"] == 17
            # Still inside the same model call: the reads happened during it.
            assert lock_is_held() and len(fake_ollama.requests) == seen
            fake_ollama.delay(0)
    finally:
        fake_ollama.delay(0)
        server.use(previous)
        runner.close()


# ------------------------------------------------------------ main.py --api
def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_main_api_refuses_to_serve_without_the_model(fake_ollama):
    from tests.test_run_normal_tool import _run

    fake_ollama.serve_models(["qwen3:4b"])
    done = _run(fake_ollama, "main.py", "--api", "--no-record", "--port", _free_port(),
                timeout=120)
    assert done.returncode == 2
    assert "qwen3:4b" in done.stderr
    assert fake_ollama.requests == []


def test_main_api_serves_the_page_on_the_model(fake_ollama):
    import subprocess
    import sys
    import urllib.request

    from tests.test_run_normal_tool import ROOT, _env

    port = _free_port()
    proc = subprocess.Popen([sys.executable, "main.py", "--api", "--no-record",
                             "--port", str(port)],
                            cwd=ROOT, env=_env(fake_ollama), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    try:
        deadline = time.monotonic() + 90
        while True:
            assert proc.poll() is None, proc.stdout.read()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/settings",
                                            timeout=2) as response:
                    body = json.loads(response.read())
                break
            except OSError:
                assert time.monotonic() < deadline, "the server did not come up"
                time.sleep(0.2)
        assert body["ollama"]["model"] == "qwen3:8b" and body["identity"]["ok"] is True
        assert body["llm_agents"] == sorted(EXPERTS)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as response:
            assert response.status == 200
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
