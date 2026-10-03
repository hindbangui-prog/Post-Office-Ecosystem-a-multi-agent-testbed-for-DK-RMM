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
from ..config.settings import EXPERTS, normal_config, scenario_meta
from ..simulation.ecosystem import PostOfficeEcosystem, build
from ..state.system_state import SystemState

if TYPE_CHECKING:
    from ..config.ollama import OllamaSettings

#: Consultations carried in each published frame.
FRAME_CONSULTATIONS = 10


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
        self._config: Dict[str, Any] = dict(config) if config is not None else normal_config()
        self._log_path = log_path
        self._run_id = run_id
        self.tick_seconds = float(tick_seconds)
        self.preset = preset or "default"
        scenario_meta(self.preset)  # an unknown preset is refused here, not mid-run
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

        #: DK-RMM, held here and not inside the ecosystem: it watches the run
        #: without being part of it.
        self.monitor = None
        self.eco: PostOfficeEcosystem = build(seed=self._seed, config=self._config,
                                              log_path=log_path, run_id=run_id,
                                              brains=self._brains, scenario=self.preset)
        self.state = SystemState(self.eco)
        self._adopt()
        self._subscribe()
        self._start_monitor()
        self._start_recorder()
        self.last_frame: Dict[str, Any] = {}
        self._publish()

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
        """
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self._lock:
            self.stopping = False  # the run being stopped is thrown away
            if preset:
                scenario_meta(preset)
                self.preset = preset
            if seed is not None:
                self._seed = int(seed)
            if config is not None:
                self._config = dict(config)
            # The monitor and its recorder change together, under the
            # recorder's lock, so a gate verdict's write never pairs the old
            # run's recorder with the new run's monitor (lock order: step,
            # then record).
            with self._record_lock:
                self._stop_monitor()
                self._generation += 1
                self._brains = self._build_brains()
                self.eco = self.eco.reset(run_id=f"{self._run_id}-{self._generation + 1}",
                                          brains=self._brains, seed=self._seed,
                                          config=self._config, scenario=self.preset)
                self.state = SystemState(self.eco)
                self._thread = None
                self._adopt()
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
