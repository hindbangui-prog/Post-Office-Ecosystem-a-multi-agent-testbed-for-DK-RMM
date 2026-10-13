"""
The live page, served off a running simulation.

`shell_html(runner)` is the page at `GET /`: the source's shell (run line,
controls, scenario strip with DK-RMM's verdict) with an expert roster and seven
panes. The first pane is the floor (`robots_html`: the source's replay page,
the interaction graph, the facility map and the robot cards, with a script
appended that follows the run), carried in the shell as an `srcdoc` so the page
needs no route beyond spec 16. Three are the shell's own tables: Consultations,
Ollama calls and DK-RMM. Each is filled here once, from what the runner
published, and then kept current by the page itself from `/consultations`,
`/llm/calls` and `/dkrmm/*`, with the WebSocket asking for a refresh the
moment a consultation event arrives. The Python fragments and the page's
renderers draw the same markup. The fifth, Runtime communication (taxonomy
design, section 6), is filled by the page alone: nothing but its static empty
state is served here, and its rows are the page's mirror of `ui/feed.py` over
the events the WebSocket relays and `GET /events` backfills.

Nothing here reads the live ecosystem: `runner.last_frame`, `runner.static`
and the runner's lock-free accessors are all it uses, so the page is served
at once while a tick is blocked in a consultation.

Two pages of their own are served beside the shell: `trajectory_html` (the
source's trajectory template, `ui/trajectory.html`, with its data slot filled
from the event logger by `views.trajectory_data`) and `rcts_html` (the RCT log
page, `ui/rcts.html`, which fetches everything it shows itself). They are the
last two panes, the Trajectory and RCT log tabs, loaded into iframes by the
page when first opened (`/ui/trajectory`, `/ui/rcts`).

Adapted from the source `post_office/ui/live.py`: `shell_html`, `robots_html`,
`frame_json`, `dkrmm_html`, `trajectory_html` and `pane_error_html` are kept;
the trace and history pages (which read the removed observability store) are
not part of this prototype, and the floor script no longer draws the source's
removed disturbance overlays.
"""

from __future__ import annotations

import json
import os
import traceback
from html import escape
from typing import Any, Callable, Dict, List

from ..config.settings import C2NEAR_PRESETS, COLLAPSE_PRESETS, scenarios
from . import views

HERE = os.path.dirname(os.path.abspath(__file__))


def _read(name: str) -> str:
    with open(os.path.join(HERE, name), "r", encoding="utf-8") as handle:
        return handle.read()


def _e(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def dk_view_of(runner: Any = None) -> Any:
    """
    DK-RMM's view on the page built for `runner`: `"four"` under a study
    preset (the C2-NEAR conditions, the collapse scenarios), where a RECOVERY
    reading is shown as STABLE (`stress/states.py`), None on Normal and
    without a runner, where the monitor's five states are shown as they are.
    """
    preset = str(getattr(runner, "preset", "") or "")
    return "four" if preset in C2NEAR_PRESETS or preset in COLLAPSE_PRESETS else None


def _dk_word(runner: Any, state: Any, dragon: Any = False) -> Any:
    """
    A state word in the page's view for `runner`: RECOVERY shown as STABLE
    under a study preset, as it is on Normal; on both, an RCT reading whose
    dragon-king test held is shown as DK (`stress/states.py`).
    """
    from ..stress.states import dk_state, four_state

    if not state:
        return state
    word = four_state(state) if dk_view_of(runner) == "four" else state
    return dk_state(word, dragon)


# ---------------------------------------------------------------- the shell
def model_of(runner: Any = None) -> Any:
    """The model a runner's experts are configured with; None (the settings' model) without one."""
    settings = getattr(runner, "settings", None)
    return getattr(settings, "model", None)


def scenario_options(runner: Any = None) -> str:
    """
    The scenario selector's options, from `scenarios()` (one, in Prototype II);
    the label names the runner's configured model.
    """
    return "".join(f'<option value="{_e(key)}">{_e(label)}</option>'
                   for key, label in scenarios(model_of(runner)))


def shell_html(runner: Any = None) -> str:
    """
    The page. With a runner, the floor and the three panes are filled from
    what it published; without one (a test reading the template) they are
    left empty for the page to fill.
    """
    page = _read("live.html").replace("<!--SCENARIOS-->", scenario_options(runner))
    if runner is None:
        fills = {"<!--FLOOR-->": "", "<!--CONSULTATIONS-->": "",
                 "<!--LLM_CALLS-->": "", "<!--DKRMM-->": ""}
    else:
        fills = {
            "<!--FLOOR-->": escape(_pane("floor", "robots_html", runner), quote=True),
            "<!--CONSULTATIONS-->": _pane("Consultations", "consultations_html", runner),
            "<!--LLM_CALLS-->": _pane("Ollama calls", "llm_calls_html", runner),
            "<!--DKRMM-->": _pane("DK-RMM", "dkrmm_html", runner),
        }
    for marker, html in fills.items():
        page = page.replace(marker, html)
    if runner is not None:
        # The run the page is built for: what it treats as "this run" until a
        # reset (its feed keeps only this run's events).
        page = page.replace("/*__RUN_ID__*/null",
                            json.dumps((runner.last_frame or {}).get("run_id")), 1)
    # DK-RMM's view for that run: "four" under a study preset, null on Normal.
    # The pane's note on the view is shown from the start under a study
    # preset; on Normal it stays hidden, no part of the page's text.
    view = dk_view_of(runner)
    page = page.replace("/*__DK_VIEW__*/null", json.dumps(view), 1)
    if view == "four":
        page = page.replace('id="dk-view-note" hidden>', 'id="dk-view-note">', 1)
    return page


def _pane(title: str, build: str, runner: Any) -> str:
    """
    One pane, or what stopped it. The builder is looked up by name at the
    moment of building, so a test can break one, and its failure is caught so
    one pane that throws never takes out the page around it.
    """
    try:
        builder: Callable[[Any], str] = globals()[build]
        return builder(runner)
    except Exception:
        return failed_pane_html(title, traceback.format_exc())


# ---------------------------------------------------------------- the floor
#: Appended after the floor page's own script. It only adds; it changes nothing
#: the page already does, which is why the page needs no live/recorded branch.
LIVE_FLOOR = """
<script>
"use strict";
/* The floor page plays a run out of `F`. Live, the run is not finished, so
   this polls the simulation and pushes a frame onto the same array. Scrubbing
   back through what has already happened keeps working, because by then it
   really is a recording; the only new thing is that the recording grows.

   Polled rather than pushed: the event socket says what happened, not where
   everything is, and a floor needs positions. One request every 400 ms is
   cheaper than the drawing it feeds. */
(function () {
  const EVERY = 400;
  let following = true;      // pinned to the newest frame until you scrub back
  let failures = 0;

  /* Stop the page playing itself: live there is only one thing that should
     move the view, the newest frame. `playing` and `wantedPlaying` are
     top-level `let` bindings in the page's own script, which a later classic
     script shares. */
  playing = false;
  wantedPlaying = false;
  syncButtons();
  loop();
  const play = document.getElementById("play");
  if (play) play.hidden = true;

  /* "0 ticks" is the length of a run that has not ended, and the graph's line
     weights and the cast's sent / received counts are folded out of the
     frames this page holds, which begin when it opens. The sub-line says so. */
  const sub = document.querySelector("header .sub");
  if (sub) {
    sub.textContent = sub.textContent.replace(/ · \\d+ ticks/, "")
      + " · traffic counts start when this page opens";
  }

  const note = document.createElement("span");
  note.className = "tickbox";
  note.style.color = "var(--accent)";
  note.textContent = "live";
  const controls = document.querySelector(".controls");
  if (controls) controls.appendChild(note);

  // Scrubbing or stepping means you want to look at something; stop dragging
  // the view forward until the Live button is pressed again.
  const live = document.createElement("button");
  live.textContent = "Live";
  live.addEventListener("click", () => { following = true; sync(); if (F.length) show(F.length - 1); });
  if (controls) controls.appendChild(live);
  for (const id of ["back", "fwd", "scrub"]) {
    const node = document.getElementById(id);
    if (node) node.addEventListener("click", () => { following = false; sync(); });
  }
  const scrub = document.getElementById("scrub");
  if (scrub) scrub.addEventListener("input", () => { following = false; sync(); });

  // The tick count and the speed menu are about a recording; the page header
  // (run line and counters) stays, the bar only matters once the view has
  // left the live tick.
  for (const id of ["tickbox", "speed"]) {
    const node = document.getElementById(id);
    if (node) node.hidden = true;
  }

  function sync() {
    live.hidden = following;
    note.textContent = following ? "live" : "paused · showing history";
    note.style.color = following ? "var(--accent)" : "var(--dim)";
  }

  async function poll() {
    try {
      const response = await fetch("/frame", { cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      const frame = await response.json();
      failures = 0;
      // A new run (a reset): the recording so far belongs to the old one.
      if (F.length && frame.run_id && F[F.length - 1].run_id
          && frame.run_id !== F[F.length - 1].run_id) {
        F.length = 0;
        following = true; sync();
        retitle(frame.run_id);
      }
      // The same tick twice is the run being paused, not a new frame.
      if (!F.length || frame.t > F[F.length - 1].t) {
        F.push(frame);
        const bar = document.getElementById("scrub");
        if (bar) bar.max = F.length - 1;
        if (following) show(F.length - 1);
      }
    } catch (error) {
      failures += 1;
      if (failures === 3) {
        note.textContent = "the server stopped answering";
        note.style.color = "#c0392b";
      }
    }
  }

  sync();

  /* The header's "seed N · preset P" was drawn from the run the page was built
     for; a reset from the API or another tab can change the seed, so it is
     redrawn from /summary for the new run. */
  async function retitle(runId) {
    try {
      const response = await fetch("/summary", { cache: "no-store" });
      if (!response.ok) return;
      const s = await response.json();
      if (s.run_id !== runId) return;          // moved on again; the next reset redraws it
      S.seed = s.seed; S.preset = s.preset;
      const line = document.querySelector("header .sub");
      if (line) {
        line.textContent = line.textContent.replace(
          /^seed \\S+ · preset \\S+/, `seed ${s.seed} · preset ${s.preset}`);
      }
    } catch (error) { /* the next frame's failures say the server went away */ }
  }

  /* `poSuspend` is what the shell calls when this pane goes behind another;
     the page defines it, and this respects it too rather than polling on
     behalf of a canvas nobody is looking at. */
  let timer = setInterval(poll, EVERY);
  const original = window.poSuspend;
  window.poSuspend = function (off) {
    if (typeof original === "function") original(off);
    playing = false;
    wantedPlaying = false;
    syncButtons();
    loop();
    clearInterval(timer);
    if (!off) { timer = setInterval(poll, EVERY); poll(); }
  };
})();
</script>
"""


def robots_html(runner) -> str:
    """The floor, the graph, the fleet and the conversation, following the run."""
    frame = runner.last_frame
    data = views.replay_data(runner.static, frame.get("summary") or {},
                             [frame.get("frame") or {}])
    page = _read("floor.html").replace(
        "/*__RUN_DATA__*/null", json.dumps(data, separators=(",", ":"), default=str))
    return page.replace("</body>", LIVE_FLOOR + "\n</body>", 1)


def frame_json(runner) -> Dict[str, Any]:
    """
    One tick, for the floor's poll, plus the roster and who is inside a model
    call now (`busy`, the agent ids; `in_flight`, the consultations). The frame
    is the published one; `busy` is read at the moment of asking, because a
    tick that consults publishes nothing until the consultation is over.
    """
    frame = runner.last_frame
    in_flight = runner.busy()
    return {**(frame.get("frame") or {}),
            "roster": frame.get("roster") or [],
            "llm_agents": frame.get("llm_agents") or [],
            "busy": [row["agent"] for row in in_flight],
            "in_flight": in_flight}


# ----------------------------------------------------------- consultations
def consultation_row(row: Dict[str, Any]) -> str:
    """One consultation, as the page draws it (and the page's `consultRow`)."""
    peer = row.get("peer") or ""
    pair = f"{row.get('owner', '')} → {peer}" if peer else f"{row.get('owner', '')} (alone)"
    outcome = str(row.get("outcome") or "")
    decision = row.get("decision")
    said = (f"DECISION: {decision}" if outcome == "decided"
            else f"rule: {decision if decision is not None else '-'}")
    latency = row.get("latency_ms")
    return (f'<tr data-id="{_e(row.get("id"))}">'
            f'<td class="t">{_e(row.get("tick"))}</td>'
            f'<td class="pair">{_e(pair)}</td>'
            f'<td class="what">{_e(row.get("kind"))} · {_e(row.get("condition"))}</td>'
            f'<td class="text">{_e(row.get("request"))}</td>'
            f'<td class="text">{_e(row.get("response"))}</td>'
            f'<td class="dec">{_e(said)}</td>'
            f'<td class="oc oc-{_e(outcome)}">{_e(outcome)}</td>'
            f'<td class="t">{_e("" if latency is None else f"{round(float(latency))} ms")}</td>'
            f'<td class="mono">{_e(row.get("model"))}</td></tr>')


def consultations_html(runner, limit: int = 40) -> str:
    """The Consultations pane's rows, newest first."""
    rows: List[Dict[str, Any]] = runner.consultations(limit)
    return "".join(consultation_row(row) for row in reversed(rows))


# ------------------------------------------------------------ model calls
def llm_call_row(row: Dict[str, Any]) -> str:
    """One model call, as the page draws it (and the page's `callRow`)."""
    prompt, completion = row.get("prompt_tokens"), row.get("completion_tokens")
    tokens = ("-" if prompt is None and completion is None
              else f"{'-' if prompt is None else prompt} + "
                   f"{'-' if completion is None else completion} tok")
    status = row.get("error") or row.get("status")
    latency = row.get("latency_ms")
    return (f'<tr data-id="{_e(row.get("call_id"))}">'
            f'<td class="t">{_e(row.get("tick"))}</td>'
            f'<td class="pair">{_e(row.get("agent_id"))}</td>'
            f'<td class="what">{_e(row.get("phase"))}</td>'
            f'<td class="mono">{_e(row.get("served_model") or "-")}</td>'
            f'<td class="t">{_e("" if latency is None else f"{round(float(latency))} ms")}</td>'
            f'<td class="t">{_e(tokens)}</td>'
            f'<td class="st{"" if row.get("status") == 200 else " bad"}">{_e(status)}</td>'
            f'<td class="mono">{_e(row.get("consultation_id"))}</td></tr>')


def llm_calls_html(runner, limit: int = 40) -> str:
    """The Ollama calls pane's rows, newest first."""
    rows: List[Dict[str, Any]] = runner.llm_calls(limit)
    return "".join(llm_call_row(row) for row in reversed(rows))


# ---------------------------------------------------------------- DK-RMM
NO_MONITOR = """<div class="empty"><b>No runtime monitor is attached to this run.</b>
DK-RMM watches the event stream from outside the simulation; without it there
is nothing here to show.</div>"""


def _decided_meta(row: Dict[str, Any]) -> str:
    """Who decided a reading, when, and why (the page's `decidedMeta`)."""
    return (str(row.get("decided_by") or "")
            + (f" · {row['decided_at']}" if row.get("decided_at") else "")
            + (f" · “{row['note']}”" if row.get("note") else ""))


def gate_html(current: Any) -> str:
    """
    The gate under the reading (the source's DK-RMM page): the reading's
    status and who decided it, a `by` and a `note`, Validate / Activate /
    Dismiss, and "explain this reading" with the box its explanation opens
    in. Enabled as the page's `paintGate` enables them: Validate and Dismiss
    while the reading is undecided (or before there is one, for the server
    to answer 409), Activate once it is validated.
    """
    row = current.as_dict() if current is not None else None
    status = str(row["status"]) if row else ""
    decided = bool(row) and status != "DISCOVERED"
    off = ' disabled' if decided else ''
    activate = '' if row and status == "VALIDATED" else ' disabled'
    explain = '' if row else ' disabled'
    return (f'<div class="gate" id="dk-gate">'
            f'<span class="status {_e(status)}" id="dk-gate-status">{_e(status)}</span>'
            f'<span class="meta" id="dk-gate-meta">{_e(_decided_meta(row) if decided else "")}</span>'
            f'<input id="dk-by" value="operator" maxlength="80" aria-label="by"'
            f' title="who is answering for this" autocomplete="off" spellcheck="false">'
            f'<input id="dk-note" placeholder="why (optional)" maxlength="500" aria-label="note"'
            f' autocomplete="off">'
            f'<button id="dk-validate"{off}>Validate</button>'
            f'<button id="dk-activate"{activate}>Activate</button>'
            f'<button id="dk-dismiss"{off}>Dismiss</button>'
            f'<span class="meta last" id="dk-gate-result"></span></div>'
            f'<div><button class="linkish" id="dk-explain"{explain}>explain this reading</button></div>'
            f'<div class="explain" id="dk-explain-box"></div>')


#: The arrow each direction is drawn with (the page's `DK_ARROWS`).
DK_ARROWS = {"up": "↑", "down": "↓", "both": "↕"}


def _n(value: Any, digits: int = 2, sign: bool = False, unit: str = "") -> str:
    """A number for the pane, "n/a" for None (the page's `na`)."""
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number:+.{digits}f}{unit}" if sign else f"{number:.{digits}f}{unit}"


def _pct(value: Any) -> str:
    """A share in [0, 1] as a percentage, "n/a" for None (the page's `pct`)."""
    return "n/a" if value is None else _n(float(value) * 100.0, 0, unit="%")


def _count(value: Any) -> str:
    return "n/a" if value is None else str(value)


def _ops_group(label: str, items: List[tuple]) -> str:
    return (f'<div class="g"><dt>{_e(label)}</dt><dd>'
            + " · ".join(f'{_e(key)} <b>{_e(text)}</b>' for key, text in items)
            + '</dd></div>')


def ops_html(operations: Any) -> str:
    """
    The operations block (the page's `opsHtml`): delivery, backlog,
    throughput and resources from the digest's `operations`, "n/a" where a
    value was not read.
    """
    ops = operations if isinstance(operations, dict) else {}
    delivery = ops.get("delivery") or {}
    backlog = ops.get("backlog") or {}
    throughput = ops.get("throughput") or {}
    resources = ops.get("resources") or {}
    zones = backlog.get("zones") or {}
    by_zone = (", ".join(f"{_e(zone)} {_e(n)}" for zone, n in zones.items())
               if zones else "n/a")
    return (
        _ops_group("delivery", [
            ("attempted", _count(delivery.get("attempted"))),
            ("delivered", _count(delivery.get("delivered"))),
            ("dropped", _count(delivery.get("dropped"))),
            ("late", _count(delivery.get("late"))),
            ("failure rate", _pct(delivery.get("rate")))])
        + _ops_group("backlog", [
            ("now", _count(backlog.get("now"))),
            ("per tick", _n(backlog.get("per_tick"), 2, sign=True)),
            ("by zone", by_zone),
            ("unfinished tasks", _count(backlog.get("unfinished_tasks")))])
        + _ops_group("throughput", [
            ("completed per tick", _n(throughput.get("completed_per_tick"), 2)),
            ("incoming per tick", _n(throughput.get("incoming_per_tick"), 2)),
            ("gap", _n(throughput.get("gap"), 2, sign=True))])
        + _ops_group("resources", [
            (str(category).replace("_", " "), _pct(value))
            for category, value in resources.items()] or [("none read", "n/a")]))


def _detail_title(detail: Any) -> str:
    """The detail dict as "key: value" lines (the page's `detailTitle`)."""
    if not isinstance(detail, dict) or not detail:
        return ""
    lines = []
    for key, value in detail.items():
        if isinstance(value, (dict, list, tuple)):
            text = json.dumps(value, separators=(",", ":"), default=str)
        elif isinstance(value, float):
            text = f"{value:.4g}"
        elif value is None:
            text = "n/a"
        else:
            text = str(value)
        lines.append(f"{key}: {text}")
    return "\n".join(lines)


def indicator_row_html(row: Dict[str, Any]) -> str:
    """One indicator row (the page's `indicatorRow`)."""
    evaluable = bool(row.get("evaluable"))
    status = str(row.get("status") or "n/a")
    st = {"ok": "st-ok", "deviating up": "st-up",
          "deviating down": "st-down"}.get(status, "st-na")
    z = float(row.get("z") or 0.0)
    return (f'<tr class="indicator{"" if evaluable else " na"}">'
            f'<td class="name" title="{_e(_detail_title(row.get("detail")))}">{_e(row["name"])}</td>'
            f'<td class="kind"><span class="tag">{_e(row.get("kind") or "base")}</span></td>'
            f'<td class="dir" title="{_e(row.get("direction") or "up")}">'
            f'{DK_ARROWS.get(str(row.get("direction")), DK_ARROWS["up"])}</td>'
            f'<td class="about">{_e(row["about"])}</td>'
            f'<td class="v">{_n(row.get("value"), 3)}</td>'
            f'<td class="b">{"-" if row.get("baseline") is None else _n(row.get("baseline"), 3)}</td>'
            f'<td class="z">{z:+.2f}σ</td>'
            f'<td class="status {st}">{_e(status)}</td></tr>')


def dkrmm_html(runner, limit: int = 60) -> str:
    """
    The DK-RMM pane, built from the monitor rather than from the run: the
    state with what was observed this window beside it, its severity and
    evidence kinds, the gate on the current reading, the history strip of
    its recent readings with this run's RCTs under it (filled by the page
    from `/dkrmm/rcts`), the operations block, and the indicators, base and
    derived, each with its value, baseline, distance and status and the
    monitor's own description. The page's `paintDkrmm`, `paintGate` and
    `paintRcts` draw the same markup.
    """
    from ..api.digest import indicator_rows, monitor_digest

    monitor = getattr(runner, "monitor", None)
    if monitor is None:
        return NO_MONITOR
    digest = monitor_digest(monitor)
    series = monitor.series(limit=limit)
    read = digest.get("tick") is not None
    # Under a study preset RECOVERY is shown as STABLE; on Normal the
    # monitor's own word. On both an RCT whose dragon-king test held is DK.
    # The page's `paintDkrmm` maps the same way.
    state = _dk_word(runner, digest["state"], digest.get("dragon")) if read else "warming up"
    css = state if read else "none"
    when = (f"at tick {digest['tick']} · assessment {digest['assessments']}"
            + (f" · next at {digest['next_at']}" if digest.get("next_at") else "")
            if read else f"first assessment at tick {digest.get('every') or '?'}")
    observed = str(digest.get("observed") or "") if read else ""
    kinds = ", ".join(digest.get("kinds") or []) or "none"
    if read and digest.get("enough_activity") is False:
        kinds = "window too quiet to read"
    evidence = "".join(f"<li>{_e(line)}</li>" for line in digest.get("evidence") or [])
    held = {int(a.tick): bool(getattr(getattr(a, "dragon", None), "is_dragon", False))
            for a in list(getattr(monitor, "history", []) or [])}
    strip = "".join(f'<span class="s-{_e(st)}" title="tick {_e(t)}: {_e(st)}"></span>'
                    for t, st in ((t, _dk_word(runner, st, held.get(int(t), False)))
                                  for t, st in zip(series.get("ticks") or [],
                                                   series.get("states") or [])))
    indicators = "".join(indicator_row_html(row) for row in indicator_rows(monitor))
    severity = digest.get("severity")
    return (f'<div class="dk-head"><span class="st s-{_e(css)}" id="dk-pane-state">{_e(state)}</span>'
            f'<span class="dk-observed" id="dk-pane-observed">{_e(observed)}</span>'
            f'<span>severity <b id="dk-pane-sev">'
            f'{"-" if severity is None else f"{float(severity):.3f}"}</b></span>'
            f'<span class="dim" id="dk-pane-when">{_e(when)}</span></div>'
            f'<div class="dk-kinds">evidence kinds: <b id="dk-pane-kinds">{_e(kinds)}</b></div>'
            f'<ul class="dk-evidence" id="dk-pane-evidence">{evidence}</ul>'
            f'{gate_html(getattr(monitor, "current", None))}'
            f'<h3>History <em>one cell per assessment, oldest first</em></h3>'
            f'<div class="strip" id="dk-pane-strip">{strip}</div>'
            f'<h3>Detected RCTs <em id="dk-rcts-n">this run</em></h3>'
            f'<div id="dk-rcts"></div>'
            f'<h3>Operations <em>this window, from the delivery log and the state of the building</em></h3>'
            f'<dl class="dk-ops" id="dk-pane-ops">{ops_html(digest.get("operations"))}</dl>'
            f'<h3>Backlog by zone <em>every tick of this run, from the building '
            f'(GET /zones); the dashed line is the scenario\'s fault</em></h3>'
            f'<div class="zones" id="dk-zones"></div>'
            f'<div class="zones-key" id="dk-zones-key"></div>'
            f'<div class="zones-flow" id="dk-zones-flow"></div>'
            f'<h3>The indicators <em>base and derived; this window, its baseline, and its distance from it</em></h3>'
            f'<table class="indicators" id="dk-pane-table"><tbody id="dk-pane-indicators">{indicators}'
            f'</tbody></table>'
            f'<div class="dk-stale" id="dk-pane-stale" hidden></div>')


# ------------------------------------------------- the trajectory, RCT log
def _fill(name: str, marker: str, data: Any) -> str:
    return _read(name).replace(
        marker, json.dumps(data, separators=(",", ":"), default=str))


def trajectory_html(runner, limit: int = 9000) -> str:
    """
    The newest rows of the live run the event logger holds, in order, on the
    source's trajectory page, which then follows the run from
    `/ui/trajectory/tail`. Only the live run: there is no store of finished
    runs to read another from.
    """
    return _fill("trajectory.html", "/*__TRAJECTORY_DATA__*/null",
                 views.trajectory_data(runner, limit))


def rcts_html() -> str:
    """The RCT log page; it reads `/dkrmm/rct-log` and polls it itself."""
    return _read("rcts.html")


# --------------------------------------------------------- a failed pane
#: A pane that failed to build, shown in place of the pane. The same
#: information as the server's log, where the failure happened.
FAILED_PANE = """<div class="failed">
<h2>The {title} view could not be built</h2>
<p>The rest of the run is unaffected and still going. This is the exception
that stopped this pane from rendering; the same traceback is in the server's
console.</p>
<pre>{detail}</pre>
</div>"""


def failed_pane_html(title: str, detail: str) -> str:
    """The failed-pane fragment, with the traceback escaped into it."""
    return FAILED_PANE.format(title=escape(title), detail=escape(detail))


#: A page that failed to build, shown in place of the four words a browser
#: puts on the screen when its source returns a 500.
PANE_ERROR = """<!doctype html>
<meta charset="utf-8">
<title>{title} could not be built</title>
<style>
 body{{margin:0;padding:22px;background:#f7f8fa;color:#1a1e24;
   font:14px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}
 h1{{font-size:16px;margin:0 0 6px}}
 p{{margin:0 0 14px;color:#525a63;max-width:66ch}}
 pre{{background:#fff;border:1px solid #dfe3e8;border-radius:4px;padding:12px;
   overflow:auto;font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;
   color:#8a1f1f;white-space:pre-wrap}}
 button{{font:inherit;padding:6px 12px;border:1px solid #dfe3e8;border-radius:4px;
   background:#fff;cursor:pointer}}
 @media (prefers-color-scheme:dark){{
   body{{background:#121519;color:#e6e9ec}} p{{color:#9aa3ac}}
   pre{{background:#1a1e24;border-color:#2a3038;color:#ff9b9b}}
   button{{background:#1a1e24;border-color:#2a3038;color:#e6e9ec}}}}
</style>
<h1>The {title} view could not be built</h1>
<p>The rest of the run is unaffected and still going. This is the exception
that stopped this page from rendering; the same traceback is in the server's
console.</p>
<pre>{detail}</pre>
<button onclick="location.reload()">Try again</button>
"""


def pane_error_html(title: str, detail: str) -> str:
    """The failed-page document, with the traceback escaped into it."""
    return PANE_ERROR.format(title=escape(title), detail=escape(detail))
