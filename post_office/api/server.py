"""
FastAPI over the running ecosystem, plus a WebSocket for the event stream.

Spec 16, and nothing else:

    GET  /                       the live page
    GET  /state                  the whole runtime state, as of the last tick
    GET  /frame                  the floor's frame, and who is inside a model call
    GET  /summary                how the run is going, with the monitor's digest
    GET  /events?after=&limit=   the event log after a sequence number
    GET  /consultations?limit=   the most recent consultations
    GET  /llm/calls?limit=       the most recent model calls, as the wire saw them
    GET  /settings               Ollama settings, identity, experts on the model
    GET  /dkrmm/state            DK-RMM's current assessment
    GET  /dkrmm/series?limit=    its recent assessments, shaped for drawing
    GET  /dkrmm/indicators       its digest and the twelve indicators
    POST /simulation/start|stop|reset|speed
    WS   /ws                     every event, live, and a tick payload per tick

Every read answers from what the runner published (`runner.last_frame`) or
from an accessor that does not take the step lock (`consultations`,
`llm_calls`, `llm_stats`, `busy`, `events`, `monitor.state()`/`series()`). A
tick with the experts on the model can last as long as a consultation, and a
read that waited for it would freeze the page for that long; reading the
published frame instead means a reader may see the run one tick behind and
never sees a tick half done. The writes go through the runner, which takes the
lock as the loop does.

Adapted from the source `post_office/api/server.py`: the reads, the controls,
the socket and `serve` are kept; the routes of the source's removed scenario
families, its settings and providers panel, the trace, sessions, history and
replay are not part of this prototype and are not served.

    python main.py --api            the seven experts on Ollama (`require_model` first)
    python main.py --api --rules    every expert on its rules
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Sequence

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

from ..config.settings import LLM_CANDIDATES, PRESETS, SCENARIOS, scenario_meta
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
    # strip can say the state without fetching another document.
    r = _runner()
    frame = r.last_frame
    labels = dict(SCENARIOS)
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
            "tick": frame.get("tick"),
            "tick_seconds": r.tick_seconds}


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
    return _monitored().series(limit=limit)


@app.get("/dkrmm/indicators", summary="The monitor's digest and the twelve indicators")
def get_dkrmm_indicators():
    monitor = _monitored()
    return {**monitor_digest(monitor), "indicators": indicator_rows(monitor)}


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
    `seed` is a different day. `preset` names the scenario, and Prototype II
    has one, `default` (NORMAL); anything else is refused.
    """
    if preset is not None and preset not in PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"no scenario called {preset!r}; there is "
                   f"{', '.join(sorted(PRESETS))}")
    return {"ok": True, "snapshot": _runner().reset(seed=seed, preset=preset or "")}


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
          settings: Any = None) -> None:     # pragma: no cover
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
    """
    import uvicorn

    from ..crew.console import quiet

    with quiet():
        built = SimulationRunner(seed=seed, config=config, log_path=log_path,
                                 run_id="api", tick_seconds=tick_seconds,
                                 llm_agents=llm_agents, preset=preset,
                                 settings=settings, rules_only=rules_only)
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
