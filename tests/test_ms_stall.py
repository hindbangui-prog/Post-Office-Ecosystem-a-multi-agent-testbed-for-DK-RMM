"""
M-S-STALL (`stress/collapse_scenarios.py`), the fifth collapse scenario: from
tick 1800 the bus delivers nothing (every message held, none dropped) and at
tick 2100 everything held is delivered in that one tick; from then on
delivery is as usual.

Covered: the registry and the scenario (start 1800, release 2100, built from
`normal_config()`, words the Normal page must not show, no em dash); the
rule `HoldUntil` on its own; the existing four scenarios' fingerprints and
start are what they were; one rules-only run on seed 13 to tick 2160 with
DK-RMM attached unchanged, driven as the driver drives it: exact Normal
before 1800, no inbox receives anything from 1801 to 2099, every held
message arrives at 2100 and none is dropped, the rule is still installed and
holds nothing after the release; and what DK-RMM's dragon-king test said on
that run (rules only, the run is deterministic): it holds from the release
reading at 2101 and the first RCT reading with it is 2121.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Tuple

import pytest

from post_office.config.settings import (COLLAPSE_LABELS, config, normal_config,
                                         scenario_meta, scenarios)
from post_office.dkrmm import DKRMM
from post_office.simulation import build
from post_office.stress import collapse_scenarios as spec
from post_office.stress.collapse_scenarios import CollapseFaults, HoldUntil, ScenarioCollector

ROOT = pathlib.Path(__file__).resolve().parents[1]
FORBIDDEN = ("attack", "perturb", "stress", "inject", "experiment", "autodk", "openrt")
SEED = 13
TICKS = 2160
RUN_ID = "ms-stall-test"
STRIPPED = ("run_id", "wall_clock")
#: The four scenarios' fingerprints before M-S-STALL was added.
FINGERPRINTS = {
    "N": "00f4090b749755f261cc001b7f0feeda66890e96d3e90f7b443f381943139405",
    "ms-drop": "7df72940cb2f7732e4a59a55b9827748d55dc339f20958c1ab888564a8fa3808",
    "ms-delay": "451217faa98c77227670262af625529d1b3e031a94d4c1f26a1a5922058404dd",
    "cs-starve": "1068600d3692416f8d340797a93c2e9f26e833869bc73bc23087f395baeecaff",
    "cs-partition": "3a9b1a1d9c892fc94d39b7ccd1cf05221b46c44ec28a5af6b5fefe71a2166103",
}


def _frozen(event: Any) -> Dict[str, Any]:
    row = json.loads(json.dumps(event.as_dict(), default=str))
    for key in STRIPPED:
        row.pop(key, None)
    return row


def _never_release(*_args, **_kwargs):
    raise AssertionError("bus.release_held was called")


# ------------------------------------------------------------- the registry
def test_ms_stall_is_registered_with_its_own_start_and_release():
    scn = spec.scenario("ms-stall")
    assert scn is spec.scenario("MS-STALL") and scn.preset == "ms-stall"
    assert (spec.STALL_START, spec.STALL_TICKS, spec.RELEASE) == (1800, 300, 2100)
    assert scn.start == 1800 and scn.holds_until == "tick 2100, when everything held is delivered"
    assert scn.mechanism_name == spec.MESSAGE_STALL == "message_stall"
    assert spec.schedule(scn) == [{
        "tick": 1800, "mechanism": "message_stall", "fault_id": "MS-STALL",
        "detail": {"holds_until": scn.holds_until, "rule": "every message held, none dropped",
                   "release_at": 2100, "stall_ticks": 300}}]
    definition = spec.definition(scn)
    assert definition["start"] == 1800 and definition["run_ticks"] == 2800
    assert spec.config(scn) == config("ms-stall") == normal_config()
    label = COLLAPSE_LABELS["ms-stall"]
    assert label == "M-S-STALL · every message held from 1800 and all delivered at 2100"
    assert dict(scenarios("qwen3:8b"))["ms-stall"] == label == scn.label
    meta = scenario_meta("ms-stall")
    assert meta["purpose"] == scn.mechanism and meta["about"] == scn.expected
    for text in (label, scn.mechanism, scn.expected, scn.holds_until, *meta.values()):
        assert not [w for w in FORBIDDEN if w in text.lower()], text
        assert "—" not in text


def test_the_four_scenarios_and_the_control_are_what_they_were():
    for name, fingerprint in FINGERPRINTS.items():
        assert spec.fingerprint(spec.scenario(name)) == fingerprint, name
    for name in ("ms-drop", "ms-delay", "cs-starve", "cs-partition"):
        scn = spec.scenario(name)
        assert scn.start == spec.START == 400 and scn.holds_until == "end of run"
        assert spec.definition(scn)["start"] == 400
    assert spec.definition(spec.scenario("N"))["start"] == 400


# ----------------------------------------------------------------- the rule
def test_hold_until_holds_everything_until_its_release_and_nothing_after():
    class Bus:
        tick = 0

    bus = Bus()
    rule = HoldUntil(bus, 2100)
    for tick, expected in ((1800, 300), (1801, 299), (2099, 1), (2100, None), (2101, None),
                           (2800, None)):
        bus.tick = tick
        assert rule(object()) == expected, tick
    assert (rule.held, rule.passed) == (3, 3)
    # No method that lets go early, removes or restores (`release_at` is the data).
    methods = [name for name in dir(rule)
               if not name.startswith("_") and callable(getattr(rule, name))]
    assert methods == []


# ------------------------------------------------------------------ the run
class StallRun:
    """One rules-only run on seed 13, driven as the driver drives it, with DK-RMM attached."""

    def __init__(self, name: str, ticks: int) -> None:
        self.scenario = spec.scenario(name)
        self.eco = build(seed=SEED, config=spec.config(self.scenario), run_id=RUN_ID)
        self.eco.bus.release_held = _never_release
        self.events: List[Dict[str, Any]] = []
        self.eco.logger.subscribe(lambda e: self.events.append(_frozen(e)))
        self.takes: List[Tuple[int, str, int]] = []
        self.eco.bus.watch_inbox(lambda agent, tick, messages:
                                 self.takes.append((int(tick), agent, len(messages))))
        self.monitor = DKRMM(self.eco).attach()
        self.faults = CollapseFaults(self.eco, self.scenario)
        self.collector = ScenarioCollector(self.eco, self.scenario, self.faults,
                                           monitor=self.monitor, mode="rules", ticks=ticks)
        self.eco.start()
        for tick in range(1, int(ticks) + 1):
            self.faults.before_tick(tick)
            self.eco.step()
            self.monitor.tick()
            self.collector.after_step()

    def topic(self, topic: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e["topic"] == topic]

    def close(self) -> None:
        self.collector.close()
        self.monitor.close()
        self.eco.close()


@pytest.fixture(scope="module")
def stall_run():
    run = StallRun("ms-stall", TICKS)
    yield run
    run.close()


def test_exact_normal_before_1800_and_the_fault_fires_once_at_1800(stall_run):
    normal = StallRun("N", spec.STALL_START - 1)
    try:
        before = [e for e in stall_run.events if e["tick"] < spec.STALL_START]
        assert before == normal.events
    finally:
        normal.close()
    fired = stall_run.topic("stress_fault_activated")
    assert len(fired) == 1 and fired[0]["tick"] == 1800
    assert fired[0]["detail"]["mechanism"] == "message_stall"
    assert fired[0]["detail"]["release_at"] == 2100
    assert stall_run.faults.faults_applied()[0]["tick"] == 1800


def test_nothing_is_received_during_the_stall_and_everything_held_arrives_at_2100(stall_run):
    rule = stall_run.faults.rule
    assert isinstance(rule, HoldUntil) and stall_run.eco.bus.delay_rule is rule
    # No inbox receives a message from 1801 to 2099.
    quiet = [t for t in stall_run.takes if spec.STALL_START < t[0] < spec.RELEASE and t[2]]
    assert quiet == []
    assert any(t[0] == spec.RELEASE and t[2] for t in stall_run.takes)
    # Nothing is dropped; every held message arrives at 2100, late.
    assert [e for e in stall_run.topic("message_dropped") if e["tick"] >= 1800] == []
    late = [e for e in stall_run.topic("agent_message_received") if e["tick"] >= 1800]
    assert late and {e["tick"] for e in late} == {2100}
    assert len(late) == rule.held > 0
    sent = {e["detail"]["message_id"] for e in stall_run.events
            if e["topic"] in ("message", "subagent_message") and 1799 <= e["tick"] <= 2098}
    assert {e["detail"]["message_id"] for e in late} == sent
    # After the release: the rule still installed, holding nothing, the bus empty of holds.
    assert rule.passed > 0 and stall_run.eco.bus._held == []
    status = stall_run.faults.status()
    assert status["held"] == rule.held and status["release_at"] == 2100
    assert status["rule_installed"] is True and status["held_now"] == 0


def test_dkrmm_reads_the_release_as_a_dragon_king_on_seed_13_rules_only(stall_run):
    history = stall_run.monitor.history
    by_tick = {a.tick: a for a in history}
    # Before the stall, as in Normal on this seed: the test never held.
    assert not any(a.dragon.is_dragon for a in history if a.tick < 1800)
    release = by_tick[2101]
    assert release.dragon.is_dragon and release.dragon.ratio >= 2.0
    assert release.dragon.fit_quality > 0.5
    assert release.severity == max(a.severity for a in history if a.tick >= 1001)
    first_rct = min(a.tick for a in history if a.dragon.is_dragon
                    and a.state.value == "RCT")
    assert first_rct == 2121


# ------------------------------------------------------------ the live page
def test_the_live_runner_carries_ms_stall_from_1800_and_the_page_draws_it():
    from post_office.api.runner import SimulationRunner
    from post_office.ui import live

    runner = SimulationRunner(rules_only=True, tick_seconds=0, preset="ms-stall", seed=SEED)
    try:
        status = runner.study_status()
        assert status["family"] == "collapse" and status["scenario"] == "MS-STALL"
        assert status["pressure_from"] == 1800 and status["holds_until"].startswith("tick 2100")
        assert status["schedule"] == [{"tick": 1800, "mechanism": "message_stall",
                                       "fault_id": "MS-STALL",
                                       "label": "every message held from 1800 and all "
                                                "delivered at 2100",
                                       "applied_at": None}]
        assert status["counters"]["held"] == 0 and status["counters"]["release_at"] is None
        assert status["dkrmm"]["view"] == "four"
        runner.eco.start()
        runner.step(1801)
        status = runner.study_status()
        assert status["schedule"][0]["applied_at"] == 1800
        assert status["counters"]["release_at"] == 2100
        assert runner.eco.bus.delay_rule is runner.faults.rule
        # The decision traces read the scenario's own start, not 400.
        summary = runner.decision_traces()["summary"]
        assert summary["fault_tick"] == 1800
    finally:
        runner.close()
    # Still a preset with its label, no longer offered by the page's selector (2026-10-23).
    assert dict(scenarios(None))["ms-stall"] == "M-S-STALL · every message held from 1800 and all delivered at 2100"
    assert 'value="ms-stall"' not in live.scenario_options(None)
    page = (ROOT / "post_office" / "ui" / "live.html").read_text(encoding="utf-8")
    assert 'const stall = c.scenario === "MS-STALL";' in page
    assert "messages held ${n(k.held)}" in page and "k.release_at" in page
    low = page.lower()
    assert not [w for w in FORBIDDEN if w in low]
