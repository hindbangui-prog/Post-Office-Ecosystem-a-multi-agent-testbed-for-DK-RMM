"""
The live page, served off a running simulation.

`shell_html(runner)` is the page at `GET /`: the source's shell (run line,
controls, scenario strip with DK-RMM's verdict) with an expert roster and five
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

Adapted from the source `post_office/ui/live.py`: `shell_html`, `robots_html`,
`frame_json`, `dkrmm_html` and `pane_error_html` are kept; the trace,
trajectory and history pages (which read the removed observability store) are
not part of this prototype, and the floor script no longer draws the source's
removed disturbance overlays.
"""

from __future__ import annotations

import json
import os
import traceback
from html import escape
from typing import Any, Callable, Dict, List

from ..config.settings import scenarios
from . import views

HERE = os.path.dirname(os.path.abspath(__file__))


def _read(name: str) -> str:
    with open(os.path.join(HERE, name), "r", encoding="utf-8") as handle:
        return handle.read()


def _e(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


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


def dkrmm_html(runner, limit: int = 60) -> str:
    """
    The DK-RMM pane, built from the monitor rather than from the run: the
    state, its severity and evidence kinds, the twelve indicators with the
    monitor's own description of each, and the history strip of its recent
    readings. The page's `paintDkrmm` draws the same markup.
    """
    from ..api.digest import indicator_rows, monitor_digest

    monitor = getattr(runner, "monitor", None)
    if monitor is None:
        return NO_MONITOR
    digest = monitor_digest(monitor)
    series = monitor.series(limit=limit)
    read = digest.get("tick") is not None
    state = digest["state"] if read else "warming up"
    css = digest["state"] if read else "none"
    when = (f"at tick {digest['tick']} · assessment {digest['assessments']}"
            + (f" · next at {digest['next_at']}" if digest.get("next_at") else "")
            if read else f"first assessment at tick {digest.get('every') or '?'}")
    kinds = ", ".join(digest.get("kinds") or []) or "none"
    if read and digest.get("enough_activity") is False:
        kinds = "window too quiet to read"
    evidence = "".join(f"<li>{_e(line)}</li>" for line in digest.get("evidence") or [])
    strip = "".join(f'<span class="s-{_e(st)}" title="tick {_e(t)}: {_e(st)}"></span>'
                    for t, st in zip(series.get("ticks") or [], series.get("states") or []))
    indicators = "".join(
        f'<tr class="indicator"><td class="name">{_e(row["name"])}</td>'
        f'<td class="about">{_e(row["about"])}</td>'
        f'<td class="v">{row["value"]:.3f}</td>'
        f'<td class="z">{row["z"]:+.2f}σ</td></tr>'
        for row in indicator_rows(monitor))
    severity = digest.get("severity")
    return (f'<div class="dk-head"><span class="st s-{_e(css)}" id="dk-pane-state">{_e(state)}</span>'
            f'<span>severity <b id="dk-pane-sev">'
            f'{"-" if severity is None else f"{float(severity):.3f}"}</b></span>'
            f'<span class="dim" id="dk-pane-when">{_e(when)}</span></div>'
            f'<div class="dk-kinds">evidence kinds: <b id="dk-pane-kinds">{_e(kinds)}</b></div>'
            f'<ul class="dk-evidence" id="dk-pane-evidence">{evidence}</ul>'
            f'<h3>History <em>one cell per assessment, oldest first</em></h3>'
            f'<div class="strip" id="dk-pane-strip">{strip}</div>'
            f'<h3>The twelve indicators <em>this window, and its distance from the baseline</em></h3>'
            f'<table class="indicators"><tbody id="dk-pane-indicators">{indicators}'
            f'</tbody></table>')


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
