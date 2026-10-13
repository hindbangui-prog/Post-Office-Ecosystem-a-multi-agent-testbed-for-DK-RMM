"""
The four collapse scenarios (`stress/collapse_scenarios.py`), as tests.

Rules-only ecosystems on seed 11, driven as `tools/run_collapse_scenarios.py`
drives them (`before_tick`, `step`, `after_step`): one run per scenario to
tick 700, plus the control `N`, built once for the module. Each scenario's
mechanism is asserted directly (what is dropped, what is late, what is
refused); nothing here asserts a collapse, which is the driver's job on the
full 2800-tick runs.

Covered: no fault before tick 400 in any scenario; M-S-DROP drops every
message from 400 and the rule is still installed at 700; M-S-DELAY delivers a
routing message at t + 11 and a non-routing one at t + 1, releases nothing
early and never calls `release_held`; C-S-STARVE leaves no charge point from
400 and refuses every rescue, nothing is ever recovered and the crew object
has no method that restores; C-S-PARTITION drops the SCHEDULING <-> RESOURCE
traffic and delivers everything else; `CollapseFaults` has exactly its three
public methods and no removal path; the registry (`settings`) lists the four
presets after the C2-NEAR ones with Normal first and unchanged, free of the
words the Normal page must not show; the runner carries a collapse preset
on a rules-only runner, reports `study_status()`, carries `study` on
`/summary`, and gives `study: None` and a fresh bus with no rule on a switch
back to `default`; the driver refuses `results/normal` and classifies only
comparable pairs.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
from typing import Any, Dict, List, Optional

import pytest

from post_office.communication.message import MessageType
from post_office.config.settings import (C2NEAR_PRESETS, COLLAPSE_PRESETS, DEFAULT_CONFIG,
                                         PRESETS, config, known_presets, normal_config,
                                         scenario_label, scenario_meta, scenario_name,
                                         scenarios)
from post_office.robots.robot import RobotState
from post_office.simulation import build
from post_office.simulation.recovery import RecoveryService
from post_office.stress import collapse
from post_office.stress import collapse_scenarios as spec
from post_office.stress.collapse_scenarios import (CollapseFaults, NoRescue, ScenarioCollector,
                                                   is_routing_related, partition_direction)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEED = 11
TICKS = 700
RUN_ID = "collapse-test"
STRIPPED = ("run_id", "wall_clock")
#: As `tests/test_live_ui.py::FORBIDDEN`: words the Normal page must not show.
FORBIDDEN = ("attack", "perturb", "stress", "inject", "experiment", "autodk", "openrt")
NORMAL_LABEL = "NORMAL · CrewAI · Ollama/qwen3:8b · DK-RMM"


# ------------------------------------------------------------------ helpers
def _frozen(event: Any) -> Dict[str, Any]:
    row = json.loads(json.dumps(event.as_dict(), default=str))
    for key in STRIPPED:
        row.pop(key, None)
    return row


def _never_release(*_args, **_kwargs):
    raise AssertionError("bus.release_held was called: a held message was let go early")


class Run:
    """One rules-only run, driven as the driver drives it, keeping every (stripped) event."""

    def __init__(self, name: str, ticks: int, seed: int = SEED) -> None:
        self.scenario = spec.scenario(name)
        self.eco = build(seed=seed, config=spec.config(self.scenario), run_id=RUN_ID)
        # Nothing in this module may let a held message go early.
        self.eco.bus.release_held = _never_release
        self.events: List[Dict[str, Any]] = []
        self.eco.logger.subscribe(lambda e: self.events.append(_frozen(e)))
        self.faults = CollapseFaults(self.eco, self.scenario)
        self.collector = ScenarioCollector(self.eco, self.scenario, self.faults, mode="rules",
                                           ticks=ticks)
        self.stations: Dict[int, List[str]] = {}
        self.held: Dict[int, int] = {}
        self.eco.start()
        self.run_to(ticks)

    def run_to(self, ticks: int) -> None:
        for tick in range(self.eco.world.tick + 1, int(ticks) + 1):
            self.faults.before_tick(tick)
            self.eco.step()
            self.collector.after_step()
            self.stations[tick] = sorted(self.eco.env.stations)
            self.held[tick] = len(self.eco.bus._held)

    @property
    def rows(self) -> List[Dict[str, Any]]:
        return self.collector.rows

    def topic(self, topic: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e["topic"] == topic]

    def sent(self) -> List[Dict[str, Any]]:
        """Every message accepted by the bus (`message` and `subagent_message` events)."""
        return [e for e in self.events if e["topic"] in ("message", "subagent_message")]

    def close(self) -> None:
        self.collector.close()
        self.eco.close()


def _before(events_: List[Dict[str, Any]], tick: int) -> List[Dict[str, Any]]:
    return [e for e in events_ if e["tick"] < tick]


def _load_driver():
    path = ROOT / "tools" / "run_collapse_scenarios.py"
    module_spec = importlib.util.spec_from_file_location("run_collapse_scenarios", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _clean(text: str) -> None:
    low = text.lower()
    found = [word for word in FORBIDDEN if word in low]
    assert not found, f"{text!r} says {found}"


def _at_400(name: str):
    """A fresh facility at tick 400 with the scenario's fault just fired (no step yet)."""
    scn = spec.scenario(name)
    eco = build(seed=SEED, config=spec.config(scn), run_id=RUN_ID)
    eco.bus.release_held = _never_release
    eco.start()
    eco.world.advance(400)
    eco.bus.advance(400)
    faults = CollapseFaults(eco, scn)
    assert faults.before_tick(400) == [scn.fault_id]
    return eco, faults


def _deliver_next(eco) -> int:
    """Advance the bus one tick and deliver, as `ecosystem.step` does first; return the new tick."""
    tick = eco.bus.tick + 1
    eco.bus.advance(tick)
    eco.bus.deliver()
    return tick


# ----------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def n_run():
    run = Run("N", TICKS)
    yield run
    run.close()


@pytest.fixture(scope="module")
def drop_run():
    run = Run("ms-drop", TICKS)
    yield run
    run.close()


@pytest.fixture(scope="module")
def delay_run():
    run = Run("ms-delay", TICKS)
    yield run
    run.close()


@pytest.fixture(scope="module")
def starve_run():
    run = Run("cs-starve", TICKS)
    yield run
    run.close()


@pytest.fixture(scope="module")
def partition_run():
    run = Run("cs-partition", TICKS)
    yield run
    run.close()


# ======================================================== before tick 400
def test_no_scenario_fault_fires_before_400_and_the_streams_are_normal_until_then(
        n_run, drop_run, delay_run, starve_run, partition_run):
    assert n_run.faults.faults_applied() == [] and n_run.topic("stress_fault_activated") == []
    normal = _before(n_run.events, 400)
    assert len(normal) > 1000
    for run in (drop_run, delay_run, starve_run, partition_run):
        fired = run.topic("stress_fault_activated")
        assert [e["tick"] for e in fired] == [400], run.scenario.id
        assert fired[0]["detail"]["fault_id"] == run.scenario.id
        assert fired[0]["detail"]["mechanism"] == run.scenario.mechanism_name
        assert fired[0]["detail"]["scenario"] == run.scenario.id
        assert fired[0]["actor"] == "SIMULATION" and fired[0]["category"] == "simulation"
        assert run.faults.faults_applied()[0]["tick"] == 400
        assert _before(run.events, 400) == normal, run.scenario.id
        assert [r for r in run.rows if r["tick"] <= 399] == [r for r in n_run.rows
                                                              if r["tick"] <= 399]
        # and the streams part at 400, where the fault is fired before the step
        assert [e for e in run.events if e["tick"] == 400] != \
               [e for e in n_run.events if e["tick"] == 400]


def test_every_scenario_is_built_from_the_normal_configuration():
    for name in spec.NAMES:
        assert spec.config(spec.scenario(name)) == normal_config()
    assert "interceptors" in normal_config() and normal_config()["interceptors"] == []


# ============================================================== M-S-DROP
def test_ms_drop_every_message_from_400_is_dropped_and_nothing_reaches_an_inbox(drop_run):
    sent = drop_run.sent()
    dropped = {e["detail"]["message_id"] for e in drop_run.topic("message_dropped")}
    assert dropped, "nothing was dropped"
    # A message sent at tick t is delivered at t + 1; from the activation at
    # 400 that delivery drops it, so everything sent from 399 on is dropped
    # (what was sent on the last tick is still pending, not yet decided).
    late = [e for e in sent if 399 <= e["tick"] < TICKS]
    assert late, "the facility fell silent before the fault"
    assert all(e["detail"]["message_id"] in dropped for e in late)
    pending = {m.message_id for m in drop_run.eco.bus._pending}
    assert {e["detail"]["message_id"] for e in sent if e["tick"] == TICKS} == pending
    early = [e for e in sent if e["tick"] < 399]
    assert not any(e["detail"]["message_id"] in dropped for e in early)
    assert min(e["tick"] for e in drop_run.topic("message_dropped")) == 400
    # the inboxes are empty after every step: the rule drops at delivery
    assert sum(len(v) for v in drop_run.eco.bus._inboxes.values()) == 0
    assert drop_run.eco.bus._held == []


def test_ms_drop_the_counter_grows_and_the_rule_is_still_installed_at_700(drop_run):
    faults = drop_run.faults
    status = faults.status()
    assert status["scenario"] == "MS-DROP" and status["applied_at"] == 400
    assert status["rule_installed"] is True
    assert drop_run.eco.bus.delay_rule is faults.rule is not None
    assert status["dropped"] == faults.rule.dropped == len(drop_run.topic("message_dropped"))
    assert status["dropped"] > 50
    assert status["held_now"] == 0 and status["delayed"] == 0
    assert faults.applied["MS-DROP"]["dropped_so_far"] == 0      # at activation
    assert all(drop_run.held[t] == 0 for t in range(1, TICKS + 1))
    # before_tick again fires nothing and installs nothing new
    rule = faults.rule
    assert faults.before_tick(400) == [] and drop_run.eco.bus.delay_rule is rule


# ============================================================= M-S-DELAY
def test_ms_delay_a_routing_message_arrives_at_t_plus_11_and_a_plain_one_at_t_plus_1():
    eco, faults = _at_400("ms-delay")
    try:
        bus = eco.bus
        route = bus.send("SCHEDULING", "ROUTING", MessageType.ROUTE_REQUEST,
                         {"operation": "plan_transport"}, correlation_id="P-T")
        plain = bus.send("SCHEDULING", "SUB-QUEUE", MessageType.SUBTASK_REQUEST,
                         {"operation": "next_task"}, correlation_id="P-T")
        assert route is not None and plain is not None and route.tick == plain.tick == 400
        t = 400
        tick = _deliver_next(eco)                                   # 401
        assert tick == t + 1
        assert [m.message_id for m in bus.peek("SUB-QUEUE")] == [plain.message_id]
        assert bus.peek("ROUTING") == [] and len(bus._held) == 1
        for _ in range(t + 2, t + 11):
            _deliver_next(eco)
            assert bus.peek("ROUTING") == [], "released early"
        assert bus.tick == t + 10 and len(bus._held) == 1
        tick = _deliver_next(eco)
        assert tick == t + 11
        assert [m.message_id for m in bus.peek("ROUTING")] == [route.message_id]
        assert bus._held == []
        (late,) = [e for e in eco.logger.recent(10_000) if e.topic == "agent_message_received"]
        assert late.tick == t + 11 and late.detail["message_id"] == route.message_id
        assert late.detail["late_by"] == spec.DELAY_TICKS == 10
        assert late.detail["message_type"] == "ROUTE_REQUEST"
        # (what `start()` posted was pending too, and passed as not routing)
        assert faults.rule.delayed == 1 and faults.rule.passed >= 1
        assert faults.status()["delayed"] == 1 and faults.status()["delay_ticks"] == 10
    finally:
        eco.close()


def test_ms_delay_in_the_run_every_late_arrival_is_exactly_10_ticks_and_nothing_is_dropped(
        delay_run):
    late = delay_run.topic("agent_message_received")
    assert late, "no routing message arrived late"
    assert all(e["detail"]["late_by"] == 10 for e in late)
    by_id = {e["detail"]["message_id"]: e for e in delay_run.sent()}
    for event in late:
        sent = by_id[event["detail"]["message_id"]]
        assert event["tick"] == sent["tick"] + 11, (sent, event)
        assert sent["tick"] >= 399
    assert delay_run.topic("message_dropped") == []
    # every late message is routing-related; a SUBTASK_REQUEST to SUB-QUEUE never is
    late_ids = {e["detail"]["message_id"] for e in late}
    for sent in delay_run.sent():
        if sent["tick"] < 399 or sent["tick"] + 11 > TICKS:        # the last ones are still held
            continue
        routing = (sent["actor"] in spec.ROUTING_GROUP or sent["target"] in spec.ROUTING_GROUP
                   or sent["detail"]["message_type"] in ("ROUTE_REQUEST", "ROUTE_RESPONSE")
                   or (sent["detail"]["message_type"] == "ROBOT_COMMAND"
                       and sent["detail"]["content"].get("operation") in spec.ROUTING_OPERATIONS))
        assert (sent["detail"]["message_id"] in late_ids) == routing, sent
    queue = [e for e in delay_run.sent() if e["tick"] >= 400 and e["target"] == "SUB-QUEUE"]
    assert queue and not any(e["detail"]["message_id"] in late_ids for e in queue)
    status = delay_run.faults.status()
    assert status["delayed"] == len(late) + status["held_now"]
    assert status["held_now"] == len(delay_run.eco.bus._held)
    assert delay_run.eco.bus.delay_rule is delay_run.faults.rule
    assert all(delay_run.held[t] == 0 for t in range(1, 400))


def test_ms_delay_the_classification_of_a_message():
    from post_office.communication.message import Message

    def message(sender: str, receiver: str, kind: MessageType, **content) -> Message:
        return Message(message_id="M", tick=1, sender=sender, receiver=receiver,
                       message_type=kind, content=content)

    assert is_routing_related(message("SCHEDULING", "ROUTING", MessageType.ROUTE_REQUEST))
    assert is_routing_related(message("ROUTING", "SCHEDULING", MessageType.ROUTE_RESPONSE))
    assert is_routing_related(message("ROUTING", "SUB-ROUTE", MessageType.SUBTASK_REQUEST))
    assert is_routing_related(message("SUB-COLLISION", "ROUTING", MessageType.SUBTASK_RESULT))
    assert is_routing_related(message("R1", "ROUTING", MessageType.ROBOT_REPORT, report="blocked"))
    for operation in spec.ROUTING_OPERATIONS:
        assert is_routing_related(message("ROUTING", "R1", MessageType.ROBOT_COMMAND,
                                          operation=operation))
    assert not is_routing_related(message("SCHEDULING", "R1", MessageType.ROBOT_COMMAND,
                                          operation="transport"))
    assert not is_routing_related(message("SCHEDULING", "SUB-QUEUE", MessageType.SUBTASK_REQUEST))
    assert not is_routing_related(message("SCHEDULING", "RESOURCE", MessageType.RESOURCE_REQUEST))
    assert not is_routing_related(message("R1", "SCHEDULING", MessageType.ROBOT_REPORT))
    assert spec.ROUTING_OPERATIONS == ("set_route", "yield", "step_aside")


# ============================================================ C-S-STARVE
def test_cs_starve_no_charge_point_from_400_and_the_rescue_is_refused(starve_run):
    assert starve_run.stations[399] == ["CS-1", "CS-2", "CS-3", "CS-4"]
    assert all(starve_run.stations[t] == [] for t in range(400, TICKS + 1))
    assert starve_run.eco.env.stations == {} and starve_run.eco.env.free_stations() == []
    by_tick = {r["tick"]: r["stations"] for r in starve_run.rows}
    assert by_tick[399] == 4 and all(by_tick[t] == 0 for t in range(400, TICKS + 1))
    (fired,) = starve_run.topic("stress_fault_activated")
    detail = fired["detail"]
    assert detail["stations_before"] == ["CS-1", "CS-2", "CS-3", "CS-4"]
    assert detail["stations_after"] == [] and detail["removed"] == detail["stations_before"]
    assert detail["rescue_crew"] == "none"
    assert isinstance(starve_run.eco.recovery, NoRescue)
    assert not isinstance(starve_run.eco.recovery, RecoveryService)
    assert starve_run.faults.status()["rescue_crew"] == "none"
    assert starve_run.faults.status()["stations"] == []
    assert starve_run.topic("recovery_completed") == []
    assert starve_run.topic("robot_recovered") == []


def test_cs_starve_a_flat_robot_is_refused_once_and_never_recovered():
    eco, faults = _at_400("cs-starve")
    try:
        robot = eco.fleet.get("R1")
        robot.battery_level = 0.005                  # less than one idle tick's drain
        for _ in range(3):                           # a plug-in is interrupted first
            faults.before_tick(eco.world.tick + 1)
            eco.step()
            if robot.battery_level <= 0.0:
                break
        assert robot.battery_level == 0.0 and robot.status is RobotState.WAITING
        waited = eco.experts["RESOURCE"].RECOVERY_AFTER
        for _ in range(waited + 2):
            faults.before_tick(eco.world.tick + 1)
            eco.step()
        requested = [e for e in eco.logger.recent(100_000)
                     if e.topic == "recovery_requested" and e.target == "R1"]
        assert len(requested) == 1
        refused = [e for e in eco.logger.recent(100_000) if e.topic == "recovery_refused"]
        assert [e.target for e in refused] == ["R1"]
        (event,) = refused
        assert event.actor == "SIMULATION" and event.category == "simulation"
        assert event.detail["reason"] == spec.NO_RESCUE_REASON == "no rescue crew in this scenario"
        assert event.detail["requested_by"] == "RESOURCE"
        assert event.tick == requested[0].tick       # the crew answers the same tick
        # Long after: still refused once, still flat, still where it stopped.
        where = robot.current_position
        for _ in range(60):
            faults.before_tick(eco.world.tick + 1)
            eco.step()
        topics = [e.topic for e in eco.logger.recent(100_000)]
        assert topics.count("recovery_refused") == 1
        assert "recovery_completed" not in topics and "robot_recovered" not in topics
        assert "recovery_deferred" not in topics and "recovery_withdrawn" not in topics
        assert robot.battery_level == 0.0 and robot.current_position == where
        assert robot.status is not RobotState.CHARGING
        assert eco.recovery.refused == 1 and eco.recovery.stats() == {
            "completed": 0, "refused": 1, "withdrawn": 0}
        assert [r["robot_id"] for r in eco.recovery.pending] == ["R1"]
        assert eco.recovery.as_dict()["crew"] == "none"
        assert faults.status()["recovery_refused"] == 1
        assert eco.env.stations == {}
    finally:
        eco.close()


def test_cs_starve_the_crew_has_no_method_that_restores():
    public = {name for name in dir(NoRescue) if not name.startswith("_")}
    assert public == {"step", "stats", "as_dict", "pending"}
    for name in dir(NoRescue):
        low = name.lower()
        for word in ("recover", "restore", "tow", "place", "claim", "charge", "release", "put"):
            assert word not in low or name.startswith("__"), name
    assert not hasattr(NoRescue, "_attempt") and not hasattr(NoRescue, "_free_station")


# ========================================================= C-S-PARTITION
def test_cs_partition_scheduling_and_resource_cannot_message_each_other_and_the_rest_can():
    eco, faults = _at_400("cs-partition")
    try:
        bus = eco.bus
        across = bus.send("SCHEDULING", "RESOURCE", MessageType.RESOURCE_REQUEST,
                          {"operation": "battery_check"}, correlation_id="P-T")
        back = bus.send("RESOURCE", "SCHEDULING", MessageType.RESOURCE_GRANT,
                        {"operation": "battery_check", "ok": True}, correlation_id="P-T")
        sub = bus.send("SCHEDULING", "SUB-QUEUE", MessageType.SUBTASK_REQUEST,
                       {"operation": "next_task"}, correlation_id="P-T")
        sideways = bus.send("RESOURCE", "ROUTING", MessageType.ROUTE_REQUEST,
                            {"operation": "plan_route"}, correlation_id="P-T")
        assert None not in (across, back, sub, sideways)
        _deliver_next(eco)
        assert [m.message_id for m in bus.peek("SUB-QUEUE")] == [sub.message_id]
        assert [m.message_id for m in bus.peek("ROUTING")] == [sideways.message_id]
        assert bus.peek("RESOURCE") == [] and bus.peek("SCHEDULING") == []
        dropped = [e for e in eco.logger.recent(10_000) if e.topic == "message_dropped"]
        assert {e.detail["message_id"] for e in dropped} == {across.message_id, back.message_id}
        assert all(e.tick == 401 for e in dropped)
        assert bus._held == []
        assert faults.rule.dropped == {"SCHEDULING->RESOURCE": 1, "RESOURCE->SCHEDULING": 1}
        assert faults.rule.passed >= 2                 # plus what `start()` posted
        status = faults.status()
        assert status["dropped"] == 2 and status["dropped_by_direction"] == faults.rule.dropped
        assert status["delayed"] == 0 and status["held_now"] == 0
    finally:
        eco.close()


def test_cs_partition_in_the_run_only_the_cross_group_traffic_is_dropped(partition_run):
    dropped = {e["detail"]["message_id"] for e in partition_run.topic("message_dropped")}
    assert dropped
    sent = [e for e in partition_run.sent() if e["tick"] >= 399]
    crossing = [e for e in sent
                if (e["actor"] in spec.SCHEDULING_GROUP and e["target"] in spec.RESOURCE_GROUP)
                or (e["actor"] in spec.RESOURCE_GROUP and e["target"] in spec.SCHEDULING_GROUP)]
    assert crossing, "nothing crossed the partition"
    assert {e["detail"]["message_id"] for e in crossing} == dropped
    assert any(e["detail"]["message_type"] == "RESOURCE_REQUEST" and e["actor"] == "SCHEDULING"
               and e["target"] == "RESOURCE" for e in crossing)
    queue = [e for e in sent if e["actor"] == "SCHEDULING" and e["target"] == "SUB-QUEUE"]
    assert queue and not any(e["detail"]["message_id"] in dropped for e in queue)
    assert partition_run.topic("agent_message_received") == []
    status = partition_run.faults.status()
    assert status["dropped"] == len(dropped) == sum(status["dropped_by_direction"].values())
    assert set(status["dropped_by_direction"]) == {"SCHEDULING->RESOURCE", "RESOURCE->SCHEDULING"}
    assert partition_run.eco.bus.delay_rule is partition_run.faults.rule
    assert partition_direction(partition_run.eco.bus.log.recent(1)[0]) in (
        None, "SCHEDULING->RESOURCE", "RESOURCE->SCHEDULING")
    assert spec.SCHEDULING_GROUP == ("SCHEDULING", "SUB-QUEUE", "SUB-DEADLINE", "SUB-ASSIGNMENT")
    assert spec.RESOURCE_GROUP == ("RESOURCE", "SUB-BATTERY", "SUB-CHARGING", "SUB-STORAGE")
    # the ids are the ones the ecosystem registers
    directory = partition_run.eco.directory
    for agent_id in spec.SCHEDULING_GROUP + spec.RESOURCE_GROUP + spec.ROUTING_GROUP:
        assert agent_id in directory, agent_id
    sub_agents = {r.agent_id for r in directory.all() if r.kind.value == "SUBAGENT"}
    assert set(directory.children_of("SCHEDULING")) & sub_agents == set(spec.SCHEDULING_GROUP[1:])
    assert set(directory.children_of("RESOURCE")) & sub_agents == set(spec.RESOURCE_GROUP[1:])
    assert set(directory.children_of("ROUTING")) & sub_agents == set(spec.ROUTING_GROUP[1:])


# ============================================================ no removal
def test_collapse_faults_has_exactly_three_public_methods_and_no_removal_path():
    public = {name for name, value in vars(CollapseFaults).items()
              if not name.startswith("_") and callable(value)}
    assert public == {"before_tick", "faults_applied", "status"}
    private = {name for name, value in vars(CollapseFaults).items()
               if name.startswith("_") and not name.startswith("__") and callable(value)}
    assert private == {"_message_drop", "_message_delay", "_charge_starvation",
                       "_message_partition", "_message_stall"}
    assert not any(isinstance(value, property) for value in vars(CollapseFaults).values())
    for name in dir(CollapseFaults):
        low = name.lower()
        assert not any(word in low for word in ("remove", "restore", "undo", "revert", "release",
                                                "reinstate", "clear")), name
    eco = build(seed=SEED, config=spec.config(spec.scenario("ms-drop")), run_id=RUN_ID)
    try:
        faults = CollapseFaults(eco, spec.scenario("ms-drop"))
        bound = {name for name in dir(faults) if not name.startswith("_")
                 and callable(getattr(faults, name))}
        assert bound == public
    finally:
        eco.close()
    # the module's source never calls release_held and never clears the rule
    source = (ROOT / "post_office" / "stress" / "collapse_scenarios.py").read_text(encoding="utf-8")
    assert "release_held(" not in source
    assert "delay_rule = None" not in source
    assert "\u2014" not in source


def test_the_definition_and_the_fingerprint_tell_the_scenarios_apart():
    prints = {name: spec.fingerprint(spec.scenario(name)) for name in spec.NAMES}
    assert len(set(prints.values())) == 6 and all(len(p) == 64 for p in prints.values())
    assert spec.fingerprint(spec.scenario("ms-drop")) == prints["ms-drop"]
    definition = spec.definition(spec.scenario("cs-starve"))
    assert definition["study"] == spec.STUDY and definition["start"] == 400
    assert definition["scenario"]["id"] == "CS-STARVE" and definition["scenario"]["preset"] == "cs-starve"
    assert definition["scenario"]["holds_until"] == "end of run"
    assert definition["config"] == normal_config() and definition["collapse"] == collapse.COLLAPSE
    assert [r["tick"] for r in definition["schedule"]] == [400]
    assert spec.schedule(spec.scenario("N")) == []
    assert spec.scenario("MS-DELAY") is spec.scenario("ms-delay") is spec.SCENARIOS["MS-DELAY"]
    assert spec.scenario("n").control and spec.scenario("N").preset == "default"
    with pytest.raises(ValueError):
        spec.scenario("c0")
    assert spec.START == 400 and spec.RUN_TICKS == 2800 and spec.SEEDS == (11, 12, 13, 14, 15)
    assert spec.RESULTS_DIR == "results/collapse_scenarios"
    for scn in spec.SCENARIOS.values():
        for text in (scn.label, scn.mechanism, scn.expected):
            _clean(text)
            assert "\u2014" not in text


# ============================================================ the registry
def test_settings_list_the_collapse_presets_after_c2near_with_normal_first_and_unchanged():
    assert PRESETS == {"default": DEFAULT_CONFIG}
    assert list(COLLAPSE_PRESETS) == ["ms-drop", "ms-delay", "cs-starve", "cs-partition",
                                      "ms-stall"]
    assert known_presets() == ["default", *C2NEAR_PRESETS, *COLLAPSE_PRESETS]
    rows = scenarios("qwen3:8b")
    assert rows[0] == ("default", NORMAL_LABEL) and rows[0][1] == scenario_label("qwen3:8b")
    assert [preset for preset, _ in rows] == known_presets()
    labels = dict(rows)
    assert labels["ms-drop"] == "M-S-DROP · all messages dropped from 400"
    assert labels["ms-delay"] == "M-S-DELAY · routing messages delayed 10 ticks from 400"
    assert labels["cs-starve"] == "C-S-STARVE · no charge point and no rescue crew from 400"
    assert labels["cs-partition"] == ("C-S-PARTITION · SCHEDULING and RESOURCE cannot message "
                                      "each other from 400")
    assert labels["ms-stall"] == ("M-S-STALL · every message held from 1800 and all delivered "
                                  "at 2100")
    for preset, scenario_id in COLLAPSE_PRESETS.items():
        _clean(labels[preset])
        meta = scenario_meta(preset)
        assert meta["scenario"] == preset == scenario_name(preset)
        assert meta["label"] == labels[preset]
        assert meta["monitoring"] == "Monitoring (observe only)"
        scn = spec.scenario(preset)
        assert scn.id == scenario_id and scn.label == labels[preset]
        assert meta["purpose"] == scn.mechanism and meta["about"] == scn.expected
        for key in ("label", "monitoring", "purpose", "about"):
            _clean(meta[key])
            assert "\u2014" not in meta[key]
        assert config(preset) == normal_config() == spec.config(scn)
    assert scenario_meta("default") == {"scenario": "normal", "label": "Normal Ecosystem",
                                        "monitoring": "Monitoring", "purpose": "No Perturbation",
                                        "about": "the facility under ordinary operating "
                                                 "conditions, with its own variability and "
                                                 "its own naturally occurring deviations"}
    assert config() == DEFAULT_CONFIG and "c2near_system_override" not in normal_config()
    with pytest.raises(ValueError):
        scenario_meta("ms-stop")
    with pytest.raises(ValueError):
        config("ms-stop")


# ============================================================== the runner
fastapi = pytest.importorskip("fastapi", reason="the API is optional")
from fastapi.testclient import TestClient  # noqa: E402

from post_office.api import server  # noqa: E402
from post_office.api.runner import SimulationRunner  # noqa: E402


@pytest.fixture
def rules():
    runner = SimulationRunner(seed=2, run_id="cs", tick_seconds=0.0, rules_only=True)
    try:
        yield runner
    finally:
        runner.close()


def test_a_rules_only_runner_carries_ms_drop_and_reports_it(rules):
    assert rules.faults is None and rules.study_status() is None and rules.c2near_status() is None
    rules.reset(preset="ms-drop")
    assert rules.preset == "ms-drop" and rules.eco.seed == 11          # the studies' first seed
    assert rules._config == normal_config() and rules.eco.config == normal_config()
    assert isinstance(rules.faults, CollapseFaults) and rules.faults.scenario.id == "MS-DROP"
    assert rules.c2near_status() is None
    before = rules.study_status()
    assert before["family"] == "collapse" and before["scenario"] == "MS-DROP"
    assert before["preset"] == "ms-drop" and before["seed"] == 11
    assert before["run_ticks"] == 2800 and before["pressure_from"] == 400
    assert before["schedule"] == [{"tick": 400, "mechanism": "message_drop", "fault_id": "MS-DROP",
                                   "label": "all messages dropped from 400", "applied_at": None}]
    assert before["counters"]["dropped"] == 0 and before["counters"]["rule_installed"] is False
    assert before["stations"] == ["CS-1", "CS-2", "CS-3", "CS-4"]
    assert before["routes_open"] == []                   # the bay fills when the run starts
    assert before["arrival_interval"] == before["arrival_interval_normal"] == 40.0
    assert before["dkrmm"]["attached"] is True and before["dkrmm"]["assessments"] == 0
    for key in ("label", "mechanism", "expected"):
        _clean(before[key])
    rules.eco.start()
    rules.step(399)
    assert rules.eco.bus.delay_rule is None
    assert rules.study_status()["routes_open"] == ["BRNO", "OSTRAVA", "PLZEN", "OLOMOUC",
                                                   "LIBEREC", "HRADEC"]
    rules.step(2)
    assert rules.eco.world.tick == 401
    status = rules.study_status()
    assert status["schedule"][0]["applied_at"] == 400
    assert rules.eco.bus.delay_rule is rules.faults.rule is not None
    assert status["counters"]["rule_installed"] is True and status["counters"]["dropped"] > 0
    dk = status["dkrmm"]
    assert dk["assessments"] == len(dk["sequence"]) >= 19
    assert dk["rct_ticks"] == [t for t, s in dk["sequence"] if s == "RCT"]
    fired = [e for e in rules.eco.logger.recent(limit=100000) if e.topic == "stress_fault_activated"]
    assert [e.detail["fault_id"] for e in fired] == ["MS-DROP"] and fired[0].tick == 400
    # the other three presets build on a rules-only runner too
    for preset in ("ms-delay", "cs-starve", "cs-partition"):
        rules.reset(preset=preset)
        assert rules.eco.seed == 11 and rules.faults.scenario.preset == preset
        assert rules.study_status()["family"] == "collapse"
        assert rules.study_status()["scenario"] == COLLAPSE_PRESETS[preset]


def test_the_summary_carries_study_and_a_switch_back_to_default_rebuilds_without_the_rule(rules):
    previous = server.use(rules)
    try:
        with TestClient(server.app) as client:
            body = client.get("/summary").json()
            assert body["preset"] == "default" and body["study"] is None and body["c2near"] is None
            response = client.post("/simulation/reset", params={"preset": "cs-partition"})
            assert response.status_code == 200 and response.json()["ok"]
            rules.eco.start()
            rules.step(405)
            old_eco, old_bus = rules.eco, rules.eco.bus
            assert old_bus.delay_rule is not None
            body = client.get("/summary").json()
            assert body["preset"] == "cs-partition" and body["c2near"] is None
            study = body["study"]
            assert study["family"] == "collapse" and study["scenario"] == "CS-PARTITION"
            assert study["schedule"][0]["applied_at"] == 400
            assert study["counters"]["dropped_by_direction"]["SCHEDULING->RESOURCE"] >= 0
            assert body["scenario_meta"]["scenario"] == "cs-partition"
            assert body["scenario_label"] == dict(scenarios("qwen3:8b"))["cs-partition"]
            # back to Normal: a new ecosystem, a new bus, no rule, no schedule
            response = client.post("/simulation/reset", params={"preset": "default"})
            assert response.status_code == 200
            assert rules.preset == "default" and rules.faults is None
            assert rules.study_status() is None and rules.c2near_status() is None
            assert rules.eco is not old_eco and rules.eco.bus is not old_bus
            assert rules.eco.bus.delay_rule is None and rules.eco.bus._held == []
            assert isinstance(rules.eco.recovery, RecoveryService)
            assert rules.eco.config == normal_config() and rules._config == normal_config()
            body = client.get("/summary").json()
            assert body["preset"] == "default" and body["study"] is None
            assert body["scenario_label"] == NORMAL_LABEL
            # an unknown preset is still refused, naming the new ones
            response = client.post("/simulation/reset", params={"preset": "ms-stop"})
            assert response.status_code == 400 and "ms-drop" in response.json()["detail"]
    finally:
        server.use(previous)


def test_c2near_status_and_study_status_agree_on_a_c2near_preset(rules):
    rules.reset(preset="c2near-c0")
    direct = rules.c2near_status()
    study = rules.study_status()
    assert study["family"] == "c2near"
    assert {k: v for k, v in study.items() if k != "family"} == direct
    assert study["condition"] == "C0"


def test_the_rct_log_tags_the_new_presets_with_their_labels():
    from post_office.observability.run_record import scenario_of

    labels = dict(scenarios("qwen3:8b"))
    for preset in COLLAPSE_PRESETS:
        assert scenario_of(preset, "qwen3:8b") == {"scenario": preset,
                                                    "scenario_label": labels[preset]}
    assert scenario_of("default", "qwen3:8b") == {"scenario": "normal",
                                                  "scenario_label": NORMAL_LABEL}


# ============================================================== the driver
def test_the_driver_refuses_results_normal_and_defaults_elsewhere():
    driver = _load_driver()
    for bad in ("results/normal", "results/normal/s1", "results/collapse_scenarios/../normal/s1"):
        with pytest.raises(ValueError, match="results.normal|refusing"):
            driver.refuse_normal(pathlib.Path(bad))
        with pytest.raises(ValueError):
            driver.refuse_normal(ROOT / bad)
    default = driver.parse_args([]).out
    assert pathlib.Path(default) == ROOT / "results" / "collapse_scenarios"
    assert driver.refuse_normal(pathlib.Path(default)) == (ROOT / spec.RESULTS_DIR).resolve()
    assert driver.FORBIDDEN == ROOT / "results" / "normal"
    assert driver.main(["--scenario", "ms-drop", "--rules", "--out", "results/normal/x"]) == 2
    assert not (ROOT / "results" / "normal" / "x").exists()
    assert [s.id for s in driver.expand(["all"])] == ["N", "MS-DROP", "MS-DELAY", "CS-STARVE",
                                                      "CS-PARTITION", "MS-STALL"]
    assert [s.id for s in driver.expand(["cs-starve", "N", "cs-starve"])] == ["N", "CS-STARVE"]
    assert driver.parse_args([]).ticks == 2800 and driver.parse_args([]).seeds == [11, 12, 13, 14, 15]


def _fake_run(run_dir: pathlib.Path, scenario_id: str, seed: int, mode: str, ticks: int,
              every: int = 50, done: bool = True) -> None:
    run_dir.mkdir(parents=True)
    with (run_dir / "series.csv").open("w", encoding="utf-8", newline="") as handle:
        handle.write("tick,dispatched,backlog,arrival_refused,robots_flat\n")
        for tick in range(1, ticks + 1):
            handle.write(f"{tick},{1 if tick % every == 0 else 0},10,0,0\n")
    (run_dir / "measurement.json").write_text(json.dumps({
        "mode": mode, "ticks": ticks,
        "totals": {"dispatched": ticks // every, "backlog_end": 10, "arrival_refused": 0,
                   "stations_end": 4},
        "counters": {"dropped": 7, "delayed": 0, "recovery_refused": 0, "held_now": 0}}),
        encoding="utf-8")
    (run_dir / "definition.json").write_text(json.dumps({
        "study": spec.STUDY, "scenario": scenario_id, "seed": seed, "mode": mode,
        "ticks": ticks}), encoding="utf-8")
    if done:
        (run_dir / "done.json").write_text(json.dumps({
            "study": spec.STUDY, "scenario": scenario_id, "seed": seed, "mode": mode,
            "ticks": ticks}), encoding="utf-8")


def test_analyze_uses_a_comparable_control_from_elsewhere_and_refuses_the_rest(tmp_path, capsys):
    """
    Seed 11: the control under `--control-from` was made in model mode, the
    run on rules, so it does not serve, and there is none under `--out`:
    `no control`. Seed 12: the control from elsewhere matches and the run
    is `STABLE`. Seed 13: the control from elsewhere has other ticks, the
    one under `--out` matches and is used. Seed 14: no control anywhere.
    Seed 15: the only control, under `--out`, was made in another mode:
    `not_comparable`, printed and recorded.
    """
    driver = _load_driver()
    out, elsewhere = tmp_path / "out", tmp_path / "c2near"
    _fake_run(elsewhere / "N" / "s11", "N", 11, "model", 500)
    _fake_run(out / "MS-DROP" / "s11", "MS-DROP", 11, "rules", 500)
    _fake_run(elsewhere / "N" / "s12", "N", 12, "rules", 500)
    _fake_run(out / "MS-DROP" / "s12", "MS-DROP", 12, "rules", 500)
    _fake_run(elsewhere / "N" / "s13", "N", 13, "rules", 600)
    _fake_run(out / "N" / "s13", "N", 13, "rules", 500)
    _fake_run(out / "MS-DROP" / "s13", "MS-DROP", 13, "rules", 500)
    _fake_run(out / "CS-STARVE" / "s14", "CS-STARVE", 14, "rules", 500)
    summary = driver.analyze(out, elsewhere)
    printed = capsys.readouterr().out
    by_seed = {row["seed"]: row for row in summary["runs"]}
    assert by_seed[11]["outcome"] == "no control"
    assert by_seed[11]["control"] == str(out / "N" / "s11")
    assert "collapse_criterion" not in by_seed[11] and "dispatched" not in by_seed[11]
    assert by_seed[12]["outcome"] == collapse.STABLE
    assert by_seed[12]["control"] == str(elsewhere / "N" / "s12")
    assert by_seed[12]["dispatched"] == 10 and by_seed[12]["dropped"] == 7
    assert by_seed[12]["evaluated_ticks"] == 101
    assert by_seed[13]["outcome"] == collapse.STABLE
    assert by_seed[13]["control"] == str(out / "N" / "s13")
    assert by_seed[14]["outcome"] == "no control" and by_seed[14]["scenario"] == "CS-STARVE"
    assert summary["control_from"] == str(elsewhere) and summary["study"] == spec.STUDY
    written = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert written["runs"] == json.loads(json.dumps(summary["runs"]))
    # a control under --out whose mode differs is refused, and said to be
    _fake_run(out / "N" / "s15", "N", 15, "model", 500)
    _fake_run(out / "MS-DELAY" / "s15", "MS-DELAY", 15, "rules", 500)
    summary = driver.analyze(out, elsewhere)
    printed = capsys.readouterr().out
    assert "refuse MS-DELAY s15: not comparable with N s15 (mode 'rules' vs control 'model')" in printed
    assert summary["not_comparable"] == [{"scenario": "MS-DELAY", "seed": 15,
                                          "reason": "mode 'rules' vs control 'model'"}]
    row = next(r for r in summary["runs"] if r["seed"] == 15)
    assert row["outcome"] == driver.NOT_COMPARABLE == "not_comparable"
    assert row["mode"] == "rules" and row["control_mode"] == "model"
    assert "collapse_criterion" not in row and "dispatched" not in row
    assert driver.run_identity(out / "N" / "s15") == {"mode": "model", "ticks": 500,
                                                      "source": "done.json"}


def test_a_short_driver_run_writes_every_file_and_never_overwrites(tmp_path, capsys):
    driver = _load_driver()
    out = tmp_path / "out"
    assert driver.main(["--scenario", "cs-partition", "--seeds", "11", "--ticks", "12",
                        "--rules", "--out", str(out)]) == 0
    run_dir = out / "CS-PARTITION" / "s11"
    for name in ("events.jsonl", "definition.json", "series.csv", "measurement.json",
                 "dkrmm.json", "summary.json", "verify.json", "done.json"):
        assert (run_dir / name).exists(), name
    done = json.loads((run_dir / "done.json").read_text(encoding="utf-8"))
    assert done == {"study": spec.STUDY, "scenario": "CS-PARTITION", "preset": "cs-partition",
                    "seed": 11, "ticks": 12, "fingerprint": spec.fingerprint(spec.scenario("cs-partition")),
                    "mode": "rules"}
    measurement = json.loads((run_dir / "measurement.json").read_text(encoding="utf-8"))
    assert measurement["study"] == spec.STUDY and measurement["scenario"] == "CS-PARTITION"
    assert measurement["preset"] == "cs-partition" and "experiment" not in measurement
    assert measurement["counters"]["scenario"] == "CS-PARTITION"
    assert measurement["totals"]["ticks"] == 12 and measurement["faults_applied"] == []
    assert len((run_dir / "series.csv").read_text(encoding="utf-8").splitlines()) == 13
    stamp = (run_dir / "done.json").stat().st_mtime_ns
    assert driver.main(["--scenario", "cs-partition", "--seeds", "11", "--ticks", "12",
                        "--rules", "--out", str(out)]) == 0
    assert "skip CS-PARTITION s11: done" in capsys.readouterr().out
    assert (run_dir / "done.json").stat().st_mtime_ns == stamp
    assert not (out / "N").exists()
