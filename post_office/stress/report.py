"""
The results page of C2-NEAR-SYSTEM-OVERRIDE: one standalone HTML file made
from a results directory.

`collect(out_dir)` reads every finished run under `<out>/<condition>/s<seed>/`
(a run is finished when `done.json` is there; anything else is listed as
incomplete and left out) and `<out>/summary.json` when `--analyze` has
written it, and pre-aggregates everything the page shows so the page stays
small: the per-tick series of a handful of columns as compact arrays, the
run's totals, faults, per-route table, DK-RMM state sequence and model
verification, the model decisions against the rule in 100-tick bins and per
target, and for C2 the attack outcomes by target, attack id and consultation
outcome, a 50-tick timeline and a few sample rows. `render(data, template)`
puts the JSON into `ui/c2near_report.html`; `write_report(out_dir)` writes
`<out>/report.html`.

The page needs no server: everything is inline and it opens from `file://`.
It reads the files the driver and `--analyze` wrote and nothing else; the
large `events.jsonl` is never parsed here (the infrastructure failures are
read from `verify.json` and `measurement.json` instead). Nothing under
`results/normal/` is read or written.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..agents.subagents.sorting_subagents import ROUTES
from . import c2near_system_override as spec
from .collapse import COLLAPSE
from .system_override import CORPUS, message_by_id

#: The template, beside the other standalone pages.
TEMPLATE = Path(__file__).resolve().parent.parent / "ui" / "c2near_report.html"
PLACEHOLDER = "/*__DATA__*/null"

#: The series columns the page draws, in `series.csv` column names.
SERIES_COLUMNS = ["tick", "arrivals", "arrival_refused", "dispatched", "backlog",
                  "robots_available", "robots_charging", "stations", "routes_open",
                  "messages", "targeted_consultations", "override_delivered",
                  "gate_accepted", "gate_rejected", "llm_failed"]
#: The trailing window of the throughput line (the criterion's `window`).
THROUGHPUT_WINDOW = int(COLLAPSE["window"])
TIMELINE_BIN = 50
RATE_BIN = 100
SAMPLE_ROWS = 24
TEXT_CHARS = 300
CONDITION_ORDER = ("N", "C0", "C2")


# ------------------------------------------------------------------ reading
def _read_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def _read_series(path: Path) -> Dict[str, List[Any]]:
    """The wanted columns of `series.csv` as arrays, plus the DK-RMM state column."""
    columns: Dict[str, List[Any]] = {key: [] for key in SERIES_COLUMNS}
    states: List[str] = []
    if not path.exists():
        return {**columns, "dkrmm_state": states}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            for key in SERIES_COLUMNS:
                columns[key].append(_int(raw.get(key)))
            states.append(str(raw.get("dkrmm_state") or ""))
    return {**columns, "dkrmm_state": states}


def _cumulative(values: Sequence[int]) -> List[int]:
    out: List[int] = []
    total = 0
    for value in values:
        total += int(value)
        out.append(total)
    return out


def _trailing(values: Sequence[int], window: int) -> List[int]:
    """Sum over (i - window, i], one per index: the criterion's throughput."""
    prefix = [0]
    for value in values:
        prefix.append(prefix[-1] + int(value))
    return [prefix[i + 1] - prefix[max(0, i + 1 - window)] for i in range(len(values))]


def _state_sequence(ticks: Sequence[int], states: Sequence[str]) -> List[List[Any]]:
    """`[[tick, state], ...]`: the first tick of every DK-RMM state change."""
    out: List[List[Any]] = []
    last: Optional[str] = None
    for tick, state in zip(ticks, states):
        if state != last:
            out.append([int(tick), state])
            last = state
    return out


def _excerpt(fault: Dict[str, Any]) -> str:
    """The detail of a fired fault, in one line, without its bookkeeping keys."""
    skip = {"fault_id", "tick", "mechanism", "experiment", "condition"}
    parts: List[str] = []
    for key, value in fault.items():
        if key in skip:
            continue
        if isinstance(value, (list, tuple)):
            text = ", ".join(str(v) for v in value) if value else "none"
            if len(value) > 6:
                text = ", ".join(str(v) for v in value[:6]) + f", +{len(value) - 6}"
        elif isinstance(value, dict):
            text = "; ".join(f"{k}={v}" for k, v in value.items()) or "none"
        elif isinstance(value, float):
            text = f"{value:.4g}"
        else:
            text = str(value)
        parts.append(f"{key}: {text}")
    return "; ".join(parts)


def _verify(data: Optional[Dict[str, Any]], totals: Dict[str, Any]) -> Dict[str, Any]:
    """The model verification and the infrastructure failures of a run."""
    data = data or {}
    served = data.get("served_models") if isinstance(data.get("served_models"), dict) else {}
    llm = data.get("llm") if isinstance(data.get("llm"), dict) else {}
    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    outcomes = llm.get("outcomes") if isinstance(llm.get("outcomes"), dict) else {}
    return {
        "found": bool(data),
        "mode": data.get("mode"),
        "ok": data.get("ok"),
        "note": data.get("note"),
        "model": settings.get("model") or identity.get("model"),
        "identity_ok": identity.get("ok"),
        "identity_problems": list(identity.get("problems") or []),
        "served_models": {str(k): _int(v) for k, v in served.items()},
        "served_by_configured_model": _int(data.get("served_by_configured_model", 0)),
        "served_by_other_models": list(data.get("served_by_other_models") or []),
        # Calls no model served (empty served-model key): the infrastructure
        # failures the driver recorded, read here rather than from the log.
        "calls_unserved": _int(served.get("", 0)),
        "model_decisions": _int(llm.get("model_decisions", 0)),
        "consult_outcomes": {str(k): _int(v) for k, v in outcomes.items()},
        "mean_latency_ms": llm.get("mean_latency_ms"),
        "llm_failed_targeted": _int(totals.get("llm_failed", 0)),
    }


# --------------------------------------------------------------- decisions
def _target_counts(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {t: {"n": 0, "changed": 0, "accepted": 0}
                                      for t in spec.TARGETS}
    for row in rows:
        cell = out.get(str(row.get("actor")))
        if cell is None:
            continue
        cell["n"] += 1
        cell["changed"] += 1 if row.get("changed_vs_rule") else 0
        cell["accepted"] += 1 if row.get("status") == "llm_accepted" else 0
    return out


def _rate_bins(rows: Sequence[Dict[str, Any]], width: int) -> List[List[int]]:
    """`[[bin_start, n, changed], ...]` over the decision rows, bins of `width` ticks."""
    bins: Dict[int, List[int]] = {}
    for row in rows:
        start = (_int(row.get("tick")) // width) * width
        cell = bins.setdefault(start, [start, 0, 0])
        cell[1] += 1
        cell[2] += 1 if row.get("changed_vs_rule") else 0
    return [bins[k] for k in sorted(bins)]


def _decisions(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list((data or {}).get("rows") or [])
    summary = dict((data or {}).get("summary") or {})
    per_target = _target_counts(rows)
    return {
        "found": data is not None,
        "n": len(rows),
        "changed": sum(1 for r in rows if r.get("changed_vs_rule")),
        "accepted": _int(summary.get("accepted", 0)),
        "rejected_by_gate": _int(summary.get("rejected_by_gate", 0)),
        "llm_failed": _int(summary.get("llm_failed", 0)),
        "rate": summary.get("changed_vs_rule_rate"),
        "by_status": summary.get("by_status") or {},
        "by_validation": summary.get("by_validation") or {},
        "by_kind": summary.get("by_kind") or {},
        "per_target": per_target,
        "bins": _rate_bins(rows, RATE_BIN),
        "bin_width": RATE_BIN,
    }


# ------------------------------------------------------------------ attack
def _attack(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if data is None:
        return None
    rows = list(data.get("rows") or [])
    summary = dict(data.get("summary") or {})
    cells: Dict[tuple, int] = {}
    timeline: Dict[int, Dict[str, int]] = {}
    by_attack: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("target")), str(row.get("attack_id")),
               str(row.get("consult_outcome")))
        cells[key] = cells.get(key, 0) + 1
        attack = by_attack.setdefault(str(row.get("attack_id")), {
            "attack_id": str(row.get("attack_id")), "target": str(row.get("target")),
            "index": row.get("index"), "delivered": 0, "decided": 0, "model_failed": 0,
            "other": 0, "accepted": 0, "rejected": 0, "llm_failed": 0, "changed_vs_rule": 0,
            "complied": 0, "evaluable": 0, "proposed_complied": 0})
        attack["delivered"] += 1
        attack["decided"] += 1 if row.get("consult_outcome") == "decided" else 0
        attack["model_failed"] += 1 if row.get("consult_outcome") == "model_failed" else 0
        attack["other"] += 1 if row.get("consult_outcome") not in ("decided", "model_failed") \
            else 0
        attack["accepted"] += 1 if row.get("accepted") else 0
        attack["rejected"] += 1 if row.get("status") == "llm_rejected" else 0
        attack["llm_failed"] += 1 if row.get("status") == "llm_failed" else 0
        attack["changed_vs_rule"] += 1 if row.get("changed_vs_rule") else 0
        attack["complied"] += 1 if row.get("complied") is True else 0
        attack["evaluable"] += 1 if row.get("complied") is not None else 0
        attack["proposed_complied"] += 1 if row.get("proposed_complied") is True else 0
        start = (_int(row.get("tick")) // TIMELINE_BIN) * TIMELINE_BIN
        cell = timeline.setdefault(start, {"bin": start, "delivered": 0, "decided": 0,
                                           "model_failed": 0, "other": 0, "accepted": 0,
                                           "rejected": 0, "complied": 0})
        cell["delivered"] += 1
        outcome = row.get("consult_outcome")
        if outcome == "decided":
            cell["decided"] += 1
        elif outcome == "model_failed":
            cell["model_failed"] += 1
        else:
            cell["other"] += 1
        if row.get("accepted"):
            cell["accepted"] += 1
        if row.get("status") == "llm_rejected":
            cell["rejected"] += 1
        if row.get("complied") is True:
            cell["complied"] += 1
    samples: List[Dict[str, Any]] = []
    for row in rows[:SAMPLE_ROWS]:
        attack_id = str(row.get("attack_id") or "")
        message = message_by_id(attack_id) or {}
        text = str(message.get("text") or "")
        if len(text) > TEXT_CHARS:
            text = text[:TEXT_CHARS].rstrip() + "..."
        samples.append({
            "tick": row.get("tick"), "target": row.get("target"), "attack_id": attack_id,
            "index": row.get("index"), "decision": row.get("decision"),
            "options": len(row.get("options") or []),
            "consult_outcome": row.get("consult_outcome"),
            "proposed_choice": row.get("proposed_choice"),
            "final_choice": row.get("final_choice"), "rule_choice": row.get("rule_choice"),
            "accepted": bool(row.get("accepted")), "gate_verdict": row.get("gate_verdict"),
            "status": row.get("status"), "complied": row.get("complied"),
            "complied_reason": row.get("complied_reason"),
            "proposed_complied": row.get("proposed_complied"),
            "text": text,
        })
    return {
        "found": True,
        "rows": len(rows),
        "summary": summary,
        "corpus_fingerprint": data.get("corpus_fingerprint"),
        "cells": [{"target": t, "attack_id": a, "consult_outcome": o, "n": n}
                  for (t, a, o), n in sorted(cells.items())],
        "by_attack_id": [by_attack[k] for k in sorted(by_attack)],
        "timeline": [timeline[k] for k in sorted(timeline)],
        "timeline_bin": TIMELINE_BIN,
        "samples": samples,
        "samples_of": len(rows),
    }


# --------------------------------------------------------------------- runs
def _run(run_dir: Path, cond_id: str, seed: int) -> Dict[str, Any]:
    done = _read_json(run_dir / "done.json") or {}
    measurement = _read_json(run_dir / "measurement.json") or {}
    totals = measurement.get("totals") if isinstance(measurement.get("totals"), dict) else {}
    series = _read_series(run_dir / "series.csv")
    ticks = series["tick"]
    states = series.pop("dkrmm_state")
    series["cum_dispatched"] = _cumulative(series["dispatched"])
    series["cum_refused"] = _cumulative(series["arrival_refused"])
    series["throughput"] = _trailing(series["dispatched"], THROUGHPUT_WINDOW)
    dkrmm = measurement.get("dkrmm") if isinstance(measurement.get("dkrmm"), dict) else {}
    current = dkrmm.get("current") if isinstance(dkrmm.get("current"), dict) else {}
    faults = [f for f in (measurement.get("faults_applied") or []) if isinstance(f, dict)]
    per_route = measurement.get("per_route") if isinstance(measurement.get("per_route"), dict) \
        else {}
    return {
        "condition": cond_id,
        "seed": seed,
        "key": f"{cond_id}/s{seed}",
        "mode": done.get("mode") or measurement.get("mode"),
        "ticks": done.get("ticks") or measurement.get("ticks"),
        "interrupted": bool(measurement.get("interrupted", False)),
        "fingerprint": done.get("fingerprint"),
        "rows": len(ticks),
        "last_tick": ticks[-1] if ticks else None,
        "series": series,
        "totals": totals,
        "fault_ticks": {str(k): _int(v) for k, v in (measurement.get("fault_ticks") or {}).items()},
        "faults": [{"fault_id": f.get("fault_id"), "tick": f.get("tick"),
                    "mechanism": f.get("mechanism"), "detail": _excerpt(f)} for f in faults],
        "per_route": {route: per_route.get(route, {}) for route in ROUTES},
        "dkrmm": {
            "final_state": current.get("state") or (states[-1] if states else ""),
            "status": current.get("status"),
            "severity": current.get("severity"),
            "evidence": list(current.get("evidence") or [])[:4],
            "assessments": dkrmm.get("assessments"),
            "sequence": _state_sequence(ticks, states),
        },
        "verify": _verify(_read_json(run_dir / "verify.json"), totals),
        "decisions": _decisions(_read_json(run_dir / "llm_decisions.json")),
        "attack": _attack(_read_json(run_dir / "attack_outcomes.json")) if cond_id == "C2"
        else None,
    }


def _seed_dirs(cond_dir: Path) -> List[tuple]:
    out: List[tuple] = []
    if not cond_dir.is_dir():
        return out
    for path in sorted(cond_dir.iterdir()):
        if not path.is_dir() or not path.name.startswith("s"):
            continue
        try:
            out.append((int(path.name[1:]), path))
        except ValueError:
            continue
    return out


def collect(out_dir: Any) -> Dict[str, Any]:
    """
    Everything the page shows, from the results directory `out_dir`: the
    finished runs, the incomplete ones (listed, not read), and the
    `--analyze` summary when it is there.
    """
    out = Path(out_dir)
    runs: List[Dict[str, Any]] = []
    incomplete: List[Dict[str, Any]] = []
    for cond_id in CONDITION_ORDER:
        for seed, run_dir in _seed_dirs(out / cond_id):
            if (run_dir / "done.json").exists():
                runs.append(_run(run_dir, cond_id, seed))
                continue
            measurement = _read_json(run_dir / "measurement.json") or {}
            if measurement.get("interrupted"):
                reason = "interrupted (no done.json)"
            elif (run_dir / "events.jsonl").exists():
                reason = "no done.json (unfinished or still running)"
            else:
                reason = "no done.json and no events.jsonl"
            incomplete.append({"condition": cond_id, "seed": seed,
                               "path": f"{cond_id}/s{seed}", "reason": reason})
    summary = _read_json(out / "summary.json")
    if not isinstance(summary, dict) or not isinstance(summary.get("runs"), list):
        summary = None
    seeds = sorted({r["seed"] for r in runs})
    return {
        "experiment": spec.EXPERIMENT,
        "label": spec.LABEL,
        "out": str(out),
        "generated": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "conditions": {c.id: {"label": c.label, "override": c.override,
                              "operational": c.operational}
                       for c in spec.CONDITIONS.values()},
        "conditions_present": [c for c in CONDITION_ORDER if any(r["condition"] == c
                                                                   for r in runs)],
        "seeds": seeds,
        "default_seed": 11 if 11 in seeds else (seeds[0] if seeds else None),
        "targets": list(spec.TARGETS),
        "routes": list(ROUTES),
        "stress_start": spec.STRESS_START,
        "run_ticks": spec.RUN_TICKS,
        "schedule": [{"fault_id": r["fault_id"], "tick": r["tick"], "mechanism": r["mechanism"]}
                     for r in spec.schedule(spec.condition("C2"))],
        "collapse_params": dict(COLLAPSE),
        "throughput_window": THROUGHPUT_WINDOW,
        "corpus": {m["id"]: {"target": t, "index": i}
                   for t, rows in CORPUS.items() for i, m in enumerate(rows)},
        "runs": runs,
        "incomplete": incomplete,
        "summary_found": summary is not None,
        "summary": summary,
    }


# ---------------------------------------------------------------- the page
def render(data: Dict[str, Any], template_path: Any = TEMPLATE) -> str:
    """The template with `data` in its data block, as one self-contained page."""
    template = Path(template_path).read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise ValueError(f"{template_path}: no {PLACEHOLDER} placeholder")
    text = json.dumps(data, separators=(",", ":"), default=str, ensure_ascii=False)
    # Inside a <script> block the sequence `</` must not appear.
    text = text.replace("</", "<\\/")
    return template.replace(PLACEHOLDER, text, 1)


def write_report(out_dir: Any, path: Any = None, template_path: Any = TEMPLATE) -> Path:
    """Write the page for `out_dir` to `path` (default `<out>/report.html`); return the path."""
    data = collect(out_dir)
    target = Path(path) if path is not None else Path(out_dir) / "report.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(data, template_path), encoding="utf-8", newline="\n")
    return target


__all__ = ["PLACEHOLDER", "SERIES_COLUMNS", "TEMPLATE", "collect", "render", "write_report"]
