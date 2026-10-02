"""
What an app run's DK-RMM made of it, kept on disk as the run goes.

Two things, both written by the runner that owns the run and both read-only with
respect to DK-RMM (they record what it produced; nothing is fed back):

    results/dkrmm/<run id>.json         every reading of the run, with the clock
                                        time it was made and any Validate /
                                        Activate / Dismiss decision, in the same
                                        record format the battery writes, plus
                                        `readings` and `app_run`
    results/rct/<run id>/<tick>.json    each RCT, saved when it is detected,
                                        with the scenario it was detected in
                                        and the explanation of what drove it as
                                        it stood at that moment

Rewritten whole at each new reading (atomically, so a crash leaves the last
complete version, never half a file).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def scenario_of(preset: str) -> Dict[str, str]:
    """
    The scenario a preset runs, by its results-column name and its label.

    The one preset, Normal (`default`, also called `normal`), is `normal` with
    the label the live page's scenario selector shows (`settings.scenario_label`);
    any other name is recorded under itself.
    """
    try:
        from ..config.settings import scenario_label, scenario_name

        if preset and scenario_name(preset) == "normal":
            return {"scenario": "normal", "scenario_label": scenario_label()}
    except Exception:                                # an unknown name is still a name
        pass
    return {"scenario": str(preset or ""), "scenario_label": str(preset or "unknown")}


def _write(path: Path, body: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


class RunRecorder:
    """Keeps one run's DK-RMM record and its RCT files up to date."""

    def __init__(self, root: str, run_id: str, scenario: str = "",
                 seed: Optional[int] = None, config: Optional[Dict[str, Any]] = None):
        self.root = Path(root)
        self.run_id = run_id
        self.scenario = scenario
        self.seed = seed
        self.config = dict(config or {})
        self.scenario_tag = scenario_of(scenario)
        # A name no earlier file has: a run id can repeat across trace files.
        name, n = run_id, 1
        while (self.root / "dkrmm" / f"{name}.json").exists():
            n += 1
            name = f"{run_id}-{n}"
        self.name = name
        self.record_path = self.root / "dkrmm" / f"{name}.json"
        self.rct_dir = self.root / "rct" / name
        self.detected_at: Dict[int, str] = {}
        self._seen = 0
        self._rcts_saved: set = set()
        self.error = ""

    def update(self, monitor, eco) -> None:
        """Called once per tick; writes only when there is a new reading."""
        history = list(getattr(monitor, "history", []) or [])
        if len(history) == self._seen and not self._unsaved_rct(history):
            return
        for reading in history[self._seen:]:
            self.detected_at.setdefault(reading.tick, _now())
        self._seen = len(history)
        for reading in history:
            if reading.state.value == "RCT" and reading.tick not in self._rcts_saved:
                self._save_rct(reading, eco)
        self.write(monitor)

    def _unsaved_rct(self, history) -> bool:
        return any(r.state.value == "RCT" and r.tick not in self._rcts_saved for r in history)

    def write(self, monitor) -> None:
        """The whole record, now. Also called after a gate decision."""
        from ..dkrmm.record import build_record

        try:
            record = build_record(self.run_id, monitor, scenario=self.scenario,
                                  seed=self.seed, config=self.config, control=True)
            record["app_run"] = True
            record.update(self.scenario_tag)
            record["scenario"] = self.scenario              # the preset, as before
            record["file"] = self.name
            record["readings"] = [{**r.as_dict(),
                                   "detected_at": self.detected_at.get(r.tick, "")}
                                  for r in getattr(monitor, "history", [])]
            _write(self.record_path, record)
            # An RCT's own file carries its reading; keep its gate status current.
            for reading in getattr(monitor, "history", []):
                path = self.rct_dir / f"{reading.tick}.json"
                if reading.state.value == "RCT" and path.exists():
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    now = reading.as_dict()
                    if saved.get("reading", {}).get("status") != now.get("status"):
                        saved["reading"] = now
                        _write(path, saved)
        except Exception as exc:                       # the run never depends on this
            self.error = f"{type(exc).__name__}: {exc}"

    def _save_rct(self, reading, eco) -> None:
        from .rct_explain import events_from_log, explain

        try:
            path = getattr(eco.logger, "path", None)
            if path and os.path.exists(path):
                eco.logger.flush()
                events = events_from_log(path, run_id=eco.run_id)
            else:
                events = eco.logger.recent(limit=100000)
            _write(self.rct_dir / f"{reading.tick}.json", {
                "run_id": self.run_id, **self.scenario_tag, "tick": reading.tick,
                "detected_at": self.detected_at.get(reading.tick, _now()),
                "reading": reading.as_dict(),
                "explanation": explain(events, reading.tick),
            })
            self._rcts_saved.add(reading.tick)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
