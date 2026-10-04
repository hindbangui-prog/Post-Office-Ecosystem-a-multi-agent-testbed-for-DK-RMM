# post_office.observability

Tracing scope and the record of what DK-RMM made of a run, kept beside the simulation and never fed back into it. `context` holds the decision in scope in a `ContextVar`: `BaseAgent` wraps each decision in `inside(decision_id, correlation_id, agent_id)` and `current_call()` reads it back. `rct_explain.explain` reads the event window behind one DK-RMM reading and lays out the trouble events by evidence kind, topic and agent, the expert consultations linked to them (strongly by task or parcel, weakly by robot) and the baseline windows, using `events_from_log` to read the JSON-lines log incrementally. `run_record.RunRecorder`, owned by `api.SimulationRunner`, rewrites the run's DK-RMM record atomically at each new reading through `dkrmm.record.build_record` and saves each RCT with its explanation, and `rct_log` lists and loads those RCT files for `api.server`. It depends on `dkrmm.monitor` for the window constants, `communication.topics` for the trouble topics and `config.settings` for the scenario label. The rule to know: everything here is read-only with respect to DK-RMM and the simulation; its windows, thresholds and states are read, never changed, and a failed write sets `RunRecorder.error` instead of stopping the run.

## Class diagram

```mermaid
---
config:
  layout: elk
---
classDiagram
  direction TB
  class BaseAgent["agents.BaseAgent"]
  <<external>> BaseAgent
  class SimulationRunner["api.SimulationRunner"]
  <<external>> SimulationRunner
  class dkrmmmonitor["dkrmm.monitor"]
  <<external>> dkrmmmonitor
  class dkrmmrecord["dkrmm.record"]
  <<external>> dkrmmrecord
  class topics["communication.topics"]
  <<external>> topics
  class configsettings["config.settings"]
  <<external>> configsettings

  class context {
    <<module>>
    +dict EMPTY
    +current_call() dict
    +inside(call_id, correlation_id, agent_id) contextmanager
  }
  class rct_explain {
    <<module>>
    +tuple KIND_ORDER
    +dict KIND_ABOUT
    +kinds_of(event) list
    +explain(events, tick, window, every, baseline) dict
    +events_from_log(path, run_id) list
    +wall_clock_at(events, ticks) dict
  }
  class rct_log {
    <<module>>
    +list_rcts(root) list
    +load_rct(root, run, tick) Optional~dict~
  }
  class run_record {
    <<module>>
    +scenario_of(preset, model) dict
  }
  class RunRecorder {
    +Path root
    +str run_id
    +str scenario
    +Optional~int~ seed
    +dict config
    +dict scenario_tag
    +str name
    +Path record_path
    +Path rct_dir
    +str error
    +update(monitor, eco) None
    +write(monitor) None
    ...
  }

  BaseAgent ..> context : inside
  SimulationRunner *-- RunRecorder : recorder
  RunRecorder ..> dkrmmmonitor : reads DKRMM.history
  RunRecorder ..> dkrmmrecord : build_record
  RunRecorder ..> rct_explain : explain, events_from_log
  RunRecorder ..> run_record : scenario_of
  rct_log ..> run_record : scenario_of
  run_record ..> configsettings : scenario_label
  rct_explain ..> topics : trouble topics
  rct_explain ..> dkrmmmonitor : WINDOW, EVERY, BASELINE
```

![observability class diagram](img/observability.svg)

## Classes

| Class | Module | Role |
|---|---|---|
| `RunRecorder` | `run_record.py` | Keeps one run's DK-RMM record and its RCT files up to date on disk, once per tick and after a gate decision. |
| `context` (module) | `context.py` | `current_call`, `inside`: the decision or sub-agent invocation in scope for tracing. |
| `rct_explain` (module) | `rct_explain.py` | `kinds_of`, `explain`, `events_from_log`, `wall_clock_at`: what drove a DK-RMM reading, read back from the event log. |
| `rct_log` (module) | `rct_log.py` | `list_rcts`, `load_rct`: every saved RCT, read back from disk. |
| `run_record` (module) | `run_record.py` | `scenario_of`: the scenario name and label a preset runs under. |
