"""
Four collapse scenarios on the Normal facility, each one mechanism, each held
to the end of the run.

Exact Normal for the first 400 ticks, then one thing goes wrong and stays
wrong:

    M-S-DROP        every message on the bus is dropped at delivery
    M-S-DELAY       every routing-related message arrives 10 ticks late
    C-S-STARVE      every charge point is removed and there is no rescue crew
    C-S-PARTITION   SCHEDULING and RESOURCE cannot message each other

plus `N`, the control: the Normal facility on the same seeds, which is the
same N as the C2-NEAR study, so its runs can serve here.

Every scenario is built from `normal_config()` unchanged. The disruption is
applied from outside the ecosystem by `CollapseFaults` at `START`, through
seams that already exist: the bus's `delay_rule` (consulted in `deliver`, the
one place delivery is decided: `None` delivers, a negative hold drops the
message with a `message_dropped` event, a positive hold releases it that
many ticks later with an `agent_message_received late_by` event), the
`env.stations` dictionary every reader uses, and the ecosystem's `recovery`
attribute, which `step` calls once a tick. Nothing in `post_office/
communication`, `simulation`, `agents`, `dkrmm` or `policy` changes.

There is no removal, undo or restoration path in this module, on purpose.
The bus rule, once installed, is never taken off and `bus.release_held` is
never called; the stations are never put back; the rescue crew is replaced
by one that refuses every request and is never re-enabled. Code that could
put things back would be code whose absence from the run has to be proved.

The measurement is `measure.Collector` and the verdict is
`collapse.classify`, both shared with the C2-NEAR study; the driver is
`tools/run_collapse_scenarios.py`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..communication.events import EventCategory
from ..communication.message import Message, MessageType
from ..config.settings import COLLAPSE_PRESETS, SCENARIO_META, normal_config
from .collapse import COLLAPSE
from .measure import Collector

# ------------------------------------------------------------------ identity
STUDY = "COLLAPSE-SCENARIOS"
LABEL = "Collapse scenarios"
#: Results live here and nowhere else. `results/normal/` is never touched.
RESULTS_DIR = "results/collapse_scenarios"

# ------------------------------------------------------------------- the run
START = 400
RUN_TICKS = 2800
SEEDS: Tuple[int, ...] = (11, 12, 13, 14, 15)
#: How late a routing-related message arrives in M-S-DELAY, in ticks.
DELAY_TICKS = 10

# ------------------------------------------------------------------- groups
#: ROUTING and its sub-agents. A message is routing-related when one end is
#: here, or its type is a route request or response, or it is one of
#: ROUTING's commands to a robot (`routing_agent.py` sends `set_route`,
#: `yield` and `step_aside` as `ROBOT_COMMAND`; nobody else sends those).
ROUTING_GROUP: Tuple[str, ...] = ("ROUTING", "SUB-ROUTE", "SUB-COLLISION")
ROUTING_TYPES: Tuple[MessageType, ...] = (MessageType.ROUTE_REQUEST, MessageType.ROUTE_RESPONSE)
ROUTING_OPERATIONS: Tuple[str, ...] = ("set_route", "yield", "step_aside")
#: The two sides of the C-S-PARTITION, each expert with its sub-agents (the
#: ids `ecosystem._populate` registers).
SCHEDULING_GROUP: Tuple[str, ...] = ("SCHEDULING", "SUB-QUEUE", "SUB-DEADLINE", "SUB-ASSIGNMENT")
RESOURCE_GROUP: Tuple[str, ...] = ("RESOURCE", "SUB-BATTERY", "SUB-CHARGING", "SUB-STORAGE")
#: The partition's two directions, as the counters name them.
SCHEDULING_TO_RESOURCE = "SCHEDULING->RESOURCE"
RESOURCE_TO_SCHEDULING = "RESOURCE->SCHEDULING"

#: Mechanism names, one per scenario, as `stress_fault_activated` records them.
MESSAGE_DROP = "message_drop"
MESSAGE_DELAY = "message_delay"
CHARGE_STARVATION = "charge_starvation"
MESSAGE_PARTITION = "message_partition"

#: What the refused rescue says, in every `recovery_refused` event.
NO_RESCUE_REASON = "no rescue crew in this scenario"


# ---------------------------------------------------------------- scenarios
@dataclass(frozen=True)
class Scenario:
    """One scenario: its identity, its mechanism in a sentence, and when it starts."""

    id: str
    preset: str
    label: str
    mechanism: str
    expected: str
    start: Optional[int]
    holds_until: str

    @property
    def control(self) -> bool:
        return self.start is None

    @property
    def fault_id(self) -> str:
        return self.id

    @property
    def mechanism_name(self) -> str:
        return MECHANISM_OF.get(self.id, "")

    @property
    def short_label(self) -> str:
        """The label without its id prefix: what the strip says of the one scheduled row."""
        _, sep, rest = self.label.partition(" · ")
        return rest if sep else self.label

    def as_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "control": self.control,
                "fault_id": self.fault_id, "mechanism_name": self.mechanism_name}


MECHANISM_OF: Dict[str, str] = {
    "MS-DROP": MESSAGE_DROP,
    "MS-DELAY": MESSAGE_DELAY,
    "CS-STARVE": CHARGE_STARVATION,
    "CS-PARTITION": MESSAGE_PARTITION,
}

def _from_settings(preset: str) -> Scenario:
    """
    One scenario from the registry's wording (`settings.SCENARIO_META`:
    `label`, `purpose` is the mechanism, `about` is what is expected), so the
    live page, the run record and this module say the same thing.
    """
    meta = SCENARIO_META[preset]
    return Scenario(id=COLLAPSE_PRESETS[preset], preset=preset, label=meta["label"],
                    mechanism=meta["purpose"], expected=meta["about"],
                    start=START, holds_until="end of run")


SCENARIOS: Dict[str, Scenario] = {
    "N": Scenario(
        id="N", preset="default", label="N · control, the Normal facility",
        mechanism="Nothing is scheduled: the Normal facility, seed-matched with the four "
                  "scenarios, for 2800 ticks.",
        expected="The Normal facility's own figures on the same seeds, which every scenario "
                 "is judged against.",
        start=None, holds_until="no change"),
    **{scenario_id: _from_settings(preset) for preset, scenario_id in COLLAPSE_PRESETS.items()},
}

#: preset -> scenario id, for the live page's presets and the driver's names.
PRESET_OF: Dict[str, str] = {s.preset: s.id for s in SCENARIOS.values() if not s.control}
#: The driver's `--scenario` names, in order.
NAMES: Tuple[str, ...] = ("N", "ms-drop", "ms-delay", "cs-starve", "cs-partition")


def scenario(key: str) -> Scenario:
    """The scenario named `key`: an id (`MS-DROP`), a preset (`ms-drop`) or `N`; a ValueError otherwise."""
    text = str(key)
    if text in PRESET_OF:
        return SCENARIOS[PRESET_OF[text]]
    upper = text.upper()
    if upper in SCENARIOS:
        return SCENARIOS[upper]
    raise ValueError(f"scenario is one of {', '.join(NAMES)}, not {key!r}")


# ------------------------------------------------------------- configuration
def config(scn: Scenario) -> Dict[str, Any]:
    """
    `normal_config()`, for every scenario including the control.

    The disruption is applied by `CollapseFaults` from outside, never through
    the configuration: no key is added, and `interceptors=[]` stays as it is.
    """
    return normal_config()


# ----------------------------------------------------------------- schedule
def schedule(scn: Scenario) -> List[Dict[str, Any]]:
    """The one row of `scn` (`{tick, mechanism, fault_id, detail}`); empty for the control."""
    if scn.control:
        return []
    detail: Dict[str, Any] = {"holds_until": scn.holds_until}
    if scn.id == "MS-DROP":
        detail["rule"] = "every message dropped at delivery"
    elif scn.id == "MS-DELAY":
        detail.update({"delay_ticks": DELAY_TICKS, "routing_group": list(ROUTING_GROUP),
                       "routing_types": [t.value for t in ROUTING_TYPES],
                       "routing_operations": list(ROUTING_OPERATIONS)})
    elif scn.id == "CS-STARVE":
        detail.update({"stations": "all removed", "rescue": "none"})
    elif scn.id == "CS-PARTITION":
        detail.update({"scheduling_group": list(SCHEDULING_GROUP),
                       "resource_group": list(RESOURCE_GROUP)})
    return [{"tick": int(scn.start), "mechanism": scn.mechanism_name,
             "fault_id": scn.fault_id, "detail": detail}]


# --------------------------------------------------------------- definition
def definition(scn: Scenario) -> Dict[str, Any]:
    """Everything a run of `scn` is defined by, as one JSON-able dictionary (`definition.json`)."""
    return {
        "study": STUDY,
        "label": LABEL,
        "scenario": scn.as_dict(),
        "run_ticks": RUN_TICKS,
        "seeds": list(SEEDS),
        "start": START,
        "schedule": schedule(scn),
        "collapse": dict(COLLAPSE),
        "config": config(scn),
    }


def fingerprint(scn: Scenario) -> str:
    """sha256 over the canonical JSON of `definition(scn)`."""
    text = json.dumps(definition(scn), sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------ classification
def is_routing_related(message: Message) -> bool:
    """Whether M-S-DELAY holds `message` (see `ROUTING_GROUP`)."""
    if message.sender in ROUTING_GROUP or message.receiver in ROUTING_GROUP:
        return True
    if message.message_type in ROUTING_TYPES:
        return True
    if message.message_type is MessageType.ROBOT_COMMAND:
        return str((message.content or {}).get("operation", "")) in ROUTING_OPERATIONS
    return False


def partition_direction(message: Message) -> Optional[str]:
    """Which way `message` crosses the C-S-PARTITION, or None when it does not cross it."""
    if message.sender in SCHEDULING_GROUP and message.receiver in RESOURCE_GROUP:
        return SCHEDULING_TO_RESOURCE
    if message.sender in RESOURCE_GROUP and message.receiver in SCHEDULING_GROUP:
        return RESOURCE_TO_SCHEDULING
    return None


# ---------------------------------------------------------------- the rules
class DropAll:
    """The M-S-DROP rule: -1 for every message, counted."""

    def __init__(self) -> None:
        self.dropped = 0

    def __call__(self, message: Message) -> int:
        self.dropped += 1
        return -1


class DelayRouting:
    """The M-S-DELAY rule: `DELAY_TICKS` for a routing-related message, None otherwise."""

    def __init__(self, ticks: int = DELAY_TICKS) -> None:
        self.ticks = int(ticks)
        self.delayed = 0
        self.passed = 0

    def __call__(self, message: Message) -> Optional[int]:
        if is_routing_related(message):
            self.delayed += 1
            return self.ticks
        self.passed += 1
        return None


class Partition:
    """The C-S-PARTITION rule: -1 across the partition, None otherwise, counted per direction."""

    def __init__(self) -> None:
        self.dropped: Dict[str, int] = {SCHEDULING_TO_RESOURCE: 0, RESOURCE_TO_SCHEDULING: 0}
        self.passed = 0

    def __call__(self, message: Message) -> Optional[int]:
        direction = partition_direction(message)
        if direction is None:
            self.passed += 1
            return None
        self.dropped[direction] += 1
        return -1

    @property
    def dropped_total(self) -> int:
        return sum(self.dropped.values())


# --------------------------------------------------------------- the rescue
class NoRescue:
    """
    The rescue crew of C-S-STARVE: there is none.

    Replaces the ecosystem's `RecoveryService` with the same `step(tick)`
    interface. It reads `env.recovery_requests` exactly as the service does
    and honours nothing: each request is written down once as
    `recovery_refused` (category simulation, actor SIMULATION) and left in
    the queue, where it stays pending to the end. There is no method here
    that moves a robot, claims a station or changes a battery.
    """

    def __init__(self, world: Any) -> None:
        self.world = world
        self.refused = 0
        self._seen: set = set()

    def step(self, tick: int) -> None:
        env = self.world.env
        for request in list(getattr(env, "recovery_requests", []) or []):
            key = (request.robot_id, int(request.tick), request.requested_by)
            if key in self._seen:
                continue
            self._seen.add(key)
            self.refused += 1
            robot = self.world.fleet.get(request.robot_id)
            self.world.logger.emit(
                EventCategory.SIMULATION, "recovery_refused", tick=int(tick),
                actor="SIMULATION", target=request.robot_id,
                requested_by=request.requested_by, reason=NO_RESCUE_REASON,
                requested_at=int(request.tick),
                battery=round(float(robot.battery_level), 1) if robot is not None else None)

    @property
    def pending(self) -> List[Dict[str, Any]]:
        """The requests nobody will honour, as dictionaries."""
        env = self.world.env
        return [r.as_dict() for r in (getattr(env, "recovery_requests", []) or [])]

    def stats(self) -> Dict[str, int]:
        """The shape `RecoveryService.stats()` has; nothing is ever completed here."""
        return {"completed": 0, "refused": self.refused, "withdrawn": 0}

    def as_dict(self) -> Dict[str, Any]:
        return {"crew": "none", "reason": NO_RESCUE_REASON, **self.stats(),
                "pending": self.pending}


# --------------------------------------------------------------- the faults
class CollapseFaults:
    """
    The one scheduled fault of a scenario, applied as its tick comes.

    The shape of `operational.ScheduledFaults`: `before_tick(tick)` fires the
    row due at `tick`, once (idempotent); `faults_applied()` lists what was
    fired; `status()` is the live page's counters. Nothing removes, restores
    or reverts: the bus rule stays installed to the end of the run and
    `bus.release_held` is never called from here.
    """

    def __init__(self, eco: Any, scn: Scenario) -> None:
        self.eco = eco
        self.scenario = scn
        self.schedule: List[Dict[str, Any]] = list(schedule(scn))
        #: fault_id -> the detail written into its activation event.
        self.applied: Dict[str, Dict[str, Any]] = {}
        #: The bus rule installed, when the scenario has one.
        self.rule: Optional[Any] = None
        #: The rescue crew of C-S-STARVE (none), once installed.
        self.no_rescue: Optional[NoRescue] = None

    # ------------------------------------------------------------- the clock
    def before_tick(self, tick: int) -> List[str]:
        """Fire the row due at `tick`, once. Called by the driver before `eco.step()`."""
        fired: List[str] = []
        for row in self.schedule:
            if int(row["tick"]) != int(tick) or row["fault_id"] in self.applied:
                continue
            mechanism = row["mechanism"]
            if mechanism == MESSAGE_DROP:
                detail = self._message_drop()
            elif mechanism == MESSAGE_DELAY:
                detail = self._message_delay()
            elif mechanism == CHARGE_STARVATION:
                detail = self._charge_starvation()
            elif mechanism == MESSAGE_PARTITION:
                detail = self._message_partition()
            else:
                raise ValueError(f"unknown scenario mechanism {mechanism!r}")
            detail = {**row["detail"], **detail}
            self.applied[row["fault_id"]] = {"tick": int(tick), "mechanism": mechanism, **detail}
            self.eco.logger.emit(
                EventCategory.SIMULATION, "stress_fault_activated", tick=int(tick),
                actor="SIMULATION", mechanism=mechanism, fault_id=row["fault_id"],
                study=STUDY, scenario=self.scenario.id, **detail)
            fired.append(row["fault_id"])
        return fired

    # ------------------------------------------------------------ mechanisms
    def _message_drop(self) -> Dict[str, Any]:
        bus = self.eco.bus
        rule = DropAll()
        bus.delay_rule = rule
        self.rule = rule
        return {"rule_installed": True, "pending_at_activation": len(bus._pending),
                "dropped_so_far": rule.dropped}

    def _message_delay(self) -> Dict[str, Any]:
        bus = self.eco.bus
        rule = DelayRouting(DELAY_TICKS)
        bus.delay_rule = rule
        self.rule = rule
        return {"rule_installed": True, "pending_at_activation": len(bus._pending),
                "delayed_so_far": rule.delayed}

    def _charge_starvation(self) -> Dict[str, Any]:
        env = self.eco.env
        before = sorted(env.stations)
        occupied: Dict[str, Optional[str]] = {}
        for station_id in before:
            station = env.stations.pop(station_id, None)
            if station is not None:
                occupied[station_id] = station.occupant
        crew = NoRescue(self.eco.world)
        pending = list(getattr(env, "recovery_requests", []) or [])
        self.eco.recovery = crew
        self.no_rescue = crew
        return {"stations_before": before, "stations_after": sorted(env.stations),
                "removed": before, "occupied_at_removal": occupied,
                "rescue_crew": "none", "pending_requests_at_activation": len(pending)}

    def _message_partition(self) -> Dict[str, Any]:
        bus = self.eco.bus
        rule = Partition()
        bus.delay_rule = rule
        self.rule = rule
        return {"rule_installed": True, "pending_at_activation": len(bus._pending),
                "dropped_so_far": dict(rule.dropped)}

    # --------------------------------------------------------------- reports
    def faults_applied(self) -> List[Dict[str, Any]]:
        """Every fault fired so far, in activation order, for the measurement file."""
        return [{"fault_id": fault_id, **detail} for fault_id, detail in self.applied.items()]

    def status(self) -> Dict[str, Any]:
        """
        Where the scenario stands, for the live page: the scenario, when its
        row fired, and the counters (messages dropped, delayed, held on the
        bus now, rescues refused, charge points left). Plain attributes and
        copies, readable without the step lock.
        """
        eco = self.eco
        applied = self.applied.get(self.scenario.fault_id)
        rule = self.rule
        dropped = 0
        by_direction: Dict[str, int] = {}
        if isinstance(rule, DropAll):
            dropped = rule.dropped
        elif isinstance(rule, Partition):
            by_direction = dict(rule.dropped)
            dropped = rule.dropped_total
        delayed = rule.delayed if isinstance(rule, DelayRouting) else 0
        passed = getattr(rule, "passed", 0) if rule is not None else 0
        try:
            held_now = len(eco.bus._held)
        except Exception:
            held_now = 0
        return {
            "scenario": self.scenario.id,
            "preset": self.scenario.preset,
            "label": self.scenario.label,
            "mechanism": self.scenario.mechanism_name,
            "start": self.scenario.start,
            "applied_at": int(applied["tick"]) if applied else None,
            "rule_installed": eco.bus.delay_rule is not None and eco.bus.delay_rule is rule,
            "dropped": int(dropped),
            "dropped_by_direction": by_direction,
            "delayed": int(delayed),
            "delay_ticks": DELAY_TICKS if isinstance(rule, DelayRouting) else None,
            "passed": int(passed),
            "held_now": int(held_now),
            "recovery_refused": int(self.no_rescue.refused) if self.no_rescue is not None else 0,
            "rescue_crew": "none" if self.no_rescue is not None else "facility",
            "stations": sorted(eco.env.stations),
        }


# ----------------------------------------------------------- the collector
class ScenarioCollector(Collector):
    """
    `measure.Collector` with the scenario named in `measurement.json`.

    The rows, the totals and the per-route table are the shared collector's,
    unchanged, so a scenario run is judged on the same columns as a C2-NEAR
    run; `measurement()` names this study and carries the scenario's
    counters (`CollapseFaults.status()`) beside the totals.
    """

    def measurement(self, interrupted: bool = False) -> Dict[str, Any]:
        out = super().measurement(interrupted=interrupted)
        out.pop("experiment", None)
        out["study"] = STUDY
        out["label"] = LABEL
        scn = self.cond
        out["condition"] = scn.id
        out["scenario"] = scn.id
        out["preset"] = scn.preset
        out["scenario_label"] = scn.label
        status = getattr(self.stress, "status", None)
        out["counters"] = status() if callable(status) else None
        return out


__all__ = [
    "CHARGE_STARVATION", "CollapseFaults", "DELAY_TICKS", "DelayRouting", "DropAll", "LABEL",
    "MECHANISM_OF", "MESSAGE_DELAY", "MESSAGE_DROP", "MESSAGE_PARTITION", "NAMES",
    "NO_RESCUE_REASON", "NoRescue", "PRESET_OF", "Partition", "RESOURCE_GROUP",
    "RESOURCE_TO_SCHEDULING", "RESULTS_DIR", "ROUTING_GROUP", "ROUTING_OPERATIONS",
    "ROUTING_TYPES", "RUN_TICKS", "SCENARIOS", "SCHEDULING_GROUP", "SCHEDULING_TO_RESOURCE",
    "SEEDS", "START", "STUDY", "Scenario", "ScenarioCollector", "config", "definition",
    "fingerprint", "is_routing_related", "partition_direction", "scenario", "schedule",
]
