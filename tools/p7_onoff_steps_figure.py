#!/usr/bin/env python3
"""
Schema, step by step: what happens in a run of P7-ONOFF (the Phase 7 ON-OFF
agent misbehaviour, `post_office/stress/onoff_attack.py`) on the demonstration
seed 11977, from the build through the first ON phase, the robot trap, the OFF
phases that cannot undo it, the hospital consignment and the horizon, with what
DK-RMM read at each step, and where a model call sits in every decision.

Every number is read from the run itself: the script runs the scenario headless
on the experts' rules (`SimulationRunner`, seed 11977, 4400 ticks, the frozen
configuration, which is what the live page runs) and reads its event log, the
scenario's status and DK-RMM's assessments. The text around the numbers is
fixed. Standard library plus the project.

    python tools/p7_onoff_steps_figure.py docs/img/p7-onoff-steps-seed11977.svg
"""
from __future__ import annotations

import html
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from post_office.api.runner import SimulationRunner  # noqa: E402
from post_office.crew.console import quiet  # noqa: E402
from post_office.stress import onoff_attack as P7  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/img/p7-onoff-steps-seed11977.svg"
SEED = P7.DEMO_SEED


# ----------------------------------------------------------------- the run
def run():
    log = os.path.join(tempfile.mkdtemp(prefix="p7fig"), "events.jsonl")
    with quiet():
        r = SimulationRunner(seed=SEED, preset=P7.PRESET, rules_only=True, verify_model=False,
                             tick_seconds=0.0, run_id="fig", log_path=log)
        r.eco.start()
        while r._tick():
            pass
        r._logger.flush()
        study = r.study_status()
        hist = [(int(a.tick), a.state.value, float(a.severity), bool(a.dragon.is_dragon), list(a.kinds))
                for a in r.monitor.history]
        r.close()
    events = [json.loads(line) for line in open(log, encoding="utf-8")]
    return events, study, hist


events, study, hist = run()
st = study["status"]
T = int(study["run_ticks"])
assert st["is_demo_seed"] and study["complete"], "the figure is drawn from the complete run of seed 11977"


def ev(topic, lo=0, hi=10 ** 9, **match):
    out = []
    for e in events:
        if e["topic"] != topic or not lo <= e["tick"] <= hi:
            continue
        d = e.get("detail") or {}
        if all(d.get(k) == v for k, v in match.items()):
            out.append(e)
    return out


phases = P7.PHASES
disp = ev("attack_displaced")
disp_phase1 = [e for e in disp if phases[0]["on_from"] <= e["tick"] < phases[0]["on_to"]]
disp_by_agent = Counter(e["actor"] for e in disp)
disp_p1_by_agent = Counter(e["actor"] for e in disp_phase1)
first_disp = disp[0]
trap = st["trap"]
robots = {r["robot"]: r for r in st["robots"]}
trapped = trap["robots"]
eps = {e["robot"]: e for e in trap["episodes"] if e["robot"] in trapped and e["end"] is None}
# ROUTING's rule answers for the trapped robots in the first OFF phase
def routing_choices(lo, hi, who):
    c = Counter()
    for e in ev("decision", lo, hi, decision="resolve_block"):
        if e["actor"] == "ROUTING" and (e["detail"].get("facts") or {}).get("robot") in who:
            c[e["detail"].get("choice")] += 1
    return c


off1 = routing_choices(phases[0]["on_to"], phases[1]["on_from"] - 1, set(trapped))
on1 = routing_choices(phases[0]["on_from"], phases[0]["on_to"] - 1, set(trapped))
released = ev("task_released")
# the trapped robots' last errands: the last task_released naming each robot before the trap
def last_release(robot, before):
    rows = [e for e in released if e["tick"] <= before and (e["detail"].get("robot_id") == robot)]
    return rows[-1] if rows else None


departed_before = len(ev("parcel_departed", 0, phases[0]["on_from"] - 1))
refusals = ev("arrival_refused")
first_refusal = refusals[0]["tick"] if refusals else None
imp = st["impact"]
hosp = st["hospital"]
first_hospital = min(h["arrives"] for h in hosp)
last_hospital = max(h["arrives"] for h in hosp)
hosp_refused = [h["id"] for h in hosp if h["state"] == "REFUSED_AT_DOCK"]
hosp_in = [h for h in hosp if h.get("in_building")]
hosp_out = [h for h in hosp if h["dispatched"] is not None]
# DK-RMM
sev = {t: s for t, _, s, _, _ in hist}
first_rct = next((t for t, s, _, _, _ in hist if s == "RCT"), None)
dk_ticks = [t for t, s, _, d, _ in hist if s == "RCT" and d]
rct_ticks = [t for t, s, _, _, _ in hist if s == "RCT"]
peak_tick = max(sev, key=sev.get)
kinds_peak = next(k for t, _, _, _, k in hist if t == peak_tick)
late_sev = [sev[t] for t in sev if phases[1]["on_from"] <= t <= T]
displaced_total = st["displacement"]["displaced"]

INK, DIM, LINE = "#171a1f", "#667085", "#dfe3e8"
GOOD, WARN, BAD, DK, ACC = "#1f7a53", "#a8560f", "#c0392b", "#7b2cbf", "#2f6fd0"
UNST, LLM = "#b64520", "#0f766e"
STATE_COL = {"STABLE": GOOD, "RECOVERY": GOOD, "DEVIATING": WARN, "UNSTABLE": UNST, "RCT": BAD, "DK": DK}

W, H = 1400, 1370
o = []


def t(x, y, s, size=12, weight=400, fill=INK, anchor="start"):
    o.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
             f'fill="{fill}" text-anchor="{anchor}">{html.escape(str(s))}</text>')


def rect(x, y, w, h, fill, stroke="none", rx=0, op=1.0, sw=1, dash=None):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
             f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" fill-opacity="{op}"{da}/>')


def line(x1, y1, x2, y2, col=INK, w=1.2, dash=None, marker=None):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    me = f' marker-end="url(#arr)"' if marker else ""
    o.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{col}" '
             f'stroke-width="{w}"{da}{me}/>')


def circ(x, y, r, fill, stroke="none", sw=1):
    o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')


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


def box(x, y, w, h, title, lines, fill="#fafbfc", stroke=LINE, title_col=INK, size=11, width=34, sw=1):
    rect(x, y, w, h, fill, stroke, 6, sw=sw)
    t(x + 10, y + 17, title, 11.5, 700, title_col)
    yy = y + 33
    for s in lines:
        for row in wrap(s, width):
            t(x + 10, yy, row, size)
            yy += 14
    return yy


o.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         'font-family="Segoe UI, Helvetica, Arial, sans-serif" role="img" aria-label="P7-ONOFF, seed 11977, '
         'step by step: the build, Normal operation, the first ON phase, the robot trap, DK-RMM\'s alert, the OFF '
         'phase that cannot undo the trap, the hospital consignment and the horizon, with where a model call sits '
         'in every decision.">')
o.append('<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
         'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#667085"/></marker></defs>')
rect(0, 0, W, H, "#ffffff")
t(40, 38, f"P7-ONOFF, seed {SEED}: what happens, step by step, and where the model is called", 20, 700)
t(40, 60, "The frozen Phase 7 configuration run through the live page on the experts' rules (main.py --rules): every "
          "number below is this run's own, from its event log, the scenario's status and DK-RMM's readings.", 12, 400, DIM)
t(40, 77, f"{P7.SCENARIO6_ID} with {P7.ATTACK_ID}: ROUTING and SCHEDULING on their rules (OFF), then violating "
          f"them (ON), four times;", 12, 400, DIM)
t(40, 93, f"20 hospital parcels for Hradec arrive between {first_hospital} and {last_hospital}; the run ends at {T}. "
          f"Rules-only here, as the frozen artifacts are; the model's place in each decision is drawn below.", 12, 400, DIM)

# ---------------------------------------------------------- the timeline
X0, X1, TMAX = 80, 1350, T
Y0, Y1 = 124, 230
X = lambda tk: X0 + (X1 - X0) * tk / TMAX  # noqa: E731
SMAX = max(5.0, max(sev.values()))
Y = lambda v: Y1 - (Y1 - Y0) * min(v, SMAX) / SMAX  # noqa: E731
rect(X(P7.CONSIGNMENT_FROM), Y0 - 4, X(P7.CONSIGNMENT_TO) - X(P7.CONSIGNMENT_FROM), Y1 - Y0 + 4, "#eef3fb")
t((X(P7.CONSIGNMENT_FROM) + X(P7.CONSIGNMENT_TO)) / 2, Y0 + 26, "hospital consignment arriving", 10, 600, ACC, "middle")
for ph in phases:
    rect(X(ph["on_from"]), Y0 - 4, X(ph["on_to"]) - X(ph["on_from"]), Y1 - Y0 + 4, BAD, op=0.13)
    t((X(ph["on_from"]) + X(ph["on_to"])) / 2, Y0 + 10, f"ON {ph['k'] + 1}", 11, 700, BAD, "middle")
for v in range(0, int(SMAX) + 1, 2):
    line(X0, Y(v), X1, Y(v), LINE, 1)
    t(X0 - 6, Y(v) + 4, v, 10, 400, DIM, "end")
t(X0 - 40, (Y0 + Y1) / 2 + 4, "severity", 10, 400, DIM, "middle")
for tk in range(0, T + 1, 400):
    t(X(tk), Y1 + 14, tk, 10, 400, DIM, "middle")
pts = " ".join(f"{X(tk):.1f},{Y(sev[tk]):.1f}" for tk in sorted(sev))
o.append(f'<polyline points="{pts}" fill="none" stroke="{ACC}" stroke-width="1.5"/>')
# trap band
if trap["occurred"] and trap["persistent"]:
    line(X(trap["started"]), Y0 - 10, X(T), Y0 - 10, DK, 3)
    t(X(trap["started"]) + 4, Y0 - 14, f"robot trap: {', '.join(trapped)} blocked from tick {trap['started']} to the horizon",
      10, 700, DK)
# page strip
SY = Y1 + 22
for tk, state, _, dragon, _ in hist:
    word = "DK" if state == "RCT" and dragon else state
    h = 16 if word in ("RCT", "DK") else 10
    rect(X(tk - 20), SY + (10 - h) / 2, X(20) - X(0) + 0.3, h, STATE_COL[word])
t(X0 - 6, SY + 9, "page", 10, 400, DIM, "end")
MARKS = [(1, 0), (2, 600), (3, 1200), (4, trap["started"]), (5, first_rct or 1341), (6, 1500), (7, 2400), (8, 4100)]
MY = SY + 34
for n, tk in MARKS:
    line(X(tk), SY + 14, X(tk), MY - 9, DIM, 1, "2 2")
    circ(X(tk), MY, 9, INK)
    t(X(tk), MY + 4, n, 11, 700, "#ffffff", "middle")

# --------------------------------------------- one decision, with the model
DY = MY + 28
t(40, DY, "Every decision of ROUTING and SCHEDULING, in every tick, goes this way (the model is called only where the rule is "
          "insufficient; the displacement comes after everything)", 13, 700)
BX, BY, BW, BH, BG = 40, DY + 12, 196, 176, 14
steps = [
    ("1  perceive", ["the facts of the question: the blocked robot, who blocks it and for how long; or the ready "
                     "tasks and the robots that could take one"], "#fafbfc", LINE, INK),
    ("2  rule first", ["the Python rule answers: WAIT, PUSH, YIELD, REROUTE or ABANDON; the best-placed robot; the "
                       "least-slack task. Its conditions are checked: still blocked 6+ ticks, low charge, a dear "
                       "detour; nobody able, equally placed robots"], "#fafbfc", LINE, INK),
    ("3  model call, if insufficient", ["--api only. CrewBrain hands the question to the expert's CrewAI agent, which "
                                        "may consult the one peer the peer map allows (ROUTING: SCHEDULING or RESOURCE; "
                                        "SCHEDULING: RESOURCE, ROUTING or DISPATCH) over the bus; Ollama answers "
                                        "(llm_call events); the owner's DECISION line is the answer. --rules: skipped."],
     "#eefaf7", LLM, LLM),
    ("4  gate and record", ["the policy gate validates the answer (schema, policy, the floor); a refused answer is "
                            "replaced by the rule's. The decision event records choice, source and reason, in ON "
                            "and OFF alike"], "#fafbfc", LINE, INK),
    ("5  ON phase: displaced", ["the scenario's wrapper replaces the recorded choice: WAIT for ROUTING; the lowest-"
                                "battery robot, or the most-slack non-urgent task, for SCHEDULING. It logs "
                                "attack_displaced: honest -> displaced. In OFF nothing changes"], "#fdf1f0", BAD, BAD),
    ("6  act", ["the robot is told what was chosen and the facility moves on it next tick. DK-RMM reads the event "
                "stream from outside and changes nothing"], "#fafbfc", LINE, INK),
]
for i, (title, lines, fill, stroke, col) in enumerate(steps):
    x = BX + i * (BW + BG)
    box(x, BY, BW, BH, title, lines, fill, stroke, col, 10.5, 32, sw=2 if stroke in (LLM, BAD) else 1)
    if i < len(steps) - 1:
        line(x + BW + 2, BY + BH / 2, x + BW + BG - 2, BY + BH / 2, DIM, 1.2, marker=True)
t(40, BY + BH + 16, "Rules-only (this run, the frozen artifacts): step 3 never happens. On the model, ROUTING's rule finds a robot "
                    "blocked 6+ ticks insufficient and consults SCHEDULING on it every few ticks for as long as the block lasts: in a "
                    "trap, hundreds of model calls,", 10.5, 400, DIM)
t(40, BY + BH + 30, "and the answer the gate accepts (YIELD, REROUTE) may differ from the rule's, so a model-enabled run can leave the "
                    "frozen path. Step 5 is applied to whatever step 4 recorded, rule or model alike, in ON phases only.", 10.5, 400, DIM)

# ------------------------------------------------------------- the steps
r1, r2 = (trapped + ["?", "?"])[:2]
e1, e2 = eps.get(r1, {}), eps.get(r2, {})
STEPS = [
    (1, "0", "Build and install", [
        f"The Normal facility (normal_config, seed {SEED}): 5 robots, 7 experts, 15 sub-agents, DK-RMM attached from "
        f"outside. The scenario installs two things on this run's own instances before the first tick: the frozen arrival "
        f"schedule (the Normal arrivals plus the 20 hospital parcels) on the generator, and the wrapper on ROUTING's and "
        f"SCHEDULING's decide. Tick 1: attack_phase OFF."],
     "Baselines forming for the first 24 windows; nothing to read yet.", None),
    (2, f"1 to {phases[0]['on_from'] - 1}", "Normal operation (OFF)", [
        f"Both agents decide by their rules; the wrapper passes every answer through unchanged. Parcels go from the dock "
        f"through sorting to the vans: {departed_before} dispatched by tick {phases[0]['on_from'] - 1}, "
        f"{len(ev('arrival_refused', 0, phases[0]['on_from'] - 1))} dock refusals. Robots top up at the four charge points "
        f"of the charging zone."],
     "Normal's own swings: STABLE, DEVIATING, now and then UNSTABLE.", "STABLE"),
    (3, f"{phases[0]['on_from']} to {phases[0]['on_to']}", "ON phase 1: the rules are overruled", [
        f"attack_phase ON at {phases[0]['on_from']}. From tick {first_disp['tick']} every blocked robot is told to WAIT whatever "
        f"ROUTING's rule said ({first_disp['detail']['honest']} -> WAIT first), and SCHEDULING hands errands to the "
        f"lowest-battery robot. In this phase {len(disp_phase1)} decisions are displaced "
        f"(ROUTING {disp_p1_by_agent.get('ROUTING', 0)}, SCHEDULING {disp_p1_by_agent.get('SCHEDULING', 0)}); the honest "
        f"decision is recorded first every time."],
     "The abrupt change (waits, blocks, chatter) is what the within-run test picks up; see step 5.", "DEVIATING"),
    (4, f"{trap['started']}", "The trap forms", [
        f"{r1} is moving to a charger with no errand; {r2} is carrying its errand behind it. Told to WAIT, neither "
        f"gives way; {r2}'s errand is taken from it and reassigned, so {r2} too now holds nothing. From tick {trap['started']} "
        f"{r1} stands at ({','.join(map(str, e1.get('cell', [])))}) wanting {r2}'s cell, {r2} at "
        f"({','.join(map(str, e2.get('cell', [])))}) wanting {r1}'s: head to head in the charging zone, both task-less. "
        f"ROUTING's rule answers for them in this phase: {', '.join(f'{k} {v}' for k, v in on1.most_common())}; "
        f"every answer but WAIT was displaced to WAIT."],
     "Blocked robots and waits rise; the readings stay in the ON phase's deviation.", "UNSTABLE"),
    (5, f"{first_rct}", "DK-RMM: RCT, dragon-king test holds", [
        f"At {peak_tick} the severity reaches {sev[peak_tick]:.1f}, the run's largest: {', '.join(kinds_peak)}. RCT from "
        f"{first_rct}; the dragon-king test holds at {', '.join(map(str, dk_ticks)) or 'no reading'}, so the page writes DK "
        f"there. This is the monitor's alert on the ON phase's abruptness, not a verdict on the run."],
     f"RCT readings in all: {len(rct_ticks)}; DK in {len(dk_ticks)}.", "DK"),
    (6, f"{phases[0]['on_to']} to {phases[1]['on_from']}", "OFF: the rules return, the trap stays", [
        f"attack_phase OFF at {phases[0]['on_to']}; nothing is displaced. ROUTING's rule now says ABANDON for both "
        f"({off1.get('ABANDON', 0)} times in this OFF phase: 'standing on the destination; this errand cannot be finished'), "
        f"but a robot that holds no errand has nothing to abandon, and the rules have no other move for it. "
        f"{r1} counts as trapped at {robots[r1]['trapped_since']} (300 ticks), {r2} at {robots[r2]['trapped_since']}. "
        f"The trap outlives the phase that made it."],
     "Little moves in the charging zone; the composite returns toward 1 as the baseline adapts.", "STABLE"),
    (7, f"{first_hospital} to {P7.ATTACK_END}", "Consignment, congestion, ON 2 to 4", [
        f"The hospital parcels arrive from {first_hospital}. With {len(trapped)} of 5 robots lost the others cannot keep up: "
        f"the dock fills (first refusal at {first_refusal}), {imp['dock_refused']} arrivals are refused at the full dock, "
        f"{len(hosp_refused)} of them hospital parcels; {len(hosp_in)} hospital parcels get in and wait, "
        f"{imp['hospital_missed_promise']} miss their promised departure. ON phases 2 to 4 displace more decisions "
        f"({displaced_total} in the run); the window closes at {P7.ATTACK_END}."],
     f"Severity {min(late_sev):.1f} to {max(late_sev):.1f} after 1800: the monitor's indicators are quiet once little moves.",
     "DEVIATING"),
    (8, f"{P7.ATTACK_END} to {T}", "The horizon", [
        f"Both agents on their rules for good; {r1} and {r2} still blocked ({robots[r1]['blocked_for']} and "
        f"{robots[r2]['blocked_for']} ticks). At {T}: {imp['dispatched_total']} parcels out ({imp['hospital_dispatched']} hospital), "
        f"{imp['parcels_in_building']} in the building, {imp['blocked_robot_ticks']:,} blocked robot-ticks. The run stops "
        f"('run complete'); the ON-OFF tab shows the summary. The Phase 7 confirmation of this configuration found O/E 1.90, "
        f"below the registered 2: not a confirmed Dragon-King, and the page never labels a run one."],
     f"{len(hist)} assessments; DK-RMM's alerts are reported beside the observed events, as alerts.", None),
]

CW, CH, GX, GY = 310, 290, 16, 20
CX0, CY0 = 40, BY + BH + 50
for i, (n, when, title, facts, dk, stt) in enumerate(STEPS):
    row, col = divmod(i, 4)
    x = CX0 + col * (CW + GX)
    y = CY0 + row * (CH + GY)
    border = DK if stt == "DK" else (BAD if n in (3, 4) else LINE)
    fill = "#fdf1f0" if n in (3, 4) else ("#f7f3ef" if n in (6, 7) else "#fafbfc")
    rect(x, y, CW, CH, fill, border, 8, sw=2 if border != LINE else 1)
    circ(x + 22, y + 22, 12, INK)
    t(x + 22, y + 26, n, 12, 700, "#ffffff", "middle")
    t(x + 42, y + 20, f"tick {when}", 11, 400, DIM)
    t(x + 42, y + 36, title, 14, 700)
    yy = y + 58
    t(x + 14, yy, "in the facility", 10, 700, DIM)
    yy += 15
    for fact in facts:
        for row_text in wrap(fact, 48):
            t(x + 14, yy, row_text, 11)
            yy += 14
    yy += 6
    line(x + 14, yy - 10, x + CW - 14, yy - 10, LINE, 1)
    t(x + 14, yy + 4, "DK-RMM reads", 10, 700, DIM)
    if stt:
        chip = ("DK", DK) if stt == "DK" else (stt, STATE_COL[stt])
        cw = 7 * len(chip[0]) + 10
        rect(x + CW - 14 - cw, yy - 8, cw, 16, chip[1], rx=8)
        t(x + CW - 14 - cw / 2, yy + 4, chip[0], 10, 700, "#ffffff", "middle")
    yy += 19
    for row_text in wrap(dk, 48):
        t(x + 14, yy, row_text, 11, 400, DK if stt == "DK" else INK)
        yy += 14
    assert yy < y + CH + 2, (n, yy - y)
    if col < 3:
        line(x + CW + 2, y + CH / 2, x + CW + GX - 2, y + CH / 2, DIM, 1.2, marker=True)

# --------------------------------------------------------------- reading
FY = CY0 + 2 * (CH + GY) + 8
t(40, FY, "How to read it", 15, 700)
for k, s in enumerate([
    "The trap is made in an ON phase (steps 3 and 4) and kept by the honest rules (step 6): ABANDON on a robot without an "
    "errand does nothing, so switching the misbehaviour OFF does not undo its consequence.",
    "DK-RMM's DK word (step 5) is the within-run rank test on the ON phase's abrupt change; it fires in about half the runs of "
    "this configuration and does not single out the trapped ones. The across-run verdict of the Phase 7 confirmation is not supported.",
    "With the model on (--api), step 3 enters the loop: ROUTING consults SCHEDULING about a robot blocked 6+ ticks, and the "
    "answer the gate accepts is the one that is displaced in ON or acted on in OFF; the frozen numbers above are the rules'.",
]):
    for j, row_text in enumerate(wrap(s, 190)):
        t(40, FY + 20 + 16 * (2 * k + j), row_text, 12.5)
o.append("</svg>")
Path(OUT).parent.mkdir(parents=True, exist_ok=True)
open(OUT, "w", encoding="utf-8").write("\n".join(o) + "\n")
print("written", OUT)
