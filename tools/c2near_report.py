#!/usr/bin/env python3
"""
C2-NEAR-SYSTEM-OVERRIDE: write the results page.

    python tools/c2near_report.py
    python tools/c2near_report.py --out results/c2_near_system_override --path report.html

Reads every finished run under `--out` (a run directory with `done.json`)
and `<out>/summary.json` when `--analyze` has written it, and writes one
standalone HTML file (`--path`, default `<out>/report.html`) that opens from
`file://` with no server and no network. An `--out` that resolves to or
inside `results/normal` is refused, as the driver refuses it; nothing under
`results/normal` is read or written.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from post_office.stress import c2near_system_override as spec  # noqa: E402
from post_office.stress.report import collect, render, TEMPLATE  # noqa: E402
from tools.run_c2near_system_override import refuse_normal  # noqa: E402


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"{spec.EXPERIMENT}: write the results page")
    parser.add_argument("--out", default=str(ROOT / spec.RESULTS_DIR),
                        help=f"results directory (default {spec.RESULTS_DIR})")
    parser.add_argument("--path", default=None,
                        help="where to write the page (default <out>/report.html)")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        out = refuse_normal(Path(args.out))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not out.is_dir():
        print(f"no results directory at {out}", file=sys.stderr)
        return 2
    data = collect(out)
    target = Path(args.path) if args.path else out / "report.html"
    try:
        refuse_normal(target.parent)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(data, TEMPLATE), encoding="utf-8", newline="\n")
    runs = data["runs"]
    by_cond = {c: sum(1 for r in runs if r["condition"] == c) for c in ("N", "C0", "C2")}
    print(f"wrote {target} ({target.stat().st_size / 1e6:.2f} MB): {len(runs)} runs included "
          f"(N {by_cond['N']}, C0 {by_cond['C0']}, C2 {by_cond['C2']}), "
          f"{len(data['incomplete'])} incomplete left out, "
          f"summary.json {'found' if data['summary_found'] else 'not found (run --analyze)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
