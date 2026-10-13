"""
Schema, step by step: what happens in the user's model-enabled M-S-STALL run
on seed 13 (record results/live/dkrmm/api-6-8.json), from Normal operation
through the stall, the release and the recovery, with what DK-RMM read at
each step. Every number is read from DK-RMM's readings in that record (60-tick
windows, one every 20 ticks); the text around the numbers is fixed.

usage: python tools/ms_stall_steps_figure.py results/live/dkrmm/api-6-8.json docs/img/ms-stall-steps-seed13-model.svg

Standard library only.
"""
import html
import json
import sys

REC, OUT = sys.argv[1], sys.argv[2]
d = json.load(open(REC, encoding="utf-8"))
assert d["scenario"] == "ms-stall" and d["seed"] == 13
R = {a["tick"]: a for a in d["readings"]}
ticks, sev = d["ticks"], d["severity_series"]


def c(tick, key):
    return R[tick]["indicators"]["counts"][key]


def snap(tick, key):
    return R[tick]["snapshot"][key]


def zone(tick, name):
    return R[tick]["snapshot"]["by_zone"].get(name, 0)


def rng(lo, hi, f):
    vals = [f(t) for t in ticks if lo <= t <= hi]
    return min(vals), max(vals)


def wait95(tick):
    return R[tick]["indicators"]["detail"].get("execution_latency_p95")


# ------------------------------------------------------------ the facts
msg_n = rng(1001, 1781, lambda t: c(t, "messages"))
done_n = rng(1001, 1781, lambda t: c(t, "tasks_completed"))
back_n = rng(1001, 1781, lambda t: snap(t, "backlog"))
w1641 = R[1641]["indicators"]["detail"]["waits"]
d1641 = R[1641]["dragon"]
z1641 = R[1641]["z"]
ret_stall = rng(1841, 2081, lambda t: c(t, "retries"))
avail_stall = rng(1861, 2081, lambda t: snap(t, "resources")["robots"]["available"])
a1881 = R[1881]
held_seq = (snap(1881, "held_now"), snap(2081, "held_now"))
late_rel = c(2101, "late")
msgs_rel = (c(2101, "messages"), c(2121, "messages"), c(2141, "messages"))
ev_rel = (R[2121]["indicators"]["events"], R[2141]["indicators"]["events"])
ev_norm = rng(1561, 1781, lambda t: R[t]["indicators"]["events"])
sync2101 = R[2101]["z"]["activity_synchronization"]
gate = rng(2141, 2281, lambda t: c(t, "gate_rejections"))
blocked = rng(2141, 2281, lambda t: c(t, "blocked"))
robots0 = [t for t in ticks if 2121 <= t <= 2301
           and snap(t, "resources")["robots"]["available"] == 0]
stable_from = min(t for t in ticks if t > 2441 and R[t]["state"] == "STABLE")
end = ticks[-1]

INK, DIM, LINE = "#171a1f", "#667085", "#dfe3e8"
GOOD, WARN, BAD, DK, ACC = "#1f7a53", "#a8560f", "#c0392b", "#7b2cbf", "#2f6fd0"
UNST = "#b64520"
STATE_COL = {"STABLE": GOOD, "RECOVERY": GOOD, "DEVIATING": WARN, "UNSTABLE": UNST,
             "RCT": BAD, "DK": DK}

W, H = 1400, 1000
o = []


def t(x, y, s, size=12, weight=400, fill=INK, anchor="start"):
    o.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
             f'fill="{fill}" text-anchor="{anchor}">{html.escape(str(s))}</text>')


def rect(x, y, w, h, fill, stroke="none", rx=0, op=1.0, sw=1):
    o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
             f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" fill-opacity="{op}"/>')


def line(x1, y1, x2, y2, col=INK, w=1.2, dash=None, marker=None):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    me = f' marker-end="url(#{marker})"' if marker else ""
    o.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{col}" '
             f'stroke-width="{w}"{da}{me}/>')


def circ(x, y, r, fill, stroke="none", sw=1):
    o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" '
             f'stroke-width="{sw}"/>')


def wrap(text, width):
    words, rows, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            rows.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        rows.append(cur)
    return rows


o.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         'font-family="Segoe UI, Helvetica, Arial, sans-serif" role="img" aria-label="M-S-STALL seed 13, '
         'model-enabled, step by step: Normal operation, one slow task at 1641, the stall from 1800, '
         'RCT shown as DK at 1881, the quiet build-up, the release at 2100, the catch-up and the recovery.">')
o.append('<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
         'markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#667085"/>'
         '</marker></defs>')
rect(0, 0, W, H, "#ffffff")
t(40, 38, "M-S-STALL, seed 13, model-enabled: what happens, step by step", 20, 700)
t(40, 60, "Your run through the live page (rules first, qwen3:8b when a rule is insufficient). Numbers are "
          "DK-RMM's readings in results/live/dkrmm/api-6-8.json: each counts a 60-tick window, one "
          "every 20 ticks.", 12, 400, DIM)
t(40, 77, "The fault: from tick 1800 the bus delivers nothing (every message held, none dropped); at 2100 "
          "everything held is delivered in one tick.", 12, 400, DIM)

# ---------------------------------------------------------- the timeline
X0, X1, TMAX = 80, 1350, 3300
Y0, Y1 = 110, 230
X = lambda tk: X0 + (X1 - X0) * tk / TMAX
Y = lambda v: Y1 - (Y1 - Y0) * v / 5.0
rect(X(1800), Y0 - 4, X(2100) - X(1800), Y1 - Y0 + 4, "#e8e3df")
t((X(1800) + X(2100)) / 2, Y0 + 10, "stall", 11, 700, WARN, "middle")
for v in (0, 1, 2, 3, 4, 5):
    line(X0, Y(v), X1, Y(v), LINE, 1)
    t(X0 - 6, Y(v) + 4, v, 10, 400, DIM, "end")
t(X0 - 40, (Y0 + Y1) / 2 + 4, "severity", 10, 400, DIM, "middle")
for tk in range(0, 3301, 400):
    t(X(tk), Y1 + 14, tk, 10, 400, DIM, "middle")
pts = " ".join(f"{X(tk):.1f},{Y(v):.1f}" for tk, v in zip(ticks, sev))
o.append(f'<polyline points="{pts}" fill="none" stroke="{ACC}" stroke-width="1.5"/>')
# page strip
SY = Y1 + 22
for a in d["state_series"]:
    st = a["state"]
    st = "DK" if st == "RCT" and a["dragon"]["is_dragon"] else st
    h = 16 if st in ("RCT", "DK") else 10
    rect(X(a["tick"] - 20), SY + (10 - h) / 2, X(20) - X(0) + 0.3, h, STATE_COL[st])
t(X0 - 6, SY + 9, "page", 10, 400, DIM, "end")
# step markers on the timeline
MARKS = [(1, 900), (2, 1641), (3, 1800), (4, 1881), (5, 1990), (6, 2100), (7, 2200), (8, 2700)]
MY = SY + 34
for n, tk in MARKS:
    line(X(tk), SY + 14, X(tk), MY - 9, DIM, 1, "2 2")
    circ(X(tk), MY, 9, INK)
    t(X(tk), MY + 4, n, 11, 700, "#ffffff", "middle")

# ------------------------------------------------------------- the steps
STEPS = [
    (1, "0 to 1799", "Normal operation", None,
     [f"Agents talk on the bus and every message arrives on time: {msg_n[0]} to {msg_n[1]} messages "
      f"per window. Robots take parcels from intake through sorting to the vans; {done_n[0]} to "
      f"{done_n[1]} tasks finished per window, {back_n[0]} to {back_n[1]} parcels in the building."],
     "STABLE, DEVIATING, sometimes UNSTABLE: Normal's own small swings.", "STABLE"),
    (2, "1641", "One slow task (still Normal)", None,
     [f"Of the {len(w1641)} tasks started in the window, one waited {max(w1641)} ticks for a robot; "
      f"the others waited {min(w1641)} to {sorted(w1641)[-2]}. The usual worst wait is 8."],
     f"Tail deviation +{z1641['tail_deviation']:.0f} sd, latency +{z1641['execution_latency']:.1f} sd: "
     f"severity {R[1641]['severity']:.2f}, the largest of the run. UNSTABLE (2 kinds). The dragon-king "
     f"test holds: {d1641['observed']:.2f} against {d1641['expected']:.2f} expected.", "DK_TEST"),
    (3, "1800 to 1880", "The stall begins", None,
     [f"The bus holds every message. Agents keep asking, hear nothing, then wait: messages per "
      f"window fall from {c(1801, 'messages')} to {c(1861, 'messages')}. SCHEDULING's questions time "
      f"out after 30 ticks and are asked again ({ret_stall[1]} retries per window). Robots finish the "
      f"errands in hand and stand idle: {avail_stall[1]} of 5 free, 0 tasks finished from 1861."],
     f"DEVIATING at 1821 ({', '.join(R[1821]['kinds'])}) and 1841 ({', '.join(R[1841]['kinds'])}).",
     "DEVIATING"),
    (4, "1861 to 1881", "DK-RMM: RCT, shown as DK", None,
     [f"Four kinds of evidence at once: {', '.join(a1881['kinds'])}. All four already at 1861, "
      f"{a1881['indicators']['propagation_across_agents']:.0%} of the acting agents affected."],
     f"UNSTABLE at 1861, RCT at 1881. Its precursor is the dragon-king test, which still holds on "
     f"step 2's reading (the last 80 readings include 1641), so the page writes DK.", "DK"),
    (5, "1900 to 2099", "Quiet build-up", None,
     [f"Messages pile up on the bus: {held_seq[0]} held at 1881, {held_seq[1]} at 2081, {late_rel} at "
      f"the release. Parcels keep arriving and nothing leaves: intake {zone(1881, 'INTAKE')} to "
      f"{zone(2081, 'INTAKE')}, backlog {snap(1881, 'backlog')} to {snap(2081, 'backlog')}."],
     "Little happens, so the readings drift back to STABLE: a silent facility looks calm.",
     "STABLE"),
    (6, "2100", "The release", None,
     [f"All {late_rel} held messages arrive in one tick, every one late. Every agent acts on five "
      f"minutes of answers, questions and commands together: messages per window "
      f"{msgs_rel[0]}, {msgs_rel[1]}, {msgs_rel[2]}; events {ev_rel[0]:,} and {ev_rel[1]:,} against "
      f"{ev_norm[0]} to {ev_norm[1]} before the stall."],
     f"Activity synchronization +{sync2101:.1f} sd at 2101: DEVIATING (nothing held over from the "
     f"quiet reading before).", "DEVIATING"),
    (7, "2120 to 2300", "Catch-up and congestion", None,
     [f"Tasks that waited through the stall finally start (worst wait {wait95(2121):.0f} ticks). "
      f"All 5 robots busy from {robots0[0]} to {robots0[-1]}; blocked robots {blocked[0]} to "
      f"{blocked[1]} per window; the policy gate refuses {gate[0]} to {gate[1]} decisions per window."],
     f"Severity {R[2121]['severity']:.2f} and {R[2141]['severity']:.2f} (the stall's own peak), "
     f"UNSTABLE. Below {R[1641]['severity']:.2f}, so not a dragon-king.", "UNSTABLE"),
    (8, f"2300 to {end}", "Recovery", None,
     [f"Blocks and refusals fall, backlog {snap(2321, 'backlog')} to {snap(2501, 'backlog')}, waits "
      f"back to {wait95(2461):.0f} by 2461. At {end}: backlog {snap(end, 'backlog')}; the page showed "
      f"81 dispatched and 3 parcels on the floor at tick 3253."],
     f"RCT at 2441 by critical slowing down (the test no longer holds), STABLE from {stable_from}, "
     f"RECOVERY at {end}.", "STABLE"),
]

CW, CH, GX, GY = 310, 262, 16, 22
CX0, CY0 = 40, MY + 56
for i, (n, when, title, _, facts, dk, st) in enumerate(STEPS):
    row, col = divmod(i, 4)
    x = CX0 + col * (CW + GX)
    y = CY0 + row * (CH + GY)
    border = DK if st in ("DK", "DK_TEST") else LINE
    rect(x, y, CW, CH, "#fafbfc" if n not in (3, 5) else "#f7f3ef", border, 8,
         sw=2 if border == DK else 1)
    circ(x + 22, y + 22, 12, INK)
    t(x + 22, y + 26, n, 12, 700, "#ffffff", "middle")
    t(x + 42, y + 20, f"tick {when}", 11, 400, DIM)
    t(x + 42, y + 36, title, 14, 700)
    yy = y + 60
    t(x + 14, yy, "in the facility", 10, 700, DIM)
    yy += 16
    for fact in facts:
        for row_text in wrap(fact, 45):
            t(x + 14, yy, row_text, 12)
            yy += 16
    if dk:
        yy += 6
        line(x + 14, yy - 10, x + CW - 14, yy - 10, LINE, 1)
        t(x + 14, yy + 4, "DK-RMM reads", 10, 700, DIM)
        if st:
            special = {"DK_TEST": ("test holds", DK), "DK": ("DK", DK)}
            chip = special[st] if st in special else (st, STATE_COL[st])
            rect(x + CW - 14 - 9 * len(chip[0]) - 8, yy - 8, 9 * len(chip[0]) + 8, 16, chip[1], rx=8)
            t(x + CW - 14 - (9 * len(chip[0]) + 8) / 2, yy + 4, chip[0], 10, 700, "#ffffff", "middle")
        yy += 20
        for row_text in wrap(dk, 45):
            t(x + 14, yy, row_text, 12, 400, DK if st in ("DK", "DK_TEST") else INK)
            yy += 16
    assert yy < y + CH, (n, yy - y)
    if col < 3:
        line(x + CW + 2, y + CH / 2, x + CW + GX - 2, y + CH / 2, DIM, 1.2, marker="arr")

# the link that makes the DK word
y1 = CY0 + 0 * (CH + GY)
xa = CX0 + 1 * (CW + GX) + CW / 2
xb = CX0 + 3 * (CW + GX) + CW / 2
o.append(f'<path d="M{xa:.1f},{y1 - 2:.1f} C{xa:.1f},{y1 - 34:.1f} {xb:.1f},{y1 - 34:.1f} '
         f'{xb:.1f},{y1 - 2:.1f}" fill="none" stroke="{DK}" stroke-width="1.6" stroke-dasharray="5 3" '
         'marker-end="url(#arr)"/>')
t((xa + xb) / 2, y1 - 30, "step 2's reading is what the test at step 4 is about", 11, 700, DK, "middle")

# --------------------------------------------------------------- reading
FY = CY0 + 2 * (CH + GY) + 6
t(40, FY, "Why the page says DK", 15, 700)
for k, s in enumerate([
    "DK at 1881 = an RCT (step 4, made by the stall) while the dragon-king test holds (on step 2, "
    "a Normal reading from before the stall).",
    "The stall's own extreme (steps 6 and 7) is smaller than step 2's, so in this run the release is "
    "not a dragon-king; the facility recovers (step 8).",
]):
    t(40, FY + 22 + 18 * k, s, 13)
o.append("</svg>")
open(OUT, "w", encoding="utf-8").write("\n".join(o) + "\n")
print("written", OUT)
