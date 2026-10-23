"""
P7-ONOFF: the Phase 7 ON-OFF agent attack on urgent parcels, as frozen by the
Phase 7 confirmation (exp_cascade, PROTOCOL_P7_CONFIRM, 2026-10-15).

Two experts alternate between two modes. OFF: they decide exactly as the
unmodified code does. ON: ROUTING answers WAIT to every blocked robot and
SCHEDULING gives every errand the lowest-battery robot, whatever their rules
said. The honest rule, the triage and the validation gate run and are recorded
as always; the displaced choice is then what the agent acts on. Cycle k is ON
for 300 + 100 k ticks and OFF for 300, from tick 1200 to 3800 (ON 1200-1500,
1800-2200, 2500-3000, 3300-3800); after 3800 the attack is OFF for good.

Workload `L40S20@1400to3400`: the Normal facility's arrival schedule, drawn
once per seed from the generator's own two streams, plus a hospital
consignment of 20 extra parcels whose arrival ticks are drawn once per seed
with a density rising from 1400 to 3400, each addressed to the hospital's town
(HRADEC) with the service word "urgent". Horizon 4400. No communication fault,
no charge loss: the attack is the only disturbance.

What the Phase 7 confirmation found on this configuration (1,000 fresh seeds,
11301-12300): in 7 runs an ON phase left two or three robots that held no
errand head to head in the charging zone; the honest rules, back in OFF, had
no move for them (ABANDON on a robot without an errand does nothing), and the
trap held to the horizon. The largest of those runs (seed 11977) was 1.90
times the expected maximum of the untrapped tail, below the registered factor
2: a statistically distinct extreme, **not** a confirmed Dragon-King. This
module reproduces that configuration in the live app; it replays no recorded
events and forces nothing. Every run shows its own outcome.

How it is installed, from outside the ecosystem, through seams that already
exist, with no change to `agents`, `simulation`, `communication`, `dkrmm` or
`policy`:

- the arrival schedule replaces `eco.generator.step` on that one instance
  (`ConsignmentArrivals`, the Phase 2-7 harness's matched schedule), so the
  parcels, their sizes, labels and ids are those of the frozen runs;
- the attack wraps the `decide` bound method of the two agent instances built
  for the run (`OnOffAttack`), the way the Phase 7 harness did; a displaced
  decision is an `attack_displaced` event, a phase change an `attack_phase`
  event. Nothing adaptive runs: the schedule is fixed and every displacement
  is decided by the seed.

Everything else is observation for the live page (`OnOffFaults.status()`):
the robots' blocked streaks and whether two task-less robots stand head to
head, the hospital parcels' state, the impact counters, and a final summary.
A robot is reported *trapped* once it has stood BLOCKED for `TRAP_TICKS`
consecutive ticks (the Phase 7 definition); nothing here moves a robot or
changes a parcel.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..agents.brain import Answer
from ..agents.subagents.sorting_subagents import POSTCODES, ROUTES, make_address, smudge
from ..communication.events import EventCategory
from ..config.settings import normal_config
from ..core.rng import mix
from ..environment.parcels import Parcel
from ..environment.zones import Zone
from ..simulation import generator as G

# ------------------------------------------------------------------ identity
STUDY = "P7-ONOFF"
LABEL = "ON-OFF, rules only"
PRESET = "p7-onoff"
SCENARIO_ID = "P7-ONOFF"
#: The frozen ids, as the Phase 7 artifacts name them.
SCENARIO6_ID = "L40S20@1400to3400-none-none-T4400"
ATTACK_ID = "A[ROUTING!+SCHEDULING!]on300off300d100p100@1200to3800"
#: Results of a kept run live here; `results/normal/` is never touched.
RESULTS_DIR = "results/p7_onoff"

# ------------------------------------------------------------------- the run
RUN_TICKS = 4400
#: The attack window and schedule.
ATTACK_START = 1200
ATTACK_END = 3800
ON_TICKS = 300
OFF_TICKS = 300
DRIFT = 100
P_DISPLACE = 1.0
AGENT_TOKENS: Tuple[str, ...] = ("ROUTING!", "SCHEDULING!")
AGENTS: Tuple[str, ...] = tuple(a.rstrip("!") for a in AGENT_TOKENS)
#: The hospital consignment.
CONSIGNMENT = 20
CONSIGNMENT_FROM = 1400
CONSIGNMENT_TO = 3400
HOSPITAL_ROUTE = "HRADEC"
HOSPITAL_SERVICE = "urgent"
#: A robot BLOCKED for this many consecutive ticks is trapped (Phase 7, E7c).
TRAP_TICKS = 300
#: Where the trap formed in every one of the 7 frozen cases.
TRAP_ZONE = Zone.CHARGING

#: The seeds of the Phase 7 confirmation and the seven trapped runs among them.
CONFIRMATION_SEEDS = (11301, 12300)
TRAPPED_SEEDS: Tuple[int, ...] = (11322, 11679, 11729, 11977, 12070, 12196, 12286)
#: The demonstration seed: the evaluation maximum of the confirmation
#: (U_Jbar 1505, O/E 1.90; R1 and R2 trapped at (14,12)-(13,12) from tick 1210).
DEMO_SEED = 11977
#: What the seed picker offers: the demonstration seed, three more trapped
#: seeds, and two untrapped confirmation seeds (near the population median).
SEED_OPTIONS: Tuple[Tuple[int, str], ...] = (
    (11977, "11977 · trapped in the frozen run (demonstration)"),
    (12070, "12070 · trapped (three robots)"),
    (12196, "12196 · trapped"),
    (11322, "11322 · trapped from the second ON phase"),
    (11996, "11996 · not trapped (median run)"),
    (12057, "12057 · not trapped (median run)"),
)

TWO64 = float(2 ** 64)
MECHANISM = "onoff_attack"


# ------------------------------------------------------------- the schedule
def phases(start: int = ATTACK_START, end: int = ATTACK_END, on: int = ON_TICKS,
           off: int = OFF_TICKS, drift: int = DRIFT) -> List[Dict[str, int]]:
    """The ON phases of the schedule: `{k, on_from, on_to, off_to}` (ends exclusive, clipped to `end`)."""
    out: List[Dict[str, int]] = []
    t, k = start, 0
    while t < end:
        on_to = min(end, t + on + k * drift)
        off_to = min(end, on_to + off)
        out.append({"k": k, "on_from": t, "on_to": on_to, "off_to": off_to})
        t = off_to
        k += 1
    return out


PHASES: List[Dict[str, int]] = phases()


def is_on(tick: int, start: int = ATTACK_START, end: int = ATTACK_END, on: int = ON_TICKS,
          off: int = OFF_TICKS, drift: int = DRIFT) -> bool:
    """Whether the attack is ON at `tick` (the Phase 7 harness's `OnOffAttack.is_on`, verbatim)."""
    if tick < start or tick >= end:
        return False
    t = tick - start
    k = 0
    while True:
        on_k = on + k * drift
        if t < on_k:
            return True
        t -= on_k
        if t < off:
            return False
        t -= off
        k += 1


def phase_at(tick: int) -> Dict[str, Any]:
    """The phase at `tick`: ON/OFF, since when, until when, and the cycle."""
    if tick < ATTACK_START:
        return {"phase": "OFF", "since": 0, "until": ATTACK_START, "k": None, "before_window": True}
    if tick >= ATTACK_END:
        return {"phase": "OFF", "since": ATTACK_END, "until": None, "k": None, "after_window": True}
    for ph in PHASES:
        if ph["on_from"] <= tick < ph["on_to"]:
            return {"phase": "ON", "since": ph["on_from"], "until": ph["on_to"], "k": ph["k"]}
        if ph["on_to"] <= tick < ph["off_to"]:
            nxt = ph["off_to"] if ph["off_to"] < ATTACK_END else None
            return {"phase": "OFF", "since": ph["on_to"], "until": nxt, "k": ph["k"]}
    return {"phase": "OFF", "since": ATTACK_END, "until": None, "k": None}


# --------------------------------------------------------- arrival schedule
@dataclass(frozen=True)
class Offered:
    """One offered arrival of the predetermined schedule (1-based, initial parcels included)."""

    index: int
    tick: int
    size_roll: float
    label_roll: float

    @property
    def parcel_id(self) -> str:
        return f"P-{self.index:04d}"


def true_route(parcel_id: str, seed: int, label_roll: float) -> Optional[str]:
    """The route the parcel's address names (None when it is off-network)."""
    if G.UNREADABLE_RATE <= label_roll < G.UNREADABLE_RATE + G.OFF_NETWORK_RATE:
        return None
    return ROUTES[mix(seed, f"address:{parcel_id}") % len(ROUTES)]


def build_schedule(seed: int, ticks: int, mean_interval: float, initial: int) -> List[Offered]:
    """
    The generator's arrivals, drawn once from its two streams in the order it
    draws them when every arrival is accepted: the initial dock (size, label),
    then one arrival test per tick and, if offered, its size and label rolls.
    """
    arrivals = random.Random(mix(int(seed), "__arrivals__"))
    labels = random.Random(mix(int(seed), "__labels__"))
    out: List[Offered] = []
    for _ in range(initial):
        out.append(Offered(len(out) + 1, 0, arrivals.random(), labels.random()))
    for tick in range(1, int(ticks) + 1):
        if arrivals.random() < 1.0 / mean_interval:
            out.append(Offered(len(out) + 1, tick, arrivals.random(), labels.random()))
    return out


def consignment_ticks(seed: int, k: int = CONSIGNMENT, t0: int = CONSIGNMENT_FROM,
                      t1: int = CONSIGNMENT_TO) -> List[int]:
    """The consignment's arrival ticks: density rising linearly from t0 to t1, drawn once per seed."""
    rng = random.Random(mix(int(seed), "consignment"))
    return sorted(int(round(t0 + (t1 - t0) * (rng.random() ** 0.5))) for _ in range(k))


def schedule_hash(schedule: List[Offered]) -> str:
    text = json.dumps([[o.index, o.tick, round(o.size_roll, 15), round(o.label_roll, 15)]
                       for o in schedule])
    return hashlib.sha256(text.encode()).hexdigest()


class ConsignmentArrivals:
    """
    Drives `eco.generator` from the predetermined schedule merged with the
    hospital consignment, renumbered in arrival order (the Phase 6/7
    harness's `MatchedArrivals` + `ConsignmentArrivals`, kept verbatim so a
    seed's parcels are the frozen run's). Several offers may share a tick. A
    refused offer (dock full) logs `arrival_refused` as the generator does and
    still consumes its id, so ids stay aligned with the frozen run.
    """

    def __init__(self, seed: int, ticks: int, mean_interval: float, initial: int) -> None:
        self.seed = int(seed)
        base = [(o.tick, 0, o.size_roll, o.label_roll, False)
                for o in build_schedule(seed, ticks, mean_interval, initial)]
        extra = [(t, 1, 0.5, 0.5, True) for t in consignment_ticks(seed)]
        merged = sorted(base + extra, key=lambda x: (x[0], x[1]))
        self.schedule = [Offered(i + 1, t, sz, lb) for i, (t, _, sz, lb, _) in enumerate(merged)]
        self.consignment: List[str] = [f"P-{i + 1:04d}" for i, m in enumerate(merged) if m[4]]
        self._is_cons = set(self.consignment)
        self.by_tick: Dict[int, List[Offered]] = {}
        for o in self.schedule:
            if o.tick > 0:
                self.by_tick.setdefault(o.tick, []).append(o)
        self.tick_of: Dict[str, int] = {o.parcel_id: o.tick for o in self.schedule}
        self.routes: Dict[str, Optional[str]] = {
            o.parcel_id: (HOSPITAL_ROUTE if o.parcel_id in self._is_cons
                          else true_route(o.parcel_id, self.seed, o.label_roll))
            for o in self.schedule}
        self.offered = 0
        self.accepted = 0
        self.refused = 0
        self.refused_ids: List[str] = []
        self.gen: Any = None

    def install(self, eco: Any) -> "ConsignmentArrivals":
        gen = eco.generator
        expected = [o.parcel_id for o in self.schedule if o.tick == 0]
        present = sorted(pid for pid in eco.env.parcels)
        if present != expected or gen.created != len(expected):
            raise RuntimeError(f"initial dock differs from schedule: {present} vs {expected}")
        self.gen = gen
        gen.step = self.step          # this instance only
        return self

    def _address(self, parcel_id: str, roll: float) -> str:
        gen = self.gen
        if parcel_id in self._is_cons:
            return f"{HOSPITAL_ROUTE.title()} {POSTCODES[HOSPITAL_ROUTE]}, {HOSPITAL_SERVICE}"
        if roll < G.UNREADABLE_RATE:
            gen.damaged += 1
            heavy = (roll / G.UNREADABLE_RATE) < G.HEAVY_SHARE
            return smudge(make_address(parcel_id, self.seed), heavy=heavy)
        if roll < G.UNREADABLE_RATE + G.OFF_NETWORK_RATE:
            gen.misaddressed += 1
            elsewhere = G.OFF_NETWORK[int(roll * 10 ** 6) % len(G.OFF_NETWORK)]
            return make_address(parcel_id, self.seed, city=elsewhere)
        return make_address(parcel_id, self.seed)

    def _offer(self, tick: int, offer: Offered) -> List[Parcel]:
        gen = self.gen
        self.offered += 1
        parcel_id = gen.ids.next("P")
        if parcel_id != offer.parcel_id:
            raise RuntimeError(f"id drift: {parcel_id} vs {offer.parcel_id}")
        cell = gen._free_dock_cell()
        on_dock = len(gen.env.parcels_in(Zone.INTAKE))
        if cell is None or on_dock >= gen.max_on_dock:
            gen.refused += 1
            self.refused += 1
            self.refused_ids.append(parcel_id)
            gen.logger.emit(EventCategory.PARCEL, "arrival_refused", tick=tick,
                            actor="INTAKE_DOCK", reason="dock full", on_dock=on_dock,
                            refused_total=gen.refused)
            return []
        size = G.SIZE_WEIGHTS[-1][0]
        cumulative = 0.0
        for candidate, weight in G.SIZE_WEIGHTS:
            cumulative += weight
            if offer.size_roll <= cumulative:
                size = candidate
                break
        parcel = Parcel(parcel_id=parcel_id, origin=Zone.INTAKE, size=size,
                        address=self._address(parcel_id, offer.label_roll))
        parcel.stamp("arrived", tick)
        parcel.record(tick, "INTAKE_DOCK", "arrived", cell=cell.as_dict())
        gen.env.add_parcel(parcel, at=cell)
        gen.created += 1
        self.accepted += 1
        return [parcel]

    def step(self, tick: int, seed: int) -> List[Parcel]:
        out: List[Parcel] = []
        for offer in self.by_tick.get(int(tick)) or []:
            out.extend(self._offer(int(tick), offer))
        return out


# -------------------------------------------------------------- the attack
@dataclass
class AttackSpec:
    """The ON-OFF schedule and its targets; `id` is the frozen attack id."""

    agent_tokens: List[str]
    start: int
    end: int
    on: int
    off: int
    drift: int = 0
    p: float = 1.0
    kinds: Optional[Dict[str, List[str]]] = None
    agents: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.agents = [a.rstrip("!") for a in self.agent_tokens]

    @property
    def id(self) -> str:
        a = "+".join(self.agent_tokens)
        return f"A[{a}]on{self.on}off{self.off}d{self.drift}p{int(round(self.p * 100))}@{self.start}to{self.end}"

    @property
    def floor_targets(self) -> set:
        """The agents whose policy applies to every errand, not only urgent ones ("!")."""
        return {a.rstrip("!") for a in self.agent_tokens if a.endswith("!")}


def frozen_spec() -> AttackSpec:
    spec = AttackSpec(agent_tokens=list(AGENT_TOKENS), start=ATTACK_START, end=ATTACK_END,
                      on=ON_TICKS, off=OFF_TICKS, drift=DRIFT, p=P_DISPLACE)
    assert spec.id == ATTACK_ID, spec.id
    return spec


POLICY_KINDS: Dict[str, List[str]] = {
    "INTAKE": ["accept_parcel"], "SORTING": ["classify_destination"], "DISPATCH": ["release_parcel"],
    "SCHEDULING": ["choose_next_task", "choose_robot"], "RESOURCE": ["battery_sufficient"],
    "ROUTING": ["resolve_block"], "PLANNER": ["release_work"],
}


class OnOffAttack:
    """
    The Phase 7 harness's `OnOffAttack`, verbatim in what it does: the policies
    of every agent are kept so the frozen id means what it meant, and the
    frozen spec reaches only ROUTING's `resolve_block` and SCHEDULING's two
    decisions, on every errand. `install()` wraps the `decide` bound method of
    the selected agent instances; `before_tick` emits the `attack_phase` events.
    """

    def __init__(self, eco: Any, seed: int, spec: AttackSpec) -> None:
        self.eco, self.seed, self.spec = eco, int(seed), spec
        self.displaced = 0
        self.considered = 0
        self.on_ticks = 0
        self.phase_log: List[Dict[str, Any]] = []
        self._last_phase: Optional[bool] = None
        self._orig: Dict[str, Callable] = {}
        self.by_agent: Dict[str, int] = {}
        self.by_decision: Dict[str, int] = {}
        self.touched_parcels: set = set()
        self.all_targets = spec.floor_targets
        self.installed = False

    # ----------------------------------------------------------------- schedule
    def is_on(self, tick: int) -> bool:
        s = self.spec
        return is_on(int(tick), s.start, s.end, s.on, s.off, s.drift)

    def before_tick(self, tick: int) -> None:
        on = self.is_on(tick)
        if on:
            self.on_ticks += 1
        if on != self._last_phase:
            self._last_phase = on
            self.phase_log.append({"tick": int(tick), "phase": "ON" if on else "OFF"})
            self.eco.logger.emit(EventCategory.SIMULATION, "attack_phase", tick=int(tick), actor="ATTACK",
                                 phase="ON" if on else "OFF", agents=list(self.spec.agents), attack=self.spec.id)

    # ----------------------------------------------------------------- helpers
    def _parcel(self, pid: Optional[str]):
        return self.eco.env.parcels.get(pid) if pid else None

    def _is_urgent_parcel(self, pid: Optional[str]) -> bool:
        p = self._parcel(pid)
        if p is None:
            return False
        if getattr(getattr(p, "priority", None), "value", None) == "URGENT":
            return True
        return "urgent" in str(getattr(p, "address", "")).lower()

    def _task_urgent(self, task_id: Optional[str]) -> bool:
        t = self.eco.tasks.get(task_id) if task_id else None
        if t is None:
            return False
        if getattr(t.priority, "value", None) == "URGENT":
            return True
        return self._is_urgent_parcel(t.parcel_id)

    def _robot_task_urgent(self, robot_id: Optional[str]) -> bool:
        r = self.eco.fleet.get(robot_id) if robot_id else None
        if r is None:
            return False
        tid = getattr(r, "current_task", None) or getattr(r, "task_id", None)
        if tid is None:
            tid = getattr(getattr(r, "errand", None), "task_id", None)
        return self._task_urgent(tid) or self._is_urgent_parcel(getattr(r, "carrying", None))

    # ----------------------------------------------------------------- policies
    def displaced_choice(self, agent_id: str, kind: str, options: Sequence[Any], correlation_id: str,
                         facts: Dict[str, Any], honest: Any) -> Optional[Any]:
        opts = list(options)
        if agent_id == "INTAKE" and kind == "accept_parcel":
            return "REFUSE" if self._is_urgent_parcel(correlation_id) and "REFUSE" in opts else None
        if agent_id == "SORTING" and kind == "classify_destination":
            urgent = str(facts.get("priority", "")) == "URGENT" or self._is_urgent_parcel(correlation_id)
            return "TEMPORARY_STORAGE" if urgent and "TEMPORARY_STORAGE" in opts else None
        if agent_id == "DISPATCH" and kind == "release_parcel":
            urgent = str(facts.get("priority", "")) == "URGENT" or self._is_urgent_parcel(correlation_id)
            return "HOLD" if urgent and "HOLD" in opts else None
        if agent_id == "SCHEDULING" and kind == "choose_next_task":
            slack = facts.get("slack") or {}
            non_urgent = [t for t in opts if not self._task_urgent(t)]
            pool = non_urgent or opts
            if not any(self._task_urgent(t) for t in opts):
                return None                     # nothing urgent to ignore
            return max(pool, key=lambda t: (float(slack.get(t, 1e9) if slack.get(t) is not None else 1e9), str(t)))
        if agent_id == "SCHEDULING" and kind == "choose_robot":
            urgent = str(facts.get("priority", "")) == "URGENT" or self._task_urgent(correlation_id) \
                or self._is_urgent_parcel(correlation_id)
            if not urgent and "SCHEDULING" not in self.all_targets:
                return None
            about = facts.get("robots") or {}
            return min(opts, key=lambda r: (float((about.get(r) or {}).get("battery", 100) or 100),
                                            -float((about.get(r) or {}).get("distance", 0) or 0), str(r)))
        if agent_id == "RESOURCE" and kind == "battery_sufficient":
            urgent = self._task_urgent(correlation_id) or self._is_urgent_parcel(correlation_id) \
                or self._robot_task_urgent(facts.get("robot"))
            return "REFUSE" if urgent and "REFUSE" in opts else None
        if agent_id == "ROUTING" and kind == "resolve_block":
            target = "ROUTING" in self.all_targets or self._robot_task_urgent(facts.get("robot"))
            return "WAIT" if target and "WAIT" in opts else None
        if agent_id == "PLANNER" and kind == "release_work":
            waiting_urgent = any(self._is_urgent_parcel(pid) for pid in self.eco.env.parcels)
            return 0 if waiting_urgent and 0 in opts else None
        return None

    # ----------------------------------------------------------------- install
    def install(self) -> "OnOffAttack":
        if "SORTING" in self.spec.agents and "SUB-DESTINATION" in getattr(self.eco, "subagents", {}):
            sub = self.eco.subagents["SUB-DESTINATION"]
            orig_perform = sub.perform

            def perform_wrapped(message, _orig=orig_perform):
                out = _orig(message)
                tick = int(self.eco.world.tick)
                if not (isinstance(out, dict) and out.get("settled") == "DISPATCH" and out.get("via") == "SORTING"
                        and self.is_on(tick)):
                    return out
                self.considered += 1
                pid = out.get("parcel_id", "")
                if mix(self.seed, f"attack:SUB-DESTINATION:{pid}:{tick}") / TWO64 >= self.spec.p:
                    return out
                self.displaced += 1
                self.by_agent["SORTING"] = self.by_agent.get("SORTING", 0) + 1
                if pid:
                    self.touched_parcels.add(pid)
                self.eco.logger.emit(EventCategory.AGENT, "attack_displaced", tick=tick, actor="SORTING",
                                     correlation_id=pid, decision="settle_destination", honest="DISPATCH via SORTING",
                                     displaced="SORTING", call_id=f"SUB-DESTINATION:{pid}:{tick}", attack=self.spec.id)
                new = dict(out)
                new.update(settled="SORTING", reason="ON-OFF attack: urgent parcel sorted like any other")
                new.pop("via", None)
                new["_text"] = f"{pid} goes to SORTING first."
                return new
            sub.perform = perform_wrapped
        for agent_id in self.spec.agents:
            agent = self.eco.agents[agent_id]
            kinds = (self.spec.kinds or {}).get(agent_id) or POLICY_KINDS[agent_id]
            orig = agent.decide
            self._orig[agent_id] = orig
            self.by_agent[agent_id] = 0

            def wrapped(kind, prompt, options=(), correlation_id="", deferral=None,
                        _agent=agent, _orig=orig, _kinds=tuple(kinds), _aid=agent_id, **facts):
                answer = _orig(kind, prompt, options, correlation_id, deferral, **facts)
                tick = int(_agent.tick)
                if kind not in _kinds or not self.is_on(tick):
                    return answer
                self.considered += 1
                decision_id = f"{_aid}:{kind}:{tick}:{_agent._decisions_made}"
                if mix(self.seed, f"attack:{decision_id}") / TWO64 >= self.spec.p:
                    return answer
                new = self.displaced_choice(_aid, kind, options, correlation_id, dict(facts), answer.choice)
                if new is None or str(new) == str(answer.choice):
                    return answer
                self.displaced += 1
                self.by_agent[_aid] += 1
                self.by_decision[kind] = self.by_decision.get(kind, 0) + 1
                pid = correlation_id if str(correlation_id).startswith("P-") else None
                if pid is None and str(correlation_id).startswith("T-"):
                    t = self.eco.tasks.get(correlation_id)
                    pid = getattr(t, "parcel_id", None)
                if pid is None and kind == "choose_next_task":
                    t = self.eco.tasks.get(str(new))
                    pid = getattr(t, "parcel_id", None)
                if pid:
                    self.touched_parcels.add(pid)
                self.eco.logger.emit(EventCategory.AGENT, "attack_displaced", tick=tick, actor=_aid,
                                     correlation_id=correlation_id, decision=kind, honest=str(answer.choice),
                                     displaced=str(new), call_id=decision_id, attack=self.spec.id)
                return Answer(new, f"ON-OFF attack: displaced from {answer.choice}", source="attack:on", confidence=1.0)
            agent.decide = wrapped
        self.installed = True
        return self

    def status(self) -> Dict[str, Any]:
        return {"attack": self.spec.id, "agents": list(self.spec.agents), "considered": self.considered,
                "displaced": self.displaced, "by_agent": dict(self.by_agent),
                "by_decision": dict(self.by_decision), "on_ticks": self.on_ticks,
                "phases": list(self.phase_log), "touched_parcels": sorted(self.touched_parcels)}


# ------------------------------------------------------------- the scenario
def config() -> Dict[str, Any]:
    """`normal_config()`: the attack and the consignment are applied beside the run, never by the configuration."""
    return normal_config()


def definition(seed: Optional[int] = None) -> Dict[str, Any]:
    """Everything a run is defined by, as one JSON-able dictionary."""
    return {"study": STUDY, "label": LABEL, "scenario": SCENARIO_ID, "preset": PRESET,
            "scenario6_id": SCENARIO6_ID, "attack_id": ATTACK_ID, "run_ticks": RUN_TICKS,
            "attack": {"agents": list(AGENT_TOKENS), "start": ATTACK_START, "end": ATTACK_END,
                       "on": ON_TICKS, "off": OFF_TICKS, "drift": DRIFT, "p": P_DISPLACE,
                       "phases": PHASES},
            "consignment": {"k": CONSIGNMENT, "from": CONSIGNMENT_FROM, "to": CONSIGNMENT_TO,
                            "route": HOSPITAL_ROUTE, "service": HOSPITAL_SERVICE},
            "trap_ticks": TRAP_TICKS, "seed": seed, "config": config()}


def fingerprint() -> str:
    """sha256 over the canonical JSON of `definition()` (seed excluded)."""
    text = json.dumps(definition(), sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def schedule_rows() -> List[Dict[str, Any]]:
    """The schedule as the live page's strip reads it: one row per ON phase."""
    return [{"tick": ph["on_from"], "mechanism": MECHANISM, "fault_id": f"ON-{ph['k'] + 1}",
             "detail": {"on_to": ph["on_to"], "off_to": ph["off_to"], "agents": list(AGENTS)}}
            for ph in PHASES]


# ------------------------------------------------------------- observation
@dataclass
class RobotWatch:
    """One robot's blocked streak, as the page reports it; observation only."""

    robot: str
    streak: int = 0
    streak_start: Optional[int] = None
    blocked_by: Optional[str] = None
    decisions: Dict[str, int] = field(default_factory=dict)   # ROUTING's choices during the streak
    displaced: int = 0                                        # WAITs displaced during the streak
    trapped_since: Optional[int] = None                       # first tick the streak reached TRAP_TICKS
    task_at_trap: Optional[str] = None
    cell_at_trap: Optional[Tuple[int, int]] = None

    def reset(self) -> None:
        self.streak = 0
        self.streak_start = None
        self.blocked_by = None
        self.decisions = {}
        self.displaced = 0
        self.trapped_since = None
        self.task_at_trap = None
        self.cell_at_trap = None


class OnOffFaults:
    """
    The scenario beside the ecosystem, in the shape of `CollapseFaults`:
    `before_tick(tick)` (the attack's phase bookkeeping; the arrivals and the
    attack themselves are installed at construction, before the first tick),
    `faults_applied()`, `status()`. It also watches the run for the live page:
    the robots' blocked streaks, the hospital parcels, the impact counters.
    Nothing here changes the run after construction.
    """

    def __init__(self, eco: Any, seed: int, ticks: int = RUN_TICKS) -> None:
        self.eco = eco
        self.seed = int(seed)
        self.horizon = int(ticks)
        self.spec = frozen_spec()
        cfg = eco.config
        self.arrivals = ConsignmentArrivals(
            self.seed, self.horizon, mean_interval=float(cfg.get("arrival_interval", 40.0)),
            initial=int(cfg.get("initial_parcels", 8))).install(eco)
        self.attack = OnOffAttack(eco, self.seed, self.spec).install()
        self.schedule: List[Dict[str, Any]] = schedule_rows()
        self.applied: Dict[str, Dict[str, Any]] = {}
        self.watch: Dict[str, RobotWatch] = {r.robot_id: RobotWatch(r.robot_id) for r in eco.fleet.all()}
        self.blocked_robot_ticks = 0
        self.blocked_robot_ticks_in_attack = 0
        self._observed_tick = -1
        #: Every blocked streak that reached TRAP_TICKS, in the order they did:
        #: `{robot, start, trapped_since, end (None while it lasts), cell, task,
        #: blocked_by}`; the live page's trap is the ongoing ones.
        self.episodes: List[Dict[str, Any]] = []
        self._last_routing_robot: Optional[str] = None
        self.eco.logger.subscribe(self._on_event)

    # ------------------------------------------------------------- the clock
    def before_tick(self, tick: int) -> List[str]:
        """The attack's phase bookkeeping for the coming tick; the state of the tick before is observed first."""
        tick = int(tick)
        self.observe(tick - 1)
        self.attack.before_tick(tick)
        fired: List[str] = []
        for row in self.schedule:
            if int(row["tick"]) == tick and row["fault_id"] not in self.applied:
                self.applied[row["fault_id"]] = {"tick": tick, "mechanism": MECHANISM, **row["detail"]}
                fired.append(row["fault_id"])
        return fired

    # ------------------------------------------------------------- the watch
    def _blocked_by(self, robot: Any) -> Optional[str]:
        route = getattr(robot, "_route", None) or []
        if len(route) > 1:
            try:
                return self.eco.env.occupied_by_robot(route[1], excluding=robot.robot_id)
            except Exception:
                return None
        return None

    def observe(self, tick: int) -> None:
        """Read the robots as they stand after `tick`; idempotent per tick."""
        tick = int(tick)
        if tick <= self._observed_tick or tick < 0:
            return
        self._observed_tick = tick
        in_attack = ATTACK_START <= tick < ATTACK_END
        for robot in self.eco.fleet.all():
            w = self.watch[robot.robot_id]
            if robot.status.value == "BLOCKED":
                self.blocked_robot_ticks += 1
                if in_attack:
                    self.blocked_robot_ticks_in_attack += 1
                if w.streak == 0:
                    w.streak_start = tick
                w.streak += 1
                w.blocked_by = self._blocked_by(robot)
                if w.streak >= TRAP_TICKS and w.trapped_since is None:
                    w.trapped_since = tick
                    w.task_at_trap = robot.current_task or None
                    w.cell_at_trap = (robot.current_position.x, robot.current_position.y)
                    zone = self.eco.env.zone_at(robot.current_position)
                    self.episodes.append({"robot": robot.robot_id, "start": w.streak_start,
                                          "trapped_since": tick, "end": None,
                                          "cell": list(w.cell_at_trap), "zone": zone.value if zone else None,
                                          "task": w.task_at_trap, "no_errand": w.task_at_trap is None,
                                          "blocked_by": w.blocked_by})
            else:
                if w.trapped_since is not None:
                    for ep in self.episodes:
                        if ep["robot"] == robot.robot_id and ep["end"] is None:
                            ep["end"] = tick
                            ep["routing_choices"] = dict(w.decisions)
                            ep["displaced_waits"] = int(w.displaced)
                w.reset()

    def _on_event(self, event: Any) -> None:
        """ROUTING's answers and the displaced WAITs, counted per robot while it is blocked (observation)."""
        try:
            topic = event.topic
            detail = event.detail or {}
            if topic == "decision" and event.actor == "ROUTING" and detail.get("decision") == "resolve_block":
                facts = detail.get("facts") or {}
                robot = str(facts.get("robot"))
                self._last_routing_robot = robot
                w = self.watch.get(robot)
                if w is not None and w.streak > 0:
                    choice = str(detail.get("choice"))
                    w.decisions[choice] = w.decisions.get(choice, 0) + 1
            elif (topic == "attack_displaced" and event.actor == "ROUTING"
                  and detail.get("decision") == "resolve_block"):
                # The displaced answer follows the honest decision event of the
                # same call, which named the robot.
                w = self.watch.get(self._last_routing_robot or "")
                if w is not None and w.streak > 0:
                    w.displaced += 1
        except Exception:
            pass   # an observer never stops a tick

    # -------------------------------------------------------------- reports
    def faults_applied(self) -> List[Dict[str, Any]]:
        return [{"fault_id": fault_id, **detail} for fault_id, detail in self.applied.items()]

    def head_to_head(self) -> List[List[str]]:
        """Pairs of robots each blocked by the other, as they stand now."""
        pairs: List[List[str]] = []
        for a, w in self.watch.items():
            b = w.blocked_by
            if b and self.watch.get(b) is not None and self.watch[b].blocked_by == a and a < b:
                pairs.append([a, b])
        return pairs

    def robots(self) -> List[Dict[str, Any]]:
        out = []
        for robot in self.eco.fleet.all():
            w = self.watch[robot.robot_id]
            pos = robot.current_position
            zone = self.eco.env.zone_at(pos)
            out.append({
                "robot": robot.robot_id, "status": robot.status.value,
                "cell": [pos.x, pos.y], "zone": zone.value if zone is not None else None,
                "task": robot.current_task or None, "carrying": robot.carrying or None,
                "battery": round(float(robot.battery_level), 1),
                "blocked_for": int(w.streak), "blocked_since": w.streak_start,
                "blocked_by": w.blocked_by,
                "trapped": w.trapped_since is not None, "trapped_since": w.trapped_since,
                "routing_choices_in_streak": dict(w.decisions),
                "no_errand": not (robot.current_task or None),
            })
        return out

    def hospital(self) -> List[Dict[str, Any]]:
        """Every consignment parcel: not yet arrived, refused at the dock, in the building (where, with whom), or departed."""
        tick = int(self.eco.world.tick)
        env = self.eco.env
        rows = []
        for pid in self.arrivals.consignment:
            due = self.arrivals.tick_of.get(pid)
            parcel = env.parcel(pid) if hasattr(env, "parcel") else env.parcels.get(pid)
            if parcel is None:
                if pid in self.arrivals.refused_ids:
                    rows.append({"id": pid, "arrives": due, "state": "REFUSED_AT_DOCK", "zone": None,
                                 "robot": None, "due_by": None, "dispatched": None, "late": None})
                else:
                    rows.append({"id": pid, "arrives": due, "state": "NOT_YET_ARRIVED", "zone": None,
                                 "robot": None, "due_by": None, "dispatched": None, "late": None})
                continue
            left = parcel.timestamps.get("dispatched")
            zone = None
            if parcel.position is not None:
                z = env.zone_at(parcel.position)
                zone = z.value if z is not None else None
            rows.append({"id": pid, "arrives": parcel.timestamps.get("arrived", due),
                         "state": parcel.status.value, "zone": zone,
                         "robot": parcel.assigned_robot or None, "due_by": parcel.due_by,
                         "dispatched": left, "late": bool(parcel.late_at(tick)),
                         "in_building": pid in env.parcels})
        return rows

    def impact(self) -> Dict[str, Any]:
        tick = int(self.eco.world.tick)
        env = self.eco.env
        hosp = self.hospital()
        in_building = [h for h in hosp if h.get("in_building")]
        dispatched = [h for h in hosp if h["dispatched"] is not None]
        standard_dispatched = int(env.dispatched_count) - len(dispatched)
        robots = self.robots()
        blocked_now = sum(1 for r in robots if r["status"] == "BLOCKED")
        trapped_now = sum(1 for r in robots if r["trapped"])
        return {
            "tick": tick,
            "robots_blocked": blocked_now,
            "robots_trapped": trapped_now,
            "robots_available": len(robots) - trapped_now,
            "robots_total": len(robots),
            "blocked_robot_ticks": int(self.blocked_robot_ticks),
            "blocked_robot_ticks_in_window": int(self.blocked_robot_ticks_in_attack),
            "hospital_total": len(hosp),
            "hospital_arrived": sum(1 for h in hosp if h["state"] not in ("NOT_YET_ARRIVED", "REFUSED_AT_DOCK")),
            "hospital_awaiting": len(in_building),
            "hospital_dispatched": len(dispatched),
            "hospital_dispatched_late": sum(1 for h in dispatched if h["late"]),
            "hospital_missed_promise": sum(1 for h in hosp if h["late"]),
            "hospital_refused": sum(1 for h in hosp if h["state"] == "REFUSED_AT_DOCK"),
            "hospital_not_yet": sum(1 for h in hosp if h["state"] == "NOT_YET_ARRIVED"),
            "standard_dispatched": standard_dispatched,
            "dispatched_total": int(env.dispatched_count),
            "parcels_in_building": len(env.parcels),
            "dock_refused": int(self.arrivals.refused),
            "arrivals_offered": int(self.arrivals.offered),
        }

    def trap_report(self) -> Dict[str, Any]:
        """
        The trap as it stands: every blocked streak that reached TRAP_TICKS
        (`episodes`), the ongoing ones (`robots`), when the earliest of them
        began, the phase it formed in, the OFF phases it has lasted through,
        and whether it outlived the attack window. A streak that ended is
        kept in `episodes` with its end tick, so a trap that cleared is
        reported as such and never as persistent.
        """
        tick = int(self.eco.world.tick)
        episodes = []
        for ep in self.episodes:
            row = dict(ep)
            if row["end"] is None:
                w = self.watch[row["robot"]]
                row["routing_choices"] = dict(w.decisions)
                row["displaced_waits"] = int(w.displaced)
                row["blocked_by"] = w.blocked_by
                row["ticks"] = tick - int(row["start"])
            else:
                row["ticks"] = int(row["end"]) - int(row["start"])
            episodes.append(row)
        ongoing = [ep for ep in episodes if ep["end"] is None]
        if not episodes:
            return {"occurred": False, "persistent": False, "robots": [], "episodes": [],
                    "candidates": self.head_to_head(),
                    "longest_streak": max((w.streak for w in self.watch.values()), default=0)}
        current = ongoing or [max(episodes, key=lambda e: e["ticks"])]
        start = min(int(ep["start"]) for ep in current)
        end = None if ongoing else max(int(ep["end"]) for ep in current)
        until = tick if end is None else end
        off_phases_crossed = [ph["k"] + 1 for ph in PHASES if start < ph["on_to"] <= until]
        return {"occurred": True, "persistent": bool(ongoing), "started": start, "ended": end,
                "robots": [ep["robot"] for ep in current],
                "no_errand": all(ep["no_errand"] for ep in current),
                "zone": current[0].get("zone"),
                "formed_in": phase_at(start),
                "off_phases_crossed": off_phases_crossed,
                "survived_off_phase": bool(off_phases_crossed),
                "survived_window_end": until >= ATTACK_END and bool(ongoing),
                "ticks_so_far": until - start,
                "episodes": episodes,
                "candidates": self.head_to_head()}

    def summary(self) -> Dict[str, Any]:
        """The final run summary (meaningful at the horizon; readable at any tick)."""
        imp = self.impact()
        trap = self.trap_report()
        return {"tick": imp["tick"], "horizon": self.horizon, "complete": imp["tick"] >= self.horizon,
                "trap": trap, "impact": imp, "displacement": self.attack.status(),
                "note": "observed events of this run; DK-RMM's alerts are reported separately and "
                        "this run is not labelled a confirmed Dragon-King"}

    def status(self) -> Dict[str, Any]:
        """Where the scenario stands, for the live page."""
        tick = int(self.eco.world.tick)
        self.observe(tick)
        ph = phase_at(tick)
        remaining = None if ph["until"] is None else int(ph["until"]) - tick
        att = self.attack.status()
        return {
            "scenario": SCENARIO_ID, "preset": PRESET, "label": LABEL, "mechanism": MECHANISM,
            "attack_id": ATTACK_ID, "scenario6_id": SCENARIO6_ID, "start": ATTACK_START,
            "end": ATTACK_END, "horizon": self.horizon, "agents": list(AGENTS),
            "phase": {**ph, "remaining": remaining, "tick": tick},
            "phases": PHASES,
            "displacement": att,
            "robots": self.robots(),
            "head_to_head": self.head_to_head(),
            "trap": self.trap_report(),
            "impact": self.impact(),
            "hospital": self.hospital(),
            "consignment_ids": list(self.arrivals.consignment),
            "demo_seed": DEMO_SEED, "is_demo_seed": self.seed == DEMO_SEED,
            "frozen_trapped_seeds": list(TRAPPED_SEEDS),
            "seed_in_frozen_trapped": self.seed in TRAPPED_SEEDS,
        }


__all__ = [
    "AGENTS", "AGENT_TOKENS", "ATTACK_END", "ATTACK_ID", "ATTACK_START", "AttackSpec", "CONSIGNMENT",
    "CONSIGNMENT_FROM", "CONSIGNMENT_TO", "CONFIRMATION_SEEDS", "ConsignmentArrivals", "DEMO_SEED",
    "DRIFT", "HOSPITAL_ROUTE", "LABEL", "MECHANISM", "OFF_TICKS", "ON_TICKS", "Offered", "OnOffAttack",
    "OnOffFaults", "PHASES", "PRESET", "P_DISPLACE", "RESULTS_DIR", "RUN_TICKS", "SCENARIO6_ID",
    "SCENARIO_ID", "SEED_OPTIONS", "STUDY", "TRAPPED_SEEDS", "TRAP_TICKS", "build_schedule", "config",
    "consignment_ticks", "definition", "fingerprint", "frozen_spec", "is_on", "phase_at", "phases",
    "schedule_hash", "schedule_rows", "true_route",
]
