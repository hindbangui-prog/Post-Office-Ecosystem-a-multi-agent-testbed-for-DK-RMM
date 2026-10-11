#!/usr/bin/env python3
"""
C2-NEAR-SYSTEM-OVERRIDE: run the conditions, then classify them.

    python tools/run_c2near_system_override.py --condition N --condition C0 --rules
    python tools/run_c2near_system_override.py --condition N --condition C0 --condition C2
    python tools/run_c2near_system_override.py --analyze

Each run is one condition (`N` control, `C0` operational stressors, `C2`
System Override plus operational stressors) and one seed, built from
`normal_config()` (plus the campaign key for C2), stepped `--ticks` ticks with
the operational faults applied as their tick comes and DK-RMM attached as an
observer, and written under `<out>/<condition>/s<seed>/`:

    definition.json      the experiment definition and its fingerprint
    events.jsonl         the run's event log
    series.csv           one measurement row per tick
    measurement.json     totals, faults applied, per-route table, summary,
                         reasoning summary, DK-RMM state
    dkrmm.json           DK-RMM's final state and its run record
    summary.json         the ecosystem's summary
    verify.json          the model identity (model mode) or the rules note
    done.json            written last; a directory that has one is skipped

`--out` defaults to `results/c2_near_system_override` and is refused when it
resolves inside `results/normal`. `--rules` puts every expert on its rules
and is allowed for N and C0 only: the attack addresses the model's input, so
C2 needs the model path. Model mode reads the Ollama settings, verifies the
configured model's identity and builds the experts with `llm_brains`, exactly
as `tools/run_normal.py` does.

`--analyze` classifies every C0 and C2 run under `--out` against the N run
of the same seed (`post_office.stress.collapse.classify`), writes
`<out>/summary.json` and prints a per-seed table.

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
from post_office.stress.collapse import classify  # noqa: E402
from post_office.stress.measure import Collector, read_series  # noqa: E402
from post_office.stress.operational import OperationalStress  # noqa: E402

#: The exit code of a run stopped by Ctrl-C (128 + SIGINT).
INTERRUPTED = 130
FORBIDDEN = ROOT / "results" / "normal"


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


# ------------------------------------------------------------------- one run
def run_one(cond: spec.Condition, seed: int, ticks: int, run_dir: Path,
            brains: Optional[Dict[str, Any]], verify: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build, step and write one run. Returns `{"interrupted": bool, ...}`.

    The loop, per tick: the operational faults due this tick are applied,
    the ecosystem steps, DK-RMM assesses (observe only; an error there is
    recorded and does not stop the run), and the collector appends its row.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    definition = spec.definition(cond)
    fingerprint = spec.fingerprint(cond)
    _write(run_dir / "definition.json",
           {**definition, "fingerprint": fingerprint, "seed": seed, "ticks": ticks,
            "mode": verify["mode"]})

    eco = build(seed, config=spec.config(cond), log_path=str(run_dir / "events.jsonl"),
                run_id=f"{spec.EXPERIMENT}-{cond.id}-s{seed}", brains=brains,
                scenario="normal")
    monitor = DKRMM(eco).attach()
    stress = OperationalStress(eco, cond)
    collector = Collector(eco, cond, stress, monitor=monitor)
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
        _write(run_dir / "dkrmm.json", {"state": state, "record": record,
                                        "errors": monitor_errors})
        _write(run_dir / "summary.json", summary)
        _write(run_dir / "verify.json", {**verify, "llm": eco.llm_summary(),
                                         "interrupted": interrupted})
        if not interrupted:
            _write(run_dir / "done.json", {"experiment": spec.EXPERIMENT,
                                           "condition": cond.id, "seed": seed,
                                           "ticks": ticks, "fingerprint": fingerprint,
                                           "mode": verify["mode"]})
    finally:
        collector.close()
        monitor.close()
        eco.close()
    totals = measurement["totals"]
    return {"interrupted": interrupted, "condition": cond.id, "seed": seed,
            "ticks": totals["ticks"], "arrivals": totals["arrivals"],
            "dispatched": totals["dispatched"], "backlog_end": totals["backlog_end"],
            "stations_end": totals["stations_end"],
            "routes_open_end": totals["routes_open_end"],
            "faults": [f["fault_id"] for f in measurement["faults_applied"]],
            "dkrmm": (state.get("current") or {}).get("state", "")}


def _table(rows: List[Dict[str, Any]], columns: Sequence[str]) -> str:
    if not rows:
        return "  (nothing)"
    width = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    head = "  " + "  ".join(f"{c:<{width[c]}}" for c in columns)
    lines = [head, "  " + "  ".join("-" * width[c] for c in columns)]
    for row in rows:
        lines.append("  " + "  ".join(f"{str(row.get(c, '')):<{width[c]}}" for c in columns))
    return "\n".join(lines)


# ------------------------------------------------------------------- analyze
def analyze(out: Path) -> Dict[str, Any]:
    """Classify every C0/C2 run under `out` against the N run of its seed."""
    results: List[Dict[str, Any]] = []
    for cond_id in ("C0", "C2"):
        cond_dir = out / cond_id
        if not cond_dir.is_dir():
            continue
        for run_dir in sorted(p for p in cond_dir.iterdir() if p.is_dir()
                              and p.name.startswith("s")):
            try:
                seed = int(run_dir.name[1:])
            except ValueError:
                continue
            series = run_dir / "series.csv"
            control = out / "N" / run_dir.name / "series.csv"
            row: Dict[str, Any] = {"condition": cond_id, "seed": seed,
                                   "run": str(run_dir.relative_to(out)),
                                   "done": (run_dir / "done.json").exists()}
            if not series.exists():
                row["outcome"] = "no series"
                results.append(row)
                continue
            if not control.exists():
                row["outcome"] = "no control"
                results.append(row)
                continue
            verdict = classify(read_series(series), read_series(control))
            row.update(verdict)
            row["control_done"] = (out / "N" / run_dir.name / "done.json").exists()
            measurement = run_dir / "measurement.json"
            if measurement.exists():
                totals = json.loads(measurement.read_text(encoding="utf-8")).get("totals", {})
                row["attack_executed"] = int(totals.get("override_delivered", 0)) > 0
                row["override_delivered"] = int(totals.get("override_delivered", 0))
                row["dispatched"] = int(totals.get("dispatched", 0))
                row["backlog_end"] = int(totals.get("backlog_end", 0))
            results.append(row)
    summary = {"experiment": spec.EXPERIMENT, "label": spec.LABEL, "out": str(out),
               "collapse_params": dict(spec.COLLAPSE), "runs": results}
    _write(out / "summary.json", summary)
    return summary


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
            _write(out / "verify.json", {**verify, "ran": False})
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
                if (run_dir / "done.json").exists():
                    print(f"skip {cond.id} s{seed}: done.json exists at {run_dir}")
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
                result = run_one(cond, seed, args.ticks, run_dir, brains, verify)
                finished.append(result)
                if result["interrupted"]:
                    interrupted = True
                    break
            if interrupted:
                break

    if finished:
        print("")
        print(f"{spec.EXPERIMENT} runs ({mode})")
        print(_table(finished, ("condition", "seed", "ticks", "arrivals", "dispatched",
                                "backlog_end", "stations_end", "routes_open_end",
                                "dkrmm", "faults", "interrupted")))

    if args.analyze and not interrupted:
        summary = analyze(out)
        print("")
        print(f"collapse classification against N (same seed); {out / 'summary.json'}")
        print(_table(summary["runs"], ("condition", "seed", "outcome", "collapse_tick",
                                       "held_to_end", "critical_stop_tick",
                                       "first_degraded_tick", "degraded_ticks",
                                       "through_degraded_ticks", "backlog_degraded_ticks",
                                       "dispatched", "backlog_end", "attack_executed",
                                       "done")))

    if interrupted:
        print("INTERRUPTED")
        return INTERRUPTED
    return 0


if __name__ == "__main__":
    sys.exit(main())
