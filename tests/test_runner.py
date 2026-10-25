"""
The API's runner: one ecosystem, a ticking thread, DK-RMM beside it (spec 16).

Every runner here talks to the fake Ollama. `tick_seconds=0` lets the thread
tick as fast as it can; a test waits on `last_frame` (the frame the loop
publishes after each tick) rather than on wall-clock time.
"""

import threading
import time

import pytest

from post_office.api.runner import SimulationRunner
from post_office.config.settings import EXPERTS
from post_office.dkrmm import OperationalState
from tests.fake_ollama import deciding_script

pytestmark = pytest.mark.usefixtures("quiet_crewai_console")

STATES = {s.value for s in OperationalState}


def _run_until(runner, tick, timeout=120.0, consulted=False):
    """Run the clock to `tick`; with `consulted`, also until a consultation has finished.

    The live clock does not wait for the model (`api/runner.py::_live_decisions`),
    so it can pass tick 50 while the first consultation is still with the
    (fake) model.
    """
    runner.start()
    end = time.monotonic() + timeout
    while runner.last_frame["tick"] < tick or (consulted and not runner.consultations(1)):
        assert time.monotonic() < end, f"runner stuck at tick {runner.last_frame['tick']}"
        time.sleep(0.01)
    runner.stop("test")
    deadline = time.monotonic() + timeout
    while runner.is_running:
        assert time.monotonic() < deadline, "the loop did not stop"
        time.sleep(0.01)


@pytest.fixture
def runner(fake_ollama):
    fake_ollama.script(deciding_script("Take the first: its way is clear."))
    made = SimulationRunner(settings=fake_ollama.settings, tick_seconds=0)
    try:
        yield made
    finally:
        made.close()


def test_runner_steps_fifty_ticks_with_the_seven_experts_on_the_model(runner):
    assert runner.llm_error == ""
    assert runner.llm_agents == sorted(EXPERTS)
    assert runner.last_frame["tick"] == 0

    # A paced clock (10 ms a tick): the clock does not wait for the model, and
    # unpaced it would run past every answer's deadline before the fake replies.
    runner.tick_seconds = 0.01
    _run_until(runner, 50, consulted=True)

    frame = runner.last_frame
    assert frame["tick"] >= 50
    assert frame["run_id"] == runner.eco.run_id
    assert {row["agent_id"] for row in frame["roster"]} >= set(EXPERTS)
    on_model = {row["agent_id"] for row in frame["roster"] if row["brain"] == "crewai"}
    assert on_model == set(EXPERTS)
    assert frame["dkrmm"]["current"]["state"] in STATES
    assert isinstance(frame["consultations"], list)

    stats = runner.llm_stats()
    assert stats["identity"]["model"] == "qwen3:8b"
    assert stats["identity"]["ok"] is True
    assert set(stats["agents"]) == set(EXPERTS)
    for key in ("calls", "fallbacks", "retries", "parse_failures", "timeouts"):
        assert stats[key] == sum(row[key] for row in stats["agents"].values())

    state = runner.monitor.state()
    assert state["assessments"] >= 2
    assert state["current"]["state"] in STATES

    consultations = runner.consultations(1000)
    assert consultations, "fifty ticks of NORMAL should consult at least once"
    assert any(row["outcome"] == "decided" for row in consultations)
    calls = runner.llm_calls(1000)
    assert calls and {c["served_model"] for c in calls} == {"qwen3:8b"}
    assert runner.snapshot()["tick"] == frame["tick"]


def test_reads_never_wait_for_the_step_lock(runner):
    """The API's reads come from the published frame and the service's own lock."""
    runner.step(3)
    held, release = threading.Event(), threading.Event()

    def hold():
        with runner._lock:
            held.set()
            release.wait(10)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert held.wait(5)
    got = {}

    def read():
        got["frame"] = runner.last_frame
        got["snapshot"] = runner.snapshot()
        got["consultations"] = runner.consultations(10)
        got["calls"] = runner.llm_calls(10)
        got["stats"] = runner.llm_stats()
        got["monitor"] = runner.monitor.state()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(5)
    finished = not reader.is_alive()
    release.set()
    holder.join(5)
    assert finished, "a read blocked on the step lock"
    assert got["frame"]["tick"] == 3 and got["snapshot"]["tick"] == 3


def test_reset_rebuilds_the_run_with_fresh_brains(runner):
    runner.step(5)
    before = {i: runner.eco.agents[i].brain for i in EXPERTS}
    old_eco = runner.eco

    runner.reset()

    assert runner.eco is not old_eco
    assert runner.last_frame["tick"] == 0 and runner.eco.world.tick == 0
    assert runner.llm_agents == sorted(EXPERTS)
    for agent_id in EXPERTS:
        brain = runner.eco.agents[agent_id].brain
        assert brain is not before[agent_id]
        assert brain.stats()["calls"] == 0
    assert runner.consultations(10) == [] and runner.llm_calls(10) == []
    assert runner.eco.run_id != old_eco.run_id
    runner.step(2)
    assert runner.last_frame["tick"] == 2


def test_rules_only_runner_builds_no_model(fake_ollama):
    made = SimulationRunner(rules_only=True, settings=fake_ollama.settings, tick_seconds=0)
    try:
        made.step(20)
        assert made.llm_agents == [] and made.llm_error == ""
        assert made.eco.crew is None
        assert made.consultations(10) == [] and made.llm_calls(10) == []
        assert made.llm_stats()["identity"] is None
    finally:
        made.close()
    assert fake_ollama.calls == []


def test_a_missing_model_leaves_a_rules_only_run_and_says_why(fake_ollama):
    fake_ollama.serve_models(["qwen3:4b"])
    made = SimulationRunner(settings=fake_ollama.settings, tick_seconds=0)
    try:
        assert made.llm_agents == []
        assert "ModelUnavailable" in made.llm_error and "qwen3:4b" in made.llm_error
        assert made.llm_stats()["identity"]["ok"] is False
        made.step(5)
        assert made.last_frame["tick"] == 5
    finally:
        made.close()
    assert fake_ollama.requests == []


def test_listeners_hear_ticks_and_resets(runner):
    heard = []
    remove = runner.add_listener(heard.append)
    runner.step(2)
    runner.reset()
    remove()
    runner.step(1)
    kinds = [m["type"] for m in heard]
    assert kinds.count("tick") == 2 and kinds[-1] == "reset"
    assert "event" in kinds
