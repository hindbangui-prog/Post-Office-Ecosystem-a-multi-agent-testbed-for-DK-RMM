# post_office.state

The read side of the running system: one JSON-serialisable view of the whole ecosystem, so that the HTTP API and the UI share a single answer to "what is the state of the system". It consists of one class, `SystemState`, which `api.SimulationRunner` creates around the `simulation.PostOfficeEcosystem` it runs (and recreates when the run is rebuilt). Its methods return only dicts and lists: `get_ecosystem_state()` assembles run info, policy, hierarchy, agents, robots, parcels, tasks, resources, environment, communications, events and counters, and the narrower getters serve agents, robots, parcels, tasks, resources, recent messages, recent events and the bus's refused messages. It reaches the data through the ecosystem's members, chiefly `communication.CommunicationLog` (via `bus.log`), `communication.EventLogger`, `robots.Fleet`, `tasks.TaskRegistry` and the environment. The rule to know: it reads and never writes, which is what makes it safe to expose over HTTP.

## Class diagram

```mermaid
classDiagram
  direction LR
  class SystemState {
    +PostOfficeEcosystem eco
    +get_ecosystem_state(messages, events) dict
    +get_agents() List~dict~
    +get_agent_state(agent_id) dict
    +get_robots() List~dict~
    +get_parcels(status, limit, inside_only) List~dict~
    +get_parcel_state(parcel_id) dict
    +get_tasks(status, limit) List~dict~
    +get_task_state(task_id) dict
    +get_resources() dict
    +get_recent_messages(limit, agent_id, ...) List~dict~
    +get_refused_messages(limit) List~dict~
    ...
  }
  class SimulationRunner["api.SimulationRunner"]
  <<external>> SimulationRunner
  class PostOfficeEcosystem["simulation.PostOfficeEcosystem"]
  <<external>> PostOfficeEcosystem
  class CommunicationLog["communication.CommunicationLog"]
  <<external>> CommunicationLog
  class EventLogger["communication.EventLogger"]
  <<external>> EventLogger
  class Fleet["robots.Fleet"]
  <<external>> Fleet
  class TaskRegistry["tasks.TaskRegistry"]
  <<external>> TaskRegistry

  SimulationRunner *-- SystemState : state
  SystemState o-- PostOfficeEcosystem : eco
  SystemState ..> CommunicationLog : recent, thread, refusals
  SystemState ..> EventLogger : recent
  SystemState ..> Fleet : all, get
  SystemState ..> TaskRegistry : all, get, for_parcel
```

![state class diagram](img/state.svg)

## Classes

| Class | Module | Role |
|---|---|---|
| `SystemState` | `system_state.py` | Read-only facade over a `PostOfficeEcosystem`: whole-system snapshot plus per-agent, per-robot, per-parcel and per-task views, resources, recent messages and events, and refused messages (`get_robot_state`, `get_recent_events` are cut from the box). |
