#!/usr/bin/env python3
"""
One NORMAL run with the seven experts on the model, and the evidence for it (spec 19).

    python tools/run_normal.py --ticks 300 --seed 1
    python tools/run_normal.py --ticks 300 --seed 1 --out results/normal --rules

Model mode (the default) reads the Ollama settings (environment over `.env`),
asks the server for the configured model's identity (`verify_model`), and stops
with exit code 2 if the model is not there, writing only `verify.json`.
Otherwise it builds the ecosystem with `llm_brains`, attaches DK-RMM, steps
`--ticks` ticks and writes, under `<out>/s<seed>/`:

    events.jsonl         the run's event log
    consultations.json   every consultation (owner, peer, request, response, decision, ...)
    llm_calls.json       every model call as the transport audit saw it
    dkrmm.json           DK-RMM's final state and its run record (states, transitions, RCTs)
    summary.json         the ecosystem's summary plus each brain's stats()
    verify.json          the identity, the base URL, the served models seen, ok

and prints a report: the identity; consultations by owner -> peer; the first
decided consultation; the decision-path table; DK-RMM's state history and RCT
ticks; fallback and retry counts.

The exit code is 0 only if `verify.json["ok"]` (the identity check passed and no
call was served by another model) and at least one model call was served by the
configured model; 1 otherwise. `--rules` runs every expert on its rules, asks
no model, writes the same six files (`verify.json` is `{"mode": "rules", ...}`)
and exits 0 when the run completes.

The report shows what the tool saw: the base URL it was configured with and
the model names the server put in its replies. It does not, and cannot, say
which server that was; that judgement is the reader's.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from post_office.config.settings import EXPERTS, normal_config  # noqa: E402
from post_office.crew.console import utf8_stdout  # noqa: E402
from post_office.dkrmm import DKRMM, build_record  # noqa: E402
from post_office.simulation import build  # noqa: E402

FILES = ("events.jsonl", "consultations.json", "llm_calls.json", "dkrmm.json",
         "summary.json", "verify.json")
#: The counters of `CrewBrain.stats()` the report adds up.
COUNTERS = ("calls", "consultations", "fallbacks", "retries", "parse_failures",
            "rejected_answers", "timeouts")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One NORMAL run and its evidence files")
    parser.add_argument("--ticks", type=int, default=300, help="ticks to run (default 300)")
    parser.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    parser.add_argument("--out", default=str(ROOT / "results" / "normal"),
                        help="results directory (default results/normal)")
    parser.add_argument("--rules", action="store_true",
                        help="every expert on its rules; no model is asked")
    return parser.parse_args(argv)


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8",
                    newline="\n")


class _Collector:
    """
    Every consultation and model call of the run, kept as they appear.

    The service keeps a bounded window of each; reading the new rows after
    every tick keeps all of them however long the run is.
    """

    def __init__(self, crew: Any) -> None:
        self.crew = crew
        self.consultations: List[Dict[str, Any]] = []
        self.calls: List[Dict[str, Any]] = []
        self._seen_consultations: set = set()
        self._seen_calls: set = set()

    def collect(self) -> None:
        if self.crew is None:
            return
        for row in self.crew.recent(500):
            if row["id"] not in self._seen_consultations:
                self._seen_consultations.add(row["id"])
                self.consultations.append(row)
        for row in self.crew.llm_calls(2000):
            if row["call_id"] not in self._seen_calls:
                self._seen_calls.add(row["call_id"])
                self.calls.append(row)


def _brain_stats(eco: Any) -> Dict[str, Dict[str, Any]]:
    out = {}
    for agent_id in EXPERTS:
        brain = eco.agents[agent_id].brain
        if getattr(brain, "name", "") == "crewai":
            out[agent_id] = brain.stats()
    return out


def _state_runs(states: List[Dict[str, Any]]) -> List[str]:
    """DK-RMM's states as runs: 'ticks 20..140  STABLE  (7 assessments)'."""
    lines: List[str] = []
    start = None
    for index, row in enumerate(states):
        if start is None:
            start = index
        last = index == len(states) - 1
        if last or states[index + 1]["state"] != row["state"]:
            first_tick, last_tick = states[start]["tick"], row["tick"]
            span = f"{first_tick}" if first_tick == last_tick else f"{first_tick}..{last_tick}"
            lines.append(f"  ticks {span:<12} {row['state']:<10} "
                         f"({index - start + 1} assessment{'s' if index > start else ''})")
            start = None
    return lines


def report(mode: str, args: argparse.Namespace, out: Path, verify: Dict[str, Any],
           consultations: List[Dict[str, Any]], summary: Dict[str, Any],
           record: Dict[str, Any], brains: Dict[str, Dict[str, Any]]) -> str:
    lines: List[str] = []
    say = lines.append
    if mode == "model":
        say("REAL RUN EVIDENCE")
        say("(what this tool saw at the configured address; it does not establish "
            "which server answered)")
    else:
        say("RULES-ONLY RUN (no model was asked)")
    say(f"mode: {mode}   ticks: {summary['ticks']}   seed: {args.seed}   out: {out}")
    say("")

    say("model identity")
    if mode == "model":
        ident = verify["identity"]
        say(f"  base_url: {verify['base_url']}")
        say(f"  model: {ident['model']}   digest: {ident['digest'] or '-'}")
        say(f"  family: {ident['family'] or '-'}   parameter_size: "
            f"{ident['parameter_size'] or '-'}   quantization: {ident['quantization'] or '-'}")
        say(f"  installed: {', '.join(ident['installed']) or 'none'}")
        say(f"  identity ok: {ident['ok']}   problems: {'; '.join(ident['problems']) or 'none'}")
        served = verify["served_models"]
        say("  served models in llm_calls: " + (", ".join(
            f"{name or '(none: no reply)'} x{n}" for name, n in served.items()) or "no calls"))
        say(f"  ok: {verify['ok']}")
    else:
        say("  none (rules-only)")
    say("")

    pairs = Counter((c["owner"], c["peer"] or "(no peer)") for c in consultations)
    say(f"consultations by owner → peer ({len(consultations)} in all)")
    for (owner, peer), n in sorted(pairs.items()):
        say(f"  {owner:<11} → {peer:<11} {n}")
    if not pairs:
        say("  none")
    outcomes = Counter(c["outcome"] for c in consultations)
    if outcomes:
        say("  outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(outcomes.items())))
    say("")

    first = next((c for c in consultations if c["outcome"] == "decided"), None)
    say("first decided consultation")
    if first is None:
        say("  none in this run")
    else:
        for label, value in (("tick", first["tick"]), ("sender", first["owner"]),
                             ("receiver", first["peer"] or "(no peer)"),
                             ("request", first["request"] or "(none)"),
                             ("response", first["response"] or "(none)"),
                             ("decision", first["decision"]), ("model", first["model"]),
                             ("latency", f"{first['latency_ms']} ms"),
                             ("consultation_id", first["id"])):
            say(f"  {label}: {value}")
    say("")

    paths = summary["decision_paths"]
    total = sum(paths.values()) or 1
    say("decision paths")
    for path, n in paths.items():
        say(f"  {path:<20} {n:>6}  {100.0 * n / total:5.1f}%")
    say("")

    states = record["state_series"]
    say(f"DK-RMM state history ({len(states)} assessments)")
    lines.extend(_state_runs(states) or ["  no assessments"])
    rct = [t["tick"] for t in record["rct_events"]]
    say(f"RCT ticks: {', '.join(map(str, rct)) if rct else 'none'}")
    say("")

    say("brains (CrewBrain.stats)")
    if brains:
        width = {c: len(c) + 2 for c in COUNTERS}
        say("  " + f"{'agent':<11}" + "".join(f"{c:>{width[c]}}" for c in COUNTERS))
        for agent_id, stats in brains.items():
            say("  " + f"{agent_id:<11}" + "".join(f"{stats[c]:>{width[c]}}" for c in COUNTERS))
        totals = {c: sum(s[c] for s in brains.values()) for c in COUNTERS}
        say("  " + f"{'total':<11}" + "".join(f"{totals[c]:>{width[c]}}" for c in COUNTERS))
        say(f"  fallbacks: {totals['fallbacks']}   retries: {totals['retries']}")
        say("  (the decision path 'fallback' also counts model answers the policy gate "
            "refused and the rule replaced)")
    else:
        say("  none on the model: fallbacks: 0   retries: 0")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    utf8_stdout()
    mode = "rules" if args.rules else "model"
    out = Path(args.out) / f"s{args.seed}"
    out.mkdir(parents=True, exist_ok=True)

    settings = identity = None
    brains = None
    if mode == "model":
        from post_office.config.ollama import load_settings
        from post_office.crew.identity import verify_model

        try:
            settings = load_settings()
        except ValueError as exc:  # InvalidBaseUrl, InvalidModelName, a bad number
            print(f"invalid Ollama settings: {exc}", file=sys.stderr)
            return 2
        identity = verify_model(settings)
        if not identity.ok:
            _write(out / "verify.json", {"mode": mode, "ok": False, "ran": False,
                                         "base_url": settings.base_url,
                                         "settings": settings.as_dict(),
                                         "identity": identity.as_dict(), "served_models": {}})
            print(f"cannot run on the model: {'; '.join(identity.problems)}", file=sys.stderr)
            return 2
        from post_office.config.settings import llm_brains

        brains = llm_brains(settings=settings, verify=False)

    if mode == "model":
        from post_office.crew.console import quiet

        console = quiet()
    else:
        console = contextlib.nullcontext()

    with console:
        eco = build(args.seed, config=normal_config(), log_path=str(out / "events.jsonl"),
                    run_id=f"normal-s{args.seed}", brains=brains, scenario="normal")
        monitor = DKRMM(eco).attach()
        collector = _Collector(eco.crew)
        try:
            eco.start()
            for _ in range(int(args.ticks)):
                eco.step()
                monitor.tick()
                collector.collect()
            eco.stop("run complete")
            summary = {**eco.summary(), "reasoning": eco.reasoning_summary()}
            stats = _brain_stats(eco)
            record = build_record(eco.run_id, monitor, scenario="normal", seed=args.seed,
                                  config=eco.config, control=True)
            state = monitor.state()
        finally:
            monitor.close()
            eco.close()
        # A call an abandoned worker finished while `close` waited for it.
        collector.collect()

    calls = collector.calls
    if mode == "model":
        served = Counter(c["served_model"] for c in calls)
        mismatched = sorted(name for name in served if name and name != settings.model)
        verify = {"mode": mode, "ran": True, "base_url": settings.base_url,
                  "settings": settings.as_dict(), "identity": identity.as_dict(),
                  "served_models": dict(sorted(served.items())),
                  "served_by_configured_model": served.get(settings.model, 0),
                  "served_by_other_models": mismatched,
                  "ok": bool(identity.ok and not mismatched)}
    else:
        verify = {"mode": mode, "ok": None,
                  "note": "rules-only run: no model was asked and no identity was checked"}

    _write(out / "consultations.json", collector.consultations)
    _write(out / "llm_calls.json", calls)
    _write(out / "dkrmm.json", {"state": state, "record": record})
    _write(out / "summary.json", {**summary, "brains": stats})
    _write(out / "verify.json", verify)

    print(report(mode, args, out, verify, collector.consultations, summary, record, stats))
    if mode == "rules":
        return 0
    return 0 if verify["ok"] and verify["served_by_configured_model"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
