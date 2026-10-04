# post_office.dkrmm

This package is DK-RMM, the Dragon-King Runtime Monitoring Model: an independent observer that reads the event stream and names the collective operational state of the ecosystem. `DKRMM.attach` subscribes `observe` to the ecosystem's `EventLogger`, the monitor keeps a moving window of events, and every `EVERY` ticks `assess` computes the twelve `BehaviouralIndicators` (`compute_indicators`), scores each against its own baseline with `zscore`, folds them into a severity series and reads `Precursors` (critical slowing down) and `DragonKing` (the rank-ordering tail test) from that series. The rules in `_classify` turn independent evidence kinds, their persistence and their spread across acting agents into an `Assessment` carrying an `OperationalState` (STABLE, DEVIATING, UNSTABLE, RCT, RECOVERY) and a `DiscoveryStatus` that only a person moves on, through `validate`, `activate` or `dismiss`. The `record` module transposes the monitor's history into per-indicator series, state transitions and a timeline of firsts, and compares a perturbed run with its matched control. It is used by api (`SimulationRunner`, `digest`), observability (`run_record`, `rct_explain`), `ui.views` and `main.py`, and depends only on `communication.topics` and on the ecosystem's logger, roster and clock. The invariant: it observes only; it is not on the bus, never sends a message, never writes to the world, and no agent or simulation module imports it, so removing it changes nothing about a run.

## Class diagram

```mermaid
classDiagram
  direction TB
  class DKRMM {
    +int every
    +int window
    +int baseline
    +list~Assessment~ history
    +Assessment current
    -deque _events
    -dict _series
    -deque _severity
    +attach() DKRMM
    +close() None
    +observe(event) None
    +tick(now) Assessment
    +assess(now) Assessment
    +validate(by, note) Assessment
    +activate(by, note) Assessment
    +dismiss(by, note) Assessment
    +series(limit) dict
    +state() dict
  }
  class monitor {
    <<module>>
    +int EVERY = 20
    +int WINDOW = 60
    +int BASELINE = 24
    +float DEVIATION_Z = 2.0
    +int UNSTABLE_KINDS = 2
    +int RCT_KINDS = 3
    +float RCT_PROPAGATION = 0.5
    +int PERSISTENT = 3
    +int MIN_ACTIVITY = 24
    +dict EVIDENCE
    ...
  }
  class Assessment {
    <<dataclass>>
    +int tick
    +OperationalState state
    +OperationalState previous
    +DiscoveryStatus status
    +BehaviouralIndicators indicators
    +dict z
    +list kinds
    +float severity
    +Precursors precursors
    +DragonKing dragon
    +str decided_by
    ...
    +as_dict() dict
  }
  class OperationalState {
    <<enumeration>>
    STABLE
    DEVIATING
    UNSTABLE
    RCT
    RECOVERY
  }
  class DiscoveryStatus {
    <<enumeration>>
    DISCOVERED
    VALIDATED
    ACTIVE
    DISMISSED
  }
  class states {
    <<module>>
    +tuple ESCALATED
  }
  class BehaviouralIndicators {
    <<dataclass>>
    +int ticks
    +int events
    +int acting_agents
    +int roster
    +float message_frequency
    +float guardrail_events
    +float retry_frequency
    +float propagation_across_agents
    +dict counts
    ...
    +values() dict
    +as_dict() dict
  }
  class indicators {
    <<module>>
    +tuple INDICATORS
    +tuple INDICATOR_NAMES
    +compute_indicators(events, ticks, roster, created, persistence) BehaviouralIndicators
  }
  class Precursors {
    <<dataclass>>
    +int points
    +float variance
    +float autocorrelation
    +float skewness
    +bool variance_rising
    +bool autocorrelation_rising
    +bool skewness_rising
    +bool enough
    +int rising
    +bool slowing_down
    +as_dict() dict
  }
  class DragonKing {
    <<dataclass>>
    +int points
    +float observed
    +float expected
    +float ratio
    +float slope
    +float fit_quality
    +bool is_dragon
    +bool enough
    +list plot
    +as_dict() dict
  }
  class signals {
    <<module>>
    +int MIN_POINTS = 12
    +float DRAGON_FACTOR = 2.0
    +precursors(series, min_points) Precursors
    +dragon_king(series, factor, tail_points, min_points) DragonKing
    +zscore(value, history) float
  }
  class record {
    <<module>>
    +int FORMAT = 1
    +series_of(history) dict
    +states_of(history) list
    +transitions_of(states) list
    +timeline_of(states, series, uptake, perturbation, changes, deviation_z) dict
    +build_record(run_id, monitor, ...) dict
    +compare_records(perturbed, control) dict
    +write_record(record, path) str
  }
  class Ecosystem["simulation.PostOfficeEcosystem"]
  <<external>> Ecosystem
  class EventLogger["communication.EventLogger"]
  <<external>> EventLogger
  class Event["communication.Event"]
  <<external>> Event
  class topics["communication.topics"]
  <<external>> topics

  DKRMM o-- Ecosystem : _eco, reads roster and clock
  DKRMM ..> EventLogger : subscribe(observe)
  DKRMM "1" o-- "*" Event : _events window
  DKRMM "1" *-- "*" Assessment : history, current
  DKRMM ..> monitor : thresholds
  DKRMM ..> indicators : compute_indicators
  DKRMM ..> signals : zscore, precursors, dragon_king
  DKRMM ..> states : ESCALATED
  Assessment --> OperationalState : state, previous
  Assessment --> DiscoveryStatus : status
  Assessment *-- BehaviouralIndicators : indicators
  Assessment *-- Precursors : precursors
  Assessment *-- DragonKing : dragon
  states ..> OperationalState : DEVIATING, UNSTABLE, RCT
  indicators ..> BehaviouralIndicators : returns
  indicators ..> topics : RETRY, REFUSAL, SWITCH, TROUBLE
  signals ..> Precursors : returns
  signals ..> DragonKing : returns
  record ..> DKRMM : reads history
  record ..> indicators : INDICATOR_NAMES
  record ..> states : ESCALATED, OperationalState
```

![dkrmm class diagram](img/dkrmm.svg)

## Classes

| Class | Module | Role |
|---|---|---|
| `DKRMM` | `monitor.py` | The monitor: subscribes to the event log, assesses a window every `EVERY` ticks, keeps the assessment history and exposes the human gate (`validate`, `activate`, `dismiss`) and the `state` / `series` reads. |
| `monitor` | `monitor.py` | `<<module>>`: the thresholds (`EVERY`, `WINDOW`, `BASELINE`, `DEVIATION_Z`, `UNSTABLE_KINDS`, `RCT_KINDS`, `RCT_PROPAGATION`, `PERSISTENT`, `MIN_ACTIVITY`, `HISTORY`) and `EVIDENCE`, the grouping of indicators into evidence kinds. |
| `Assessment` | `monitor.py` | One reading: state, previous state, discovery status, indicators, z-scores, evidence kinds, severity, precursors, dragon-king test, and who decided it. |
| `OperationalState` | `states.py` | The collective condition the monitor can name: STABLE, DEVIATING, UNSTABLE, RCT, RECOVERY. |
| `DiscoveryStatus` | `states.py` | How far a finding has come through the human gate: DISCOVERED, VALIDATED, ACTIVE, DISMISSED. |
| `states` | `states.py` | `<<module>>`: `ESCALATED`, the three states above STABLE in order of severity. |
| `BehaviouralIndicators` | `indicators.py` | One window's twelve indicator values (rates per tick and shares of the population) plus the raw counts behind them. |
| `indicators` | `indicators.py` | `<<module>>`: `INDICATORS` (name and description of the twelve), `INDICATOR_NAMES`, and `compute_indicators` over one window of events. |
| `Precursors` | `signals.py` | Critical-slowing-down reading of the severity series: variance, lag-1 autocorrelation, skewness and whether each is rising; `slowing_down` is the early warning. |
| `DragonKing` | `signals.py` | Rank-ordering test of the series' largest value against a tail fitted without it: expected, observed, ratio, fit quality, `is_dragon`. |
| `signals` | `signals.py` | `<<module>>`: `precursors`, `dragon_king` and `zscore`. |
| `record` | `record.py` | `<<module>>`: builds the per-run DK-RMM artifact (`series_of`, `states_of`, `transitions_of`, `timeline_of`, `build_record`), compares a perturbed run with its control (`compare_records`) and writes it (`write_record`). |
