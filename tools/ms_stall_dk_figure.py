"""
Schema: why the live page shows DK on M-S-STALL seed 13 (model-enabled run
made by the user, record results/live/dkrmm/api-6-8.json). Every number is
read from that record (DK-RMM's own readings); nothing is recomputed except
the fitted lines, drawn from the recorded slope and expected value.

usage: python tools/ms_stall_dk_figure.py results/live/dkrmm/api-6-8.json docs/img/ms-stall-dk-seed13-model.svg

Standard library only.
"""
import html
import json
import math
import sys

REC, OUT = sys.argv[1], sys.argv[2]
d = json.load(open(REC, encoding="utf-8"))
ticks, sev = d["ticks"], d["severity_series"]
R = {a["tick"]: a for a in d["readings"]}
SS = d["state_series"]
assert d["scenario"] == "ms-stall" and d["seed"] == 13

INK, DIM, LINE = "#171a1f", "#667085", "#dfe3e8"
GOOD, WARN, BAD, DK, ACC = "#1f7a53", "#a8560f", "#c0392b", "#7b2cbf", "#2f6fd0"
UNST = "#b64520"
COL = {"STABLE": GOOD, "DEVIATING": WARN, "UNSTABLE": UNST, "RCT": BAD, "DK": DK}

W, H = 1400, 1220
o = []


def t(x, y, s, size=13, weight=400, fill=INK, anchor="start", italic=False):
    it = ' font-style="italic"' if italic else ""
    o.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
             f'fill="{fill}" text-anchor="{anchor}"{it}>{html.escape(str(s))}</text>')


def line(x1, y1, x2, y2, c=INK, w=1.2, dash=None, marker=None):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    me = f' marker-end="url(#{marker})"' if marker else ""
    o.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{c}" '
             f'stroke-width="{w}"{da}{me}/>')


def rect(x, y, w, h, fill="#fff", stroke="none", rx=0, op=1.0):
    o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
             f'fill="{fill}" stroke="{stroke}" fill-opacity="{op}"/>')


def circ(x, y, r, fill, stroke="none"):
    o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}"/>')


o.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         'font-family="Segoe UI, Helvetica, Arial, sans-serif" role="img" aria-label="M-S-STALL seed 13, '
         'model-enabled live run: the page shows DK at tick 1881 because that reading is an RCT and the '
         'dragon-king test still holds on the extreme reading of tick 1641, which came before the stall.">')
o.append('<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
         'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#171a1f"/></marker>'
         f'<marker id="arrdk" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
         f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{DK}"/></marker></defs>')
rect(0, 0, W, H, "#ffffff")
t(40, 38, "M-S-STALL, seed 13, model-enabled: why the live page shows DK at tick 1881", 20, 700)
t(40, 60, "Run made by the user through the live page (rules first, qwen3:8b when a rule is insufficient). "
          "Source: results/live/dkrmm/api-6-8.json, DK-RMM's own readings; DK-RMM unchanged.", 13, 400, DIM)
t(40, 78, "DK on the page = a reading DK-RMM calls RCT while its dragon-king test holds. "
          "The test is about the largest of the last 80 readings, not about the reading it is attached to.",
  13, 400, DIM)

# ------------------------------------------------------------- panel 1
t(40, 112, "1  The run: DK-RMM severity per reading (every 20 ticks) and the state the page shows",
  16, 700)
X0, X1, TMAX = 90, 1350, 3300
Y0, Y1, SMAX = 150, 360, 5.0
X = lambda tk: X0 + (X1 - X0) * tk / TMAX
Y = lambda v: Y1 - (Y1 - Y0) * v / SMAX
# stall band
rect(X(1800), Y0 - 6, X(2100) - X(1800), Y1 - Y0 + 6, "#e8e3df")
t((X(1800) + X(2100)) / 2, Y0 + 8, "stall: bus holds", 11, 700, WARN, "middle")
t((X(1800) + X(2100)) / 2, Y0 + 22, "every message", 11, 700, WARN, "middle")
t(X(2100) + 4, Y0 + 8, "release 2100", 11, 700, WARN)
# axes
for v in range(0, 6):
    line(X0, Y(v), X1, Y(v), LINE, 1)
    t(X0 - 8, Y(v) + 4, v, 11, 400, DIM, "end")
t(X0 - 52, (Y0 + Y1) / 2, "severity", 11, 400, DIM, "middle")
for tk in range(0, 3301, 400):
    t(X(tk), Y1 + 16, tk, 11, 400, DIM, "middle")
pts = " ".join(f"{X(tk):.1f},{Y(v):.1f}" for tk, v in zip(ticks, sev))
o.append(f'<polyline points="{pts}" fill="none" stroke="{ACC}" stroke-width="1.6"/>')
for tk, v in zip(ticks, sev):
    circ(X(tk), Y(v), 1.8, ACC)
# annotations
s1641 = R[1641]["severity"]
circ(X(1641), Y(s1641), 6, "none", DK)
o[-1] = o[-1].replace('stroke="#7b2cbf"/>', 'stroke="#7b2cbf" stroke-width="2.5"/>')
t(X(1641) - 10, Y(s1641) - 6, "1641: 4.53, the largest reading of the run", 12, 700, DK, "end")
t(X(1641) - 10, Y(s1641) + 10, "Normal (before the stall): one task waited 47 ticks", 12, 400, DK, "end")
for tk, lab, dy in ((2121, "2121: 3.23", -10), (2141, "2141: 3.77 (the release)", -10)):
    pass
t(X(2141) + 8, Y(R[2141]["severity"]) - 4, "2121-2141: 3.23, 3.77 (the release)", 12, 700, INK)
t(X(2141) + 8, Y(R[2141]["severity"]) + 12, "below 4.53, so not a dragon-king", 12, 400, DIM)
circ(X(1881), Y(R[1881]["severity"]), 6, "none", DK)
line(X(1881) - 6, Y(R[1881]["severity"]) - 5, X(1881) - 40, Y(2.5) + 4, DK, 1.2)
t(X(1881) - 44, Y(2.5), "1881: 1.53, RCT, shown as DK", 12, 700, DK, "end")

# state strip (the page's study view: RECOVERY folded into STABLE, RCT with the test held is DK)
SY = Y1 + 34
t(X0 - 8, SY + 11, "page", 11, 400, DIM, "end")
for a in SS:
    st = a["state"]
    st = "STABLE" if st == "RECOVERY" else st
    if st == "RCT" and a["dragon"]["is_dragon"]:
        st = "DK"
    hgt = 22 if st in ("RCT", "DK") else 14
    rect(X(a["tick"] - 20), SY + (14 - hgt) / 2, X(20) - X(0) + 0.3, hgt, COL[st])
lx = X0
for name in ("STABLE", "DEVIATING", "UNSTABLE", "RCT", "DK"):
    rect(lx, SY + 32, 10, 10, COL[name])
    t(lx + 14, SY + 41, name, 11, 400, INK)
    lx += 100
# dragon-held span and the 80-reading window
dragon_ticks = [a["tick"] for a in SS if a["dragon"]["is_dragon"]]
BY = SY + 64
rect(X(dragon_ticks[0] - 20), BY, X(dragon_ticks[-1]) - X(dragon_ticks[0] - 20), 8, DK, op=0.35)
t(X(dragon_ticks[0] - 20), BY + 22,
  f"dragon-king test holds on every reading from {dragon_ticks[0]} to {dragon_ticks[-1]}: "
  "1641 is the largest of the last 80", 11, 400, DK)
WY = BY + 46
line(X(301), WY, X(1881), WY, INK, 1)
line(X(301), WY - 5, X(301), WY + 5, INK, 1)
line(X(1881), WY - 5, X(1881), WY + 5, INK, 1)
t(X(301) + 4, WY + 16, "the 80 readings the test reads at 1881: ticks 301 to 1881 (1600 ticks)", 11, 400, INK)

# ------------------------------------------------------------- panel 2
P2 = 590
t(40, P2, "2  The dragon-king test, as DK-RMM recorded it (log value against log rank of the 12 largest; "
          "line fitted on ranks 2 to 12, rank 1 left out)", 16, 700)


def rank_plot(x0, y0, w, h, reading, title, verdict, vcol, lab=None):
    dg = reading["dragon"]
    pl = dg["plot"]
    xs = [p[0] for p in pl]
    ys = [p[1] for p in pl]
    a_int, slope = math.log(dg["expected"]), dg["slope"]
    lo = min(min(ys), a_int + slope * xs[-1], -0.4) - 0.1
    hi = max(max(ys), a_int) + 0.25
    px = lambda v: x0 + 40 + (w - 60) * v / 2.6
    py = lambda v: y0 + h - 30 - (h - 60) * (v - lo) / (hi - lo)
    rect(x0, y0, w, h, "#fafbfc", LINE, 6)
    t(x0 + 12, y0 + 20, title, 13, 700)
    line(px(0), py(lo), px(2.6), py(lo), DIM, 1)
    line(px(0), py(lo), px(0), py(hi), DIM, 1)
    t(px(2.6), py(lo) + 16, "log rank", 11, 400, DIM, "end")
    t(px(0) - 6, py(hi) + 4, "log value", 11, 400, DIM, "end")
    line(px(0), py(a_int), px(xs[-1]), py(a_int + slope * xs[-1]), INK, 1.4, "5 3")
    for i, (x, y) in enumerate(pl):
        circ(px(x), py(y), 5 if i == 0 else 3.4, DK if i == 0 else ACC)
    # gap at rank 1
    line(px(0) + 10, py(a_int), px(0) + 10, py(ys[0]) + (6 if ys[0] > a_int else -6), DK, 1.4,
         marker="arrdk")
    lx, ly = lab if lab else (px(0) + 16, (py(a_int) + py(ys[0])) / 2 - 6)
    t(lx, ly, f"observed {dg['observed']:.2f} (rank 1, purple)", 12, 700, DK)
    t(lx, ly + 15, f"expected {dg['expected']:.2f} (where the line meets rank 1)", 12, 400, INK)
    t(x0 + 12, y0 + h - 8,
      f"ratio {dg['ratio']:.2f} (needs 2)  ·  fit quality {dg['fit_quality']:.3f} (needs > 0.5)  ·  "
      f"slope {dg['slope']:.3f}", 12, 400, INK)
    t(x0 + w - 12, y0 + 20, verdict, 13, 700, vcol, "end")


rank_plot(40, P2 + 14, 640, 300, R[1881], "At 1881: rank 1 is the 4.53 of tick 1641",
          "test holds", DK)
rank_plot(720, P2 + 14, 640, 300, R[2441],
          "At 2441: ranks 2 to 12 are the readings after the release (2121 to 2401)", "test does not hold", BAD,
          lab=(800, P2 + 214))

# ------------------------------------------------------------- panel 3
P3 = P2 + 350
t(40, P3, "3  Why 1881 is an RCT, and why the page then writes DK", 16, 700)
a1881 = R[1881]
prev = R[1861]
rows = [
    ("at least 3 kinds of evidence", ", ".join(a1881["kinds"]) + f" ({len(a1881['kinds'])})", True),
    ("at least 1 kind held from the reading before",
     f"1861 had the same four ({len(set(a1881['kinds']) & set(prev['kinds']))} held)", True),
    ("propagation at least 0.5",
     f"{a1881['indicators']['propagation_across_agents']:.2f} of the acting agents (exactly at the line)", True),
    ("dragon-king test OR critical slowing down",
     "dragon-king: yes (panel 2); slowing down: no", True),
]
yy = P3 + 26
for cond, val, ok in rows:
    t(56, yy, "✓", 14, 700, GOOD)
    t(78, yy, cond, 13, 700)
    t(400, yy, val, 13, 400)
    yy += 22
t(56, yy + 4, "→  DK-RMM: RCT.  The page: RCT with the test held, shown as DK.", 13, 700, DK)
t(56, yy + 24, "The four kinds at 1881 come from the stall: retry +4.9, interaction density +9.5,",
  12, 400, INK)
t(56, yy + 40, "dependency graph +3.2, synchrony +3.4 standard deviations. The word DK comes from 1641.",
  12, 400, INK)

# 1641 composition, right side
cx0 = 900
t(cx0, P3 + 26, "What the 4.53 at 1641 is made of (severity = sum of", 13, 700)
t(cx0, P3 + 43, "the 20 indicators' directional z-scores, divided by 20)", 13, 700)
parts = [("tail deviation", 3.05, DK), ("execution latency", 0.48, ACC),
         ("the other 18", round(s1641 - 3.05 - 0.48, 2), "#97a0ad")]
bx, by, bw = cx0, P3 + 58, 440
tot = sum(p[1] for p in parts)
for name, v, c in parts:
    wv = bw * v / tot
    rect(bx, by, wv, 22, c)
    bx += wv
bx = cx0
ty = by + 40
for name, v, c in parts:
    rect(bx, ty - 9, 10, 10, c)
    t(bx + 14, ty, f"{name} {v:.2f}", 12, 400, INK)
    bx += 150
t(cx0, ty + 22, "task wait p95: 47 ticks against a baseline p95 of 8 (ratio 5.875).", 12, 400, INK)
t(cx0, ty + 38, "Waits of the 8 tasks started in that window: 1, 8, 1, 8, 1, 8, 47, 1.", 12, 400, INK)
t(cx0, ty + 54, "The indicator's own baseline is 1.05 with almost no spread: +61 sd.", 12, 400, INK)

# ------------------------------------------------------------- panel 4
P4 = P3 + 200
t(40, P4, "4  Reading", 16, 700)
lines = [
    "The extreme reading of this run is tick 1641, before the stall starts: the Normal facility, one task "
    "that waited 47 ticks. It stands far above the tail, so the test holds from 1641.",
    "The stall makes 1861 to 1881 abnormal on four kinds at once; at 1881 the RCT rule is met and its precursor "
    "is the dragon-king test, still holding on 1641. The page therefore writes DK at 1881.",
    "The release (3.23 and 3.77) is the stall's own extreme, but it stays below 4.53, and once it fills ranks 2 to "
    "12 the fit explains 4.53 too: at 2441 the test no longer holds and that RCT stays RCT.",
]
yy = P4 + 24
for s in lines:
    t(56, yy, s, 13, 400, INK)
    yy += 22
o.append("</svg>")
open(OUT, "w", encoding="utf-8").write("\n".join(o) + "\n")
print("written", OUT, "dragon span", dragon_ticks[0], dragon_ticks[-1])
