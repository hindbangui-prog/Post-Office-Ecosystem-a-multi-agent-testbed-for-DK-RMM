# post_office.ui

This package is the browser front end: three Python modules with no classes, and four HTML pages they serve. `live` builds the pages from what `SimulationRunner` published: `shell_html` fills `live.html` (the shell at `GET /`, with its run line, controls, expert roster and seven panes), `robots_html` fills `floor.html` with the building and the first frame and appends the `LIVE_FLOOR` script that keeps it polling `/frame`, `trajectory_html` fills `trajectory.html` from `views.trajectory_data`, and `rcts_html` returns `rcts.html` unchanged. `views` holds the data shapes: `static_of` and `frame_of`, which the runner calls once per ecosystem and after every tick under its lock, plus `describe` and the trajectory fold shared by the first page load and its live tail. `feed` holds the rules of the Runtime communication pane as pure functions over event dicts, mirrored line for line by the JavaScript in `live.html` so they can be tested without a browser. The pages talk back to `api.server` only through fetch, POST and the `/ws` socket, and `live.html` carries the other three pages as iframes (the floor by `srcdoc`, the trajectory and the RCT log by `src`). The package is imported only by api (runner and server) and reads `communication.taxonomy`, `dkrmm.indicators` and `api.digest`. The rule to know: the page builders in `live` never read the live ecosystem, only `runner.last_frame`, `runner.static` and the runner's lock-free accessors, so a page is served at once even while a tick is blocked in a consultation.

## Class diagram

```mermaid
classDiagram
  direction TB
  class live {
    <<module>>
    +str LIVE_FLOOR
    +shell_html(runner) str
    +robots_html(runner) str
    +frame_json(runner) dict
    +consultations_html(runner, limit) str
    +llm_calls_html(runner, limit) str
    +dkrmm_html(runner, limit) str
    +gate_html(current) str
    +trajectory_html(runner, limit) str
    +rcts_html() str
    +model_of(runner) str
    +pane_error_html(title, detail) str
    ...
  }
  class views {
    <<module>>
    +list ROBOT_STATES
    +list PARCEL_STATES
    +dict WHAT_THEY_DO
    +static_of(eco, ticks, preset) dict
    +frame_of(eco, tick) dict
    +replay_data(static, summary, frames) dict
    +describe(event, limit) str
    +event_type_for(category, topic) str
    +trajectory_row(event, base) list
    +trajectory_tail(runner, after_id, started, limit) dict
    +trajectory_data(runner, limit) dict
    +dkrmm_catalogue() list
    ...
  }
  class feed {
    <<module>>
    +sender_of(event) str
    +receiver_of(event) str
    +edge_of(event) tuple
    +request_text_of(event) str
    +pair(rows) dict
    +latency_of(event, response) dict
    +model_of(event, by_consultation, configured_model) str
    +chain_keys_of(event) set
    +chain_select(rows, seed_event) set
    +feed_row(event, paired_response, ...) dict
    ...
  }
  class page_live["live.html"] {
    <<page>>
    +slots SCENARIOS FLOOR CONSULTATIONS LLM_CALLS DKRMM RUN_ID
    +tabs floor, consultations, llm, dkrmm, feed, trajectory, rcts
    +GET /summary /frame /settings /taxonomy /events
    +GET /consultations /llm/calls
    +GET /dkrmm/state series indicators rcts explain
    +POST /simulation/start stop reset speed
    +POST /dkrmm/validate activate dismiss
    +WS /ws reads event and reset messages
  }
  class page_floor["floor.html"] {
    <<page>>
    +slot RUN_DATA
    +floor, interaction graph, robot cards
    +listens for postMessage from live.html
    +GET /frame every 400 ms, via LIVE_FLOOR
    +GET /summary after a reset, via LIVE_FLOOR
  }
  class page_trajectory["trajectory.html"] {
    <<page>>
    +slot TRAJECTORY_DATA
    +GET /ui/trajectory/tail every 1 s
  }
  class page_rcts["rcts.html"] {
    <<page>>
    +GET /dkrmm/rct-log
    +GET /dkrmm/rct-log/item
  }
  class server["api.server"]
  <<external>> server
  class Runner["api.SimulationRunner"]
  <<external>> Runner
  class digest["api.digest"]
  <<external>> digest
  class taxonomy["communication.taxonomy"]
  <<external>> taxonomy
  class indicators["dkrmm.indicators"]
  <<external>> indicators

  server ..> live : GET / , /frame, /ui/trajectory, /ui/rcts
  server ..> views : describe, trajectory_tail
  Runner ..> views : static_of, frame_of
  live ..> Runner : reads last_frame, static, accessors
  live ..> views : replay_data, trajectory_data
  live ..> digest : monitor_digest, indicator_rows
  live ..> page_live : shell_html fills
  live ..> page_floor : robots_html fills, appends LIVE_FLOOR
  live ..> page_trajectory : trajectory_html fills
  live ..> page_rcts : rcts_html serves as is
  feed ..> views : describe
  feed ..> taxonomy : TYPES
  views ..> taxonomy : classify
  views ..> indicators : INDICATORS
  page_live --> page_floor : iframe srcdoc, postMessage
  page_live --> page_trajectory : iframe src /ui/trajectory
  page_live --> page_rcts : iframe src /ui/rcts
  page_live ..> feed : same rules mirrored in JS
  page_live ..> server : fetch, POST, WS
  page_floor ..> server : fetch
  page_trajectory ..> server : fetch
  page_rcts ..> server : fetch
```

![ui class diagram](img/ui.svg)

## Classes

The package defines no classes. Its Python modules are drawn as `<<module>>` boxes and its HTML files as `<<page>>` boxes; a page box lists the data slot the server fills and the routes the page calls, and is a page, not a class.

| Class | Module | Role |
|---|---|---|
| `live` | `live.py` | `<<module>>`: builds and serves the pages (`shell_html`, `robots_html`, `trajectory_html`, `rcts_html`), the `/frame` payload (`frame_json`), the server-side fragments of the Consultations, Ollama calls and DK-RMM panes (`consultations_html`, `llm_calls_html`, `dkrmm_html`, `gate_html`, `consultation_row`, `llm_call_row`), `model_of`, `scenario_options`, and the failure fragments (`failed_pane_html`, `pane_error_html`). |
| `views` | `views.py` | `<<module>>`: the data behind each view: `static_of`, `frame_of`, `replay_data`, `describe`, the trajectory fold (`event_type_for`, `trajectory_row`, `trajectory_tail`, `trajectory_data`) and `dkrmm_catalogue`, plus the interned state lists and `WHAT_THEY_DO`. |
| `feed` | `feed.py` | `<<module>>`: the Runtime communication feed's rules: sender, receiver and edge of a row, request, response, reply and decision texts, request/reply pairing (`pair_key_of`, `reply_to_of`, `pair`), latency, model attribution (`models_by_consultation`, `model_of`), chains (`chain_keys_of`, `chain_select`, `chain_select_by_id`) and `feed_row`. |
| `live.html` | `live.html` | `<<page>>`: the shell at `GET /`; polls the read routes, posts the controls and DK-RMM verdicts, listens on `/ws`, and holds the floor, trajectory and RCT log pages in iframes. |
| `floor.html` | `floor.html` | `<<page>>`: the floor, interaction graph and robot cards, carried in the shell as `srcdoc`; follows the run through the `LIVE_FLOOR` script that `live.robots_html` appends. |
| `trajectory.html` | `trajectory.html` | `<<page>>`: the Trajectory tab at `GET /ui/trajectory`; tails new rows from `/ui/trajectory/tail`. |
| `rcts.html` | `rcts.html` | `<<page>>`: the RCT log tab at `GET /ui/rcts`; reads `/dkrmm/rct-log` and `/dkrmm/rct-log/item` itself. |
