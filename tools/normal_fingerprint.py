#!/usr/bin/env python3
"""
Fingerprint the rules-only Normal scenario, filtered, so that Prototype II can
be compared with the source it was copied from.

    python tools/normal_fingerprint.py --write OUT.json
    python tools/normal_fingerprint.py --from-source SOURCE --write OUT.json

Behaviour: four configurations run headless on the experts' rules for 1600
ticks with DK-RMM attached (the app's Normal on seeds 11 and 1, the default
configuration on 11, the code defaults on 1). Hashed: every per-tick
snapshot, DK-RMM's readings without `decided_at`, and the event log after the
filter `STRIP` (the model-layer notices dropped, the model-layer keys pruned
from `simulation_started.detail.config`, `wall_clock` and `run_id` removed, the
taxonomy stamp `interaction_type`, `channel` and `detail.in_reply_to` removed,
`seq` renumbered over the kept rows). The `events` counters of the snapshots
and of the summary are netted of the dropped rows, so they count the kept
stream. The summary is kept as its world counts only.

`--from-source` runs the same recipe against the source package in a
subprocess (the source on `sys.path`, `PYTHONHASHSEED=0`, its `.env` loading
disabled) and records the source tree hash with the result. Without it the
recipe runs against this project.

Only the temporary directory and OUT are written.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Set by `--from-source` for its subprocess: the package root whose
#: `post_office` the recipe imports. Unset, it is this project.
PACKAGE_ROOT = Path(os.environ.get("NF_PACKAGE_ROOT") or ROOT)
sys.path.insert(0, str(PACKAGE_ROOT))

#: What exists only because of one side's model layer and is filtered from
#: both sides identically before hashing (see docs/alignment-baseline.md).
STRIP = {
    "topics": {"llm_async", "discussions", "interception", "llm"},
    "config_keys": {"llm_async", "llm_deterministic", "llm_max_pending", "llm_timeout_s",
                    "llm_deadline_ticks", "llm_det_latency_ticks", "discussions",
                    "discussion_calls", "discussion_deadline_ticks", "discussion_max_open",
                    "discussion_bias", "perturbations", "interceptors"},
    # The traces the dropped rows would leave in what is kept: `seq` of the
    # kept rows is renumbered densely, and the `events` counters of every
    # snapshot and of the summary are netted of the rows dropped up to then.
    "side_effects": ["seq renumbered", "events counters netted"],
}

#: The runtime communication taxonomy's stamp, which the source never wrote:
#: two top-level keys on every event and one detail key on the bus's carried
#: messages. Removed from both sides before hashing, like `wall_clock` and
#: `run_id`, so the recorded baseline stays what it was. Kept beside `STRIP`
#: rather than in it because the baseline records `STRIP` and is compared
#: against it.
STAMP_KEYS = ("interaction_type", "channel")
STAMP_DETAIL_KEYS = ("in_reply_to",)

#: The world counts of `summary()` that are compared.
SUMMARY_KEYS = ("parcels_created", "parcels_dispatched", "parcels_refused",
                "parcels_returned", "parcels_late", "vans_departed", "tasks", "messages",
                "events", "reroutes", "supervisor_interventions", "robots_recovered")

#: The run names, their seeds and the short name inside each run id.
RUNS = (("app_normal_rules_seed11", "app11", 11),
        ("app_normal_rules_seed1", "app1", 1),
        ("default_config_seed11", "def11", 11),
        ("code_defaults_seed1", "code1", 1))


def h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def filter_rows(rows, strip=STRIP):
    """The event rows with the model-layer notices and keys taken out.

    `seq` is renumbered 1..N over the kept rows in their original order, so a
    dropped notice leaves no gap or offset in the numbering after it. The
    taxonomy's stamp (`STAMP_KEYS`, `STAMP_DETAIL_KEYS`) is removed too.
    """
    out = []
    for row in rows:
        if row.get("topic") in strip["topics"]:
            continue
        row = dict(row)
        row["seq"] = len(out) + 1
        row.pop("wall_clock", None)
        row.pop("run_id", None)
        for key in STAMP_KEYS:
            row.pop(key, None)
        if isinstance(row.get("detail"), dict) and \
                any(key in row["detail"] for key in STAMP_DETAIL_KEYS):
            row["detail"] = {k: v for k, v in row["detail"].items()
                             if k not in STAMP_DETAIL_KEYS}
        if row.get("topic") == "simulation_started":
            detail = dict(row.get("detail") or {})
            if isinstance(detail.get("config"), dict):
                detail["config"] = {k: v for k, v in detail["config"].items()
                                    if k not in strip["config_keys"]}
            row["detail"] = detail
        out.append(row)
    return out


def stripped_ticks(rows, strip=STRIP):
    """The tick of every row the filter drops, in log order."""
    return [row.get("tick", 0) for row in rows if row.get("topic") in strip["topics"]]


def net_snapshots(snaps, dropped_ticks):
    """Each snapshot with its `events` counter netted of the rows dropped up to its tick.

    A snapshot is taken after its tick has run, so every row of that tick or
    earlier is already in the counter; a notice at tick 0 is netted from every
    snapshot.
    """
    out = []
    for snap in snaps:
        snap = dict(snap)
        snap["events"] = snap["events"] - sum(1 for t in dropped_ticks if t <= snap["tick"])
        out.append(snap)
    return out


def run_one(name, seed, cfg, ticks=1600, strip=STRIP):
    from post_office.dkrmm import DKRMM
    from post_office.simulation.ecosystem import build

    log = os.path.join(tempfile.mkdtemp(), "events.jsonl")
    eco = build(seed=seed, config=cfg, run_id=f"fp-{name}", log_path=log, scenario="normal")
    monitor = DKRMM(eco).attach()
    eco.start()
    snaps = []
    for _ in range(ticks):
        eco.step()
        monitor.tick()
        snaps.append(eco.snapshot())
    eco.logger.flush()
    rows = []
    with open(log, encoding="utf-8") as fh:
        for line in fh:
            rows.append(json.loads(line))
    dropped = stripped_ticks(rows, strip)
    rows = filter_rows(rows, strip)
    snaps = net_snapshots(snaps, dropped)
    readings = []
    for r in monitor.history:
        d = r.as_dict()
        d.pop("decided_at", None)
        readings.append(d)
    summary = eco.summary()
    try:
        eco.close()
    except Exception:
        pass
    return {"seed": seed, "ticks": ticks, "events": len(rows),
            "snapshots_sha256": h(snaps), "dkrmm_readings_sha256": h(readings),
            "dkrmm_states": [r["state"] for r in readings],
            "rct_ticks": [r["tick"] for r in readings if r["state"] == "RCT"],
            "event_stream_filtered_sha256": h(rows),
            "summary": {k: (summary[k] - len(dropped) if k == "events" else summary[k])
                        for k in SUMMARY_KEYS}}


def _configs(side):
    """The four configurations, built the way each side builds them."""
    if side == "source":
        from post_office.api.runner import interactive_config
        from post_office.config.settings import config

        return (interactive_config(config("default")), interactive_config(config("default")),
                config("default"), None)
    from post_office.config.settings import DEFAULT_CONFIG, normal_config

    return (normal_config(), normal_config(), DEFAULT_CONFIG, None)


def runs(ticks=1600, side="prototype"):
    out = {}
    for (name, short, seed), cfg in zip(RUNS, _configs(side)):
        out[name] = run_one(short, seed, cfg, ticks)
    return out


def strip_json(strip=STRIP):
    return {k: (sorted(v) if isinstance(v, set) else list(v)) for k, v in strip.items()}


def from_source(source: Path, ticks: int) -> dict:
    """`runs()` against the source package, in a subprocess."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PO_")}
    env.update({"PYTHONHASHSEED": "0", "PO_NO_DOTENV": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "NF_PACKAGE_ROOT": str(source)})
    env.pop("PYTHONPATH", None)
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--emit-runs",
                           "source", "--ticks", str(ticks)],
                          cwd=str(source), env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"source run failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-source", default="")
    ap.add_argument("--write", default="")
    ap.add_argument("--ticks", type=int, default=1600)
    ap.add_argument("--emit-runs", default="", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.emit_runs:
        print(json.dumps(runs(a.ticks, side=a.emit_runs), default=str))
        return 0
    if a.from_source:
        from tools.provenance import tree_sha

        source = Path(a.from_source).resolve()
        before = tree_sha(source)
        result_runs = from_source(source, a.ticks)
        if tree_sha(source) != before:
            raise RuntimeError("the source tree changed while it was being run")
        result = {"source_tree_sha256": before}
    else:
        result_runs = runs(a.ticks)
        result = {"source_tree_sha256": None}
    result.update({"generated_at": datetime.datetime.now(datetime.timezone.utc)
                   .isoformat(timespec="seconds"),
                   "ticks": a.ticks, "strip": strip_json(), "runs": result_runs})
    text = json.dumps(result, indent=1, default=str) + "\n"
    if a.write:
        Path(a.write).parent.mkdir(parents=True, exist_ok=True)
        Path(a.write).write_text(text, encoding="utf-8", newline="\n")
    for k, v in result_runs.items():
        print(k, v["events"], v["event_stream_filtered_sha256"][:16],
              v["snapshots_sha256"][:16], v["dkrmm_readings_sha256"][:16],
              "RCT at", v["rct_ticks"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
