"""
The controls an operator actually needs over a running facility.

Start, stop and reset are there. What changes *which* run you are looking at
rather than where it has got to is how fast the clock turns, the scenario
(Prototype II has one), and a fresh seed when you want a different day rather
than the same one again.

Reset deliberately keeps the seed -- "put that back how it was" -- so a new
seed is a separate thing you ask for, not something reset does to you when you
were not expecting it.

Carried from the source and trimmed of the removed routes and presets (see
docs/provenance_trimmed_tests.md).
"""

from __future__ import annotations

import pytest

from post_office.simulation import build
from tests.presets import busy_config


@pytest.fixture
def eco():
    made = build(seed=4, run_id="controls")
    made.start()
    yield made
    made.close()


# ----------------------------------------------------------- the ecosystem
def test_a_reset_keeps_the_seed_unless_it_is_given_another(eco):
    for _ in range(40):
        eco.step()
    again = eco.reset()
    assert again.seed == 4
    assert again.world.tick == 0


def test_a_reset_can_be_handed_a_new_seed(eco):
    for _ in range(40):
        eco.step()
    fresh = eco.reset(seed=99)

    assert fresh.seed == 99
    assert fresh.world.tick == 0
    fresh.start()
    for _ in range(120):
        fresh.step()
    same = build(seed=4, run_id="control")
    same.start()
    for _ in range(120):
        same.step()
    assert fresh.summary() != same.summary(), "a new seed ran the same day again"
    same.close()


def test_a_reset_can_be_handed_a_different_scenario(eco):
    from post_office.config.settings import config

    busy = eco.reset(config=busy_config())
    busy.start()
    for _ in range(200):
        busy.step()

    ordinary = build(seed=4, run_id="ordinary", config=config("default"))
    ordinary.start()
    for _ in range(200):
        ordinary.step()

    assert (busy.summary()["parcels_created"]
            > ordinary.summary()["parcels_created"]), "the scenario did not take"
    ordinary.close()


# ------------------------------------------------------------------ the API
@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient

    from post_office.api import server
    from post_office.api.runner import SimulationRunner

    runner = SimulationRunner(seed=4, run_id="controls", tick_seconds=0.25, rules_only=True)
    previous = server.use(runner)
    runner.eco.start()
    with TestClient(server.app) as test_client:
        yield test_client
    server.use(previous)
    runner.close()


def test_the_clock_speed_can_be_set_and_read_back(client):
    before = client.get("/summary").json()
    assert before["tick_seconds"] > 0

    changed = client.post("/simulation/speed", json={"tick_seconds": 0.05})
    assert changed.status_code == 200
    assert client.get("/summary").json()["tick_seconds"] == 0.05


def test_a_speed_nobody_could_watch_is_refused(client):
    assert client.post("/simulation/speed", json={"tick_seconds": 0}).status_code == 422
    assert client.post("/simulation/speed",
                       json={"tick_seconds": 999}).status_code == 422


def test_a_new_run_gets_a_new_seed_and_starts_over(client):
    from post_office.api import server

    server.runner.step(30)
    before = client.get("/summary").json()

    fresh = client.post("/simulation/reset", params={"seed": 77}).json()
    assert fresh["ok"]

    after = client.get("/summary").json()
    assert after["seed"] == 77
    assert after["tick"] == 0
    assert before["seed"] != 77, "the test seed was 77 already; pick another"


def test_an_unknown_scenario_is_refused_rather_than_guessed(client):
    assert client.post("/simulation/reset",
                       params={"preset": "chaos"}).status_code == 400
