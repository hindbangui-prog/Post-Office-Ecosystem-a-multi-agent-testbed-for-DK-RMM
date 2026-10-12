"""
One SVG of the backlog by zone, per seed, from the kept run directories.

    python tools/zone_backlog_figure.py \
        --run "rules M-S-DROP=results/m_s_drop_crewai/live_rules/MS-DROP" \
        --run "rules N control=results/m_s_drop_crewai/live_rules/N" \
        --out docs/img/ms-drop-zone-backlog-rules.svg

Each `--run LABEL=DIR` is a directory of `s<seed>/zone_backlog.csv` files
(`observability/zone_backlog.py`). One row of panels per `--run`, one panel
per seed; each panel draws total, intake, sorting, storage, dispatch and
carried for every tick (as a step line: a vertex wherever the value changes), with a dashed line at the fault tick. The values
are the CSV's, drawn as they are; nothing is smoothed or derived. Standard
library only. Refuses to overwrite an existing file.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional

LINES = [("total", "total inside", "#222222"), ("intake", "intake", "#c2410c"),
         ("sorting", "sorting", "#2f6fd0"), ("storage", "storage", "#0f8a80"),
         ("dispatch", "dispatch", "#1f7a53"), ("carried", "on a robot", "#b8860b")]


def read(path: Path) -> List[Dict[str, int]]:
    with path.open(encoding="utf-8") as handle:
        return [{k: int(row[k]) for k in ["tick"] + [key for key, _, _ in LINES]}
                for row in csv.DictReader(handle)]


def steps(rows: List[Dict[str, int]], key: str) -> List[tuple]:
    """
    The series as a step line: a vertex where the value changes (at the
    tick it changes, from the old value to the new) and at both ends. Every
    tick's value is still on the line; runs of equal values are just not
    repeated, which keeps the file small.
    """
    if not rows:
        return []
    out = [(rows[0]["tick"], rows[0][key])]
    for prev, row in zip(rows, rows[1:]):
        if row[key] != prev[key]:
            out.append((row["tick"], prev[key]))
            out.append((row["tick"], row[key]))
    out.append((rows[-1]["tick"], rows[-1][key]))
    return out


def figure(runs: List[tuple], fault: Optional[int], title: str) -> str:
    seeds = sorted({int(p.name[1:]) for _, d in runs for p in d.iterdir()
                    if p.is_dir() and p.name[1:].isdigit()
                    and (p / "zone_backlog.csv").exists()})
    data = {(label, s): read(d / f"s{s}" / "zone_backlog.csv")
            for label, d in runs for s in seeds if (d / f"s{s}" / "zone_backlog.csv").exists()}
    if not data:
        raise SystemExit("no zone_backlog.csv found")
    top = max(r["total"] for rows in data.values() for r in rows)
    step = 5 if top <= 30 else 10
    ymax = ((top + step - 1) // step) * step
    xmax = max(r["tick"] for rows in data.values() for r in rows)
    pw, ph, gap, left, top_pad = 250, 170, 22, 150, 86
    width = left + len(seeds) * (pw + gap) + 20
    height = top_pad + len(runs) * (ph + 54) + 40
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
           f'width="{width}" height="{height}" font-family="Segoe UI, Helvetica, Arial, sans-serif" '
           f'font-size="12" role="img" aria-label="{title}">',
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
           f'<text x="20" y="30" font-size="17" font-weight="700" fill="#222">{title}</text>',
           '<text x="20" y="50" fill="#555">Parcels inside the building at the end of each tick, '
           'by zone (zone_backlog.csv; each parcel in exactly one zone or on a robot). '
           f'Dashed line: the fault at tick {fault}.</text>' if fault is not None else '']
    x0 = 20
    for key, name, colour in LINES:
        out.append(f'<rect x="{x0}" y="62" width="14" height="4" fill="{colour}"/>'
                   f'<text x="{x0 + 19}" y="68" fill="#333">{name}</text>')
        x0 += 30 + 7 * len(name)
    for i, (label, _) in enumerate(runs):
        y0 = top_pad + i * (ph + 54) + 20
        out.append(f'<text x="20" y="{y0 + ph / 2}" font-weight="700" fill="#222">{label}</text>')
        for j, s in enumerate(seeds):
            x = left + j * (pw + gap)
            rows = data.get((label, s))
            out.append(f'<text x="{x}" y="{y0 - 6}" fill="#333">seed {s}</text>')
            out.append(f'<rect x="{x}" y="{y0}" width="{pw}" height="{ph}" fill="none" stroke="#d0d4da"/>')
            for v in range(0, ymax + 1, step):
                yy = y0 + ph - ph * v / ymax
                out.append(f'<line x1="{x}" x2="{x + pw}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="#eef0f3"/>')
                if j == 0:
                    out.append(f'<text x="{x - 5}" y="{yy + 4:.1f}" text-anchor="end" fill="#777">{v}</text>')
            for t in range(0, xmax + 1, 700):
                xx = x + pw * t / xmax
                out.append(f'<text x="{xx:.1f}" y="{y0 + ph + 14}" text-anchor="middle" fill="#777">{t}</text>')
            if fault is not None:
                xx = x + pw * fault / xmax
                out.append(f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{y0}" y2="{y0 + ph}" '
                           'stroke="#b1452f" stroke-dasharray="4 3"/>')
            if not rows:
                out.append(f'<text x="{x + pw / 2}" y="{y0 + ph / 2}" text-anchor="middle" fill="#999">no run</text>')
                continue
            for key, _, colour in reversed(LINES):
                pts = " ".join(f"{x + pw * t / xmax:.1f},{y0 + ph - ph * v / ymax:.1f}"
                               for t, v in steps(rows, key))
                out.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="1.2"/>')
            end = rows[-1]
            out.append(f'<text x="{x + pw - 4}" y="{y0 + 14}" text-anchor="end" fill="#333">'
                       f'tick {end["tick"]}: intake {end["intake"]}, total {end["total"]}</text>')
    out.append("</svg>")
    return "\n".join(o for o in out if o)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--run", action="append", required=True, help="LABEL=DIR")
    parser.add_argument("--fault-tick", type=int, default=400)
    parser.add_argument("--title", default="Backlog by zone, M-S-DROP and its no-drop control")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"refusing to overwrite {args.out}")
    runs = []
    for item in args.run:
        label, _, d = item.partition("=")
        runs.append((label, Path(d)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(figure(runs, args.fault_tick, args.title) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
