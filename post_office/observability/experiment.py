"""
One live run of the app, kept on disk as an experiment run directory.

Opt-in: only a runner given an `experiment_dir` (`python main.py --api
--experiment-dir PATH`) builds one of these, and only for the presets an
experiment is run on here: a collapse scenario (`ms-drop`, `ms-delay`,
`cs-starve`, `cs-partition`) and its no-fault control (`c2near-n`, the Normal
configuration with an empty schedule, or `default`). Every other run of the app
is unchanged and writes nothing here.

The directory has the layout of `tools/run_collapse_scenarios.py`, so that
tool's `--analyze` and `tools/analyze_ms_drop_model.py` read a run made in the
browser exactly as one made by the driver:

    <experiment_dir>/<scenario id>/s<seed>/     MS-DROP/s11, N/s11, ...
        definition.json        what was run: scenario, seed, ticks (the stop
                               tick), mode, model identity, source "live UI"
        events.jsonl           every event of the run, as the logger made it
        series.csv             the study's per-tick row (`stress/measure.py`)
        measurement.json       its totals, faults applied and DK-RMM block
        zone_backlog.csv       `observability/zone_backlog.py`, every tick
        dkrmm_assessments.jsonl  every DK-RMM reading as it was made (values,
                               baselines, z, evaluable, evidence, state)
        dkrmm.json             the monitor's final state and record
        decision_traces.jsonl  `observability/decision_trace.py`, per decision
        message_traces.jsonl   the same, per ROUTE_REQUEST, RESOURCE_REQUEST,
                               TASK_ASSIGNMENT and ROBOT_COMMAND message
        trace_summary.json     the traces counted before and after the fault
        summary.json           the ecosystem's summary
        verify.json            mode, model identity, and which model served
                               every call (the driver's served-model check)
        status.json            running / complete / incomplete / failed, the
                               tick reached and why
        done.json              only when the run reached its stop tick

A directory that already exists is never written into: the run goes to
`s<seed>-2`, `s<seed>-3`, ... instead (which `--analyze` does not pick up on its
own; it reads `s<seed>` only).

Nothing here acts on the run. A recorder that fails records the reason in
`status.json` and `errors`, and the run goes on.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Presets recorded, and the scenario id their directory is named after.
CONTROL_PRESETS = ("c2near-n", "default")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _write(path: Path, body: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def scenario_for(preset: str) -> Optional[Any]:
    """The collapse-study scenario a preset is recorded as, or None if it is not recorded."""
    from ..stress import collapse_scenarios as spec

    if preset in spec.NAMES and preset != "N":
        return spec.scenario(preset)
    if preset in CONTROL_PRESETS:
        return spec.scenario("N")
    return None


def run_dir_for(root: Any, scenario_id: str, seed: int) -> Path:
    """`<root>/<scenario>/s<seed>`, or the first `-2`, `-3`, ... that does not exist."""
    base = Path(root) / scenario_id
    name, n = f"s{int(seed)}", 1
    while (base / name).exists():
        n += 1
        name = f"s{int(seed)}-{n}"
    return base / name


class ExperimentRecorder:
    """Keeps one live run's experiment directory up to date."""

    def __init__(self, root: Any, eco: Any, monitor: Any, preset: str, seed: int,
                 stop_at: Optional[int], mode: str, identity: Optional[Dict[str, Any]] = None,
                 settings: Any = None, zones: Any = None, tracer: Any = None,
                 llm_agents: Optional[List[str]] = None, llm_error: str = "",
                 faults: Any = None) -> None:
        from ..stress import collapse_scenarios as spec

        scn = scenario_for(preset)
        if scn is None:
            raise ValueError(f"preset {preset!r} is not kept as a run directory")
        self.eco, self.monitor, self.preset = eco, monitor, preset
        self.scenario = scn
        self.seed = int(seed)
        self.stop_at = None if stop_at is None else int(stop_at)
        self.mode = mode
        self.settings = settings
        self.zones, self.tracer = zones, tracer
        self.errors: List[str] = []
        self.status = "running"
        self.reason = ""
        self.finished = False
        self.dir = run_dir_for(root, scn.id, seed)
        self.dir.mkdir(parents=True, exist_ok=False)
        # The study's collector. For a collapse scenario it reads the runner's
        # own `CollapseFaults`; the control's has no row and is never fired, so
        # it reads zero counters, as the driver's N run does.
        self._faults = (faults if isinstance(faults, spec.CollapseFaults)
                        else spec.CollapseFaults(eco, scn))
        self.collector = spec.ScenarioCollector(eco, scn, self._faults, monitor=monitor,
                                                mode=mode, ticks=self.stop_at)
        self._calls: List[Dict[str, Any]] = []
        self._call_ids: set = set()
        self._assessed = 0
        definition = {**spec.definition(scn), "fingerprint": spec.fingerprint(scn),
                      "seed": self.seed, "ticks": self.stop_at, "mode": mode,
                      "preset": preset, "run_id": eco.run_id,
                      "source": "live UI (post_office/api/runner.py, --experiment-dir)",
                      "llm_agents": list(llm_agents or []), "llm_error": llm_error,
                      "started_at": _now()}
        _write(self.dir / "definition.json", definition)
        verify: Dict[str, Any] = {"mode": mode}
        if mode == "model":
            ok = bool((identity or {}).get("ok"))
            verify.update({"base_url": getattr(settings, "base_url", None),
                           "settings": settings.as_dict() if settings is not None else None,
                           "identity": identity, "ok": ok})
        else:
            verify.update({"ok": None, "note": "rules-only run: no model was asked "
                                               "and no identity was checked"})
        self._verify = verify
        # The events so far (the ecosystem as built), then every new one.
        self._events = (self.dir / "events.jsonl").open("w", encoding="utf-8", newline="\n")
        self._last_seq = 0
        for event in eco.logger.recent(limit=1000000):
            self._write_event(event)
        self._unsubscribe = eco.logger.subscribe(self._write_event)
        self._assessments = (self.dir / "dkrmm_assessments.jsonl").open(
            "w", encoding="utf-8", newline="\n")
        self._status()

    # ---------------------------------------------------------- per event
    def _write_event(self, event: Any) -> None:
        if self._events is None or event.seq <= self._last_seq:
            return
        try:
            self._events.write(json.dumps(event.as_dict(), default=str) + "\n")
            self._last_seq = event.seq
        except Exception as exc:
            self.errors.append(f"events: {type(exc).__name__}: {exc}")

    # ----------------------------------------------------------- per tick
    def after_tick(self) -> None:
        """Called by the runner after the tick's step, monitor and zone sample."""
        if self.finished:
            return
        try:
            self.collector.after_step()
        except Exception as exc:
            self.errors.append(f"collector: {type(exc).__name__}: {exc}")
        crew = getattr(self.eco, "crew", None)
        if crew is not None:
            try:
                for row in crew.llm_calls(2000):
                    if row["call_id"] not in self._call_ids:
                        self._call_ids.add(row["call_id"])
                        self._calls.append(row)
            except Exception as exc:
                self.errors.append(f"llm_calls: {type(exc).__name__}: {exc}")
        history = list(getattr(self.monitor, "history", []) or []) if self.monitor else []
        for reading in history[self._assessed:]:
            try:
                self._assessments.write(json.dumps(reading.as_dict(), default=str) + "\n")
            except Exception as exc:
                self.errors.append(f"assessment: {type(exc).__name__}: {exc}")
        self._assessed = len(history)
        if int(self.eco.world.tick) % 100 == 0:
            self.flush()

    def flush(self) -> None:
        for handle in (self._events, self._assessments):
            if handle is not None:
                try:
                    handle.flush()
                except Exception:
                    pass
        self._status()

    # ------------------------------------------------------------- status
    def _status(self) -> None:
        try:
            _write(self.dir / "status.json", self.state())
        except Exception as exc:
            self.errors.append(f"status: {type(exc).__name__}: {exc}")

    def state(self) -> Dict[str, Any]:
        return {"status": self.status, "reason": self.reason,
                "tick": int(self.eco.world.tick), "stop_at": self.stop_at,
                "scenario": self.scenario.id, "preset": self.preset, "seed": self.seed,
                "mode": self.mode, "dir": str(self.dir), "updated_at": _now(),
                "errors": list(self.errors[:20])}

    # ------------------------------------------------------------ writing
    def snapshot(self, status: str, reason: str) -> None:
        """Write every file as the run stands now (a pause or the end)."""
        from ..dkrmm.record import build_record

        self.status, self.reason = status, reason
        complete = status == "complete"
        eco = self.eco
        self.flush()
        try:
            self.collector.write(self.dir, interrupted=not complete)
        except Exception as exc:
            self.errors.append(f"series: {type(exc).__name__}: {exc}")
        if self.zones is not None:
            try:
                self.zones.write(self.dir / "zone_backlog.csv")
            except Exception as exc:
                self.errors.append(f"zones: {type(exc).__name__}: {exc}")
        if self.tracer is not None:
            try:
                self.tracer.write(self.dir / "decision_traces.jsonl")
                self.tracer.write_messages(self.dir / "message_traces.jsonl")
                _write(self.dir / "trace_summary.json",
                       self.tracer.summary(fault_tick=self._fault_tick()))
            except Exception as exc:
                self.errors.append(f"traces: {type(exc).__name__}: {exc}")
        try:
            if self.monitor is not None:
                record = build_record(eco.run_id, self.monitor, scenario="normal",
                                      seed=self.seed, config=eco.config,
                                      control=self.scenario.control)
                _write(self.dir / "dkrmm.json", {"state": self.monitor.state(),
                                                 "record": record, "errors": []})
        except Exception as exc:
            self.errors.append(f"dkrmm: {type(exc).__name__}: {exc}")
        try:
            _write(self.dir / "summary.json",
                   {**eco.summary(), "reasoning": eco.reasoning_summary(),
                    "interrupted": not complete})
        except Exception as exc:
            self.errors.append(f"summary: {type(exc).__name__}: {exc}")
        try:
            verify = {**self._verify, "llm": eco.llm_summary(), "interrupted": not complete}
            if self.mode == "model":
                from collections import Counter

                configured = getattr(self.settings, "model", None)
                served = Counter(c.get("served_model") for c in self._calls)
                other = sorted(n for n in served if n and n != configured)
                verify.update({"served_models": dict(sorted((str(k), v) for k, v in served.items())),
                               "served_by_configured_model": served.get(configured, 0),
                               "served_by_other_models": other,
                               "calls_failed": sum(1 for c in self._calls
                                                   if c.get("error") or c.get("status") != 200),
                               "ok": bool(self._verify.get("ok") and not other)})
            _write(self.dir / "verify.json", verify)
        except Exception as exc:
            self.errors.append(f"verify: {type(exc).__name__}: {exc}")
        if complete:
            from ..stress import collapse_scenarios as spec

            _write(self.dir / "done.json", {
                "study": spec.STUDY, "scenario": self.scenario.id,
                "preset": self.scenario.preset, "seed": self.seed, "ticks": self.stop_at,
                "fingerprint": spec.fingerprint(self.scenario), "mode": self.mode,
                "source": "live UI", "ui_preset": self.preset})
        self._status()

    def _fault_tick(self) -> Optional[int]:
        from ..stress import collapse_scenarios as spec

        return None if self.scenario.control else int(self.scenario.start)

    def finish(self, status: str, reason: str) -> None:
        """The last snapshot; nothing is written after it."""
        if self.finished:
            return
        self.snapshot(status, reason)
        self.finished = True
        self.close()

    def close(self) -> None:
        if self._unsubscribe is not None:
            try:
                self._unsubscribe()
            except Exception:
                pass
            self._unsubscribe = None
        try:
            self.collector.close()
        except Exception:
            pass
        for name in ("_events", "_assessments"):
            handle = getattr(self, name)
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
                setattr(self, name, None)


__all__ = ["CONTROL_PRESETS", "ExperimentRecorder", "run_dir_for", "scenario_for"]
