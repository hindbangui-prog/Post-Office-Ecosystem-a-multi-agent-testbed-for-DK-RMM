"""
Run the post office ecosystem from the command line.

    python main.py --ticks 300 --seed 1             the seven experts on CrewAI/Ollama
    python main.py --rules --ticks 300 --seed 1     every expert on its Python rules
    python main.py --rules --log run.jsonl          the same, with the event log on disk

The run is the NORMAL scenario, watched by DK-RMM; the summary and the
monitor's state are printed as JSON at the end. In model mode (the default) the
Ollama settings are read from the environment and `.env` first and
`require_model` must find the configured model on the server: if it does not
(or the settings are invalid) the reason goes to stderr and the exit code is 2,
and nothing is substituted. A model-mode run also prints the first decided
consultation, if there was one. `--api` arrives in a later task.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional, Sequence

from post_office.config.settings import normal_config
from post_office.dkrmm import DKRMM
from post_office.simulation import build

#: Consultations read back after each tick; far more than one tick closes.
RECENT = 500


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post office ecosystem prototype II")
    parser.add_argument("--ticks", type=int, default=600, help="ticks to run (default 600)")
    parser.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--rules", action="store_true",
                      help="run every expert on its deterministic rules")
    mode.add_argument("--api", action="store_true", help="serve the live API")
    parser.add_argument("--log", default=None, help="write the JSONL event log here")
    return parser.parse_args(argv)


def run(ticks: int, seed: int, log: Optional[str],
        brains: Optional[Dict[str, Any]] = None) -> int:
    if log:
        os.makedirs(os.path.dirname(os.path.abspath(log)), exist_ok=True)
    eco = build(seed, config=normal_config(), log_path=log, scenario="normal", brains=brains)
    monitor = None
    try:
        monitor = DKRMM(eco).attach()
        eco.start()
        first: Optional[Dict[str, Any]] = None
        for _ in range(int(ticks)):
            eco.step()
            monitor.tick()
            if first is None and eco.crew is not None:
                # Read every tick: the service keeps only its most recent
                # consultations, so the first one may be gone by the end.
                first = next((row for row in eco.crew.recent(RECENT)
                              if row["outcome"] == "decided"), None)
        print(json.dumps(eco.summary(), indent=1, default=str))
        print(json.dumps(monitor.state(), indent=1, default=str))
        if eco.crew is not None:
            print("first decided consultation:")
            print(json.dumps(first, indent=1, default=str) if first is not None
                  else "none in this run")
    finally:
        if monitor is not None:
            monitor.close()
        eco.close()
    return 0


def run_rules(ticks: int, seed: int, log: Optional[str]) -> int:
    return run(ticks, seed, log)


def run_model(ticks: int, seed: int, log: Optional[str]) -> int:
    from post_office.config.ollama import load_settings
    from post_office.crew.identity import ModelUnavailable, require_model

    try:
        settings = load_settings()
        require_model(settings)
    except (ModelUnavailable, ValueError) as exc:  # ValueError: InvalidBaseUrl, InvalidModelName, ...
        print(f"cannot run on the model: {exc}", file=sys.stderr)
        return 2

    from post_office.config.settings import llm_brains
    from post_office.crew.console import quiet

    with quiet():
        # Already verified above; the brains are built without asking again.
        return run(ticks, seed, log, brains=llm_brains(settings=settings, verify=False))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.api:
        print("API arrives in a later task", file=sys.stderr)
        return 2
    if args.rules:
        return run_rules(args.ticks, args.seed, args.log)
    return run_model(args.ticks, args.seed, args.log)


if __name__ == "__main__":
    sys.exit(main())
