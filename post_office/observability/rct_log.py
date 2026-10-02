"""
The RCT log: every RCT the app's runs have saved, read back from disk.

`run_record.RunRecorder` writes one file per RCT, when it is detected, to
`results/rct/<run>/<tick>.json`, with the reading and the explanation of what
drove it as it stood at that moment. This lists those files across all runs and
returns one of them whole. It only reads: nothing here touches DK-RMM or the
files it lists.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_run(run: str) -> str:
    """A run folder name, never a path that leaves the log folder."""
    run = str(run or "")
    if (not run or run in (".", "..") or "/" in run or "\\" in run
            or "\0" in run or run.startswith(".")):
        raise ValueError(f"not a run name: {run!r}")
    return run


def _run_scenario(root: Path, run: str) -> Dict[str, str]:
    """For an RCT saved before RCTs carried a scenario: its run's record says."""
    from .run_record import scenario_of

    try:
        record = json.loads((root / "dkrmm" / f"{run}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"scenario": "", "scenario_label": "unknown"}
    # The record keeps the preset the run was started with (`default` for Normal).
    preset = str(record.get("scenario") or "")
    return scenario_of(preset) if preset else {"scenario": "", "scenario_label": "unknown"}


def _row(run: str, body: Dict[str, Any], fallback) -> Dict[str, Any]:
    reading = body.get("reading") or {}
    explanation = body.get("explanation") or {}
    if body.get("scenario"):
        from .run_record import scenario_of

        tag = {"scenario": str(body["scenario"]),
               "scenario_label": str(body.get("scenario_label")
                                     or scenario_of(str(body["scenario"]))["scenario_label"])}
    else:
        tag = fallback()
    return {"run": run, "run_id": body.get("run_id", ""), **tag, "tick": body.get("tick"),
            "detected_at": body.get("detected_at", ""),
            "severity": reading.get("severity"), "kinds": reading.get("kinds") or [],
            "evidence": reading.get("evidence") or [],
            "status": reading.get("status", ""),
            "summary": explanation.get("summary", "")}


def list_rcts(root) -> List[Dict[str, Any]]:
    """Every saved RCT under `root`, newest detection first, without the cause."""
    base = Path(root) / "rct"
    if not base.is_dir():
        return []
    rows = []
    for folder in base.iterdir():
        if not folder.is_dir():
            continue
        known: Dict[str, Dict[str, str]] = {}

        def fallback(run=folder.name, known=known):
            if run not in known:
                known[run] = _run_scenario(Path(root), run)
            return known[run]

        for path in folder.glob("*.json"):
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue                        # half-written or damaged: skip it
            if isinstance(body, dict) and isinstance(body.get("tick"), int):
                rows.append(_row(folder.name, body, fallback))
    rows.sort(key=lambda r: (str(r["detected_at"]), r["run"], r["tick"]), reverse=True)
    return rows


def load_rct(root, run: str, tick: int) -> Optional[Dict[str, Any]]:
    """One saved RCT whole, with its cause; None when there is no such file."""
    path = Path(root) / "rct" / _safe_run(run) / f"{int(tick)}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
