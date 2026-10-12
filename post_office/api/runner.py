"""
The thing that owns the running ecosystem while an API server is up.

HTTP is request/response and a simulation is a loop, so something has to hold
the loop and let requests interrupt it. That is this class. It runs the tick
loop in a background thread, takes one lock around every mutation, and hands
out read-only state to whoever asks.

The lock is coarse on purpose: one mutex around a whole tick rather than fine
locking inside the agents. The alternative, agents that have to be thread-safe,
would put concurrency into the layer this project most needs to stay simple and
reproducible.

A tick with the experts on the model can take as long as a consultation does
(seconds on a desktop GPU, up to `CONSULT_DEADLINE_S`), so the reads the API
serves never wait for that lock. After every tick the loop publishes
`last_frame`, a plain dictionary built under the lock (the snapshot, the
summary, the whole state, the floor's frame, the roster, the monitor's state),
and the reads come from it or from accessors that carry their own lock or none
(the consultation service's `recent`/`llm_calls`/`in_flight`, the brains'
counters, DK-RMM's `state`, the event logger's `since`). A reader may
therefore see the run one tick behind; it never sees a tick half done and it
never holds a tick up.

Nothing here reaches into the ecosystem beyond the methods the ecosystem
already offers, so a run driven from `main.py` and a run driven over HTTP are
the same run.

With a `record_dir`, DK-RMM's record of the run and each RCT with its cause
are kept on disk as the run goes (`observability/run_record.py`); the recorder
only reads the monitor and the event logger, and a recorder that fails never
stops a tick.

A run on a `c2near-*` preset (the C2-NEAR collapse study, `stress/
c2near_system_override.py`) carries its `ScheduledFaults` beside the ecosystem
the way the study's driver does: `before_tick` is called inside the lock just
before `eco.step()`, and `c2near_status()` reports the schedule, the campaign's
counters and DK-RMM's state sequence for the live page. A run on a collapse
scenario preset (`ms-drop`, `ms-delay`, `cs-starve`, `cs-partition`; `stress/
collapse_scenarios.py`) carries its `CollapseFaults` the same way, and
`study_status()` reports either kind under its `family`. On `default` none of
that exists (`faults` is None, `c2near_status()` and `study_status()` are None)
and a tick is exactly what it was.

Adapted from the source runner: the lock, the thread, start/stop/reset, the
listeners, DK-RMM beside the run and the run recorder are kept; tracing,
stress drivers, injection, live brain switching and discussions are not part
of this prototype.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from ..communication.events import Event
from ..config.settings import (C2NEAR_PRESETS, COLLAPSE_PRESETS, EXPERTS, normal_config,
                               scenario_meta)
from ..config.settings import config as preset_config
from ..simulation.ecosystem import PostOfficeEcosystem, build
from ..state.system_state import SystemState

if TYPE_CHECKING:
    from ..config.ollama import OllamaSettings

#: Consultations carried in each published frame.
FRAME_CONSULTATIONS = 10

#: The seed a C2-NEAR preset starts on when none is asked for: the study's first.
C2NEAR_DEFAULT_SEED = 11


def _is_c2near(preset: str) -> bool:
    return str(preset or "") in C2NEAR_PRESETS


def _is_collapse(preset: str) -> bool:
    return str(preset or "") in COLLAPSE_PRESETS


def _is_study(preset: str) -> bool:
    """A preset that carries a schedule beside the run: C2-NEAR or a collapse scenario."""
    return _is_c2near(preset) or _is_collapse(preset)


def _fault_label(row: Dict[str, Any]) -> str:
    """One schedule row in the words the live page's strip uses."""
    from ..stress import c2near_system_override as spec

    mechanism, detail = row.get("mechanism"), row.get("detail") or {}
    if mechanism == spec.ARRIVAL_SURGE:
        return f"arrivals x{detail.get('factor', spec.ARRIVAL_FACTOR):g}"
    if mechanism == spec.ROUTE_CLOSED:
        return f"route {detail.get('route', '?')} closed"
    if mechanism == spec.CHARGE_LOSS:
        removed = detail.get("removed") or list(spec.CHARGING_REMOVED)
        return f"{len(removed)} of 4 charge points removed"
    if mechanism == spec.ATTACK:
        return "System Override campaign armed"
    return str(row.get("fault_id", mechanism))


class SimulationRunner:
    """
    One ecosystem, a thread to tick it, and a lock around the pair.

    `llm_agents=()` puts all seven experts on the model; `rules_only=True`
    puts none of them there. Before the brains are built, `require_model`
    must find the configured model on the Ollama server (unless
    `verify_model=False`); if it cannot, or the brains cannot be built for any
    other reason, `llm_error` says why and the run is rules-only, with
    `llm_agents == []`. Nothing is substituted.

    The locking rule: `start`, `stop`, `reset`, `step` and the loop mutate the
    run and take `_lock`; the loop holds it for exactly one tick (step, then
    the monitor, then publishing `last_frame`) and sleeps without it. The
    reads (`last_frame`, `snapshot`, `consultations`, `llm_calls`,
    `llm_stats`, `busy`, `events`, `event_counts`, `run_events`, `static`,
    `settings`, `monitor.state()`) never take it, and request handlers read
    nothing else: `state`, `eco` and `llm_agents` reach into the live
    ecosystem and are for code that holds the lock or runs when the loop does
    not.
    """

    def __init__(self, seed: int = 1, config: Optional[Dict[str, Any]] = None,
                 log_path: Optional[str] = None, run_id: str = "api",
                 tick_seconds: float = 0.25, llm_agents: Sequence[str] = (),
                 preset: str = "default", settings: Optional["OllamaSettings"] = None,
                 verify_model: bool = True, rules_only: bool = False,
                 record_dir: Optional[Union[Path, str]] = None) -> None:
        self._seed = int(seed)
        self.preset = preset or "default"
        scenario_meta(self.preset)  # an unknown preset is refused here, not mid-run
        if config is not None:
            self._config: Dict[str, Any] = dict(config)
        elif _is_study(self.preset):
            self._config = preset_config(self.preset)
        else:
            self._config = normal_config()
        #: The configuration a `default` run is built with, kept so a switch
        #: back from a C2-NEAR or collapse preset restores exactly it.
        self._normal_config: Dict[str, Any] = (dict(self._config) if not _is_study(self.preset)
                                               else normal_config())
        #: The schedule beside a `c2near-*` run (`ScheduledFaults`) or a
        #: collapse scenario (`CollapseFaults`); None on `default`.
        self.faults: Optional[Any] = None
        self._log_path = log_path
        self._run_id = run_id
        self.tick_seconds = float(tick_seconds)
        self._settings = settings
        self._verify = bool(verify_model)
        self.rules_only = bool(rules_only)
        #: The experts this runner is to put on the model; it outlives any one
        #: ecosystem, since every reset rebuilds from it.
        self._llm_wanted: List[str] = [str(a) for a in llm_agents] or list(EXPERTS)

        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        #: The running loop's own stop flag. Replaced rather than cleared when a
        #: new loop starts, so a loop still asleep when the next one begins
        #: cannot be revived by it, which would leave two threads ticking.
        self._stop = threading.Event()
        self._stop.set()
        #: A stop has been asked for and the tick in progress has not ended.
        self.stopping = False
        self._stop_reason = "stopped over the API"
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        #: Bumped on every reset, so each ecosystem gets its own run id.
        self._generation = 0
        #: Where DK-RMM's record and each RCT with its cause are kept
        #: (`observability/run_record.py`). None writes nothing, which is what
        #: the tests use unless they pass a `tmp_path`.
        self._record_dir = record_dir
        self.recorder = None
        #: The recorder's own lock: the tick's `update` and a gate verdict's
        #: `record_gate` (a request thread, without the step lock) write the
        #: same files through the same `.tmp`, so they take turns here.
        self._record_lock = threading.Lock()
        #: Why the recorder last failed in a tick ("" when it has not): the
        #: run went on regardless, and `/dkrmm/rct-log` reports it.
        self.record_error = ""

        self.llm_error = ""
        #: The model identity `require_model` returned (a dict), None when no
        #: model was asked for.
        self.identity: Optional[Dict[str, Any]] = None
        #: The Ollama settings the brains were built with (None when none were
        #: loaded: a rules-only run, or settings that would not load).
        self.settings: Optional["OllamaSettings"] = settings
        self._brains: Dict[str, Any] = self._build_brains()
        self._require_model_for(self.preset, self._brains)

        #: DK-RMM, held here and not inside the ecosystem: it watches the run
        #: without being part of it.
        self.monitor = None
        self.eco: PostOfficeEcosystem = build(seed=self._seed, config=self._config,
                                              log_path=log_path, run_id=run_id,
                                              brains=self._brains, scenario=self.preset)
        self.state = SystemState(self.eco)
        self._adopt()
        self._attach_faults()
        self._subscribe()
        self._start_monitor()
        self._start_recorder()
        self.last_frame: Dict[str, Any] = {}
        self._publish()

    # ------------------------------------------------------------- C2-NEAR
    def _require_model_for(self, preset: str, brains: Dict[str, Any]) -> None:
        """
        A `c2near-c2` run needs the experts on the model: its System Override
        campaign is delivered through the model consultations, and a run
        without them would be a C2 run with no campaign, which the study
        refuses to run in silence. A ValueError, which the server turns into
        a 400; the other presets need nothing.
        """
        if preset != "c2near-c2":
            return
        if self.rules_only or not brains:
            why = ("every expert is on its rules" if self.rules_only
                   else f"the brains could not be built ({self.llm_error or 'no model'})")
            raise ValueError("the C2-NEAR C2 condition (System Override campaign) needs the "
                             f"experts on the model, and {why}; serve the app in model mode "
                             "to run it. N and C0 run on rules.")

    def _attach_faults(self) -> None:
        """
        The schedule beside a study ecosystem, None otherwise: the C2-NEAR
        `ScheduledFaults` for a `c2near-*` preset, the one-row
        `CollapseFaults` for a collapse scenario (which needs no model, so a
        rules-only runner carries it too). Called under the lock, once per
        ecosystem, after `_adopt`. For C2 the campaign must be the
        consultation service's agent hooks and bound to this ecosystem
        (`ecosystem._install_crew` binds it), or the run is refused: a C2 run
        never proceeds without its campaign.
        """
        self.faults = None
        if _is_collapse(self.preset):
            from ..stress.collapse_scenarios import CollapseFaults, scenario

            self.faults = CollapseFaults(self.eco, scenario(self.preset))
            return
        if not _is_c2near(self.preset):
            return
        from ..stress.c2near_system_override import condition
        from ..stress.operational import ScheduledFaults

        cond = condition(C2NEAR_PRESETS[self.preset])
        self.faults = ScheduledFaults(self.eco, cond)
        if cond.override:
            campaign = self.faults.campaign()
            if campaign is None or not getattr(campaign, "bound", False):
                self.faults = None
                raise RuntimeError("C2: the ecosystem carries no bound System Override "
                                   "campaign as its consultation hooks; the run is refused")

    def _dkrmm_block(self) -> Dict[str, Any]:
        """
        DK-RMM's state sequence for a study's strip: current state,
        assessments, RCT ticks. Built only for the study presets (it is what
        `study_status()` and `c2near_status()` carry; Normal's `/summary`
        uses `monitor_digest` and never this block), and in their four-state
        view (`stress/states.py`): `view: "four"`, `state`, `sequence` and
        `counts` show RECOVERY as STABLE, `raw_state` keeps the monitor's own
        word for the current reading. The monitor's history is read, never
        changed.
        """
        from ..stress.states import four_state, four_state_counts

        history = list(getattr(self.monitor, "history", []) or []) if self.monitor else []
        raw_sequence = [[int(a.tick), a.state.value] for a in history]
        rct_ticks = [tick for tick, state in raw_sequence if state == "RCT"]
        raw_current = history[-1].state.value if history else None
        raw_counts: Dict[str, int] = {}
        for _, state in raw_sequence:
            raw_counts[state] = raw_counts.get(state, 0) + 1
        return {
            "attached": self.monitor is not None,
            "view": "four",
            "state": four_state(raw_current),
            "raw_state": raw_current,
            "assessments": len(history),
            "sequence": [[tick, four_state(state)] for tick, state in raw_sequence],
            "counts": four_state_counts(raw_counts),
            "rct_ticks": rct_ticks,
            "first_rct_tick": rct_ticks[0] if rct_ticks else None,
        }

    def study_status(self) -> Optional[Dict[str, Any]]:
        """
        Where any study run stands, for the live page's strip; None on
        `default`. For a `c2near-*` preset it is `c2near_status()` under
        `family: "c2near"`; for a collapse scenario, `family: "collapse"`
        with the scenario, its one schedule row (`label`, `tick`,
        `applied_at`), the counters of `CollapseFaults.status()`, the routes
        open, the charge points, the arrival interval and the DK-RMM block.
        Read without the step lock, like the other reads.
        """
        if _is_c2near(self.preset):
            status = self.c2near_status()
            return None if status is None else {"family": "c2near", **status}
        faults = self.faults
        if faults is None or not _is_collapse(self.preset):
            return None
        from ..stress import collapse_scenarios as spec

        eco = self.eco
        scn = faults.scenario
        applied = dict(faults.applied)
        schedule = []
        for row in faults.schedule:
            fired = applied.get(row["fault_id"])
            schedule.append({"tick": int(row["tick"]), "mechanism": row["mechanism"],
                             "fault_id": row["fault_id"], "label": scn.short_label,
                             "applied_at": int(fired["tick"]) if fired else None})
        try:
            counters = faults.status()
        except Exception:
            counters = None
        board = eco.env.departures
        try:
            routes_open = [route for route in board.routes if board.at_bay(route) is not None]
        except Exception:
            routes_open = []
        return {
            "family": "collapse",
            "scenario": scn.id,
            "preset": scn.preset,
            "label": scn.label,
            "mechanism": scn.mechanism,
            "expected": scn.expected,
            "holds_until": scn.holds_until,
            "seed": eco.seed,
            "run_ticks": spec.RUN_TICKS,
            "pressure_from": spec.START,
            "schedule": schedule,
            "counters": counters,
            "routes_open": routes_open,
            "stations": sorted(eco.env.stations),
            "arrival_interval": float(eco.generator.mean_interval),
            "arrival_interval_normal": float(eco.config.get("arrival_interval", 0.0)),
            "dkrmm": self._dkrmm_block(),
        }

    def c2near_status(self) -> Optional[Dict[str, Any]]:
        """
        Where a C2-NEAR run stands, for the live page's strip; None on
        `default`. Read without the step lock, like the other reads: every
        figure is a plain attribute or a copied list, and may be one tick
        behind.

            condition, condition_label, seed, run_ticks, pressure_from
            schedule        every row of the condition's schedule with its
                            `label` and `applied_at` (the tick it fired, or None)
            routes_open, stations, arrival_interval (now), arrival_interval_normal
            campaign        None for N and C0; for C2 `delivered`, `responded`,
                            `pending` (delivered, answer not back yet),
                            `no_usable_answer` (delivered and never answered:
                            a consultation closed as timeout, model failure
                            or no valid decision), `by_target`, `targets`,
                            `start_tick`, `bound`
            dkrmm           `attached`, `view` ("four"), `state` (current, in
                            the four-state view), `raw_state` (the monitor's
                            word), `assessments` (count), `sequence` ([tick,
                            state] per assessment, four-state), `counts`
                            (four-state), `rct_ticks`, `first_rct_tick`
        """
        faults = self.faults
        if faults is None or not _is_c2near(self.preset):
            return None
        eco = self.eco
        applied = dict(faults.applied)
        schedule = []
        for row in faults.schedule:
            fired = applied.get(row["fault_id"])
            schedule.append({"tick": int(row["tick"]), "mechanism": row["mechanism"],
                             "fault_id": row["fault_id"], "label": _fault_label(row),
                             "applied_at": int(fired["tick"]) if fired else None})
        try:
            routes_open = faults.routes_open()
            stations = faults.stations_available()
        except Exception:
            routes_open, stations = [], []
        campaign = None
        agent = faults.campaign()
        if faults.cond.override:
            delivered = agent.deliveries() if agent is not None else []
            responded = agent.responses() if agent is not None else []
            pending = len(getattr(agent, "pending", {}) or {}) if agent is not None else 0
            by_target: Dict[str, Dict[str, int]] = {}
            for target in (getattr(agent, "targets", None) or []):
                by_target[target] = {"delivered": 0, "responded": 0}
            for row in delivered:
                by_target.setdefault(row["target"], {"delivered": 0, "responded": 0})
                by_target[row["target"]]["delivered"] += 1
            for row in responded:
                by_target.setdefault(row["target"], {"delivered": 0, "responded": 0})
                by_target[row["target"]]["responded"] += 1
            campaign = {
                "targets": list(getattr(agent, "targets", []) or []),
                "start_tick": getattr(agent, "start_tick", None),
                "bound": bool(getattr(agent, "bound", False)),
                "delivered": len(delivered), "responded": len(responded),
                "pending": pending,
                "no_usable_answer": max(0, len(delivered) - len(responded) - pending),
                "by_target": by_target,
            }
        from ..stress import c2near_system_override as spec

        return {
            "condition": faults.cond.id,
            "condition_label": faults.cond.label,
            "seed": eco.seed,
            "run_ticks": spec.RUN_TICKS,
            # The first tick of the schedule (`STRESS_START`); named so the
            # page's script, which the Normal page serves too, can read it
            # without carrying a word the Normal page must not show.
            "pressure_from": spec.STRESS_START,
            "schedule": schedule,
            "routes_open": routes_open,
            "routes_closed": list(faults.closed_routes),
            "stations": stations,
            "arrival_interval": float(eco.generator.mean_interval),
            "arrival_interval_normal": float(eco.config.get("arrival_interval", 0.0)),
            "campaign": campaign,
            "dkrmm": self._dkrmm_block(),
        }

    # ------------------------------------------------------------------ brains
    def _build_brains(self) -> Dict[str, Any]:
        """
        A fresh `CrewBrain` for each wanted expert, or none and a reason why.

        Fresh every time: a brain counts its own calls and fallbacks, so one
        reused across a reset would report the previous run's figures under the
        new run's name. Never raises: an unreachable server or a missing model
        means a rules-only run with `llm_error` saying so, not an API server
        that will not start.
        """
        self.llm_error = ""
        self.identity = None
        if self.rules_only:
            return {}
        try:
            from ..config.ollama import load_settings
            from ..config.settings import llm_brains
            from ..crew.identity import ModelIdentity, ModelUnavailable, require_model

            settings = self._settings if self._settings is not None else load_settings()
            self.settings = settings
            if self._verify:
                try:
                    self.identity = require_model(settings).as_dict()
                except ModelUnavailable as exc:
                    self.identity = exc.identity.as_dict()
                    raise
            else:
                self.identity = {**ModelIdentity(model=settings.model,
                                                 base_url=settings.base_url).as_dict(),
                                 "ok": None, "problems": ["not verified (verify_model=False)"]}
            return llm_brains(self._llm_wanted, settings=settings, verify=False)
        except Exception as exc:  # ModelUnavailable, InvalidBaseUrl, ImportError, ...
            self.llm_error = f"{type(exc).__name__}: {exc}"
            return {}

    @property
    def llm_wanted(self) -> List[str]:
        """The experts asked for, whether or not the brains could be built."""
        return [] if self.rules_only else list(self._llm_wanted)

    @property
    def llm_agents(self) -> List[str]:
        """The agents of the running ecosystem that are actually on the model."""
        return sorted(agent_id for agent_id, agent in self.eco.agents.items()
                      if getattr(getattr(agent, "brain", None), "name", "") == "crewai")

    def llm_stats(self) -> Dict[str, Any]:
        """
        How much of this run the model has actually decided: the brains'
        `stats()` summed, each brain's own row, and the model identity.

        Read without the step lock: the counters are plain integers a tick
        may be adding to, so a figure can be one decision behind.
        """
        brains = dict(self._brains)
        total: Dict[str, Any] = {key: 0 for key in (
            "calls", "consultations", "questions", "delegations", "fallbacks",
            "rejected_answers", "parse_failures", "timeouts", "retries")}
        total["reachable"] = False
        total["agents"] = {}
        for agent_id, brain in sorted(brains.items()):
            try:
                stats = brain.stats()
            except Exception:
                continue
            for key in list(total):
                if key not in ("reachable", "agents"):
                    total[key] += int(stats.get(key) or 0)
            total["reachable"] = bool(total["reachable"] or stats.get("reachable"))
            total["agents"][agent_id] = stats
        total["identity"] = self.identity
        total["error"] = self.llm_error
        return total

    def consultations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """The run's most recent consultations, oldest first; [] without the model."""
        crew = getattr(self.eco, "crew", None)
        return crew.recent(limit) if crew is not None else []

    def llm_calls(self, limit: int = 100) -> List[Dict[str, Any]]:
        """The run's most recent model calls, as the transport audit saw them."""
        crew = getattr(self.eco, "crew", None)
        return crew.llm_calls(limit) if crew is not None else []

    def snapshot(self) -> Dict[str, Any]:
        """The ecosystem's snapshot as of the last published tick."""
        return dict(self.last_frame.get("snapshot") or {})

    def busy(self) -> List[Dict[str, Any]]:
        """
        The consultations in flight now, and which expert in each is inside a
        model call (`ConsultationService.in_flight`). Read at the moment of
        asking, not from `last_frame`: a tick that consults publishes nothing
        until the consultation is over, and this is the reading that says what
        it is waiting on meanwhile.
        """
        crew = self._crew
        return crew.in_flight() if crew is not None else []

    def events(self, after: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        """The kept events with `seq > after`, oldest first."""
        return [event.as_dict() for event in self._logger.since(after, limit)]

    def event_counts(self) -> Dict[str, Any]:
        """How many events the run has logged, in all and by category.topic."""
        return {"total": self._logger.total, "counts": self._logger.counts()}

    def run_events(self) -> Tuple[List[Any], str]:
        """
        This run's events for an explanation, and where they came from: the
        whole log file when the logger writes one (`"log"`), otherwise the
        logger's in-memory tail (`"memory"`), which may not reach back to the
        start of the baseline. Read without the step lock, as the source read
        them.
        """
        from ..observability.rct_explain import events_from_log

        logger = self._logger           # one logger is one run, ids included
        path = getattr(logger, "path", None)
        if path and os.path.exists(path):
            logger.flush()
            return events_from_log(path, run_id=logger.run_id), "log"
        return logger.recent(limit=100000), "memory"

    def _adopt(self) -> None:
        """
        Keep the parts of a new ecosystem the lock-free reads use, and what
        never changes about it. Called under the lock, once per ecosystem.
        """
        from ..ui.views import static_of

        self._logger = self.eco.logger
        self._crew = getattr(self.eco, "crew", None)
        self.static = static_of(self.eco, preset=self.preset)

    # -------------------------------------------------------------- streaming
    def _subscribe(self) -> None:
        def relay(event: Event) -> None:
            payload = {"type": "event", **event.as_dict()}
            for listener in list(self._listeners):
                try:
                    listener(payload)
                except Exception:
                    pass  # a dead socket must not stop the simulation
        self.eco.logger.subscribe(relay)

    def add_listener(self, fn: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        self._listeners.append(fn)

        def remove() -> None:
            if fn in self._listeners:
                self._listeners.remove(fn)
        return remove

    def _broadcast(self, payload: Dict[str, Any]) -> None:
        for listener in list(self._listeners):
            try:
                listener(payload)
            except Exception:
                pass

    # ------------------------------------------------------------- the frame
    def _roster(self) -> List[Dict[str, Any]]:
        rows = []
        for agent_id in self.eco.order:
            brain = getattr(self.eco.agents.get(agent_id), "brain", None)
            config = getattr(brain, "config", None)
            rows.append({"agent_id": agent_id, "brain": getattr(brain, "name", ""),
                         "model": getattr(config, "model_type", None)})
        return rows

    def _publish(self) -> None:
        """Build `last_frame` from the run as it stands. Called under the lock."""
        monitor_state = None
        if self.monitor is not None:
            try:
                monitor_state = self.monitor.state()
            except Exception:
                monitor_state = None
        from ..ui.views import frame_of

        frame = frame_of(self.eco)
        frame["run_id"] = self.eco.run_id
        self.last_frame = {
            "run_id": self.eco.run_id,
            "tick": int(self.eco.world.tick),
            "running": bool(self.eco.world.running),
            "seed": self.eco.seed,
            "snapshot": self.eco.snapshot(),
            "summary": self.eco.summary(),
            "state": self.state.get_ecosystem_state(messages=40, events=40),
            "frame": frame,
            "roster": self._roster(),
            "llm_agents": self.llm_agents,
            "consultations": self.consultations(FRAME_CONSULTATIONS),
            "dkrmm": monitor_state,
        }

    # -------------------------------------------------------------- controls
    def start(self) -> Dict[str, Any]:
        with self._lock:
            self.stopping = False  # a start cancels a pause still pending
            self.eco.start()
            if self._thread is None or not self._thread.is_alive():
                # A new flag, not a cleared one (see `_stop`).
                self._stop = threading.Event()
                self._thread = threading.Thread(target=self._watch, daemon=True,
                                                name="post-office-ticker",
                                                args=(self._stop,))
                self._thread.start()
            self._publish()
            return self.snapshot()

    def stop(self, reason: str = "stopped over the API") -> Dict[str, Any]:
        """
        Stop after the tick in progress.

        Answers at once: a tick with the experts on the model can take as long
        as a consultation, so the flag is raised first and the stop itself is
        done by whoever holds the lock next, this call if the lock is free,
        otherwise the loop as it exits. `stopping` says which state the run is
        in meanwhile.
        """
        self._stop.set()
        self._stop_reason = reason
        self.stopping = True
        if self._lock.acquire(timeout=0.25):
            try:
                self._finish_stop()
            finally:
                self._lock.release()
        return self.snapshot()

    def _finish_stop(self) -> None:
        """The stop itself, under the lock, exactly once per request to stop."""
        if not self.stopping:
            return
        self.stopping = False
        self.eco.stop(self._stop_reason)
        self._publish()

    def reset(self, seed: Optional[int] = None, config: Optional[Dict[str, Any]] = None,
              preset: str = "") -> Dict[str, Any]:
        """
        Throw the ecosystem away and build a fresh one, with fresh brains.

        On the same seed, configuration and scenario unless given others. The
        model is checked again (`require_model`), so a model removed or a
        server stopped in between is reported in `llm_error`.

        A `preset` that is a C2-NEAR condition builds on that condition's
        configuration (`settings.config(preset)`), on seed 11 (the study's
        first) when the run was not already on a C2-NEAR preset and no `seed`
        is given; `default` after one restores the configuration the runner's
        Normal run had. `c2near-c2` on a rules-only runner, or on one whose
        brains cannot be built, is refused with a ValueError before anything
        is touched: the run goes on as it was.
        """
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self._lock:
            if preset:
                scenario_meta(preset)
            # What the new run will be, decided before anything is touched,
            # so a refusal below leaves the current run exactly as it is.
            next_preset = preset or self.preset
            next_seed, next_config = self._seed, self._config
            if preset:
                if _is_study(preset):
                    # A study preset (C2-NEAR or a collapse scenario) entered
                    # from Normal starts on the studies' first seed.
                    if seed is None and not _is_study(self.preset):
                        next_seed = C2NEAR_DEFAULT_SEED
                    next_config = preset_config(preset)
                elif _is_study(self.preset):
                    next_config = dict(self._normal_config)
            if seed is not None:
                next_seed = int(seed)
            if config is not None:
                next_config = dict(config)
            if next_preset == "c2near-c2" and self.rules_only:
                self._require_model_for(next_preset, {})          # raises
            if next_preset == "c2near-c2":
                # The brains are built first and checked, with the model
                # error of a failed build put back if the switch is refused.
                held = (self.llm_error, self.identity, self.settings)
                brains = self._build_brains()
                try:
                    self._require_model_for(next_preset, brains)
                except ValueError:
                    self.llm_error, self.identity, self.settings = held
                    raise
            else:
                brains = None
            self.stopping = False  # the run being stopped is thrown away
            self.preset, self._seed, self._config = next_preset, next_seed, next_config
            if config is not None and not _is_study(self.preset):
                self._normal_config = dict(config)
            # The monitor and its recorder change together, under the
            # recorder's lock, so a gate verdict's write never pairs the old
            # run's recorder with the new run's monitor (lock order: step,
            # then record).
            with self._record_lock:
                self._stop_monitor()
                self._generation += 1
                self._brains = brains if brains is not None else self._build_brains()
                self.eco = self.eco.reset(run_id=f"{self._run_id}-{self._generation + 1}",
                                          brains=self._brains, seed=self._seed,
                                          config=self._config, scenario=self.preset)
                self.state = SystemState(self.eco)
                self._thread = None
                self._adopt()
                self._attach_faults()
                self._subscribe()
                self._start_monitor()
                self._start_recorder()
            self._publish()
        self._broadcast({"type": "reset", "run_id": self.eco.run_id})
        return self.snapshot()

    def step(self, ticks: int = 1) -> Dict[str, Any]:
        """Advance by hand, for when the loop is not running."""
        for _ in range(max(1, int(ticks))):
            self._tick()
        return self.snapshot()

    # ---------------------------------------------------------- the monitor
    def _start_monitor(self) -> None:
        """
        Attach DK-RMM to the ecosystem this runner just built.

        A monitor that failed to start means a run without a monitor, never a
        simulation that refuses to run.
        """
        try:
            from ..dkrmm import DKRMM

            self.monitor = DKRMM(self.eco).attach()
        except Exception:
            self.monitor = None

    def _start_recorder(self) -> None:
        """
        A record of this run's DK-RMM readings and RCTs, when asked for: only
        with a `record_dir` and a monitor. A recorder that cannot be built
        means a run that is not recorded, never one that does not run.
        """
        self.recorder = None
        self.record_error = ""
        if not self._record_dir or self.monitor is None:
            return
        try:
            from ..observability.run_record import RunRecorder

            self.recorder = RunRecorder(self._record_dir, self.eco.run_id,
                                        scenario=self.preset, seed=self._seed,
                                        config={"llm_agents": self.llm_agents},
                                        model=getattr(self.settings, "model", None))
        except Exception as exc:
            self.recorder = None
            self.record_error = f"{type(exc).__name__}: {exc}"

    def record_gate(self) -> None:
        """
        A person validated, activated or dismissed a reading: keep it. Called
        from a request thread without the step lock; the recorder's own lock
        keeps it from writing over a tick's update, and from reading the
        recorder and the monitor while a reset is swapping them. A recorder
        of another run than the runner's current one is never written: the
        run is read here, under the lock a reset swaps the monitor, the
        recorder and the run under, so the monitor is that run's too.
        """
        with self._record_lock:
            recorder, monitor = self.recorder, self.monitor
            if recorder is None or monitor is None:
                return
            if recorder.run_id != self.eco.run_id:
                return
            recorder.write(monitor)

    def _stop_monitor(self) -> None:
        if self.monitor is not None:
            try:
                self.monitor.close()
            except Exception:
                pass
            self.monitor = None

    # ------------------------------------------------------------- the thread
    def _tick(self, stop: Optional[threading.Event] = None) -> bool:
        """
        One tick under the lock: the step, the monitor (and its recorder),
        the published frame.
        False, and no tick, if `stop` was set while waiting for the lock.
        """
        with self._lock:
            if stop is not None and stop.is_set():
                return False
            if self.faults is not None:
                # The C2-NEAR schedule, as the study's driver applies it: the
                # faults of the coming tick, before that tick is stepped.
                self.faults.before_tick(self.eco.world.tick + 1)
            self.eco.step()
            if self.monitor is not None:
                try:
                    self.monitor.tick()
                except Exception:
                    pass  # the observer is never the reason the observed stops
                if self.recorder is not None:
                    try:
                        with self._record_lock:
                            self.recorder.update(self.monitor, self.eco)
                    except Exception as exc:  # nor is its recorder
                        self.record_error = f"{type(exc).__name__}: {exc}"
            self._publish()
            frame = self.last_frame
        self._broadcast({"type": "tick", **frame["snapshot"]})
        return True

    def _watch(self, stop: threading.Event) -> None:
        """
        Tick until told to stop: lock, step, monitor, publish, unlock, sleep.

        The sleep is to the next tick's due time, `tick_seconds` after the last
        one was due, so a slow tick (a consultation) is not followed by a
        further pause and the pace holds on average where `time.sleep` is
        coarse. A loop that falls a tick or more behind starts its schedule
        again rather than racing to catch up. The flag is passed in, so this
        loop answers to the event it was started with and to no later one.
        """
        due = time.monotonic()
        while not stop.is_set():
            if not self._tick(stop):  # stopped while waiting for the lock
                break
            interval = self.tick_seconds
            if interval <= 0.0:
                continue
            due += interval
            wait = due - time.monotonic()
            if wait > 0.0:
                stop.wait(wait)
            elif wait < -interval:
                due = time.monotonic()
        # A stop requested while a tick was in progress is completed here, by
        # the thread that held the lock, so the request could answer at once.
        if self.stopping and stop is self._stop:
            with self._lock:
                self._finish_stop()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        with self._lock:
            self._stop_monitor()
            self.eco.close()
