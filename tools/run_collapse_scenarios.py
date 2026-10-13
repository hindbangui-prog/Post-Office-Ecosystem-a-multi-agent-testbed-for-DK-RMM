#!/usr/bin/env python3
"""
Collapse scenarios: run them, then classify them against the control.

    python tools/run_collapse_scenarios.py --scenario all --rules
    python tools/run_collapse_scenarios.py --scenario ms-drop --scenario cs-starve --rules
    python tools/run_collapse_scenarios.py --scenario all --rules --control-from results/c2_near_system_override
    python tools/run_collapse_scenarios.py --analyze

Each run is one scenario (`N` control, `ms-drop`, `ms-delay`, `cs-starve`,
`cs-partition`, `ms-stall`; `all` is the six) and one seed, built from
`normal_config()`, stepped `--ticks` ticks with the scenario's one fault fired
at its start (400; M-S-STALL 1800) by `CollapseFaults` and DK-RMM attached as
an observer, and written under `<out>/<scenario id>/s<seed>/` (`N`, `MS-DROP`,
`MS-DELAY`, `CS-STARVE`, `CS-PARTITION`, `MS-STALL`):

    definition.json      the scenario definition, its fingerprint, the seed,
                         the mode (rules / model) and the ticks asked for
    events.jsonl         the run's event log
    series.csv           one measurement row per tick (`measure.Collector`)
    measurement.json     mode, ticks, totals, the fault applied, the
                         scenario's counters, per-route table, summary,
                         reasoning summary, DK-RMM state
    dkrmm.json           DK-RMM's final state, its run record, and `dk`: the
                         readings whose dragon-king test held, and those of
                         them the monitor called RCT (the live page's DK)
    summary.json         the ecosystem's summary
    verify.json          the model identity and the served-model check
                         (model mode) or the rules note
    done.json            written last, with `mode` and `ticks`; a directory
                         that has one is skipped and never overwritten

`--out` defaults to `results/collapse_scenarios` and is refused when it
resolves inside `results/normal`. `--rules` puts every expert on its rules
and is allowed for all six: none of these mechanisms needs the model. Model
mode is exactly the C2-NEAR driver's: the Ollama settings are read, the
configured model's identity verified, the experts built with `llm_brains`
per run, and `verify.json` records which model served every call.

`--control-from <dir>` names a results directory whose `N/s<seed>` runs
serve as the control (the C2-NEAR study's N is the same N) when such a run
exists there, is done, and was made in the same mode with the same `--ticks`;
otherwise the control is `<out>/N/s<seed>`. With `--control-from`, `all`
skips the N runs it finds there.

`--analyze` classifies every scenario run under `--out` against its control
(`post_office.stress.collapse.classify`), only when the two were made in the
same mode and with the same `--ticks` (read from `done.json`, else
`definition.json`); a pair that differs is printed and recorded as
`not_comparable`. It writes `<out>/summary.json` and prints the table.

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
# The C2-NEAR driver's helpers (the results/normal refusal, run identity,
# the table, the model-call collector and the served-model check) are the
# same here, so they are imported from it rather than copied.
sys.path.insert(0, str(ROOT / "tools"))

import run_c2near_system_override as c2driver  # noqa: E402

from post_office.communication.events import EventCategory  # noqa: E402
from post_office.crew.console import utf8_stdout  # noqa: E402
from post_office.dkrmm import DKRMM, build_record  # noqa: E402
from post_office.stress.states import four_state  # noqa: E402
from post_office.simulation import build  # noqa: E402
from post_office.stress import collapse_scenarios as spec  # noqa: E402
from post_office.stress.collapse import classify  # noqa: E402
from post_office.stress.measure import read_series  # noqa: E402

INTERRUPTED = c2driver.INTERRUPTED
FORBIDDEN = c2driver.FORBIDDEN
NOT_COMPARABLE = c2driver.NOT_COMPARABLE
refuse_normal = c2driver.refuse_normal
run_identity = c2driver.run_identity
_write = c2driver._write
_read_json = c2driver._read_json
_table = c2driver._table

CHOICES = (*spec.NAMES, "all")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"{spec.LABEL}: run the scenarios, then classify them against N")
    parser.add_argument("--scenario", action="append", choices=CHOICES,
                        help="scenario to run (repeatable; `all` is every one); default: none")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(spec.SEEDS),
                        help=f"seeds (default {' '.join(map(str, spec.SEEDS))})")
    parser.add_argument("--ticks", type=int, default=spec.RUN_TICKS,
                        help=f"ticks per run (default {spec.RUN_TICKS})")
    parser.add_argument("--out", default=str(ROOT / spec.RESULTS_DIR),
                        help=f"results directory (default {spec.RESULTS_DIR})")
    parser.add_argument("--rules", action="store_true",
                        help="every expert on its rules (allowed for every scenario)")
    parser.add_argument("--control-from", default=None,
                        help="a results directory whose N/s<seed> runs serve as the control "
                             "(same mode and ticks); otherwise the N under --out")
    parser.add_argument("--analyze", action="store_true",
                        help="classify every scenario run under --out against its control")
    return parser.parse_args(argv)


def expand(names: Sequence[str]) -> List[spec.Scenario]:
    """The scenarios asked for, in the study's order, each once; `all` is the six."""
    wanted = set()
    for name in names:
        if name == "all":
            wanted.update(spec.NAMES)
        else:
            wanted.add(name)
    return [spec.scenario(name) for name in spec.NAMES if name in wanted]


def control_dir(out: Path, seed: int, mode: Optional[str], ticks: Optional[int],
                control_from: Optional[Path]) -> Path:
    """
    The control run for `seed`: `<control_from>/N/s<seed>` when it exists
    there, is done, and matches `mode` and `ticks`; else `<out>/N/s<seed>`.
    """
    if control_from is not None:
        candidate = control_from / "N" / f"s{seed}"
        if (candidate / "done.json").exists():
            identity = run_identity(candidate)
            if ((mode is None or identity["mode"] == mode)
                    and (ticks is None or identity["ticks"] == ticks)):
                return candidate
    return out / "N" / f"s{seed}"


# ------------------------------------------------------------------- one run
def run_one(scn: spec.Scenario, seed: int, ticks: int, run_dir: Path,
            brains: Optional[Dict[str, Any]], verify: Dict[str, Any],
            settings: Any = None) -> Dict[str, Any]:
    """
    Build, step and write one run. Returns `{"interrupted": bool, ...}`.

    The loop, per tick: the fault due this tick is fired, the ecosystem
    steps, DK-RMM assesses (observe only; an error there is recorded and does
    not stop the run), the model calls so far are read from the service, and
    the collector appends its row.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    definition = spec.definition(scn)
    fingerprint = spec.fingerprint(scn)
    mode = verify["mode"]
    _write(run_dir / "definition.json",
           {**definition, "fingerprint": fingerprint, "seed": seed, "ticks": ticks,
            "mode": mode})

    eco = build(seed, config=spec.config(scn), log_path=str(run_dir / "events.jsonl"),
                run_id=f"{spec.STUDY}-{scn.id}-s{seed}", brains=brains, scenario="normal")
    monitor = DKRMM(eco).attach()
    faults = spec.CollapseFaults(eco, scn)
    collector = spec.ScenarioCollector(eco, scn, faults, monitor=monitor, mode=mode,
                                       ticks=ticks)
    calls = c2driver._CallCollector(eco.crew)
    monitor_errors: List[str] = []
    interrupted = False
    try:
        eco.logger.emit(EventCategory.SIMULATION, "collapse_scenario", tick=0,
                        actor="SIMULATION", study=spec.STUDY, scenario=scn.id,
                        fingerprint=fingerprint, definition=definition)
        eco.start()
        try:
            for tick in range(1, int(ticks) + 1):
                faults.before_tick(tick)
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
                              config=eco.config, control=scn.control)
        state = monitor.state()
        measurement = collector.write(run_dir, interrupted=interrupted)
        eco.logger.flush()
        dk = dk_of(monitor.history)
        _write(run_dir / "dkrmm.json", {"state": state, "record": record,
                                        "errors": monitor_errors, "dk": dk})
        _write(run_dir / "summary.json", summary)
        run_verify = {**verify, "llm": eco.llm_summary(), "interrupted": interrupted}
        if mode == "model" and settings is not None:
            calls.collect()
            run_verify.update(c2driver._served_check(calls.calls, settings.model,
                                                     bool(verify.get("ok"))))
        _write(run_dir / "verify.json", run_verify)
        if not interrupted:
            _write(run_dir / "done.json", {"study": spec.STUDY, "scenario": scn.id,
                                           "preset": scn.preset, "seed": seed,
                                           "ticks": ticks, "fingerprint": fingerprint,
                                           "mode": mode})
    finally:
        collector.close()
        monitor.close()
        eco.close()
    totals = measurement["totals"]
    counters = measurement.get("counters") or {}
    last = collector.rows[-1] if collector.rows else {}
    return {"interrupted": interrupted, "scenario": scn.id, "seed": seed,
            "ticks": totals["ticks"], "arrivals": totals["arrivals"],
            "arrival_refused": totals["arrival_refused"],
            "dispatched": totals["dispatched"], "backlog_end": totals["backlog_end"],
            "stations_end": totals["stations_end"],
            "routes_open_end": totals["routes_open_end"],
            "robots_flat_end": int(last.get("robots_flat", 0) or 0),
            "faults": [f["fault_id"] for f in measurement["faults_applied"]],
            "dropped": counters.get("dropped", 0), "delayed": counters.get("delayed", 0),
            "refused": counters.get("recovery_refused", 0),
            "held": counters.get("held", 0),
            "first_dk_tick": dk["first_dk_tick"], "dk_readings": dk["dk_readings"],
            "max_ratio": dk["max_ratio"],
            # The printed table shows the study's four-state view (RECOVERY
            # as STABLE); `dkrmm.json` keeps the monitor's own word.
            "dkrmm": four_state((state.get("current") or {}).get("state", "")),
            "rcts": int((state.get("counts") or {}).get("RCT", 0) or 0)}


# ------------------------------------------------------------------- analyze
def dk_of(history: Sequence[Any]) -> Dict[str, Any]:
    """
    What DK-RMM's dragon-king test said over a run, read off the monitor's
    readings as they were made (nothing recomputed): the ticks at which it
    held, the first one, the RCT readings at which it held (the live page's
    DK) and the first of those, and the largest observed-to-expected ratio
    with its tick.
    """
    dragons = [int(a.tick) for a in history if a.dragon.is_dragon]
    page = [int(a.tick) for a in history
            if a.dragon.is_dragon and getattr(a.state, "value", a.state) == "RCT"]
    best = max(history, key=lambda a: float(a.dragon.ratio), default=None)
    return {"dragon_ticks": dragons, "first_dragon_tick": dragons[0] if dragons else None,
            "dk_ticks": page, "first_dk_tick": page[0] if page else None,
            "dk_readings": len(page),
            "max_ratio": round(float(best.dragon.ratio), 3) if best is not None else None,
            "max_ratio_tick": int(best.tick) if best is not None else None}


def _run_dirs(out: Path, scenario_id: str) -> List[Path]:
    return c2driver._run_dirs(out, scenario_id)


def _dkrmm_of(run_dir: Path) -> Dict[str, Any]:
    """
    The run's final DK-RMM state in the four-state view, its RCT count and
    its dragon-king summary (`dk_of`), from `dkrmm.json`.
    """
    data = _read_json(run_dir / "dkrmm.json") or {}
    state = data.get("state") or {}
    dk = data.get("dk") or {}
    return {"dkrmm": four_state((state.get("current") or {}).get("state", "")),
            "rcts": int((state.get("counts") or {}).get("RCT", 0) or 0),
            "first_dk_tick": dk.get("first_dk_tick"), "dk_readings": dk.get("dk_readings"),
            "max_ratio": dk.get("max_ratio")}


def analyze(out: Path, control_from: Optional[Path] = None) -> Dict[str, Any]:
    """Classify every scenario run under `out` against the control of its seed."""
    results: List[Dict[str, Any]] = []
    not_comparable: List[Dict[str, Any]] = []
    for name in spec.NAMES:
        scn = spec.scenario(name)
        if scn.control:
            continue
        for run_dir in _run_dirs(out, scn.id):
            seed = int(run_dir.name[1:])
            mine = run_identity(run_dir)
            ctl_dir = control_dir(out, seed, mine["mode"], mine["ticks"], control_from)
            series = run_dir / "series.csv"
            control = ctl_dir / "series.csv"
            row: Dict[str, Any] = {"scenario": scn.id, "preset": scn.preset, "seed": seed,
                                   "run": str(run_dir.relative_to(out)),
                                   "control": str(ctl_dir),
                                   "done": (run_dir / "done.json").exists(),
                                   "control_done": (ctl_dir / "done.json").exists()}
            if not series.exists():
                row["outcome"] = "no series"
                results.append(row)
                continue
            if not control.exists():
                row["outcome"] = "no control"
                results.append(row)
                continue
            theirs = run_identity(ctl_dir)
            row["mode"], row["ticks"] = mine["mode"], mine["ticks"]
            row["control_mode"], row["control_ticks"] = theirs["mode"], theirs["ticks"]
            problems = []
            if mine["mode"] != theirs["mode"]:
                problems.append(f"mode {mine['mode']!r} vs control {theirs['mode']!r}")
            if mine["ticks"] != theirs["ticks"]:
                problems.append(f"ticks {mine['ticks']!r} vs control {theirs['ticks']!r}")
            if problems:
                reason = "; ".join(problems)
                print(f"refuse {scn.id} s{seed}: not comparable with N s{seed} ({reason}); "
                      "a run is classified only against a control made in the same mode "
                      "and with the same --ticks")
                row["outcome"] = NOT_COMPARABLE
                row["not_comparable_reason"] = reason
                results.append(row)
                not_comparable.append({"scenario": scn.id, "seed": seed, "reason": reason})
                continue
            verdict = classify(read_series(series), read_series(control))
            row.update(verdict)
            measurement = _read_json(run_dir / "measurement.json") or {}
            totals = measurement.get("totals", {})
            counters = measurement.get("counters") or {}
            row["dispatched"] = int(totals.get("dispatched", 0))
            row["backlog_end"] = int(totals.get("backlog_end", 0))
            row["arrival_refused"] = int(totals.get("arrival_refused", 0))
            row["dropped"] = counters.get("dropped", 0)
            row["delayed"] = counters.get("delayed", 0)
            row["refused"] = counters.get("recovery_refused", 0)
            row["held"] = counters.get("held", 0)
            row["held_now"] = counters.get("held_now", 0)
            row["stations_end"] = int(totals.get("stations_end", 0))
            rows = read_series(series)
            row["robots_flat_end"] = int(rows[-1].get("robots_flat", 0) or 0) if rows else 0
            row.update(_dkrmm_of(run_dir))
            results.append(row)
    summary = {"study": spec.STUDY, "label": spec.LABEL, "out": str(out),
               "control_from": None if control_from is None else str(control_from),
               "collapse_params": dict(spec.COLLAPSE), "runs": results,
               "not_comparable": not_comparable}
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
    print(_table(runs, ("scenario", "seed", "mode", "ticks", "outcome", "criterion",
                        "collapse_tick", "held_to_end", "first_degraded_tick",
                        "critical_stop_tick", "degraded_ticks", "dispatched", "backlog_end",
                        "arrival_refused", "robots_flat_end", "dropped", "delayed", "refused",
                        "held", "dkrmm", "rcts", "first_dk_tick", "dk_readings", "max_ratio",
                        "done")))


# ---------------------------------------------------------------------- main
def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    utf8_stdout()
    try:
        out = refuse_normal(Path(args.out))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    control_from = Path(args.control_from).resolve() if args.control_from else None
    scenarios = expand(args.scenario or [])
    if not scenarios and not args.analyze:
        print("nothing to do: give --scenario (repeatable, or `all`) and/or --analyze",
              file=sys.stderr)
        return 2

    mode = "rules" if args.rules else "model"
    settings = None
    verify: Dict[str, Any] = {"mode": mode}
    if scenarios and mode == "model":
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
    elif scenarios:
        verify = {"mode": mode, "ok": None,
                  "note": "rules-only run: no model was asked and no identity was checked"}

    if mode == "model" and scenarios:
        from post_office.crew.console import quiet
        console = quiet()
    else:
        console = contextlib.nullcontext()

    finished: List[Dict[str, Any]] = []
    interrupted = False
    with console:
        for scn in scenarios:
            for seed in args.seeds:
                run_dir = out / scn.id / f"s{seed}"
                if scn.control and control_from is not None:
                    elsewhere = control_dir(out, seed, mode, args.ticks, control_from)
                    if elsewhere != run_dir and (elsewhere / "done.json").exists():
                        print(f"skip N s{seed}: the control is {elsewhere} (--control-from)")
                        continue
                done = _read_json(run_dir / "done.json")
                if done is not None:
                    print(f"skip {scn.id} s{seed}: done (mode={done.get('mode')}, "
                          f"ticks={done.get('ticks')}) at {run_dir}")
                    continue
                if (run_dir / "events.jsonl").exists():
                    print(f"skip {scn.id} s{seed}: an incomplete run is at {run_dir} "
                          "(no done.json); move it away to run this seed again")
                    continue
                print(f"run  {scn.id} s{seed}: {args.ticks} ticks, {mode} -> {run_dir}")
                brains = None
                if settings is not None:
                    from post_office.config.settings import llm_brains
                    brains = llm_brains(settings=settings, verify=False)
                result = run_one(scn, seed, args.ticks, run_dir, brains, verify,
                                 settings=settings)
                finished.append(result)
                if result["interrupted"]:
                    interrupted = True
                    break
            if interrupted:
                break

    if finished:
        print("")
        print(f"{spec.LABEL} runs ({mode})")
        print(_table(finished, ("scenario", "seed", "ticks", "arrivals", "arrival_refused",
                                "dispatched", "backlog_end", "stations_end",
                                "routes_open_end", "robots_flat_end", "dropped", "delayed",
                                "refused", "held", "dkrmm", "rcts", "first_dk_tick",
                                "dk_readings", "max_ratio", "faults", "interrupted")))

    if args.analyze and not interrupted:
        summary = analyze(out, control_from)
        print_analysis(summary, out)

    if interrupted:
        print("INTERRUPTED")
        return INTERRUPTED
    return 0


if __name__ == "__main__":
    sys.exit(main())
