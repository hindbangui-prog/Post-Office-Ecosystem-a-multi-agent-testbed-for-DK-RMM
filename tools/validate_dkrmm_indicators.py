"""
Validation runs for the DK-RMM operational indicators (design of 2026-10-12,
section 8). Rules only, no model, headless.

    PYTHONHASHSEED=0 python tools/validate_dkrmm_indicators.py --out DIR [--ticks N] [--seeds NORMAL FAULT] [--old-tree PATH]

Three scenarios of `post_office.stress.collapse_scenarios`, each built from
`normal_config()` with the fault applied from outside by `CollapseFaults`:

- Normal (`N`), the normal seed, at 300 ticks and at `--ticks`: the event
  stream hashed with the monitor attached and without it (the two must be
  equal: the monitor is an observer), and the per-window DK-RMM states
  "before" (the code at the `--old-tree` worktree, run in a subprocess from
  that directory) and "after" (this tree), with the windows whose state
  changed listed side by side.
- M-S-DROP (`ms-drop`), the fault seed, at `--ticks`: per assessment window
  the delivery counts, the failure rate, the backlog, the throughput, the
  saturation and the kinds; the first tick of each state; the first window
  after the fault with a failure rate at or above 0.99; whether the backlog
  grew and then stopped at the dock cap; the throughput after the fault.
- M-S-DELAY (`ms-delay`), the fault seed, at `--ticks`: the same, plus the
  late events and the distribution of `late_by` read from the events, the
  drops (expected none), the failure rate set beside the routing share of
  the attempted messages (computed from the events three ways: one end is
  ROUTING, one end is in the routing group, the scenario's own
  `is_routing_related` rule), the latency mean and p95, the tail detail per
  metric and the first tick of each state.

Everything is written to `--out` as `validation.json` and `validation.md`.
Nothing is written under `results/`, and nothing under the repository.
The scenario workers run in parallel subprocesses (`--jobs`), each a fresh
interpreter with PYTHONHASHSEED=0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT.parent
DEFAULT_OUT = SCRATCH / "dkrmm_validation"
DEFAULT_OLD_TREE = SCRATCH / "old_tree"
NORMAL_SHORT = 300

#: The script run in the old worktree for the "before" state sequence. The
#: old monitor has no `evaluable`, so it prints only tick, state and kinds.
BEFORE_SCRIPT = r'''
import json, os, sys
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
root, seed, ticks = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
sys.path.insert(0, root)
from post_office.dkrmm import DKRMM
from post_office.simulation import build
from post_office.stress import collapse_scenarios as spec
scn = spec.scenario("N")
eco = build(seed, config=spec.config(scn), run_id=f"before-N-s{seed}", scenario="normal")
monitor = DKRMM(eco).attach()
faults = spec.CollapseFaults(eco, scn)
eco.start()
for t in range(1, ticks + 1):
    faults.before_tick(t)
    eco.step()
    monitor.tick()
rows = [{"tick": a.tick, "state": a.state.value, "kinds": list(a.kinds)} for a in monitor.history]
counts = monitor.state()["counts"]
eco.close()
print(json.dumps({"windows": rows, "counts": counts, "assessments": len(rows)}))
'''


# ------------------------------------------------------------------ running
class StreamTap:
    """A read-only subscriber: hashes every event (less run_id and wall_clock) and keeps the ones the analysis reads."""

    KEEP = ("message", "subagent_message", "message_dropped",
            "agent_message_received", "van_departed")

    def __init__(self, keep: bool = True) -> None:
        self.hash = hashlib.sha256()
        self.count = 0
        self.kept: List[Dict[str, Any]] = []
        self._keep = keep

    def __call__(self, event: Any) -> None:
        row = event.as_dict()
        row.pop("run_id", None)
        row.pop("wall_clock", None)
        self.hash.update(json.dumps(row, sort_keys=True, default=str).encode("utf-8"))
        self.count += 1
        if self._keep and event.topic in self.KEEP:
            self.kept.append({"tick": int(event.tick), "topic": event.topic,
                              "actor": event.actor, "target": event.target,
                              "detail": dict(event.detail)})

    def digest(self) -> str:
        return self.hash.hexdigest()


def run_scenario(key: str, seed: int, ticks: int, watched: bool = True,
                 keep_events: bool = True):
    """Build, attach (or not), step. Returns (monitor or None, tap, scenario)."""
    sys.path.insert(0, str(ROOT))
    from post_office.dkrmm import DKRMM
    from post_office.simulation import build
    from post_office.stress import collapse_scenarios as spec

    scn = spec.scenario(key)
    eco = build(seed, config=spec.config(scn),
                run_id=f"validate-{scn.id}-s{seed}", scenario="normal")
    tap = StreamTap(keep=keep_events)
    eco.logger.subscribe(tap)
    monitor = DKRMM(eco).attach() if watched else None
    faults = spec.CollapseFaults(eco, scn)
    eco.start()
    for tick in range(1, ticks + 1):
        faults.before_tick(tick)
        eco.step()
        if monitor is not None:
            monitor.tick()
    eco.close()
    return monitor, tap, scn


# ----------------------------------------------------------------- reading
def _val(assessment, name: str) -> Optional[float]:
    if not assessment.evaluable.get(name, True):
        return None
    return round(float(getattr(assessment.indicators, name)), 4)


def window_row(assessment) -> Dict[str, Any]:
    """One assessment as the columns the report tables read."""
    ind = assessment.indicators
    detail = ind.detail
    delivery = detail.get("delivery") or {}
    backlog = detail.get("backlog") or {}
    resources = detail.get("resources") or {}
    tail = detail.get("tail") or {}
    dock = resources.get("dock") or {}
    return {
        "tick": assessment.tick,
        "state": assessment.state.value,
        "kinds": list(assessment.kinds),
        "not_evaluated": list(assessment.not_evaluated),
        "events": ind.events,
        "attempted": delivery.get("attempted"),
        "delivered": delivery.get("delivered"),
        "dropped": delivery.get("dropped"),
        "late": delivery.get("late"),
        "held_now": delivery.get("held_now"),
        "failure_rate": _val(assessment, "communication_failure_rate"),
        "backlog_now": backlog.get("backlog_now"),
        "backlog_growth": _val(assessment, "backlog_growth"),
        "increasing_for": backlog.get("increasing_for"),
        "by_zone": backlog.get("by_zone"),
        "task_completion_rate": _val(assessment, "task_completion_rate"),
        "completion_gap": _val(assessment, "completion_gap"),
        "resource_saturation": _val(assessment, "resource_saturation"),
        "dock": (round(dock["value"], 4) if dock.get("value") is not None else None),
        "dock_on": dock.get("on_dock"), "dock_max": dock.get("max_on_dock"),
        "dependency_graph_divergence": _val(assessment, "dependency_graph_divergence"),
        "tail_deviation": _val(assessment, "tail_deviation"),
        "tail": {m: {k: (round(v, 4) if isinstance(v, float) else v)
                     for k, v in row.items()} for m, row in tail.items()},
        "execution_latency": _val(assessment, "execution_latency"),
        "execution_latency_p95": detail.get("execution_latency_p95"),
        "activity_synchronization": _val(assessment, "activity_synchronization"),
        "severity": round(assessment.severity, 4),
        "propagation": round(ind.propagation_across_agents, 4),
    }


def first_ticks(rows: List[Dict[str, Any]]) -> Dict[str, Optional[int]]:
    return {state: next((r["tick"] for r in rows if r["state"] == state), None)
            for state in ("DEVIATING", "UNSTABLE", "RCT", "RECOVERY")}


def counts_of(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    out = {s: 0 for s in ("STABLE", "DEVIATING", "UNSTABLE", "RCT", "RECOVERY")}
    for r in rows:
        out[r["state"]] = out.get(r["state"], 0) + 1
    return out


def routing_shares(kept: List[Dict[str, Any]], start: int, ticks: int) -> Dict[str, Any]:
    """The routing share of the attempted messages after the fault, three ways, from the events."""
    sys.path.insert(0, str(ROOT))
    from post_office.stress import collapse_scenarios as spec

    group = set(spec.ROUTING_GROUP)
    types = {t.value for t in spec.ROUTING_TYPES}
    ops = set(spec.ROUTING_OPERATIONS)
    attempted = strict = in_group = by_rule = 0
    for e in kept:
        if e["topic"] not in ("message", "subagent_message") or e["tick"] < start:
            continue
        attempted += 1
        a, b = e["actor"], e["target"]
        if a == "ROUTING" or b == "ROUTING":
            strict += 1
        related = a in group or b in group
        if related:
            in_group += 1
        mtype = str(e["detail"].get("message_type") or "")
        if not related:
            if mtype in types:
                related = True
            elif mtype == "robot_command" or mtype.upper() == "ROBOT_COMMAND":
                related = str((e["detail"].get("content") or {}).get("operation", "")) in ops
        if related:
            by_rule += 1
    def share(n: int) -> Optional[float]:
        return round(n / attempted, 4) if attempted else None
    return {"attempted_after_start": attempted,
            "routing_endpoint": {"count": strict, "share": share(strict),
                                 "rule": "sender or receiver is ROUTING"},
            "routing_group": {"count": in_group, "share": share(in_group),
                              "rule": f"sender or receiver in {sorted(group)}"},
            "scenario_rule": {"count": by_rule, "share": share(by_rule),
                              "rule": "collapse_scenarios.is_routing_related: group, route types, routing robot commands"}}


def delay_facts(kept: List[Dict[str, Any]], start: int) -> Dict[str, Any]:
    late = [e for e in kept if e["topic"] == "agent_message_received"
            and int(e["detail"].get("late_by") or 0) > 0]
    dist = Counter(int(e["detail"].get("late_by") or 0) for e in late)
    attempted_after = sum(1 for e in kept if e["topic"] in ("message", "subagent_message") and e["tick"] >= start)
    late_after = sum(1 for e in late if e["tick"] >= start)
    return {"late_events": len(late),
            "late_before_start": sum(1 for e in late if e["tick"] < start),
            "late_after_start": late_after,
            "attempted_after_start": attempted_after,
            "late_over_attempted_after_start": round(late_after / attempted_after, 4) if attempted_after else None,
            "late_by_distribution": {str(k): v for k, v in sorted(dist.items())},
            "dropped_events": sum(1 for e in kept if e["topic"] == "message_dropped"),
            "attempted_total": sum(1 for e in kept if e["topic"] in ("message", "subagent_message"))}


def drop_facts(rows: List[Dict[str, Any]], kept: List[Dict[str, Any]], start: int) -> Dict[str, Any]:
    after = [r for r in rows if r["tick"] > start]
    first_99 = next((r["tick"] for r in after
                     if r["failure_rate"] is not None and r["failure_rate"] >= 0.99), None)
    growth = [r["backlog_growth"] for r in after if r["backlog_growth"] is not None]
    grew = any(g > 0 for g in growth)
    first_cap = next((r["tick"] for r in after if r["dock"] is not None and r["dock"] >= 1.0), None)
    at_cap = [r for r in after if r["dock"] is not None and r["dock"] >= 1.0]
    zero_at_cap = (bool(at_cap) and any(r["backlog_growth"] == 0 for r in at_cap))
    growth_after_cap = sorted({r["backlog_growth"] for r in at_cap if r["backlog_growth"] is not None})
    growth_past_cap = sorted({r["backlog_growth"] for r in after
                              if first_cap is not None and r["tick"] > first_cap
                              and r["backlog_growth"] is not None})
    departed_after = sum(int(e["detail"].get("parcels") or 0) for e in kept
                         if e["topic"] == "van_departed" and e["tick"] > start)
    van_events_after = sum(1 for e in kept if e["topic"] == "van_departed" and e["tick"] > start)
    loaded_after = [[e["tick"], int(e["detail"].get("parcels") or 0)] for e in kept
                    if e["topic"] == "van_departed" and e["tick"] > start
                    and int(e["detail"].get("parcels") or 0) > 0]
    last_loaded = max((t for t, _ in loaded_after), default=None)
    tcr_after = sorted({r["task_completion_rate"] for r in after if r["task_completion_rate"] is not None})
    tcr_after_last = sorted({r["task_completion_rate"] for r in after
                             if last_loaded is not None and r["tick"] > last_loaded + 60
                             and r["task_completion_rate"] is not None})
    return {"first_window_failure_rate_ge_0_99": first_99,
            "first_ticks_after_start": first_ticks(after),
            "failure_rates_after_start": [r["failure_rate"] for r in after],
            "backlog_grew_after_start": grew,
            "max_backlog_growth_after_start": max(growth) if growth else None,
            "first_window_dock_at_cap": first_cap,
            "backlog_growth_zero_at_dock_cap": zero_at_cap,
            "backlog_growth_values_at_dock_cap": growth_after_cap,
            "backlog_growth_values_past_first_cap_window": growth_past_cap,
            "parcels_departed_after_start": departed_after,
            "van_departed_events_after_start": van_events_after,
            "departures_with_parcels_after_start": loaded_after,
            "last_tick_parcels_departed": last_loaded,
            "task_completion_rates_after_start": tcr_after,
            "task_completion_rates_after_last_loaded_departure_plus_window": tcr_after_last,
            "max_resource_saturation_after_start": max((r["resource_saturation"] for r in after
                                                        if r["resource_saturation"] is not None), default=None),
            "dock_values_after_start": sorted({r["dock"] for r in after if r["dock"] is not None})}


# ----------------------------------------------------------------- workers
def worker_normal(seed: int, ticks: int) -> Dict[str, Any]:
    monitor, tap_w, _ = run_scenario("N", seed, ticks, watched=True, keep_events=False)
    _none, tap_u, _ = run_scenario("N", seed, ticks, watched=False, keep_events=False)
    rows = [window_row(a) for a in monitor.history]
    return {"scenario": "N", "seed": seed, "ticks": ticks,
            "hash_watched": tap_w.digest(), "hash_unwatched": tap_u.digest(),
            "hash_equal": tap_w.digest() == tap_u.digest(),
            "events_watched": tap_w.count, "events_unwatched": tap_u.count,
            "after": {"windows": [{"tick": r["tick"], "state": r["state"], "kinds": r["kinds"]}
                                  for r in rows],
                      "counts": monitor.state()["counts"], "assessments": len(rows)},
            "windows": rows}


def worker_fault(key: str, seed: int, ticks: int) -> Dict[str, Any]:
    sys.path.insert(0, str(ROOT))
    from post_office.stress import collapse_scenarios as spec

    monitor, tap, scn = run_scenario(key, seed, ticks, watched=True, keep_events=True)
    rows = [window_row(a) for a in monitor.history]
    out: Dict[str, Any] = {"scenario": scn.id, "preset": key, "seed": seed, "ticks": ticks,
                           "start": spec.START, "events": tap.count,
                           "counts": monitor.state()["counts"], "assessments": len(rows),
                           "first_ticks": first_ticks(rows), "windows": rows,
                           "drop": drop_facts(rows, tap.kept, spec.START)}
    if key == "ms-delay":
        out["delay"] = delay_facts(tap.kept, spec.START)
        out["delay"]["expected_late_by"] = spec.DELAY_TICKS
        out["routing_share"] = routing_shares(tap.kept, spec.START, ticks)
        after = [r for r in rows if r["tick"] > spec.START]
        rates = [r["failure_rate"] for r in after if r["failure_rate"] is not None]
        out["delay"]["failure_rate_after_start"] = {
            "min": min(rates) if rates else None, "max": max(rates) if rates else None,
            "mean": round(sum(rates) / len(rates), 4) if rates else None}
    return out


def before_normal(old_tree: Path, seed: int, ticks: int, out_dir: Path) -> Dict[str, Any]:
    script = out_dir / "_before_states.py"
    script.write_text(BEFORE_SCRIPT, encoding="utf-8")
    env = dict(os.environ, PYTHONHASHSEED="0")
    python = old_tree / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)
    proc = subprocess.run([str(python), str(script), str(old_tree), str(seed), str(ticks)],
                          cwd=str(old_tree), env=env, capture_output=True, text=True, check=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def diff_windows(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_tick_b = {r["tick"]: r for r in before}
    by_tick_a = {r["tick"]: r for r in after}
    out = []
    for tick in sorted(set(by_tick_b) | set(by_tick_a)):
        b, a = by_tick_b.get(tick), by_tick_a.get(tick)
        if b is None or a is None or b["state"] != a["state"]:
            out.append({"tick": tick,
                        "before": b["state"] if b else None, "before_kinds": b["kinds"] if b else None,
                        "after": a["state"] if a else None, "after_kinds": a["kinds"] if a else None})
    return out


# ------------------------------------------------------------------ driver
def _spawn(args: List[str], out_dir: Path, name: str) -> subprocess.Popen:
    env = dict(os.environ, PYTHONHASHSEED="0")
    log = open(out_dir / f"{name}.log", "w", encoding="utf-8")
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve())] + args,
                            cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)


def _worker_main(args: argparse.Namespace) -> int:
    if args.worker == "normal":
        data = worker_normal(args.seed, args.ticks)
    else:
        data = worker_fault(args.worker, args.seed, args.ticks)
    Path(args.worker_out).write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    return 0


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.3f}"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) or "-"
    return str(v)


def _table(headers: List[str], rows: List[List[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(v) for v in row) + " |")
    return "\n".join(lines)


WINDOW_COLS = ["tick", "state", "attempted", "delivered", "dropped", "late", "failure_rate",
               "backlog_now", "backlog_growth", "task_completion_rate", "completion_gap",
               "resource_saturation", "dock", "dependency_graph_divergence", "tail_deviation", "kinds"]


def write_markdown(data: Dict[str, Any], path: Path) -> None:
    md: List[str] = ["# DK-RMM operational indicators: validation runs", "",
                     f"Generated by `tools/validate_dkrmm_indicators.py` (rules only, PYTHONHASHSEED=0). "
                     f"Ticks: {data['ticks']}; seeds: Normal {data['seeds']['normal']}, "
                     f"faults {data['seeds']['fault']}.", ""]
    for n in data["normal"]:
        md += [f"## Normal, seed {n['seed']}, {n['ticks']} ticks", "",
               f"- event stream hash with the monitor attached: `{n['hash_watched']}`",
               f"- event stream hash without it: `{n['hash_unwatched']}`",
               f"- equal: **{n['hash_equal']}** ({n['events_watched']} events either way)", "",
               "| | STABLE | DEVIATING | UNSTABLE | RCT | RECOVERY | assessments |", "|---|---|---|---|---|---|---|"]
        for label, side in (("before", n["before"]), ("after", n["after"])):
            c = side["counts"]
            md.append(f"| {label} | {c.get('STABLE', 0)} | {c.get('DEVIATING', 0)} | {c.get('UNSTABLE', 0)} | "
                      f"{c.get('RCT', 0)} | {c.get('RECOVERY', 0)} | {side['assessments']} |")
        md += ["", f"Windows whose state changed ({len(n['changed'])} of {n['after']['assessments']}):", ""]
        md.append(_table(["tick", "before", "before kinds", "after", "after kinds"],
                         [[d["tick"], d["before"], d["before_kinds"], d["after"], d["after_kinds"]]
                          for d in n["changed"]]))
        md.append("")
    for key in ("ms_drop", "ms_delay"):
        f = data[key]
        md += [f"## {f['scenario']}, seed {f['seed']}, {f['ticks']} ticks (fault at {f['start']})", "",
               f"- state counts: {f['counts']}",
               f"- first tick of each state: {f['first_ticks']}; first tick after {f['start']}: {f['drop']['first_ticks_after_start']}",
               f"- first window after {f['start']} with failure rate >= 0.99: {f['drop']['first_window_failure_rate_ge_0_99']}",
               f"- backlog grew after the fault: {f['drop']['backlog_grew_after_start']} "
               f"(max growth {f['drop']['max_backlog_growth_after_start']}); first window with the dock at its cap: "
               f"{f['drop']['first_window_dock_at_cap']}; growth values seen at the cap: {f['drop']['backlog_growth_values_at_dock_cap']}; "
               f"after the first cap window: {f['drop']['backlog_growth_values_past_first_cap_window']}",
               f"- parcels departed after the fault: {f['drop']['parcels_departed_after_start']} "
               f"({f['drop']['van_departed_events_after_start']} van departures); task_completion_rate values after the fault: "
               f"{f['drop']['task_completion_rates_after_start']}; departures with parcels after the fault (tick, parcels): "
               f"{f['drop']['departures_with_parcels_after_start']}; rates once the last loaded departure has left the window: "
               f"{f['drop']['task_completion_rates_after_last_loaded_departure_plus_window']}",
               f"- max resource_saturation after the fault: {f['drop']['max_resource_saturation_after_start']}; "
               f"dock values after the fault: {f['drop']['dock_values_after_start']}", ""]
        if "delay" in f:
            d = f["delay"]
            md += [f"- late events: {d['late_events']} (before the fault: {d['late_before_start']}); late_by distribution: {d['late_by_distribution']} "
                   f"(scenario says {d['expected_late_by']}); dropped events: {d['dropped_events']}; attempted messages in the run: {d['attempted_total']}",
                   f"- failure rate per window after the fault: {d['failure_rate_after_start']}; over the whole run after the fault: "
                   f"{d['late_after_start']} late of {d['attempted_after_start']} attempted = {d['late_over_attempted_after_start']}",
                   "- routing share of attempted messages after the fault:"]
            for name, row in f["routing_share"].items():
                if isinstance(row, dict):
                    md.append(f"    - {name}: {row['count']} of {f['routing_share']['attempted_after_start']} = {row['share']} ({row['rule']})")
            md.append("")
        md += ["Per assessment window:", ""]
        md.append(_table(WINDOW_COLS, [[r[c] for c in WINDOW_COLS] for r in f["windows"]]))
        md.append("")
        if "delay" in f:
            md += ["Latency and tail per window (after the fault):", ""]
            md.append(_table(["tick", "state", "execution_latency", "execution_latency_p95",
                              "task_wait p95 now/base/ratio", "message_delay p95 now/base/ratio",
                              "zone_backlog p95 now/base/ratio", "tail_deviation"],
                             [[r["tick"], r["state"], r["execution_latency"], r["execution_latency_p95"],
                               _tail_cell(r["tail"].get("task_wait")), _tail_cell(r["tail"].get("message_delay")),
                               _tail_cell(r["tail"].get("zone_backlog")), r["tail_deviation"]]
                              for r in f["windows"] if r["tick"] > f["start"]]))
            md.append("")
    path.write_text("\n".join(md) + "\n", encoding="utf-8")


def _tail_cell(row: Optional[Dict[str, Any]]) -> str:
    if not row:
        return "n/a"
    parts = [_fmt(row.get("p95_now")), _fmt(row.get("p95_baseline")), _fmt(row.get("ratio"))]
    note = row.get("note") or ""
    return "/".join(parts) + (f" ({note})" if note else "")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory (never under results/)")
    parser.add_argument("--ticks", type=int, default=2800, help="ticks of the long runs")
    parser.add_argument("--seeds", type=int, nargs=2, default=(1, 11), metavar=("NORMAL", "FAULT"),
                        help="the Normal seed and the fault-scenario seed")
    parser.add_argument("--old-tree", type=Path, default=DEFAULT_OLD_TREE,
                        help="worktree of the code before the extension, for the 'before' states")
    parser.add_argument("--jobs", type=int, default=2, help="parallel scenario workers")
    parser.add_argument("--worker", choices=("normal", "ms-drop", "ms-delay"), help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--worker-out", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return _worker_main(args)

    out_dir: Path = args.out.resolve()
    if ROOT in out_dir.parents or out_dir == ROOT:
        parser.error(f"--out must be outside the repository ({ROOT})")
    out_dir.mkdir(parents=True, exist_ok=True)
    normal_seed, fault_seed = args.seeds

    jobs = [("normal-300", ["--worker", "normal", "--seed", str(normal_seed), "--ticks", str(NORMAL_SHORT)]),
            (f"normal-{args.ticks}", ["--worker", "normal", "--seed", str(normal_seed), "--ticks", str(args.ticks)]),
            (f"ms-drop-{args.ticks}", ["--worker", "ms-drop", "--seed", str(fault_seed), "--ticks", str(args.ticks)]),
            (f"ms-delay-{args.ticks}", ["--worker", "ms-delay", "--seed", str(fault_seed), "--ticks", str(args.ticks)])]
    pending = list(jobs)
    running: List[Tuple[str, subprocess.Popen]] = []
    results: Dict[str, Path] = {}
    while pending or running:
        while pending and len(running) < max(1, args.jobs):
            name, extra = pending.pop(0)
            target = out_dir / f"{name}.json"
            results[name] = target
            running.append((name, _spawn(extra + ["--worker-out", str(target)], out_dir, name)))
            print(f"started {name}", flush=True)
        name, proc = running[0]
        code = proc.wait()
        running.pop(0)
        print(f"finished {name} (exit {code})", flush=True)
        if code != 0:
            raise SystemExit(f"worker {name} failed; see {out_dir / (name + '.log')}")

    data: Dict[str, Any] = {"ticks": args.ticks, "seeds": {"normal": normal_seed, "fault": fault_seed},
                            "old_tree": str(args.old_tree), "normal": []}
    for name in ("normal-300", f"normal-{args.ticks}"):
        n = json.loads(results[name].read_text(encoding="utf-8"))
        print(f"before: Normal seed {normal_seed}, {n['ticks']} ticks in {args.old_tree}", flush=True)
        n["before"] = before_normal(args.old_tree, normal_seed, n["ticks"], out_dir)
        n["changed"] = diff_windows(n["before"]["windows"], n["after"]["windows"])
        data["normal"].append(n)
    data["ms_drop"] = json.loads(results[f"ms-drop-{args.ticks}"].read_text(encoding="utf-8"))
    data["ms_delay"] = json.loads(results[f"ms-delay-{args.ticks}"].read_text(encoding="utf-8"))

    (out_dir / "validation.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    write_markdown(data, out_dir / "validation.md")
    for n in data["normal"]:
        print(f"Normal {n['ticks']}: hash equal {n['hash_equal']}; before {n['before']['counts']}; after {n['after']['counts']}")
    for key in ("ms_drop", "ms_delay"):
        f = data[key]
        print(f"{f['scenario']}: counts {f['counts']}; first {f['first_ticks']}; "
              f"first rate>=0.99 after start {f['drop']['first_window_failure_rate_ge_0_99']}")
    print(f"written {out_dir / 'validation.json'} and {out_dir / 'validation.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
