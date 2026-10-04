# post_office.simulation

The assembled ecosystem and the clock that drives it. `PostOfficeEcosystem` builds everything in a fixed order: the `EventLogger`, `SeededRNG` and `IdFactory`, the facility from `environment.build_environment()`, the fleet from `robots.build_fleet()`, the `TaskRegistry`, the shared `core.World` with its `Policy` and `PolicyGate`, the `RecoveryService`, the `MessageBus`, the `ParcelGenerator`, and then every agent (supervisor, planner, experts, sub-agents, robot agents), attached in the order that is also the tick order. Each `step()` advances the clock, delivers the previous tick's messages, lets the generator put new parcels on the intake dock, steps every agent in declared order, lets `RecoveryService` act on the recovery requests agents left on the environment, departs any van whose time has come, and returns a snapshot. `ParcelGenerator` draws arrivals and label damage from their own named random streams so that changing an agent never changes when parcels arrive. The package is used by `api.runner` and `state.system_state`, and depends on nearly every other package. The rule to know: same seed and same config give the same event stream, so agent order is declared here explicitly and physical interventions (towing a flat robot, departing a van) are done by the engine, never by an agent.

## Class diagram

```mermaid
classDiagram
  direction LR
  class PostOfficeEcosystem {
    +int seed
    +dict config
    +str scenario
    +dict agents
    +List~str~ order
    +Fleet fleet
    +TaskRegistry tasks
    +PolicyGate gate
    +step() dict
    +run(ticks, on_tick) None
    +start() None
    +stop(reason) None
    +close() None
    +reset(run_id, brains, seed, config, scenario) PostOfficeEcosystem
    +snapshot() dict
    +summary() dict
    +reasoning_summary() dict
    -_build() None
    -_populate(cfg) None
    -_depart_vans(tick) None
    ...
  }
  class ParcelGenerator {
    +PostOfficeEnvironment env
    +float mean_interval
    +int initial
    +int max_on_dock
    +int created
    +int refused
    -Random _stream
    -Random _labels
    +seed_dock(tick, seed) List~Parcel~
    +step(tick, seed) List~Parcel~
    +as_dict() dict
  }
  class RecoveryService {
    +int DELAY$
    +World world
    +int completed
    +int refused
    +int withdrawn
    +step(tick) None
    +stats() dict
    -_attempt(request, tick) str
  }
  class ecosystem {
    <<module>>
    +build(seed, config, log_path, run_id, brains, scenario) PostOfficeEcosystem
  }
  class World["core.World"]
  <<external>> World
  class PostOfficeEnvironment["environment.PostOfficeEnvironment"]
  <<external>> PostOfficeEnvironment
  class RecoveryRequest["environment.RecoveryRequest"]
  <<external>> RecoveryRequest
  class BaseAgent["agents.BaseAgent"]
  <<external>> BaseAgent
  class MessageBus["communication.MessageBus"]
  <<external>> MessageBus
  class EventLogger["communication.EventLogger"]
  <<external>> EventLogger

  ecosystem ..> PostOfficeEcosystem : creates
  PostOfficeEcosystem *-- World : world
  PostOfficeEcosystem *-- PostOfficeEnvironment : env
  PostOfficeEcosystem *-- EventLogger : logger
  PostOfficeEcosystem *-- MessageBus : bus
  PostOfficeEcosystem *-- ParcelGenerator : generator
  PostOfficeEcosystem *-- RecoveryService : recovery
  PostOfficeEcosystem "1" *-- "*" BaseAgent : agents, stepped in order
  ParcelGenerator o-- PostOfficeEnvironment : env, add_parcel()
  ParcelGenerator o-- EventLogger : logger
  RecoveryService o-- World : world
  RecoveryService ..> RecoveryRequest : acts on env.recovery_requests
```

![simulation class diagram](img/simulation.svg)

## Classes

| Class | Module | Role |
|---|---|---|
| `PostOfficeEcosystem` | `ecosystem.py` | Builds the facility, fleet, registry, world, bus, generator, recovery service and every agent, and runs the fixed-order tick loop that produces one snapshot per tick. |
| `ParcelGenerator` | `generator.py` | Puts new parcels on the intake dock on its own random stream (geometric arrivals, occasional damaged or off-network labels) and refuses arrivals when the dock is full. |
| `RecoveryService` | `recovery.py` | Engine-side handler for agents' recovery requests: after a delay, tows a flat robot to a free charge point, or defers or withdraws the request. |
| `ecosystem` (module) | `ecosystem.py` | `build()`: convenience constructor for `PostOfficeEcosystem`. |
