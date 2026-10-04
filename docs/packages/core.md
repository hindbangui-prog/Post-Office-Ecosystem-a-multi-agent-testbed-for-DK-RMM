# post_office.core

The small things every layer needs: reproducible randomness, readable identifiers, the supervisor's standing orders and the bundle of shared handles agents are attached with. `SeededRNG` gives each named participant its own `random.Random` stream, derived from the run seed and the participant's label through `mix()`, so adding a robot does not shift anybody else's draws; `IdFactory` hands out per-prefix counters such as `P-0007` and `T-0012` instead of UUIDs. `World` is a plain dataclass that gathers the facility, task registry, fleet, generators, logger, `Policy` and the policy gate, and `World.advance()` is its only behaviour (it moves the shared clock). The simulation ecosystem builds one `World` and hands it to every agent at attach time; `agents`, `communication`, `crew` and `discussion` import from here, and the `visible()` helper strips hidden `<think>` reasoning from model replies for `crew` and `discussion`. The package depends on `environment`, `robots`, `tasks` and `communication` only for the types `World` holds. The rule to know: `World` holds no agents and has no behaviour of its own, so an agent can never reach another agent through it, and `Policy` is written only by the supervisor and read by everybody else.

## Class diagram

```mermaid
classDiagram
  direction LR
  class World {
    <<dataclass>>
    +PostOfficeEnvironment env
    +TaskRegistry tasks
    +Fleet fleet
    +SeededRNG rng
    +EventLogger logger
    +IdFactory ids
    +Policy policy
    +Any gate
    +int tick
    +str objective
    +bool running
    +advance(tick) None
  }
  class Policy {
    <<dataclass>>
    +int max_concurrent_transports
    +float reserve_battery
    +float resume_battery
    +bool urgent_first
    +bool store_normal_parcels
    +int status_report_every
    +float max_storage_load
    +dict notes
    +as_dict() dict
  }
  class SeededRNG {
    +int seed
    +Random world
    -dict _streams
    +stream(label) Random
    +labels() list
  }
  class IdFactory {
    -dict _counters
    -int _width
    +next(prefix) str
    +issued(prefix) int
    +reset() None
  }
  class rng {
    <<module>>
    +mix(seed, label) int
  }
  class visible {
    <<module>>
    +visible(text) str
  }
  class PostOfficeEnvironment["environment.PostOfficeEnvironment"]
  <<external>> PostOfficeEnvironment
  class TaskRegistry["tasks.TaskRegistry"]
  <<external>> TaskRegistry
  class Fleet["robots.Fleet"]
  <<external>> Fleet
  class EventLogger["communication.EventLogger"]
  <<external>> EventLogger

  World o-- Policy : policy
  World o-- SeededRNG : rng
  World o-- IdFactory : ids
  World o-- PostOfficeEnvironment : env
  World o-- TaskRegistry : tasks
  World o-- Fleet : fleet
  World o-- EventLogger : logger
  SeededRNG ..> rng : uses mix
```

![core class diagram](img/core.svg)

## Classes

| Class | Module | Role |
|---|---|---|
| `World` | `world.py` | Dataclass of shared, non-agent runtime handles passed to every agent at attach time; `advance()` sets the tick on itself and the environment. |
| `Policy` | `world.py` | Dataclass of the supervisor's standing orders (transport limit, battery thresholds, storage load cap, report cadence). |
| `SeededRNG` | `rng.py` | Run seed plus one lazily created `random.Random` stream per named participant. |
| `IdFactory` | `ids.py` | Monotonic per-prefix counters producing readable, run-stable ids such as `P-0007`. |
| `rng` (module) | `rng.py` | `mix(seed, label)`: derives an independent sub-seed by hashing the run seed with a label. |
| `visible` (module) | `visible.py` | `visible(text)`: a model reply with every form of `<think>` reasoning removed. |
