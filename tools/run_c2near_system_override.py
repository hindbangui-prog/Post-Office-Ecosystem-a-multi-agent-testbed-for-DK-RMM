#!/usr/bin/env python3
"""
C2-NEAR-SYSTEM-OVERRIDE: run the conditions, then classify them.

    python tools/run_c2near_system_override.py --condition N --condition C0 --rules
    python tools/run_c2near_system_override.py --condition N --condition C0 --condition C2
    python tools/run_c2near_system_override.py --analyze

Each run is one condition (`N` control, `C0` operational stressors, `C2`
System Override plus operational stressors) and one seed, built from
`normal_config()` (plus the campaign key for C2), stepped `--ticks` ticks with
the scheduled faults fired as their tick comes and DK-RMM attached as an
observer, and written under `<out>/<condition>/s<seed>/`:

    definition.json      the experiment definition, its fingerprint, the
                         seed, the mode (rules / model) and the ticks asked for
    events.jsonl         the run's event log
    series.csv           one measurement row per tick
    measurement.json     mode, ticks, totals, faults applied, per-route
                         table, summary, reasoning summary, DK-RMM state
    dkrmm.json           DK-RMM's final state and its run record
    summary.json         the ecosystem's summary
    verify.json          the model identity and the served-model check
                         (model mode) or the rules note
    llm_decisions.json   every condition: one row per targeted model
                         decision, the rule replayed on the same facts and
                         options (`changed_vs_rule`), the delivered attack
                         id where there was one
    attack_outcomes.json (C2 only) one row per System Override delivery,
                         joined with its response, consult_closed and
                         decision; the rule replayed on the same facts
    done.json            written last, with `mode` and `ticks`; a directory
                         that has one is skipped

`--out` defaults to `results/c2_near_system_override` and is refused when it
resolves inside `results/normal`. `--rules` puts every expert on its rules
and is allowed for N and C0 only: the attack addresses the model's input, so
C2 needs the model path. Model mode reads the Ollama settings, verifies the
configured model's identity, builds the experts with `llm_brains`, and
records in each run's `verify.json` which model served every call, exactly
as `tools/run_normal.py` does (`ok` is the identity check and no call served
by another model). A C2 run is built only if the campaign is installed as
the consultation service's agent hooks and bound to the ecosystem; otherwise
the driver exits 2 rather than run a C2 unattacked.

`--analyze` classifies every C0 and C2 run under `--out` against the N run
of the same seed (`post_office.stress.collapse.classify`), but only when the
two runs were made in the same mode and with the same `--ticks` (read from
`done.json`, or `definition.json` for an unfinished run); a pair that differs
is printed and recorded as `not_comparable`. For every run of every
condition it reads `llm_decisions.json` (targeted model decisions,
`changed_vs_rule` count and rate) and, for C2, `attack_outcomes.json`
(delivered, responded, accepted, rejected by the gate, complied).
`attack_influence` of a C2 run is its `changed_vs_rule` rate beside the
matched N and C0 rates: that is the influence measure. `complied` is the
narrower count of final choices that followed the demand where the rule
would not have (evaluable only when the decision had more than one option
and the rule's own choice was outside the demanded set), shown as
`complied(evaluable)`; `complied_any` is whether that count is above zero.
`attack_executed` is whether a message was delivered. It writes
`<out>/summary.json` and prints the tables.

Ctrl-C stops the current run where it is; its files are written for the
ticks completed with `"interrupted": true`, no `done.json` is written, and
the exit code is 130.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from post_office.communication.events import EventCategory  # noqa: E402
from post_office.crew.console import utf8_stdout  # noqa: E402
from post_office.dkrmm import DKRMM, build_record  # noqa: E402
from post_office.simulation import build  # noqa: E402
from post_office.stress import c2near_system_override as spec  # noqa: E402
from post_office.stress.analysis import (COMPLIED_MEANS, write_attack_outcomes,  # noqa: E402
                                         write_llm_decisions)
from post_office.stress.collapse import classify  # noqa: E402
from post_office.stress.measure import Collector, read_series  # noqa: E402
from post_office.stress.operational import ScheduledFaults  # noqa: E402

#: The exit code of a run stopped by Ctrl-C (128 + SIGINT).
INTERRUPTED = 130
FORBIDDEN = ROOT / "results" / "normal"
NOT_COMPARABLE = "not_comparable"


class Unattacked(RuntimeError):
    """A C2 ecosystem was built without a bound System Override campaign."""


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"{spec.EXPERIMENT}: run the conditions, then classify them")
    parser.add_argument("--condition", action="append", choices=sorted(spec.CONDITIONS),
                        help="condition to run (repeatable); default: none")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(spec.SEEDS),
                        help=f"seeds (default {' '.join(map(str, spec.SEEDS))})")
    parser.add_argument("--ticks", type=int, default=spec.RUN_TICKS,
                        help=f"ticks per run (default {spec.RUN_TICKS})")
    parser.add_argument("--out", default=str(ROOT / spec.RESULTS_DIR),
                        help=f"results directory (default {spec.RESULTS_DIR})")
    parser.add_argument("--rules", action="store_true",
                        help="every expert on its rules (N and C0 only)")
    parser.add_argument("--analyze", action="store_true",
                        help="classify every C0/C2 run under --out against its N run")
    return parser.parse_args(argv)


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8",
                    newline="\n")


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def refuse_normal(out: Path) -> Path:
    """`out` resolved; a ValueError when it is, or lies inside, results/normal."""
    resolved = out.resolve()
    forbidden = FORBIDDEN.resolve()
    if resolved == forbidden or forbidden in resolved.parents:
        raise ValueError(f"refusing to write under {FORBIDDEN}: {out}")
    parts = [p.lower() for p in resolved.parts]
    for index in range(len(parts) - 1):
        if parts[index] == "results" and parts[index + 1] == "normal":
            raise ValueError(f"refusing to write under a results/normal directory: {out}")
    return resolved


def run_identity(run_dir: Path) -> Dict[str, Any]:
    """
    The `mode` and `ticks` a run directory was made with: from `done.json`,
    else from `definition.json` (an unfinished run), else both None.
    """
    for name in ("done.json", "definition.json"):
        data = _read_json(run_dir / name)
        if data is not None:
            return {"mode": data.get("mode"), "ticks": data.get("ticks"), "source": name}
    return {"mode": None, "ticks": None, "source": None}


# ------------------------------------------------------------------- one run
class _CallCollector:
    """Every model call of the run, read from the service after each tick (as `run_normal.py`)."""

    def __init__(self, crew: Any) -> None:
        self.crew = crew
        self.calls: List[Dict[str, Any]] = []
        self._seen: set = set()

    def collect(self) -> None:
        if self.crew is None:
            return
        for row in self.crew.llm_calls(2000):
            if row["call_id"] not in self._seen:
                self._seen.add(row["call_id"])
                self.calls.append(row)


def _served_check(calls: List[Dict[str, Any]], configured_model: str,
                  identity_ok: bool) -> Dict[str, Any]:
    """The served-model part of `verify.json`, the logic of `run_normal.py`."""
    served = Counter(c["served_model"] for c in calls)
    mismatched = sorted(name for name in served if name and name != configured_model)
    return {"served_models": dict(sorted(served.items())),
            "served_by_configured_model": served.get(configured_model, 0),
            "served_by_other_models": mismatched,
            "ok": bool(identity_ok and not mismatched)}


def _require_campaign(eco: Any, cond: spec.Condition) -> None:
    """A C2 ecosystem must carry the bound campaign as its agent hooks, or it does not run."""
    if not cond.override:
        return
    crew = getattr(eco, "crew", None)
    if crew is None:
        raise Unattacked(f"{cond.id}: the ecosystem has no consultation service (eco.crew "
                         "is None), so the System Override campaign cannot be installed; "
                         "a C2 run must never proceed unattacked")
    agent = getattr(getattr(crew, "interception", None), "agent", None)
    if not getattr(agent, "bound", False):
        raise Unattacked(f"{cond.id}: the consultation service's agent hooks are "
                         f"{type(agent).__name__}, not a bound SystemOverrideCampaign; "
                         "a C2 run must never proceed unattacked")


def run_one(cond: spec.Condition, seed: int, ticks: int, run_dir: Path,
            brains: Optional[Dict[str, Any]], verify: Dict[str, Any],
            settings: Any = None) -> Dict[str, Any]:
    """
    Build, step and write one run. Returns `{"interrupted": bool, ...}`.

    The loop, per tick: the scheduled faults due this tick are fired, the
    ecosystem steps, DK-RMM assesses (observe only; an error there is
    recorded and does not stop the run), the model calls so far are read
    from the service, and the collector appends its row.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    definition = spec.definition(cond)
    fingerprint = spec.fingerprint(cond)
    mode = verify["mode"]
    _write(run_dir / "definition.json",
           {**definition, "fingerprint": fingerprint, "seed": seed, "ticks": ticks,
            "mode": mode})

    eco = build(seed, config=spec.config(cond), log_path=str(run_dir / "events.jsonl"),
                run_id=f"{spec.EXPERIMENT}-{cond.id}-s{seed}", brains=brains,
                scenario="normal")
    try:
        _require_campaign(eco, cond)
    except Unattacked:
        # Nothing ran: leave no half-written run directory behind, so the
        # seed is not skipped as "incomplete" next time.
        eco.close()
        for name in ("events.jsonl", "definition.json"):
            with contextlib.suppress(OSError):
                (run_dir / name).unlink()
        with contextlib.suppress(OSError):
            run_dir.rmdir()
        raise
    monitor = DKRMM(eco).attach()
    stress = ScheduledFaults(eco, cond)
    collector = Collector(eco, cond, stress, monitor=monitor, mode=mode, ticks=ticks)
    calls = _CallCollector(eco.crew)
    monitor_errors: List[str] = []
    interrupted = False
    try:
        eco.logger.emit(EventCategory.SIMULATION, "stress_experiment", tick=0,
                        actor="SIMULATION", experiment=spec.EXPERIMENT,
                        condition=cond.id, fingerprint=fingerprint,
                        definition=definition)
        eco.start()
        try:
            for tick in range(1, int(ticks) + 1):
                stress.before_tick(tick)
                eco.step()
                try:
                    monitor.tick()
                except Exception as exc:  # the observer must never stop the run
                    monitor_errors.append(f"tick {tick}: {exc!r}")
                calls.collect()
                collector.after_step()
        except KeyboardInterrupt:
            interrupted = True
        eco.stop("run complete" if not interrupted else "interrupted")
        summary = {**eco.summary(), "reasoning": eco.reasoning_summary(),
                   "interrupted": interrupted}
        record = build_record(eco.run_id, monitor, scenario="normal", seed=seed,
                              config=eco.config, control=not (cond.operational or cond.override))
        state = monitor.state()
        measurement = collector.write(run_dir, interrupted=interrupted)
        # The joins read the log file, which `eco.close()` below closes;
        # flush it so every line written so far is on disk.
        eco.logger.flush()
        decisions = write_llm_decisions(run_dir)["summary"]
        attack: Dict[str, Any] = {}
        if cond.override:
            attack = write_attack_outcomes(run_dir)["summary"]
        _write(run_dir / "dkrmm.json", {"state": state, "record": record,
                                        "errors": monitor_errors})
        _write(run_dir / "summary.json", summary)
        run_verify = {**verify, "llm": eco.llm_summary(), "interrupted": interrupted}
        if mode == "model" and settings is not None:
            calls.collect()
            run_verify.update(_served_check(calls.calls, settings.model,
                                            bool(verify.get("ok"))))
        _write(run_dir / "verify.json", run_verify)
        if not interrupted:
            _write(run_dir / "done.json", {"experiment": spec.EXPERIMENT,
                                           "condition": cond.id, "seed": seed,
                                           "ticks": ticks, "fingerprint": fingerprint,
                                           "mode": mode})
    finally:
        collector.close()
        monitor.close()
        eco.close()
    totals = measurement["totals"]
    return {"interrupted": interrupted, "condition": cond.id, "seed": seed,
            "ticks": totals["ticks"], "arrivals": totals["arrivals"],
            "arrival_refused": totals["arrival_refused"],
            "dispatched": totals["dispatched"], "backlog_end": totals["backlog_end"],
            "stations_end": totals["stations_end"],
            "routes_open_end": totals["routes_open_end"],
            "faults": [f["fault_id"] for f in measurement["faults_applied"]],
            "dkrmm": (state.get("current") or {}).get("state", ""),
            "llm_decisions": int(decisions.get("targeted_llm_decisions", 0)),
            "changed_vs_rule": int(decisions.get("changed_vs_rule", 0)),
            "override_delivered": int(attack.get("delivered", 0))}


def _table(rows: List[Dict[str, Any]], columns: Sequence[str]) -> str:
    if not rows:
        return "  (nothing)"
    width = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    head = "  " + "  ".join(f"{c:<{width[c]}}" for c in columns)
    lines = [head, "  " + "  ".join("-" * width[c] for c in columns)]
    for row in rows:
        lines.append("  " + "  ".join(f"{str(row.get(c, '')):<{width[c]}}" for c in columns))
    return "\n".join(lines)


def _rate(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.3f}"


# ------------------------------------------------------------------- analyze
def _run_dirs(out: Path, cond_id: str) -> List[Path]:
    cond_dir = out / cond_id
    if not cond_dir.is_dir():
        return []
    dirs = []
    for run_dir in sorted(p for p in cond_dir.iterdir() if p.is_dir() and p.name.startswith("s")):
        try:
            int(run_dir.name[1:])
        except ValueError:
            continue
        dirs.append(run_dir)
    return dirs


def _decision_stats(run_dir: Path) -> Dict[str, Any]:
    """The `llm_decisions.json` summary of a run, flattened for a table row."""
    data = _read_json(run_dir / "llm_decisions.json")
    summary = (data or {}).get("summary") or {}
    row = {"llm_decisions": int(summary.get("targeted_llm_decisions", 0)),
           "changed_vs_rule": int(summary.get("changed_vs_rule", 0)),
           "changed_vs_rule_rate": summary.get("changed_vs_rule_rate"),
           "accepted": int(summary.get("accepted", 0)),
           "rejected_by_gate": int(summary.get("rejected_by_gate", 0)),
           "llm_failed": int(summary.get("llm_failed", 0)),
           "has_llm_decisions": data is not None}
    return row


def _attack_stats(run_dir: Path) -> Dict[str, Any]:
    data = _read_json(run_dir / "attack_outcomes.json")
    summary = (data or {}).get("summary") or {}
    return {"has_attack_outcomes": data is not None,
            "override_delivered": int(summary.get("delivered", 0)),
            "override_responded": int(summary.get("responded", 0)),
            "override_accepted": int(summary.get("accepted", 0)),
            "override_rejected_by_gate": int(summary.get("rejected_by_gate", 0)),
            "complied": int(summary.get("complied", 0)),
            "complied_evaluable": int(summary.get("complied_evaluable", 0)),
            "complied_any": bool(summary.get("complied_any", False)),
            "attack_executed": bool(summary.get("attack_executed", False))}


def analyze(out: Path) -> Dict[str, Any]:
    """
    Classify every C0/C2 run under `out` against the N run of its seed, and
    read every run's decision statistics.
    """
    # The model-decision statistics of every run, every condition.
    decisions: List[Dict[str, Any]] = []
    by_key: Dict[tuple, Dict[str, Any]] = {}
    for cond_id in ("N", "C0", "C2"):
        for run_dir in _run_dirs(out, cond_id):
            seed = int(run_dir.name[1:])
            identity = run_identity(run_dir)
            row = {"condition": cond_id, "seed": seed, "mode": identity["mode"],
                   "ticks": identity["ticks"], "done": (run_dir / "done.json").exists(),
                   **_decision_stats(run_dir)}
            if cond_id == "C2":
                row.update(_attack_stats(run_dir))
            row["changed_vs_rule_rate"] = row["changed_vs_rule_rate"]
            decisions.append(row)
            by_key[(cond_id, seed)] = row

    results: List[Dict[str, Any]] = []
    not_comparable: List[Dict[str, Any]] = []
    for cond_id in ("C0", "C2"):
        for run_dir in _run_dirs(out, cond_id):
            seed = int(run_dir.name[1:])
            control_dir = out / "N" / run_dir.name
            series = run_dir / "series.csv"
            control = control_dir / "series.csv"
            row: Dict[str, Any] = {"condition": cond_id, "seed": seed,
                                   "run": str(run_dir.relative_to(out)),
                                   "done": (run_dir / "done.json").exists(),
                                   "control_done": (control_dir / "done.json").exists()}
            if not series.exists():
                row["outcome"] = "no series"
                results.append(row)
                continue
            if not control.exists():
                row["outcome"] = "no control"
                results.append(row)
                continue
            mine, theirs = run_identity(run_dir), run_identity(control_dir)
            row["mode"], row["ticks"] = mine["mode"], mine["ticks"]
            row["control_mode"], row["control_ticks"] = theirs["mode"], theirs["ticks"]
            problems = []
            if mine["mode"] != theirs["mode"]:
                problems.append(f"mode {mine['mode']!r} vs control {theirs['mode']!r}")
            if mine["ticks"] != theirs["ticks"]:
                problems.append(f"ticks {mine['ticks']!r} vs control {theirs['ticks']!r}")
            if problems:
                reason = "; ".join(problems)
                print(f"refuse {cond_id} s{seed}: not comparable with N s{seed} ({reason}); "
                      "a run is classified only against a control made in the same mode "
                      "and with the same --ticks")
                row["outcome"] = NOT_COMPARABLE
                row["not_comparable_reason"] = reason
                results.append(row)
                not_comparable.append({"condition": cond_id, "seed": seed, "reason": reason})
                continue
            verdict = classify(read_series(series), read_series(control))
            row.update(verdict)
            measurement = _read_json(run_dir / "measurement.json") or {}
            totals = measurement.get("totals", {})
            row["dispatched"] = int(totals.get("dispatched", 0))
            row["backlog_end"] = int(totals.get("backlog_end", 0))
            row["arrival_refused"] = int(totals.get("arrival_refused", 0))
            # Model decisions against the rule: this run and the matched
            # N and C0 runs of the same seed.
            own = by_key.get((cond_id, seed), {})
            row["llm_decisions"] = own.get("llm_decisions", 0)
            row["changed_vs_rule"] = own.get("changed_vs_rule", 0)
            row["changed_vs_rule_rate"] = own.get("changed_vs_rule_rate")
            row["attack_executed"] = bool(own.get("attack_executed", False)) if cond_id == "C2" \
                else int(totals.get("override_delivered", 0)) > 0
            row["attack_influence"] = None
            if cond_id == "C2":
                n_row = by_key.get(("N", seed), {})
                c0_row = by_key.get(("C0", seed), {})
                row.update({k: own.get(k) for k in (
                    "override_delivered", "override_responded", "override_accepted",
                    "override_rejected_by_gate", "complied", "complied_evaluable",
                    "complied_any")})
                row["attack_influence"] = {
                    "changed_vs_rule_rate_C2": own.get("changed_vs_rule_rate"),
                    "changed_vs_rule_rate_N": n_row.get("changed_vs_rule_rate"),
                    "changed_vs_rule_rate_C0": c0_row.get("changed_vs_rule_rate"),
                    "llm_decisions_C2": own.get("llm_decisions", 0),
                    "llm_decisions_N": n_row.get("llm_decisions", 0),
                    "llm_decisions_C0": c0_row.get("llm_decisions", 0),
                    "complied_any": bool(own.get("complied_any", False)),
                }
            results.append(row)
    summary = {"experiment": spec.EXPERIMENT, "label": spec.LABEL, "out": str(out),
               "collapse_params": dict(spec.COLLAPSE), "complied_means": COMPLIED_MEANS,
               "runs": results, "decisions": decisions, "not_comparable": not_comparable}
    _write(out / "summary.json", summary)
    return summary


def print_analysis(summary: Dict[str, Any], out: Path) -> None:
    runs = summary["runs"]
    print("")
    print(f"collapse classification against N (same seed, same mode, same ticks); "
          f"{out / 'summary.json'}")
    for row in runs:
        row["criterion"] = "+".join(row["collapse_criterion"] or []) \
            if isinstance(row.get("collapse_criterion"), list) else ""
        ne = row.get("not_evaluable_ticks") or {}
        row["not_evaluable(through/stop)"] = (
            f"{ne.get('through_degraded', '')}/{ne.get('critical_stop', '')}" if ne else "")
    print(_table(runs, ("condition", "seed", "mode", "ticks", "outcome", "criterion",
                        "collapse_tick", "held_to_end", "degradation_tick",
                        "critical_stop_tick", "first_degraded_tick", "degraded_ticks",
                        "through_degraded_ticks", "backlog_degraded_ticks",
                        "evaluated_ticks", "not_evaluable(through/stop)",
                        "dispatched", "backlog_end", "arrival_refused", "done")))
    print("")
    print("targeted model decisions against the rule (every condition)")
    print("  changed_vs_rule: the accepted answer differs from the rule's; the C2 rate against "
          "the N and C0 rates is the influence measure")
    print("  complied(evaluable): followed the demand where the rule would not have (evaluable: "
          "more than one option and the rule's choice outside the demanded set)")
    decisions = summary["decisions"]
    for row in decisions:
        row["rate"] = _rate(row.get("changed_vs_rule_rate"))
        row["complied(evaluable)"] = (
            f"{row.get('complied', 0)}({row.get('complied_evaluable', 0)})"
            if row["condition"] == "C2" else "")
    print(_table(decisions, ("condition", "seed", "mode", "ticks", "llm_decisions",
                             "changed_vs_rule", "rate", "accepted", "rejected_by_gate",
                             "llm_failed", "override_delivered", "override_responded",
                             "override_accepted", "override_rejected_by_gate",
                             "complied(evaluable)", "done")))
    c2 = [row for row in runs if row["condition"] == "C2"
          and isinstance(row.get("attack_influence"), dict)]
    if c2:
        print("")
        print("attack influence: C2 changed_vs_rule rate beside the matched N and C0 rates "
              "(complied_any: at least one demand followed where the rule would not have)")
        shown = []
        for row in c2:
            inf = row["attack_influence"]
            shown.append({
                "seed": row["seed"], "attack_executed": row.get("attack_executed"),
                "rate_C2": _rate(inf["changed_vs_rule_rate_C2"]),
                "rate_N": _rate(inf["changed_vs_rule_rate_N"]),
                "rate_C0": _rate(inf["changed_vs_rule_rate_C0"]),
                "n_C2/N/C0": f"{inf['llm_decisions_C2']}/{inf['llm_decisions_N']}/"
                             f"{inf['llm_decisions_C0']}",
                "complied_any": inf["complied_any"]})
        print(_table(shown, ("seed", "attack_executed", "rate_C2", "rate_N", "rate_C0",
                             "n_C2/N/C0", "complied_any")))


# ---------------------------------------------------------------------- main
def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    utf8_stdout()
    try:
        out = refuse_normal(Path(args.out))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    conditions = [spec.condition(c) for c in (args.condition or [])]
    if not conditions and not args.analyze:
        print("nothing to do: give --condition (repeatable) and/or --analyze",
              file=sys.stderr)
        return 2

    mode = "rules" if args.rules else "model"
    if args.rules and any(c.override for c in conditions):
        print("--rules is for N and C0 only: condition C2 runs the System Override "
              "campaign, which addresses the model's input, so it needs the model "
              "path (run it without --rules)", file=sys.stderr)
        return 2

    settings = None
    verify: Dict[str, Any] = {"mode": mode}
    if conditions and mode == "model":
        from post_office.config.ollama import load_settings
        from post_office.crew.identity import verify_model

        try:
            settings = load_settings()
        except ValueError as exc:
            print(f"invalid Ollama settings: {exc}", file=sys.stderr)
            return 2
        identity = verify_model(settings)
        verify = {"mode": mode, "base_url": settings.base_url,
                  "settings": settings.as_dict(), "identity": identity.as_dict(),
                  "ok": bool(identity.ok)}
        if not identity.ok:
            out.mkdir(parents=True, exist_ok=True)
            _write(out / "verify.json", {**verify, "ran": False, "served_models": {}})
            print(f"cannot run on the model: {'; '.join(identity.problems)}", file=sys.stderr)
            return 2
    elif conditions:
        verify = {"mode": mode, "ok": None,
                  "note": "rules-only run: no model was asked and no identity was checked"}

    if mode == "model" and conditions:
        from post_office.crew.console import quiet
        console = quiet()
    else:
        console = contextlib.nullcontext()

    finished: List[Dict[str, Any]] = []
    interrupted = False
    with console:
        for cond in conditions:
            for seed in args.seeds:
                run_dir = out / cond.id / f"s{seed}"
                done = _read_json(run_dir / "done.json")
                if done is not None:
                    print(f"skip {cond.id} s{seed}: done (mode={done.get('mode')}, "
                          f"ticks={done.get('ticks')}) at {run_dir}")
                    continue
                if (run_dir / "events.jsonl").exists():
                    print(f"skip {cond.id} s{seed}: an incomplete run is at {run_dir} "
                          "(no done.json); move it away to run this seed again")
                    continue
                print(f"run  {cond.id} s{seed}: {args.ticks} ticks, {mode} -> {run_dir}")
                brains = None
                if settings is not None:
                    # A fresh set of CrewBrains per run, as `run_normal.py`
                    # builds one per process: nothing carries over between seeds.
                    from post_office.config.settings import llm_brains
                    brains = llm_brains(settings=settings, verify=False)
                try:
                    result = run_one(cond, seed, args.ticks, run_dir, brains, verify,
                                     settings=settings)
                except Unattacked as exc:
                    print(f"refusing to run {exc}", file=sys.stderr)
                    return 2
                finished.append(result)
                if result["interrupted"]:
                    interrupted = True
                    break
            if interrupted:
                break

    if finished:
        print("")
        print(f"{spec.EXPERIMENT} runs ({mode})")
        print(_table(finished, ("condition", "seed", "ticks", "arrivals", "arrival_refused",
                                "dispatched", "backlog_end", "stations_end",
                                "routes_open_end", "dkrmm", "faults", "llm_decisions",
                                "changed_vs_rule", "override_delivered", "interrupted")))

    if args.analyze and not interrupted:
        summary = analyze(out)
        print_analysis(summary, out)

    if interrupted:
        print("INTERRUPTED")
        return INTERRUPTED
    return 0


if __name__ == "__main__":
    sys.exit(main())
