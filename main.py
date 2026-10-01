"""
Run the post office ecosystem from the command line.

    python main.py --rules --ticks 300 --seed 1     every expert on its Python rules
    python main.py --rules --log run.jsonl          the same, with the event log on disk

`--rules` is the only working mode for now: the CrewAI brains and the API
arrive in later tasks. The run is the NORMAL scenario, watched by DK-RMM; the
summary and the monitor's state are printed as JSON at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional, Sequence

from post_office.config.settings import normal_config
from post_office.dkrmm import DKRMM
from post_office.simulation import build


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


def run_rules(ticks: int, seed: int, log: Optional[str]) -> int:
    if log:
        os.makedirs(os.path.dirname(os.path.abspath(log)), exist_ok=True)
    eco = build(seed, config=normal_config(), log_path=log, scenario="normal")
    monitor = None
    try:
        monitor = DKRMM(eco).attach()
        eco.start()
        for _ in range(int(ticks)):
            eco.step()
            monitor.tick()
        print(json.dumps(eco.summary(), indent=1, default=str))
        print(json.dumps(monitor.state(), indent=1, default=str))
    finally:
        if monitor is not None:
            monitor.close()
        eco.close()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.api:
        print("API arrives in a later task", file=sys.stderr)
        return 2
    if not args.rules:
        print("model brains arrive in a later task", file=sys.stderr)
        return 2
    return run_rules(args.ticks, args.seed, args.log)


if __name__ == "__main__":
    sys.exit(main())
