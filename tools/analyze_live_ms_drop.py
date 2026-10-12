"""
The live M-S-DROP experiment, read from the run directories the live runner
keeps (`python main.py --api --experiment-dir ROOT --stop-at 2800`).

Usage (from the repository root):

    python tools/analyze_live_ms_drop.py \
        --condition rules=results/m_s_drop_crewai/live_rules \
        --condition model=results/m_s_drop_crewai/live \
        --out results/m_s_drop_crewai/live_analysis

Each `--condition NAME=ROOT` is a root holding `MS-DROP/s<seed>/` and its
no-drop control `N/s<seed>/`. For every run directory found, what is read and
from where:

events      `tools/analyze_ms_drop_model.analyze_run` over `events.jsonl`:
            decisions (all, eligible, accepted, refused), consultations,
            model calls (ok / failed, served model, latency), messages sent /
            dropped / delivered by type, robot commands applied, operations.
traces      `decision_traces.jsonl`, `message_traces.jsonl` and
            `trace_summary.json` (the identifier links of
            `observability/decision_trace.py`): the four pathway message kinds
            by delivery outcome, robot commands applied, and per decision
            phase the stages (reply answered, eligible, consulted, model
            calls, gate, subject messages and their delivery, robot commands
            applied). Later robot commands are joined to a decision by
            `relink_later`, the tracer's corrected task-id rule, so runs kept
            before that correction are read by the same rule.
zones       `zone_backlog.csv`: intake, sorting, storage, dispatch, carried
            and total at fixed ticks and at the maximum; arrivals,
            completions and dock refusals before and after the fault; whether
            every row reconciles.
dkrmm       `dkrmm_assessments.jsonl` (every reading as it was made): raw
            state counts before and after the fault, the first DEVIATING /
            UNSTABLE / RCT at or after it, the final state, and every reading
            at or after the fault whose state was STABLE or RECOVERY while
            the intake count rose over its window (the readings the study's
            four-state strip paints green).
collapse    `stress/collapse.classify` of the run's `series.csv` against the
            `N/s<seed>` control of the same condition, unchanged criterion,
            only when both have the same mode and the same ticks.
status      `status.json`, `done.json` and `verify.json` as written.

Nothing is computed that a file does not record; a missing file is reported
as missing. Writes `<out>/analysis.json` and `<out>/analysis.md`, never over
an existing file and never inside `results/normal`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from analyze_ms_drop_model import analyze_run  # noqa: E402

from post_office.stress.collapse import classify  # noqa: E402
from post_office.stress.measure import read_series  # noqa: E402

FAULT_TICK = 400
AT_TICKS = (399, 400, 800, 1200, 1600, 2000, 2400, 2800)
ZONES = ("intake", "sorting", "storage", "dispatch", "carried", "total")
KINDS = ("ROUTE_REQUEST", "RESOURCE_REQUEST", "TASK_ASSIGNMENT", "ROBOT_COMMAND")


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def run_dirs(root: Path, scenario: str) -> List[Path]:
    base = root / scenario
    if not base.is_dir():
        return []
    out = []
    for path in sorted(base.iterdir()):
        if path.is_dir() and path.name.startswith("s") and path.name[1:].isdigit():
            out.append(path)
    return out


# ------------------------------------------------------------------ zones
def zones_of(run: Path, fault: int) -> Dict[str, Any]:
    path = run / "zone_backlog.csv"
    if not path.exists():
        return {"available": False}
    rows = []
    with path.open(encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row = {k: (int(v) if v not in ("", "True", "False") and k != "reconciled" else v)
                   for k, v in raw.items()}
            rows.append(row)
    by_tick = {r["tick"]: r for r in rows}
    at = {str(t): {z: by_tick[t][z] for z in ZONES} for t in AT_TICKS if t in by_tick}
    peak = max(rows, key=lambda r: r["total"]) if rows else None
    peak_intake = max(rows, key=lambda r: r["intake"]) if rows else None

    def flows(pred) -> Dict[str, int]:
        keep = [r for r in rows[1:] if pred(r["tick"])]
        return {k: sum(int(r[k]) for r in keep)
                for k in ("arrivals", "dock_refusals", "completions", "returned", "gate_refused")}

    return {"available": True, "ticks": len(rows) - 1, "at": at,
            "peak_total": {"tick": peak["tick"], "total": peak["total"]} if peak else None,
            "peak_intake": {"tick": peak_intake["tick"], "intake": peak_intake["intake"]}
            if peak_intake else None,
            "flows_pre": flows(lambda t: t < fault), "flows_post": flows(lambda t: t >= fault),
            "rows_not_reconciled": sum(1 for r in rows[1:] if r["reconciled"] != "True"),
            "_rows": rows}


# ------------------------------------------------------------------ dkrmm
def dkrmm_of(run: Path, fault: int, zone_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    readings = _jsonl(run / "dkrmm_assessments.jsonl")
    if not readings:
        return {"available": False}
    intake = {r["tick"]: r["intake"] for r in zone_rows}
    pre: Dict[str, int] = {}
    post: Dict[str, int] = {}
    first: Dict[str, int] = {}
    quiet_growth = []
    previous_tick = 0
    for reading in readings:
        tick, state = int(reading["tick"]), str(reading["state"])
        bucket = post if tick >= fault else pre
        bucket[state] = bucket.get(state, 0) + 1
        if tick >= fault:
            first.setdefault(state, tick)
            if state in ("STABLE", "RECOVERY") and previous_tick in intake and tick in intake:
                rise = intake[tick] - intake[previous_tick]
                if rise > 0:
                    quiet_growth.append({
                        "tick": tick, "state": state, "window_from": previous_tick,
                        "intake_from": intake[previous_tick], "intake_to": intake[tick],
                        "evidence": reading.get("evidence"), "kinds": reading.get("kinds"),
                        "enough_activity": reading.get("enough_activity"),
                        "failure_rate": (reading.get("indicators") or {}).get(
                            "communication_failure_rate"),
                        "not_evaluated": reading.get("not_evaluated")})
        previous_tick = tick
    last = readings[-1]
    return {"available": True, "assessments": len(readings),
            "every": readings[1]["tick"] - readings[0]["tick"] if len(readings) > 1 else None,
            "counts_pre": pre, "counts_post": post,
            "first_after_fault": {k: first[k] for k in ("DEVIATING", "UNSTABLE", "RCT",
                                                        "STABLE", "RECOVERY") if k in first},
            "final": last["state"], "final_tick": last["tick"],
            "indicators_final": sorted((last.get("indicators") or {}).keys()),
            "stable_or_recovery_with_intake_rising_after_fault": quiet_growth}


# ------------------------------------------------------------------ traces
def task_ids(run: Path) -> set:
    """Every task id the run's registry created (`task_created` events)."""
    out = set()
    path = run / "events.jsonl"
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if '"task_created"' in line:
                event = json.loads(line)
                if event.get("topic") == "task_created":
                    task = (event.get("detail") or {}).get("task_id")
                    if task:
                        out.add(str(task))
    return out


def relink_later(decisions: List[Dict[str, Any]], messages: List[Dict[str, Any]],
                 tasks: set) -> Dict[str, str]:
    """
    The decision each later ROBOT_COMMAND belongs to, by the tracer's rule
    as corrected on 2026-10-12: the latest decision (by event sequence)
    whose subject is the command's task id (`content.task_id`, or a
    `correlation_id` the registry created as a task), made before it. A
    command attached as a decision's effect keeps that decision. Runs kept
    before the correction could also join on a parcel id; this re-derives
    every such link from the recorded identifiers, so all runs are read by
    one rule.
    """
    by_subject: Dict[str, List[tuple]] = {}
    for d in decisions:
        if d.get("subject") in tasks:
            by_subject.setdefault(d["subject"], []).append((d["seq"], d["decision_id"]))
    for rows in by_subject.values():
        rows.sort()
    out: Dict[str, str] = {}
    for m in messages:
        if m.get("type") != "ROBOT_COMMAND":
            continue
        if m.get("link") == "effect" and m.get("decision_id"):
            out[m["message_id"]] = m["decision_id"]
            continue
        keys = [str(m["task_id"])] if m.get("task_id") else []
        if m.get("correlation_id") in tasks:
            keys.append(m["correlation_id"])
        for key in keys:
            earlier = [d for seq, d in by_subject.get(key, []) if seq < m["seq"]]
            if earlier:
                out[m["message_id"]] = earlier[-1]
                break
    return out


def traces_of(run: Path, fault: int) -> Dict[str, Any]:
    summary = _read_json(run / "trace_summary.json")
    messages = _jsonl(run / "message_traces.jsonl")
    decisions = _jsonl(run / "decision_traces.jsonl")
    if summary is None and not messages:
        return {"available": False}
    kinds: Dict[str, Dict[str, Dict[str, int]]] = {}
    for m in messages:
        phase = "pre" if m["tick"] < fault else "post"
        row = kinds.setdefault(phase, {}).setdefault(m["kind"], {})
        state = m["outcome"]["state"]
        row["sent"] = row.get("sent", 0) + 1
        row[state] = row.get(state, 0) + 1
        if (m.get("applied") or {}).get("state") == "applied":
            row["applied"] = row.get("applied", 0) + 1
    # Stage counts per decision phase. Effects come as recorded; later
    # commands are re-derived (`relink_later`).
    links = relink_later(decisions, messages, task_ids(run))
    by_id = {m["message_id"]: m for m in messages}
    phase_of = {d["decision_id"]: ("pre" if d["tick"] < fault else "post") for d in decisions}
    stages: Dict[str, Dict[str, int]] = {}
    for d in decisions:
        st = stages.setdefault(phase_of[d["decision_id"]], {})
        add = lambda key, n=1: st.__setitem__(key, st.get(key, 0) + n)  # noqa: E731
        add("decisions")
        add("answer_a_reply", int(bool(d.get("request"))))
        add("eligible", int(bool(d.get("eligible"))))
        consult = d.get("consultation")
        add("consulted", int(consult is not None))
        if consult:
            calls = consult.get("llm_calls") or []
            add("model_calls", len(calls))
            add("model_calls_failed", sum(1 for c in calls if c.get("error") or c.get("status") != 200))
        status = d.get("status") or ""
        add("status_" + status)
        add("gate_refused", int(d.get("validation") in ("policy", "state")))
        sent = [by_id[m["message_id"]] for m in d.get("messages") or [] if m["message_id"] in by_id]
        add("sent_subject_message", int(bool(sent)))
        add("subject_messages", len(sent))
        add("subject_messages_received",
            sum(1 for m in sent if m["outcome"]["state"] in ("received", "received late")))
        cmds = [m for m in sent if m["type"] == "ROBOT_COMMAND"]
        add("robot_commands", len(cmds))
        add("robot_commands_applied",
            sum(1 for m in cmds if (m.get("applied") or {}).get("state") == "applied"))
    for mid, decision_id in links.items():
        m = by_id[mid]
        if m.get("link") == "effect":
            continue
        st = stages.setdefault(phase_of.get(decision_id, "pre"), {})
        st["later_commands"] = st.get("later_commands", 0) + 1
        if (m.get("applied") or {}).get("state") == "applied":
            st["later_commands_applied"] = st.get("later_commands_applied", 0) + 1
    relinked = sum(1 for mid, d in links.items()
                   if by_id[mid].get("link") != "effect" and by_id[mid].get("decision_id") != d)
    return {"available": True, "by_kind": kinds, "stages": stages,
            "later_links_rederived_differing_from_recorded": relinked, "summary": summary}


# ------------------------------------------------------------------ one run
def run_of(run: Path, fault: int) -> Dict[str, Any]:
    zones = zones_of(run, fault)
    rows = zones.pop("_rows", []) if zones.get("available") else []
    events = analyze_run(run, fault_tick=fault) if (run / "events.jsonl").exists() else None
    verify = _read_json(run / "verify.json") or {}
    return {"dir": str(run), "seed": int(run.name[1:]),
            "status": _read_json(run / "status.json"),
            "done": (run / "done.json").exists(),
            "definition": _read_json(run / "definition.json"),
            "verify": {k: verify.get(k) for k in ("mode", "ok", "served_models",
                                                  "served_by_configured_model",
                                                  "served_by_other_models", "calls_failed",
                                                  "identity", "llm")},
            "events": events, "zones": zones, "dkrmm": dkrmm_of(run, fault, rows),
            "traces": traces_of(run, fault)}


def collapse_of(run: Path, control: Path) -> Dict[str, Any]:
    mine, theirs = _read_json(run / "definition.json") or {}, _read_json(control / "definition.json") or {}
    if not (control / "series.csv").exists():
        return {"outcome": "no control", "control": str(control)}
    problems = [f"{key} {mine.get(key)!r} vs control {theirs.get(key)!r}"
                for key in ("mode", "ticks") if mine.get(key) != theirs.get(key)]
    if problems:
        return {"outcome": "not comparable", "reason": "; ".join(problems), "control": str(control)}
    verdict = classify(read_series(run / "series.csv"), read_series(control / "series.csv"))
    return {**verdict, "control": str(control)}


def analyze(conditions: Dict[str, Path], fault: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"fault_tick": fault, "conditions": {}}
    for name, root in conditions.items():
        block: Dict[str, Any] = {"root": str(root), "MS-DROP": [], "N": []}
        for scenario in ("MS-DROP", "N"):
            for run in run_dirs(root, scenario):
                row = run_of(run, fault)
                if scenario == "MS-DROP":
                    row["collapse"] = collapse_of(run, root / "N" / run.name)
                block[scenario].append(row)
        out["conditions"][name] = block
    return out


# ------------------------------------------------------------------ markdown
def _g(d: Any, *keys: str, default: Any = "-") -> Any:
    for key in keys:
        if not isinstance(d, dict) or key not in d:
            return default
        d = d[key]
    return d


def _table(head: List[str], rows: List[List[Any]]) -> List[str]:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join("-" if v is None else str(v) for v in row) + " |" for row in rows]
    return lines + [""]


def markdown(result: Dict[str, Any]) -> str:
    fault = result["fault_tick"]
    lines = [f"# Live M-S-DROP experiment, measured", "",
             f"Fault tick {fault}; `pre` is before it, `post` from it on. Every figure is read "
             "from the run directories named below; `-` means the file does not record it.", ""]
    runs = []
    for cond, block in result["conditions"].items():
        for scenario in ("MS-DROP", "N"):
            for r in block[scenario]:
                runs.append((cond, scenario, r))
    lines += ["## Runs", ""]
    lines += _table(["condition", "scenario", "seed", "mode", "status", "tick", "done",
                     "served models", "model calls failed"],
                    [[c, s, r["seed"], _g(r, "definition", "mode"), _g(r, "status", "status"),
                      _g(r, "status", "tick"), r["done"],
                      json.dumps(_g(r, "verify", "served_models", default=None)),
                      _g(r, "verify", "calls_failed")] for c, s, r in runs])
    lines += ["## Decisions, consultations and model calls", ""]
    rows = []
    for c, s, r in runs:
        e = r["events"] or {}
        for ph in ("pre", "post"):
            d = _g(e, "decision_totals", ph, default={})
            cons = _g(e, "consultations", ph, default={})
            calls = _g(e, "llm_calls", ph, default={})
            rows.append([c, s, r["seed"], ph, _g(d, "all"), _g(d, "eligible"),
                         sum((_g(cons, "opened", default={}) or {}).values())
                         if isinstance(_g(cons, "opened", default=None), dict) else "-",
                         _g(d, "model_accepted"), _g(d, "model_rejected"),
                         _g(calls, "total"), _g(calls, "ok"), _g(calls, "failed"),
                         _g(calls, "latency", "median_ms")])
    lines += _table(["condition", "scenario", "seed", "phase", "decisions", "eligible",
                     "consultations", "model accepted", "model rejected", "model calls",
                     "ok", "failed", "median latency ms"], rows)
    lines += ["## Decision stages (identifier traces)", "",
              "Per decision phase. Later robot commands are joined to a decision by task id "
              "(`relink_later`); `relinked` counts the links that differ from those the run "
              "recorded (non-zero only for runs kept before the tracer's correction).", ""]
    rows = []
    for c, s, r in runs:
        st = _g(r, "traces", "stages", default={}) or {}
        for ph in ("pre", "post"):
            v = st.get(ph, {})
            rows.append([c, s, r["seed"], ph, v.get("decisions", 0), v.get("answer_a_reply", 0),
                         v.get("eligible", 0), v.get("consulted", 0),
                         f"{v.get('model_calls', 0)} / {v.get('model_calls_failed', 0)}",
                         f"{v.get('status_llm_accepted', 0)} / {v.get('status_llm_rejected', 0)}"
                         f" / {v.get('status_llm_failed', 0)}",
                         v.get("gate_refused", 0),
                         f"{v.get('subject_messages_received', 0)} of {v.get('subject_messages', 0)}",
                         f"{v.get('robot_commands_applied', 0)} of {v.get('robot_commands', 0)}",
                         f"{v.get('later_commands_applied', 0)} of {v.get('later_commands', 0)}",
                         _g(r, "traces", "later_links_rederived_differing_from_recorded")
                         if ph == "pre" else ""])
    lines += _table(["condition", "scenario", "seed", "phase", "decisions", "answer a reply",
                     "eligible", "consulted", "model calls / failed",
                     "model accepted / rejected / failed", "gate refused",
                     "subject messages received", "robot commands applied",
                     "later commands applied", "relinked"], rows)
    lines += ["## Pathway messages (identifier traces)", "",
              "Per kind: sent / received on time / dropped / pending at the end; robot "
              "commands also applied (a `command_<operation>` event matched by sender, "
              "robot and correlation id in the tick the robot took the command).", ""]
    rows = []
    for c, s, r in runs:
        kinds = _g(r, "traces", "by_kind", default={}) or {}
        for ph in ("pre", "post"):
            k = kinds.get(ph, {})
            cells = []
            for kind in KINDS:
                v = k.get(kind, {})
                cell = (f"{v.get('sent', 0)} / {v.get('received', 0)} / {v.get('dropped', 0)}"
                        f" / {v.get('pending', 0)}")
                if kind == "ROBOT_COMMAND":
                    cell += f" · applied {v.get('applied', 0)}"
                cells.append(cell)
            rows.append([c, s, r["seed"], ph] + cells)
    lines += _table(["condition", "scenario", "seed", "phase"] + list(KINDS), rows)
    lines += ["## Backlog by zone", "",
              "Parcels inside the building, by zone, at the end of the tick named "
              "(`zone_backlog.csv`); each parcel is in exactly one zone or on a robot.", ""]
    rows = []
    for c, s, r in runs:
        z = r["zones"]
        if not z.get("available"):
            rows.append([c, s, r["seed"], "missing"] + ["-"] * 6)
            continue
        for t in ("399", "800", "1600", "2800"):
            v = z["at"].get(t, {})
            rows.append([c, s, r["seed"], t] + [v.get(k, "-") for k in ZONES])
    lines += _table(["condition", "scenario", "seed", "tick"] + list(ZONES), rows)
    rows = []
    for c, s, r in runs:
        z = r["zones"]
        if not z.get("available"):
            continue
        rows.append([c, s, r["seed"],
                     f"{z['flows_pre']['arrivals']} / {z['flows_post']['arrivals']}",
                     f"{z['flows_pre']['completions']} / {z['flows_post']['completions']}",
                     f"{z['flows_pre']['dock_refusals']} / {z['flows_post']['dock_refusals']}",
                     f"{z['peak_intake']['intake']} at {z['peak_intake']['tick']}",
                     z["rows_not_reconciled"]])
    lines += _table(["condition", "scenario", "seed", "arrivals pre / post",
                     "left on a van pre / post", "dock refusals pre / post", "peak intake",
                     "rows not reconciled"], rows)
    lines += ["## DK-RMM (current monitor, every reading as made)", ""]
    rows = []
    for c, s, r in runs:
        k = r["dkrmm"]
        if not k.get("available"):
            rows.append([c, s, r["seed"], "missing"] + ["-"] * 5)
            continue
        post = k["counts_post"]
        rows.append([c, s, r["seed"], k["assessments"],
                     " / ".join(str(post.get(x, 0)) for x in
                                ("STABLE", "RECOVERY", "DEVIATING", "UNSTABLE", "RCT")),
                     " / ".join(str(k["first_after_fault"].get(x, "-")) for x in
                                ("DEVIATING", "UNSTABLE", "RCT")),
                     k["final"],
                     len(k["stable_or_recovery_with_intake_rising_after_fault"])])
    lines += _table(["condition", "scenario", "seed", "readings",
                     "post: STABLE / RECOVERY / DEVIATING / UNSTABLE / RCT",
                     "first post DEVIATING / UNSTABLE / RCT", "final",
                     "post readings STABLE or RECOVERY with intake rising"], rows)
    lines += ["## Collapse (criterion unchanged, against N of the same seed and condition)", ""]
    rows = []
    for c, s, r in runs:
        if s != "MS-DROP":
            continue
        v = r.get("collapse") or {}
        crit = v.get("collapse_criterion")
        rows.append([c, r["seed"], v.get("outcome"),
                     "+".join(crit) if isinstance(crit, list) else crit,
                     v.get("collapse_tick"), v.get("first_degraded_tick"),
                     v.get("held_to_end"), v.get("reason", "")])
    lines += _table(["condition", "seed", "outcome", "criterion", "collapse tick",
                     "first degraded tick", "held to end", "note"], rows)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--condition", action="append", required=True,
                        help="NAME=ROOT, a root holding MS-DROP/s<seed> and N/s<seed>")
    parser.add_argument("--fault-tick", type=int, default=FAULT_TICK)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.out.resolve()
    if "results" in out.parts and "normal" in out.parts[out.parts.index("results"):]:
        parser.error("refusing to write inside results/normal")
    targets = [out / "analysis.json", out / "analysis.md"]
    existing = [str(t) for t in targets if t.exists()]
    if existing:
        parser.error("refusing to overwrite: " + ", ".join(existing))
    conditions: Dict[str, Path] = {}
    for item in args.condition:
        name, _, root = item.partition("=")
        if not name or not root:
            parser.error(f"--condition takes NAME=ROOT, not {item!r}")
        conditions[name] = Path(root)
    result = analyze(conditions, args.fault_tick)
    if not any(block["MS-DROP"] or block["N"] for block in result["conditions"].values()):
        parser.error("no MS-DROP/s<seed> or N/s<seed> run directory under the given roots")
    out.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    targets[1].write_text(markdown(result), encoding="utf-8")
    print(f"wrote {targets[0]} and {targets[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
