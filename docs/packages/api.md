# post_office.api

This package serves one running simulation over HTTP and a WebSocket. `SimulationRunner` owns the `PostOfficeEcosystem` (built by `simulation.build` and rebuilt by `reset`), a `SystemState` view of it, the `DKRMM` monitor attached beside the run and, with a `record_dir`, an observability `RunRecorder`; it ticks the ecosystem on a background thread under one coarse lock and after every tick publishes `last_frame`, a plain dictionary the reads are answered from. The `server` module is the FastAPI app: its routes read `last_frame` or the runner's lock-free accessors, send the controls (start, stop, reset, speed) through the runner, pass a person's DK-RMM verdict (a `Judgement` body) to the monitor, serve the ui pages and relay the event stream on `/ws`. `digest` condenses the monitor's state into the one-line strip at the top of the page and the twelve indicator rows. The package depends on simulation, state, config, crew, dkrmm, observability, `communication.taxonomy` and ui, and is started by `main.py --api`, which calls `serve`. The rule to know: request handlers never take the step lock, so a reader may see the run one tick behind but never a tick half done, and a tick that is inside a model consultation never freezes the page.

## Class diagram

```mermaid
classDiagram
  direction TB
  class server {
    <<module>>
    +FastAPI app
    +SimulationRunner runner
    +use(new) SimulationRunner
    +serve(host, port, seed, tick_seconds, ...) None
    +websocket_support() str
    +GET / /state /frame /summary
    +GET /events /consultations /llm/calls /settings /taxonomy
    +GET /dkrmm/state series indicators rcts explain
    +GET /dkrmm/rct-log /dkrmm/rct-log/item
    +POST /dkrmm/validate activate dismiss
    +GET /ui/trajectory /ui/trajectory/tail /ui/rcts
    +POST /simulation/start stop reset speed
    +WS /ws
  }
  class SpeedPatch {
    +float tick_seconds
  }
  class Judgement {
    +str by
    +str note
  }
  class digest {
    <<module>>
    +monitor_digest(monitor) dict
    +indicator_rows(monitor) list
  }
  class SimulationRunner {
    +float tick_seconds
    +str preset
    +PostOfficeEcosystem eco
    +SystemState state
    +DKRMM monitor
    +RunRecorder recorder
    +dict last_frame
    +bool stopping
    +str llm_error
    -RLock _lock
    +start() dict
    +stop(reason) dict
    +reset(seed, config, preset) dict
    +step(ticks) dict
    +events(after, limit) list
    +event_counts() dict
    +run_events() tuple
    +add_listener(fn) Callable
    +record_gate() None
    +close() None
    ...
  }
  class BaseModel["pydantic.BaseModel"]
  <<external>> BaseModel
  class Ecosystem["simulation.PostOfficeEcosystem"]
  <<external>> Ecosystem
  class SystemState["state.SystemState"]
  <<external>> SystemState
  class DKRMM["dkrmm.DKRMM"]
  <<external>> DKRMM
  class RunRecorder["observability.RunRecorder"]
  <<external>> RunRecorder
  class ui["ui.live and ui.views"]
  <<external>> ui

  BaseModel <|-- SpeedPatch
  BaseModel <|-- Judgement
  server o-- SimulationRunner : runner, set by use()
  server ..> SpeedPatch : POST /simulation/speed body
  server ..> Judgement : verdict body
  server ..> digest : monitor_digest, indicator_rows
  server ..> ui : shell_html, frame_json, trajectory_html, rcts_html, trajectory_tail
  SimulationRunner *-- Ecosystem : eco, build() and reset()
  SimulationRunner *-- SystemState : state
  SimulationRunner *-- DKRMM : monitor, beside the run
  SimulationRunner *-- RunRecorder : recorder, with record_dir
  SimulationRunner ..> ui : static_of, frame_of
  digest ..> DKRMM : state()
```

![api class diagram](img/api.svg)

## Classes

| Class | Module | Role |
|---|---|---|
| `SimulationRunner` | `runner.py` | Owns the ecosystem, the tick thread and the lock; starts, stops, resets and steps the run, attaches DK-RMM and the run recorder, publishes `last_frame` and relays events to WebSocket listeners. |
| `server` | `server.py` | `<<module>>`: the FastAPI `app`, the served `runner` (`use`), `serve` and `websocket_support`, and the 27 routes, one handler function each (`get_root`, `get_state`, ..., `set_speed`, `stream`). |
| `SpeedPatch` | `server.py` | Pydantic body of `POST /simulation/speed`: `tick_seconds`, bounded between the 512x floor and 10 s. |
| `Judgement` | `server.py` | Pydantic body of `POST /dkrmm/validate`, `/activate` and `/dismiss`: who answers and why. |
| `digest` | `digest.py` | `<<module>>`: `monitor_digest`, the current assessment in a few fields (with `attached: false` when there is no monitor), and `indicator_rows`, the twelve indicators with their descriptions, values and z-scores. |
