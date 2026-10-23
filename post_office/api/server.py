"""
FastAPI over the running ecosystem, plus a WebSocket for the event stream.

Spec 16 of 2026-10-01 plus `GET /taxonomy` (the taxonomy design of 2026-10-02,
section 5) plus the DK-RMM and page routes of the trajectory and RCT log
design of 2026-10-02, section 5, and nothing else:

    GET  /                       the live page
    GET  /state                  the whole runtime state, as of the last tick
    GET  /frame                  the floor's frame, and who is inside a model call
    GET  /summary                how the run is going, with the monitor's digest
    GET  /events?after=&limit=   the event log after a sequence number
    GET  /consultations?limit=   the most recent consultations
    GET  /llm/calls?limit=       the most recent model calls, as the wire saw them
    GET  /zones?after=&limit=    the unfinished parcels by zone, one row per tick
    GET  /decision-traces?limit=&eligible=&after_tick=   decisions linked to their
                                 messages, deliveries and robot commands by ids
    GET  /settings               Ollama settings, identity, experts on the model
    GET  /taxonomy               the runtime communication taxonomy, as a table
    GET  /dkrmm/state            DK-RMM's current assessment
    GET  /dkrmm/series?limit=    its recent assessments, shaped for drawing
    GET  /dkrmm/indicators       its digest and the indicators
    GET  /dkrmm/rcts             the RCTs of this run, newest first
    GET  /dkrmm/explain?tick=    what drove one reading, from the run's events
    GET  /dkrmm/rct-log          every RCT this app's runs saved, with the scenarios
    GET  /dkrmm/rct-log/item?run=&tick=   one saved RCT, with its cause
    POST /dkrmm/validate|activate|dismiss a person's verdict on the current reading
    GET  /ui/trajectory?limit=&run_id=&archived=   the live run's events, in order
    GET  /ui/trajectory/tail?after_id=&started=&limit=&run_id=   rows since an id, for that page
    GET  /ui/rcts                the RCT log page
    POST /simulation/start|stop|reset|speed
    WS   /ws                     every event, live, and a tick payload per tick

Every read answers from what the runner published (`runner.last_frame`) or
from an accessor that does not take the step lock (`consultations`,
`llm_calls`, `llm_stats`, `busy`, `events`, `event_counts`, `run_events`,
`monitor.state()`/`series()`/`history`, the RCT files on disk). A
tick with the experts on the model can last as long as a consultation, and a
read that waited for it would freeze the page for that long; reading the
published frame instead means a reader may see the run one tick behind and
never sees a tick half done. The writes go through the runner, which takes the
lock as the loop does, except the gate verdicts: as in the source they call
the monitor's own method without the step lock, so a verdict never waits for
a consultation-long tick, and only the recorder's write after them is
serialised with the tick's (the runner's `_record_lock`).

Adapted from the source `post_office/api/server.py`: the reads, the controls,
the socket and `serve` are kept, and so are the DK-RMM gate, the run's RCTs,
the explainer, the RCT log and the trajectory (over the event logger); the
routes of the source's removed scenario families, its settings and providers
panel, the trace, sessions, history and replay are not part of this prototype
and are not served. FastAPI's generated
`/docs`, `/redoc` and `/openapi.json` are switched off as well.

    python main.py --api            the seven experts on Ollama (`require_model` first)
    python main.py --api --rules    every expert on its rules
    python main.py --api --no-record   the same, writing no record and no RCT files
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union

try:
    from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse
    from pydantic import BaseModel, Field
except ImportError as exc:      # pragma: no cover
    raise SystemExit(
        "The API needs fastapi and uvicorn:\n"
        "    pip install fastapi uvicorn[standard]\n"
        "The simulation itself does not -- `python main.py` runs without them."
    ) from exc

from ..config.settings import LLM_CANDIDATES, known_presets, scenario_meta, scenarios
from .digest import indicator_rows, monitor_digest
from .runner import SimulationRunner

#: The runner the routes read. None until `serve` (or a test, through `use`)
#: puts one here: building one at import would verify the model against
#: whatever Ollama the environment names, which an import must not do.
runner: Optional[SimulationRunner] = None

app = FastAPI(
    title="Automated post office: prototype II",
    version="0.1.0",
    description=(
        "A supervisor, a planner, seven expert agents on CrewAI and a local "
        "Ollama model, fifteen sub-agents and five robots running an automated "
        "post office, watched by DK-RMM. Every endpoint here is a view of one "
        "running simulation."
    ),
    # Spec 16 and nothing else: no generated /docs, /redoc or /openapi.json.
    docs_url=None, redoc_url=None, openapi_url=None,
)


def use(new: Optional[SimulationRunner]) -> Optional[SimulationRunner]:
    """Serve `new` from now on; the runner it replaces, which the caller closes."""
    global runner
    previous, runner = runner, new
    return previous


def _runner() -> SimulationRunner:
    if runner is None:
        raise HTTPException(status_code=503, detail="no simulation is being served")
    return runner


class SpeedPatch(BaseModel):
    """
    Bounded at both ends: 10 s a tick is a stall, and below the floor the run
    stops being paced at all rather than being paced quickly. The floor is the
    fastest the speed control offers, 512x, a tick every 1.95 ms.
    """

    tick_seconds: float = Field(ge=0.001953125, le=10.0)


def _no_store(body: Any, html: bool = False):
    headers = {"Cache-Control": "no-store"}
    if html:
        return HTMLResponse(body, headers=headers)
    return JSONResponse(body, headers=headers)


def _frame() -> Dict[str, Any]:
    return _runner().last_frame


# ------------------------------------------------------------------ the page
@app.get("/", response_class=HTMLResponse, include_in_schema=False,
         summary="The live page")
def get_root():
    """
    The shell, the floor and the three panes, over the run going on now.

    Built per request from the published frame, never cached: a cache would
    need invalidating every tick. If the shell itself cannot be built the
    failure is shown where it happened, with the traceback, and the server's
    log has it too.
    """
    import traceback

    from ..ui import live

    try:
        return _no_store(live.shell_html(_runner()), html=True)
    except HTTPException:
        raise
    except Exception:
        logging.getLogger("post_office.api").exception("the live page failed")
        return HTMLResponse(live.pane_error_html("live", traceback.format_exc()),
                            status_code=500, headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------- reading
@app.get("/state", summary="The whole runtime state, as of the last tick")
def get_state():
    return _frame().get("state") or {}


@app.get("/frame", summary="One tick of the floor, and who is inside a model call")
def get_frame():
    from ..ui import live

    return _no_store(live.frame_json(_runner()))


@app.get("/summary", summary="How the run is going")
def get_summary():
    # `running` is the world's, and the page's run line needs it to say whether
    # what it is watching is still moving. `seed`, `preset` and `tick` say
    # *which* run this is. `scenario_meta` comes from the settings, so the page,
    # the API and the run record cannot drift into different accounts of what
    # the scenario is. `dkrmm` is the monitor's digest, carried here so the
    # strip can say the state without fetching another document. `c2near` is
    # the C2-NEAR run's schedule, campaign counters and DK-RMM sequence
    # (`runner.c2near_status`), null on Normal.
    from ..ui.live import model_of

    r = _runner()
    frame = r.last_frame
    labels = dict(scenarios(model_of(r)))
    return {**(frame.get("summary") or {}),
            "run_id": frame.get("run_id"),
            "running": bool(frame.get("running")),
            # A stop asked for while a tick is in progress: the run is still
            # `running` until that tick ends, and the page should say so.
            "stopping": bool(getattr(r, "stopping", False)),
            "seed": frame.get("seed"), "preset": r.preset,
            "scenario_meta": scenario_meta(r.preset),
            "scenario_label": labels.get(r.preset, r.preset),
            "llm_agents": list(frame.get("llm_agents") or []),
            "dkrmm": monitor_digest(r.monitor),
            # The operation watch beside the monitor (`runner.operation_status`):
            # the fleet's condition as facts, on every preset.
            "operation": r.operation_status(),
            "c2near": r.c2near_status(),
            # Any study's standing (`runner.study_status`: C2-NEAR or a
            # collapse scenario, under `family`), null on Normal.
            "study": r.study_status(),
            "tick": frame.get("tick"),
            "tick_seconds": r.tick_seconds,
            # Whether this run is kept on disk as an experiment run directory
            # (`--experiment-dir`), where, its status and stop tick
            # (`runner.experiment_status`). Named `kept` because the live
            # page, which the Normal page shares, reads it.
            "kept": r.experiment_status()}


@app.get("/events", summary="The structured event log after a sequence number")
def get_events(after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=2000)):
    """
    Events with `seq > after`, oldest first. A client tailing the log asks for
    what came after the last row it drew; `after=0` is from the oldest kept.
    """
    from ..ui.views import describe

    r = _runner()
    rows = r.events(after=after, limit=limit)
    for row in rows:
        row["text"] = describe(row)
    return {"events": rows, "last_seq": rows[-1]["seq"] if rows else after,
            **r.event_counts()}


@app.get("/consultations", summary="The most recent consultations, oldest first")
def get_consultations(limit: int = Query(50, ge=1, le=500)):
    return {"consultations": _runner().consultations(limit)}


@app.get("/llm/calls", summary="The most recent model calls, oldest first")
def get_llm_calls(limit: int = Query(100, ge=1, le=2000)):
    return {"calls": _runner().llm_calls(limit)}


@app.get("/zones", summary="The unfinished parcels by zone, one row per tick")
def get_zones(after: int = Query(-1, ge=-1), limit: int = Query(5000, ge=1, le=50000)):
    """
    Rows of `observability/zone_backlog.py` with `tick > after`, oldest first:
    intake, sorting, storage, dispatch, carried, other, total (they sum to it),
    loaded_on_van, arrivals, dock_refusals, completions, returned,
    gate_refused, reconciled, unfinished_tasks. `fault_tick` is the collapse
    scenario's start (null on other presets) and `stop_at` the run's stop tick.
    """
    r = _runner()
    study = r.study_status() or {}
    fault = study.get("pressure_from") if study.get("family") in ("collapse", "onoff") else None
    return {"rows": r.zone_rows(after, limit), "fault_tick": fault, "stop_at": r.stop_at,
            "run_id": r.last_frame.get("run_id")}


@app.get("/decision-traces", summary="Decisions linked to their messages and commands")
def get_decision_traces(limit: int = Query(40, ge=1, le=2000),
                        eligible: bool = Query(True),
                        after_tick: int = Query(-1, ge=-1)):
    """
    The decision traces of `observability/decision_trace.py`, oldest first
    (the newest `limit`), only the decisions eligible for the model unless
    `eligible=false`, with the run's counts before and after the fault.
    """
    return _runner().decision_traces(limit, eligible_only=eligible, after_tick=after_tick)


@app.get("/settings", summary="Which model the experts talk to, and how much it decided")
def get_settings():
    """
    The Ollama settings in force and the identity `require_model` found, the
    experts actually on the model in this run (`llm_agents`; fewer than
    `llm_candidates` with `llm_error` saying why when the brains could not be
    built), and the brains' counters (`llm_stats`), so a run whose experts all
    fell back to their rules cannot pass for a model run.
    """
    r = _runner()
    settings = r.settings
    return {"ollama": settings.as_dict() if settings is not None else None,
            "identity": r.identity,
            "llm_agents": list(r.last_frame.get("llm_agents") or []),
            "llm_candidates": list(LLM_CANDIDATES),
            "llm_error": r.llm_error,
            "llm_stats": r.llm_stats()}


@app.get("/taxonomy", summary="The runtime communication taxonomy: channels and types")
def get_taxonomy():
    """
    `taxonomy.table()`: the channels (id, label, colour, dash, description) and
    the interaction types (type, channel, description, and the has_receiver,
    latency and model hints). The page fetches it once at load and builds its
    legend, filters and colours from it; the table in `docs/events.md` is
    checked against it by a test. A pure table, so it answers with or without
    a runner, and no-store like the other reads so a redeploy is never read
    through a cache.
    """
    from ..communication import taxonomy

    return _no_store(taxonomy.table())


# ----------------------------------------------------------------- DK-RMM
def _monitored():
    """The runtime monitor, or a 503 saying plainly that there is not one."""
    monitor = getattr(_runner(), "monitor", None)
    if monitor is None:
        raise HTTPException(status_code=503,
                            detail="this run has no runtime monitor attached")
    return monitor


@app.get("/dkrmm/state", summary="What DK-RMM makes of the run as it stands")
def get_dkrmm_state():
    """
    The current assessment, its evidence, and the counts behind it. Read-only
    in the strongest sense: the monitor never touched the run that produced
    this, and reading it does not either.
    """
    return _monitored().state()


@app.get("/dkrmm/series", summary="The recent assessments, shaped for drawing")
def get_dkrmm_series(limit: int = Query(120, ge=1, le=400)):
    """
    The monitor's own series, plus `dragon`: for each tick of it, whether
    that reading's dragon-king test held (the page shows an RCT reading
    whose test held as DK). Read from the monitor's history, by tick.
    """
    monitor = _monitored()
    series = monitor.series(limit=limit)
    held = {int(a.tick): bool(getattr(getattr(a, "dragon", None), "is_dragon", False))
            for a in list(monitor.history)}
    series["dragon"] = [held.get(int(t), False) for t in series.get("ticks") or []]
    return series


@app.get("/dkrmm/indicators", summary="The monitor's digest and the indicators")
def get_dkrmm_indicators():
    """
    The digest (state, what was observed this window, the operations block)
    and one row per indicator in the registry's order, base and derived,
    each with its value, baseline, z, status and the counts behind it.
    """
    monitor = _monitored()
    return {**monitor_digest(monitor), "indicators": indicator_rows(monitor)}


@app.get("/dkrmm/rcts", summary="Every RCT DK-RMM has detected in this run")
def get_dkrmm_rcts():
    """
    The RCT readings of the whole run, newest first, with the clock time each
    was detected. Read from the monitor's history and the event log; DK-RMM is
    not changed.
    """
    from ..observability.rct_explain import wall_clock_at

    r = _runner()
    monitor = _monitored()
    history = list(monitor.history)       # a copy: a tick may be appending
    rows = [a.as_dict() for a in history if a.state.value == "RCT"]
    clocks: Dict[int, str] = {}
    if rows:                              # no RCT, no reason to read the log
        events, _ = r.run_events()
        clocks = wall_clock_at(events, [row["tick"] for row in rows])
    return {"rcts": [{"tick": row["tick"], "detected_at": clocks.get(row["tick"], ""),
                      "severity": row.get("severity"), "kinds": row.get("kinds") or [],
                      "evidence": row.get("evidence") or [], "status": row.get("status"),
                      "dragon": bool((row.get("dragon") or {}).get("is_dragon"))}
                     for row in reversed(rows)],
            "assessments": len(history), "run_id": r.last_frame.get("run_id")}


@app.get("/dkrmm/explain", summary="What drove one DK-RMM reading")
def get_dkrmm_explain(tick: int = Query(..., ge=0)):
    """
    The events, agents and expert consultations behind the reading at `tick`,
    read back out of the run's event log (`source`: `log` from the log file,
    `memory` from the logger's in-memory tail). An explanation for a person;
    DK-RMM itself is not consulted or changed.
    """
    from ..observability.rct_explain import explain

    _monitored()
    events, source = _runner().run_events()
    return {**explain(events, tick), "source": source}


def _rct_root():
    """Where this app's runs save their RCTs, or None when it is not recording."""
    r = _runner()
    recorder = getattr(r, "recorder", None)
    if recorder is not None:
        return recorder.root
    folder = getattr(r, "_record_dir", None)
    return folder or None


@app.get("/dkrmm/rct-log", summary="Every RCT saved by this app's runs, newest first")
def get_dkrmm_rct_log():
    """
    The RCT log: each RCT saved when it was detected, by this run and earlier
    ones, read back from the record folder's `rct/`. The cause is fetched per
    RCT from /dkrmm/rct-log/item. Read only; DK-RMM is not consulted.

    `scenarios` is every scenario the app offers (`settings.scenarios`: Normal
    and the three C2-NEAR conditions, each under its own name) with its
    count, even with no RCT yet, then any other scenario found among the
    saved RCTs. `record_error` says why the recorder last failed, "" when it
    has not.
    """
    from ..config.settings import scenarios as offered
    from ..observability.rct_log import list_rcts
    from ..observability.run_record import scenario_of
    from ..ui.live import model_of

    r = _runner()
    root = _rct_root()
    recorder = getattr(r, "recorder", None)
    current = recorder.name if recorder is not None else ""
    model = model_of(r)
    rows = list_rcts(root) if root else []
    for row in rows:
        row["current"] = bool(current) and row["run"] == current
    here = scenario_of(r.preset, model)
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["scenario"]] = counts.get(row["scenario"], 0) + 1
    listed, seen = [], set()
    for preset, _ in offered(model):
        tag = scenario_of(preset, model)
        seen.add(tag["scenario"])
        listed.append({**tag, "count": counts.get(tag["scenario"], 0)})
    for row in rows:                    # a recorded experiment or an older name
        if row["scenario"] not in seen:
            seen.add(row["scenario"])
            listed.append({"scenario": row["scenario"],
                           "scenario_label": row["scenario_label"],
                           "count": counts[row["scenario"]]})
    error = getattr(r, "record_error", "") or getattr(recorder, "error", "") or ""
    return {"rcts": rows, "current_run": current, "recording": bool(root),
            "folder": str(root) if root else "",
            "current_scenario": here["scenario"],
            "current_scenario_label": here["scenario_label"],
            "scenarios": listed, "record_error": error}


@app.get("/dkrmm/rct-log/item", summary="One saved RCT with the cause saved with it")
def get_dkrmm_rct_log_item(run: str = Query(...), tick: int = Query(..., ge=0)):
    from ..observability.rct_log import load_rct

    root = _rct_root()
    if not root:
        raise HTTPException(status_code=404, detail="This app is not saving RCTs.")
    try:
        body = load_rct(root, run, tick)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if body is None:
        raise HTTPException(status_code=404, detail=f"No RCT saved for {run} at tick {tick}.")
    return body


class Judgement(BaseModel):
    """A person's verdict on what the monitor discovered."""

    by: str = Field("operator", max_length=80,
                    description="who is answering for this")
    note: str = Field("", max_length=500,
                      description="why, in their own words")


def _judge(verdict: str, patch: Judgement, nothing: str) -> Dict[str, Any]:
    """
    The monitor's own `validate`, `activate` or `dismiss`, then the run record
    kept up to date. 409 when there is nothing to decide.

    Without the step lock, as in the source: a verdict is a few attribute
    assignments on the current reading and must not wait for a tick that is
    inside a consultation. The monitor is the runner's at the moment of
    deciding: if a reset replaced it meanwhile, the verdict is asked of the
    new one (409 while it has nothing), never left on the discarded run.
    """
    r = _runner()
    while True:
        monitor = _monitored()
        decided = getattr(monitor, verdict)(by=patch.by, note=patch.note)
        if r.monitor is monitor:
            break
    if decided is None:
        raise HTTPException(status_code=409, detail=nothing)
    r.record_gate()
    return decided.as_dict()


@app.post("/dkrmm/validate", summary="A person agrees with the current reading")
def post_dkrmm_validate(patch: Judgement):
    """
    The gate the model is built around.

    A monitor that could confirm its own findings would be a monitor whose
    findings mean whatever it says they mean. So this is the one thing in
    DK-RMM that cannot happen without a person, and it is an HTTP endpoint
    rather than a rule precisely so that somebody has to reach for it.
    """
    return _judge("validate", patch, "there is nothing assessed yet to validate")


@app.post("/dkrmm/activate", summary="A validated reading is being acted on")
def post_dkrmm_activate(patch: Judgement):
    return _judge("activate", patch, "only a validated finding can be activated")


@app.post("/dkrmm/dismiss", summary="A person disagrees with the current reading")
def post_dkrmm_dismiss(patch: Judgement):
    """Kept rather than deleted: a false positive is evidence about the model."""
    return _judge("dismiss", patch, "there is nothing assessed yet to dismiss")


# ---------------------------------------------------- the trajectory, RCT log
@app.get("/ui/trajectory", response_class=HTMLResponse, include_in_schema=False,
         summary="The live run's events, in order")
def get_ui_trajectory(limit: int = Query(9000, ge=100, le=60000),
                      run_id: str = Query("", description="accepted for the source's "
                                                          "links; only the live run "
                                                          "is served"),
                      archived: bool = Query(False, description="accepted and "
                                                                "ignored: the live "
                                                                "run is never "
                                                                "finished")):
    """
    The Trajectory tab: the newest events the run's logger holds, on the
    source's trajectory page, which then follows the run. `run_id` and
    `archived` are accepted as the source's page took them; there is no store
    of finished runs, so a `run_id` other than the live one answers 404 and
    the page is never marked finished.
    """
    from ..ui import live

    r = _runner()
    live_run = r.last_frame.get("run_id") or ""
    if run_id and run_id != live_run:
        raise HTTPException(status_code=404,
                            detail=f"run {run_id!r} is not the live run ({live_run!r}); "
                                   "only the live run's trajectory is served")
    return _no_store(live.trajectory_html(r, limit), html=True)


@app.get("/ui/trajectory/tail", include_in_schema=False,
         summary="Rows logged since an id, as the trajectory page holds them")
def get_trajectory_tail(after_id: int = Query(0, ge=0),
                        started: str = Query("", description="the timestamp "
                                                             "the page opened "
                                                             "with"),
                        limit: int = Query(800, ge=1, le=2000),
                        run_id: str = Query("", description="the run the page "
                                                            "was opened on")):
    """
    What the trajectory page polls while it is following the run:
    `{rows, last_id, total}` over the logger's events after `after_id`, each
    row built by the same `views.trajectory_row` the page was folded with, so
    a live row reads exactly like the same row folded a minute later.

    A page opened on an earlier run is answered 409, never with the next run's
    rows (a reset starts `seq` again at 1): when its `run_id` is not the live
    run, or when its `started` is earlier than the live run's first event
    (seq 1, while the logger still holds it). The page then stops following
    and says the run has ended.
    """
    from datetime import datetime

    from ..ui import views

    r = _runner()
    live_run = r.last_frame.get("run_id") or ""
    if run_id and run_id != live_run:
        raise HTTPException(status_code=409, detail=(
            f"run {run_id} has ended; the live run is {live_run}"))
    first = r.events(after=0, limit=1)
    if started and first and first[0]["seq"] == 1:
        try:
            earlier = (datetime.fromisoformat(started)
                       < datetime.fromisoformat(first[0]["wall_clock"]))
        except (TypeError, ValueError):
            earlier = False
        if earlier:
            raise HTTPException(status_code=409, detail=(
                f"the page began at {started}, before the live run {live_run} did; "
                "that run has ended"))
    return _no_store(views.trajectory_tail(r, after_id=after_id,
                                           started=started, limit=limit))


@app.get("/ui/rcts", response_class=HTMLResponse, include_in_schema=False,
         summary="The RCT log: every detected RCT and its cause")
def get_ui_rcts():
    from ..ui import live

    return _no_store(live.rcts_html(), html=True)


# ------------------------------------------------------------------- writing
@app.post("/simulation/start", summary="Set the objective going and begin ticking")
def start_simulation():
    return {"ok": True, "snapshot": _runner().start()}


@app.post("/simulation/stop", summary="Stop after the tick in progress")
def stop_simulation(reason: str = "stopped over the API"):
    return {"ok": True, "snapshot": _runner().stop(reason)}


@app.post("/simulation/reset", summary="Rebuild the ecosystem")
def reset_simulation(seed: Optional[int] = Query(None, ge=0),
                     preset: Optional[str] = Query(None)):
    """
    Put the run back to tick zero, with fresh brains (and the model checked
    again).

    With no arguments it is the same day again: same seed, same scenario.
    `seed` is a different day. `preset` names the scenario: `default`
    (NORMAL), one of the C2-NEAR presets (`c2near-n`, `c2near-c0`,
    `c2near-c2`, the last of which needs the experts on the model) or one of
    the collapse scenarios (`ms-drop`, `ms-delay`, `cs-starve`,
    `cs-partition`, which run on rules or on the model alike); anything
    else is refused, and so is a C2-NEAR switch the runner cannot make (400
    with its reason; the run goes on as it was).
    """
    presets = known_presets()
    if preset is not None and preset not in presets:
        raise HTTPException(
            status_code=400,
            detail=f"no scenario called {preset!r}; there is "
                   f"{', '.join(sorted(presets))}")
    try:
        snapshot = _runner().reset(seed=seed, preset=preset or "")
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "snapshot": snapshot}


@app.post("/simulation/speed", summary="Change how fast the clock turns")
def set_speed(patch: SpeedPatch):
    """
    Seconds of wall clock per simulated tick. The simulation itself is
    unchanged: the same run at 1x and at 20x produces the same events in the
    same order, because nothing in it is timed against the wall.
    """
    r = _runner()
    r.tick_seconds = float(patch.tick_seconds)
    return {"ok": True, "tick_seconds": r.tick_seconds}


# ----------------------------------------------------------------- streaming
@app.websocket("/ws")
async def stream(socket: WebSocket):
    """
    Live events and tick snapshots.

    The bridge between two worlds: the simulation ticks on a plain thread and
    the socket lives in an event loop, so events are dropped into an
    `asyncio.Queue` from the thread and drained here. The queue is bounded --
    a client that cannot keep up loses events rather than growing the server's
    memory until something falls over. The greeting carries the state as of
    the last published tick.
    """
    await socket.accept()
    r = runner
    if r is None:
        await socket.close(code=1013)
        return
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    def on_event(payload: Dict[str, Any]) -> None:
        loop.call_soon_threadsafe(_offer, queue, payload)

    remove = r.add_listener(on_event)
    try:
        await socket.send_json({"type": "hello",
                                "state": r.last_frame.get("state") or {}})
        while True:
            payload = await queue.get()
            await socket.send_json(payload)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        remove()


def _offer(queue: "asyncio.Queue", payload: Dict[str, Any]) -> None:
    try:
        queue.put_nowait(payload)
    except asyncio.QueueFull:
        pass          # a slow client loses events; it does not slow the run


def websocket_support() -> str:
    """
    The WebSocket implementation uvicorn will use, or "" when it has none.

    Worth checking at startup rather than discovering from a browser. Plain
    `pip install uvicorn` has no WebSocket support, and what uvicorn does about
    that is answer 404 to the handshake -- so the socket silently never opens.
    The page polls as well, so it still fills in; the live push does not.
    """
    for name in ("websockets", "wsproto"):
        try:
            __import__(name)
            return name
        except ImportError:
            continue
    return ""


def serve(host: str = "127.0.0.1", port: int = 8000,
          seed: int = 1, tick_seconds: float = 0.25,
          config: Optional[Dict[str, Any]] = None,
          log_path: Optional[str] = None,
          llm_agents: Sequence[str] = (),
          start: bool = False,
          preset: str = "default",
          rules_only: bool = False,
          settings: Any = None,
          record_dir: Optional[Union[Path, str]] = None,
          experiment_dir: Optional[Union[Path, str]] = None,
          stop_at: Optional[int] = None) -> None:     # pragma: no cover
    """
    Run the server. Called by `python main.py --api`.

    The runner is built here: in model mode it verifies the configured model
    (`require_model`, with `settings`, or the environment's when None) before
    the brains are built, and a model that has gone missing means a run served
    rules-only with `llm_error` saying why. `main.py` checks first and refuses
    to start instead. `rules_only` puts every expert on its rules.

    `start` decides whether the simulation is already ticking when the first
    page loads. It defaults to False, so opening the app shows the floor laid
    out at tick zero and waits to be told to go.

    `record_dir` is where DK-RMM's record and each RCT are kept
    (`<record_dir>/dkrmm/`, `<record_dir>/rct/`); None records nothing.
    """
    import uvicorn

    from ..crew.console import quiet

    with quiet():
        built = SimulationRunner(seed=seed, config=config, log_path=log_path,
                                 run_id="api", tick_seconds=tick_seconds,
                                 llm_agents=llm_agents, preset=preset,
                                 settings=settings, rules_only=rules_only,
                                 record_dir=record_dir, experiment_dir=experiment_dir,
                                 stop_at=stop_at)
        previous = use(built)
        if previous is not None:
            previous.close()
        try:
            if built.llm_error:
                print(f"\n  The experts are on their rules: {built.llm_error}\n")
            if start:
                built.start()
            if not websocket_support():
                print("\n  The event socket will not work: uvicorn has no WebSocket\n"
                      "  implementation installed, and answers 404 to the handshake.\n"
                      "      pip install \"uvicorn[standard]\"\n"
                      "  The page still works -- it polls -- but WS /ws will not.\n")
            uvicorn.run(app, host=host, port=port, log_level="info")
        finally:
            use(None)
            built.close()
