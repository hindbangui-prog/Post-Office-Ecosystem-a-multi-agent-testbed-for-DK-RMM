"""
Phase 7: the runner and the HTTP surface.

Carried from the source and trimmed to the routes spec 16 keeps (every test
deleted with its route is listed in docs/provenance_trimmed_tests.md). The
runners here are rules-only: what is under test is the HTTP layer and the loop,
and the model-mode surface is `test_api_trimmed.py`'s.
"""

from __future__ import annotations

import json
import re
import time

import pytest

from post_office.api.runner import SimulationRunner

fastapi = pytest.importorskip("fastapi", reason="the API is optional")
from fastapi.testclient import TestClient      # noqa: E402


@pytest.fixture
def client(tmp_path):
    from post_office.api import server

    runner = SimulationRunner(seed=2, run_id="test", tick_seconds=0.0, rules_only=True)
    previous = server.use(runner)
    runner.eco.start()
    runner.step(120)                          # a stepped run, not a timed one
    with TestClient(server.app) as test_client:
        yield test_client
    server.use(previous)
    runner.close()


# ------------------------------------------------------------------ runner
def test_the_runner_steps_without_a_thread():
    runner = SimulationRunner(seed=4, run_id="stepped", tick_seconds=0.0, rules_only=True)
    runner.eco.start()
    snapshot = runner.step(50)
    assert snapshot["tick"] == 50
    assert runner.is_running is False          # never started the loop
    runner.close()


def test_a_reset_returns_to_tick_zero_on_the_same_seed():
    runner = SimulationRunner(seed=4, run_id="r", tick_seconds=0.0, rules_only=True)
    runner.eco.start()
    runner.step(30)
    before = runner.eco.summary()["parcels_created"]
    runner.reset()
    assert runner.eco.world.tick == 0
    runner.eco.start()
    runner.step(30)
    assert runner.eco.summary()["parcels_created"] == before
    runner.close()


def test_a_restarted_loop_cannot_revive_the_one_it_replaced(tmp_path):
    """
    The old loop sleeps between ticks. If `start()` cleared the shared flag
    rather than replacing it, a loop asleep at that moment would wake to find
    itself un-stopped and carry on -- two threads ticking one ecosystem, and no
    way left to stop either of them.
    """
    runner = SimulationRunner(seed=4, run_id="loops", tick_seconds=5.0, rules_only=True)
    runner.start()
    retired = runner._stop                 # the first loop's own flag
    runner.reset()
    runner.start()
    assert retired.is_set(), "the old loop is still told to stop"
    assert runner._stop is not retired, "and the new one has its own flag"
    assert not runner._stop.is_set()
    runner.close()


# -------------------------------------------------------------- the reads
@pytest.mark.parametrize("path", [
    "/state", "/events", "/summary",
])
def test_every_read_endpoint_answers_with_json(client, path):
    response = client.get(path)
    assert response.status_code == 200
    json.dumps(response.json())            # nothing unserialisable slipped in


def test_the_state_endpoint_contains_everything_the_spec_lists(client):
    state = client.get("/state").json()
    for key in ("run", "policy", "hierarchy", "agents", "robots", "parcels",
                "tasks", "resources", "environment", "communications",
                "events", "counters"):
        assert key in state, key


# ------------------------------------------------------------- the writes
def test_stopping_over_http_stops_the_release_of_work(client):
    client.post("/simulation/stop")
    assert client.get("/state").json()["run"]["running"] is False


# ------------------------------------------------------- settings and traces
@pytest.mark.parametrize("path", [
    "/settings",
])
def test_every_tracking_endpoint_answers_with_json(client, path):
    response = client.get(path)
    assert response.status_code == 200
    json.dumps(response.json())


def test_the_address_people_actually_type_serves_the_ui(client):
    """
    Running the project and opening it means opening the root of the server,
    so the root is the live page itself (spec 16), not a redirect to it.
    """
    landing = client.get("/", follow_redirects=False)
    assert landing.status_code == 200
    assert "<!doctype html>" in landing.text.lower()


@pytest.mark.parametrize("path", [
    "/",
])
def test_every_page_of_the_live_ui_is_served(client, path):
    page = client.get(path)
    assert page.status_code == 200
    assert "<title>" in page.text or "<!doctype html>" in page.text.lower()
    # Built fresh each time, because a cache would need invalidating every tick.
    assert page.headers.get("cache-control") == "no-store"


def test_no_served_page_repeats_an_element_id(client):
    """
    Two elements with one id is a silent bug: `getElementById` returns the
    first, so the code reaching for the second gets the wrong thing and throws
    somewhere else entirely.

    The whole document is scanned, scripts and comments included. The floor
    page travels inside the shell as an escaped `srcdoc`, so its own ids are
    not the shell's and are checked on their own.
    """
    from post_office.api import server
    from post_office.ui import live

    pages = {"/": client.get("/").text, "floor": live.robots_html(server.runner)}
    for name, body in pages.items():
        ids = re.findall(r'\bid="([^"]+)"', body)
        repeated = {name for name in ids if ids.count(name) > 1}
        assert not repeated, f"{name} repeats: {sorted(repeated)}"


def test_the_server_can_tell_whether_its_socket_will_work(client):
    """
    Plain `pip install uvicorn` answers 404 to a WebSocket handshake rather
    than failing loudly, so the check exists to say so at startup instead of
    leaving somebody staring at a page that never fills in.
    """
    from post_office.api import server

    assert server.websocket_support() in ("websockets", "wsproto", "")


def test_the_live_shell_names_the_pages_it_mounts(client):
    body = client.get("/").text
    for path in ("/frame", "/consultations", "/llm/calls", "/dkrmm/state",
                 "/dkrmm/series", "/dkrmm/indicators", "/settings", "/ws"):
        assert path in body
    assert "/summary" in body, "the run line polls it"


def test_the_floor_follows_the_run_one_frame_at_a_time(client):
    """`/frame` is what makes the floor live; it has to be small and current."""
    from post_office.api import server

    first = client.get("/frame").json()
    # "v" is the departure board as of this tick, "g" the bag room, and "d"
    # which experts stopped to reason on it. The rest is the run the frame
    # belongs to and who is inside a model call.
    assert set(first) == {"t", "r", "p", "m", "c", "v", "g", "d",
                          "run_id", "roster", "llm_agents", "busy", "in_flight"}
    assert len(first["r"]) == 5, "one entry per robot"
    server.runner.step(4)
    later = client.get("/frame").json()
    assert later["t"] == first["t"] + 4


def test_the_built_file_and_the_served_page_share_their_builders(client):
    """
    Two copies of "what a frame is" would have drifted the first time either
    changed, so the runner and the views call the same function.
    """
    from post_office.ui import views

    from post_office.api import server

    served = client.get("/frame").json()
    built = views.frame_of(server.runner.eco)
    assert set(built) <= set(served)
    assert len(served["r"]) == len(built["r"])


def test_the_settings_say_whether_any_agent_is_actually_using_a_model(client):
    """
    A rules-only run uses no model, and the settings say so rather than
    leaving a reader to infer it from an empty page.
    """
    body = client.get("/settings").json()
    assert body["llm_agents"] == [], "a deterministic run uses no model"
    # And it says which agents could have one.
    from post_office.config.settings import LLM_CANDIDATES

    assert body["llm_candidates"] == list(LLM_CANDIDATES)
    assert body["llm_error"] == ""


# ------------------------------------------------------------- the socket
def test_the_stream_answers_at_both_of_its_names(client):
    # /ws streams the log live and GET /events returns the recorded one.
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "hello"
    assert client.get("/events").status_code == 200


def test_the_websocket_opens_with_the_whole_state_then_streams(client):
    from post_office.api import server

    with client.websocket_connect("/ws") as socket:
        hello = socket.receive_json()
        assert hello["type"] == "hello"
        assert "agents" in hello["state"]
        server.runner.step(2)
        payload = socket.receive_json()
        assert payload["type"] in ("event", "tick")


# ------------------------------------------------- launching without running
def test_a_new_runner_is_built_but_not_ticking():
    """
    What `serve()` relies on. A run that begins the moment the process does is
    a run whose first seconds nobody chose: by the time a browser has loaded,
    parcels have arrived and been sorted, and the operator is reading history
    rather than watching a simulation.
    """
    runner = SimulationRunner(seed=4, run_id="paused", tick_seconds=0.0, rules_only=True)
    assert runner.is_running is False
    assert runner.eco.world.tick == 0
    runner.close()


def test_the_app_can_start_and_stop_the_run_over_http(client):
    """The two endpoints the Start button drives, and the state it reads back."""
    client.post("/simulation/stop")
    assert client.get("/summary").json()["running"] is False
    client.post("/simulation/start")
    assert client.get("/summary").json()["running"] is True
    client.post("/simulation/stop")


def test_the_shell_offers_a_control_for_a_run_that_starts_paused(client):
    """
    The button has to exist on the page for the paused launch to be usable at
    all, and it has to talk to endpoints that are really there.
    """
    page = client.get("/").text
    assert 'id="go"' in page
    assert "/simulation/start" in page and "/simulation/stop" in page
    # And it rebuilds the floor when the run is rebuilt, or the floor would
    # keep scrubbing through the run that was thrown away.
    assert "restack" in page


# --------------------------------------------------------------------------
# A failed pane. The shell is built from fragments; an exception in one of
# them must say what happened in the pane, not take the page out.
# --------------------------------------------------------------------------

def test_the_monitor_tab_renders_normally(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "could not be built" not in page.text


def test_a_failed_monitor_tab_shows_why_rather_than_four_words(client, monkeypatch):
    from post_office.ui import live

    def explode(*a, **kw):
        raise RuntimeError("the monitor's window was not where it was left")

    monkeypatch.setattr(live, "dkrmm_html", explode)
    page = client.get("/")
    # The page still builds; the pane says what it lost.
    assert page.status_code == 200
    assert "could not be built" in page.text
    assert "RuntimeError" in page.text
    assert "the monitor&#x27;s window was not where it was left" in page.text \
        or "the monitor's window was not where it was left" in page.text
    assert "the rest of the run is unaffected" in page.text.lower()


def test_the_failed_pane_escapes_what_it_prints():
    """A traceback is data. It goes on the page as text, never as markup."""
    from post_office.ui import live

    page = live.pane_error_html("DK-RMM", "<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


# --------------------------------------------------------------------------
# Pacing. `tick_seconds` is wall-clock seconds per simulated tick; it decides
# how fast the run is watched, never what the run does.
# --------------------------------------------------------------------------

def _paced_runner(tick_seconds, tmp_path):
    runner = SimulationRunner(seed=5, run_id="pace", tick_seconds=tick_seconds,
                              rules_only=True)
    runner.eco.start()
    return runner


def test_every_tick_is_broadcast_once_and_in_order(tmp_path):
    """
    A listener that saw one message per ten ticks would be watching a
    different run from the one being recorded.
    """
    runner = _paced_runner(0.001953125, tmp_path)        # 512x
    seen = []
    runner.add_listener(lambda payload: seen.append(payload))
    try:
        runner.start()
        # Waited on tick payloads specifically: the same listener also receives
        # event broadcasts.
        def tick_rows():
            return [row["tick"] for row in list(seen)
                    if row.get("type") == "tick"]

        deadline = time.time() + 5.0
        while len(tick_rows()) < 60 and time.time() < deadline:
            time.sleep(0.02)
        runner.stop()
        ticks = tick_rows()
        assert len(ticks) >= 60, "the loop did not reach the paced rate"
        # One per tick, consecutive, none skipped and none repeated.
        assert ticks == list(range(ticks[0], ticks[0] + len(ticks)))
    finally:
        runner.close()


def test_stopping_during_a_batch_is_not_deferred_to_the_end_of_it(tmp_path):
    runner = _paced_runner(0.001953125, tmp_path)
    try:
        runner.start()
        time.sleep(0.25)
        runner.stop()
        settled = runner.eco.world.tick
        time.sleep(0.25)
        assert runner.eco.world.tick == settled, "ticked on after stop"
        assert not runner.is_running
    finally:
        runner.close()


def test_the_pace_does_not_change_the_run(tmp_path):
    """
    Pacing is how fast you watch, never what you watch. Same seed, two very
    different paces, one trajectory.
    """
    def digest(tick_seconds):
        runner = SimulationRunner(seed=9, run_id="same", tick_seconds=tick_seconds,
                                  rules_only=True)
        runner.eco.start()
        runner.step(400)                       # stepped by hand, not by the loop
        events = [(e.tick, e.category, e.topic, e.actor, e.target)
                  for e in runner.eco.logger.recent(100000)]
        summary = {k: v for k, v in runner.eco.summary().items()
                   if k not in ("run_id",)}
        runner.close()
        return events, summary

    slow_events, slow_summary = digest(0.25)
    fast_events, fast_summary = digest(0.001953125)
    assert slow_summary == fast_summary
    assert slow_events == fast_events


def test_the_api_takes_the_new_speeds_and_refuses_what_it_cannot_pace(client):
    for tick_seconds in (1.0, 0.25, 0.0625, 0.03125, 0.0078125, 0.001953125):
        answer = client.post("/simulation/speed",
                             json={"tick_seconds": tick_seconds})
        assert answer.status_code == 200, tick_seconds
        assert answer.json()["tick_seconds"] == tick_seconds
    # Below the fastest the control offers, and above a stall.
    assert client.post("/simulation/speed", json={"tick_seconds": 0.0}
                       ).status_code == 422
    assert client.post("/simulation/speed", json={"tick_seconds": 0.0001}
                       ).status_code == 422
    assert client.post("/simulation/speed", json={"tick_seconds": 11.0}
                       ).status_code == 422


def test_the_speed_control_offers_what_the_api_accepts():
    """Every option in the selector must be a speed the API will take."""
    from post_office.api.server import SpeedPatch
    from post_office.ui import live

    page = live.shell_html()
    offered = re.findall(r'<option value="([0-9.]+)">?[^<]*</option>', page)
    values = [float(v) for v in offered if float(v) <= 10.0]
    assert 0.0078125 in values and 0.001953125 in values
    for value in values:
        SpeedPatch(tick_seconds=value)         # raises if the API would refuse
