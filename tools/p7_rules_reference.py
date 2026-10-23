#!/usr/bin/env python3
"""
The rules-only reference for the P7-ONOFF-MODEL page: `post_office/stress/p7_rules_reference.json`.

For each seed of the ON-OFF seed picker (`onoff_attack.SEED_OPTIONS`) the existing
`p7-onoff` preset is run on the live path (`SimulationRunner`, every expert on its
rules, DK-RMM attached) to its horizon of 4400 ticks, and what the page would show
at the horizon is kept: the trap, the impact counters, the displacement count and
DK-RMM's block, with the sha256 of the run's event stream (ticks 1-4400, without
wall_clock/run_id/seq, the convention of `tests/test_p7_onoff.py`) so the figures
can be traced to the run that produced them. These are not new experiments: the
runs are deterministic in the seed and seed 11977's stream is the frozen Phase 7
confirmation run's (its hash is checked against `FROZEN_EVENTS_SHA256_4400`).

    PYTHONHASHSEED=0 .venv/bin/python tools/p7_rules_reference.py [--seeds 11977 12070 ...]

The page's side-by-side column reads this file through `onoff_model.reference(seed)`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from post_office.api.runner import SimulationRunner  # noqa: E402
from post_office.crew.console import quiet  # noqa: E402
from post_office.stress import onoff_attack as spec  # noqa: E402
from post_office.stress.onoff_model import REFERENCE_PATH  # noqa: E402

FROZEN_EVENTS_SHA256_4400 = "f70f84e795f8325164b490493b526afb13f3b764d0042d34b1844928e440ec5e"

IMPACT_KEYS = ("robots_blocked", "robots_trapped", "robots_available", "robots_total", "blocked_robot_ticks",
               "blocked_robot_ticks_in_window", "hospital_total", "hospital_arrived", "hospital_awaiting",
               "hospital_dispatched", "hospital_dispatched_late", "hospital_missed_promise", "hospital_refused",
               "standard_dispatched", "dispatched_total", "parcels_in_building", "dock_refused")


def events_sha(log_path: str, upto: int) -> str:
    rows = []
    for line in open(log_path, encoding="utf-8"):
        event = json.loads(line)
        if not 1 <= int(event.get("tick", 0)) <= upto:
            continue
        for key in ("wall_clock", "run_id", "seq"):
            event.pop(key, None)
        rows.append(json.dumps(event, sort_keys=True, separators=(",", ":")))
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def run(seed: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        log = os.path.join(tmp, "events.jsonl")
        with quiet():
            runner = SimulationRunner(seed=seed, preset=spec.PRESET, rules_only=True, verify_model=False,
                                      tick_seconds=0.0, run_id="p7ref", log_path=log)
            try:
                runner.eco.start()
                while runner.eco.world.tick < spec.RUN_TICKS and runner._tick():
                    pass
                runner._logger.flush()
                study = runner.study_status()
                sha = events_sha(log, spec.RUN_TICKS)
            finally:
                runner.close()
    st = study["status"]
    trap = st["trap"]
    dk = study["dkrmm"]
    summary = study["summary"] or {}
    return {
        "tick": int(st["impact"]["tick"]),
        "complete": bool(study["complete"]),
        "events_sha256": sha,
        "trap": {k: trap.get(k) for k in ("occurred", "persistent", "started", "ended", "robots", "no_errand",
                                           "zone", "formed_in", "off_phases_crossed", "survived_window_end",
                                           "ticks_so_far", "longest_streak")},
        "episodes": len(trap.get("episodes") or []),
        "impact": {k: st["impact"].get(k) for k in IMPACT_KEYS},
        "displaced": int((st["displacement"] or {}).get("displaced", 0)),
        "dkrmm": {k: dk.get(k) for k in ("attached", "assessments", "state", "rct_ticks", "first_rct_tick",
                                         "dk_ticks", "first_dk_tick", "counts")},
        "summary_note": summary.get("note", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, nargs="*", default=[seed for seed, _ in spec.SEED_OPTIONS])
    parser.add_argument("--out", default=str(REFERENCE_PATH))
    args = parser.parse_args()
    out_path = Path(args.out)
    data = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    runs = data.setdefault("runs", {})
    for seed in args.seeds:
        row = run(int(seed))
        if int(seed) == spec.DEMO_SEED and row["events_sha256"] != FROZEN_EVENTS_SHA256_4400:
            print(f"seed {seed}: event stream differs from the frozen confirmation run "
                  f"({row['events_sha256'][:16]} != {FROZEN_EVENTS_SHA256_4400[:16]}); not written", file=sys.stderr)
            return 1
        runs[str(int(seed))] = row
        t = row["trap"]
        trap_text = f"yes ({', '.join(t['robots'])} from {t['started']})" if t["occurred"] else "no"
        print(f"seed {seed}: trap {trap_text}"
              f", hospital dispatched {row['impact']['hospital_dispatched']} of {row['impact']['hospital_arrived']} arrived"
              f", DK readings {len(row['dkrmm']['dk_ticks'] or [])}, events {row['events_sha256'][:16]}", flush=True)
    data.update({
        "preset": spec.PRESET, "horizon": spec.RUN_TICKS,
        "source": "tools/p7_rules_reference.py: the p7-onoff preset on the live path, every expert on its rules, "
                  "to the horizon; deterministic in the seed; seed 11977 checked against the frozen Phase 7 run",
        "computed": date.today().isoformat(),
        "seed_options": [[seed, label] for seed, label in spec.SEED_OPTIONS],
    })
    out_path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"written {out_path} ({len(runs)} seeds)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
