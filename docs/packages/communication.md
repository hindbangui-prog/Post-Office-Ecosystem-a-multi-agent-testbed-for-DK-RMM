# post_office.communication

This package is the only channel between agents and the record of everything that happens in a run. `MessageBus` routes `Message` envelopes between registered agents: each send is checked against the `Directory` and its `may_send` rules (the `AgentKind` hierarchy in `ALLOWED_KINDS` plus the rule that a sub-agent may only address its parent), recorded in the bus's `CommunicationLog`, and delivered into inboxes at the start of the next tick, or held when a perturbation has set a `delay_rule`. `EventLogger` writes every event as one JSON line, keeps the newest `Event` objects in memory for the API and calls its subscribers; on each `emit` it adds the `provenance` stamp in force and the interaction type and channel that `taxonomy.classify` assigns. `topics` holds the topic groupings (retry, refusal, switch, trouble) shared by DK-RMM and the perturbation tracer, and `provenance` the context-variable attribution that perturbation injectors open. Agents, the simulation ecosystem, crew, observability, dkrmm, api and ui all import it, while it depends only on `core.ids.IdFactory`. The rule to know: no agent imports the bus (each is handed a `send` callable that closes over its own id), and every message, delivered or refused, is written to the log, so there is no private channel.

## Class diagram

```mermaid
classDiagram
  direction TB
  class MessageBus {
    +Directory directory
    +EventLogger logger
    +CommunicationLog log
    +Callable delay_rule
    +int tick
    +register(agent_id, kind, role, parent_id) None
    +deregister(agent_id) None
    +sender_for(agent_id) Callable
    +send(sender, receiver, message_type, content, ...) Message
    +broadcast(sender, receivers, message_type, ...) list
    +deliver() int
    +release_held() int
    +inbox(agent_id) list
    ...
  }
  class CommunicationLog {
    +int sent
    +int refused
    +add(message) None
    +add_refusal(message, reason) None
    +recent(limit, agent_id, correlation_id, message_type) list
    +thread(correlation_id) list
    +refusals(limit) list
    +interaction_counts() dict
    +as_dict(limit) dict
  }
  class Message {
    <<dataclass>>
    +str message_id
    +int tick
    +str sender
    +str receiver
    +MessageType message_type
    +dict content
    +str correlation_id
    +str timestamp
    +str text
    +str in_reply_to
    +now()$ str
    +reply_content(fields) dict
    +as_dict() dict
  }
  class MessageType {
    <<enumeration>>
    OBJECTIVE
    POLICY
    PLAN_PROPOSAL
    PLAN_APPROVAL
    PLAN_REJECTION
    STATUS_REQUEST
    STATUS_REPORT
    WORK_NOTICE
    TASK_ASSIGNMENT
    TASK_ACCEPTED
    ...
  }
  class Directory {
    +register(agent_id, kind, role, parent_id, created_tick) AgentRecord
    +deregister(agent_id) None
    +get(agent_id) AgentRecord
    +all() list
    +of_kind(kind) list
    +children_of(agent_id) list
    +parent_of(agent_id) str
    +may_send(sender, receiver) tuple
    +tree() dict
    +as_dict() dict
  }
  class AgentRecord {
    <<dataclass>>
    +str agent_id
    +AgentKind kind
    +str role
    +str parent_id
    +list children
    +int created_tick
    +bool active
    +as_dict() dict
  }
  class AgentKind {
    <<enumeration>>
    SUPERVISOR
    PLANNER
    EXPERT
    SUBAGENT
    ROBOT
  }
  class directory {
    <<module>>
    +dict ALLOWED_KINDS
  }
  class EventLogger {
    +str run_id
    +str path
    +emit(category, topic, tick, actor, target, correlation_id, detail) Event
    +routed_sink(routes, default, actor) Callable
    +sink_for(category, actor) Callable
    +subscribe(fn) Callable
    +recent(limit, category, actor, correlation_id) list
    +since(after, limit) list
    +counts() dict
    +int total
    +flush() None
    +close() None
  }
  class Event {
    +int seq
    +int tick
    +str category
    +str topic
    +str actor
    +str target
    +str correlation_id
    +dict detail
    +str interaction_type
    +str channel
    +as_dict() dict
    ...
  }
  class EventCategory {
    +str AGENT
    +str COMMUNICATION
    +str TASK
    +str ROBOT
    +str PARCEL
    +str RESOURCE
    +str BATTERY
    +str SUPERVISOR
    +str SIMULATION
  }
  class events {
    <<module>>
    +read_events(path) Iterator
  }
  class taxonomy {
    <<module>>
    +tuple EXPERT_IDS
    +Mapping CHANNELS
    +Mapping TYPES
    +agent_kind(agent_id) str
    +classify(category, topic, actor, target, message_type) Classification
    +table() dict
  }
  class Channel {
    <<dataclass>>
    +str id
    +str label
    +str colour
    +str dash
    +str description
  }
  class InteractionType {
    <<dataclass>>
    +str interaction_type
    +str channel
    +str description
    +str has_receiver
    +str latency
    +bool model
  }
  class Classification {
    <<dataclass>>
    +str interaction_type
    +str channel
    +bool fallback
  }
  class provenance {
    <<module>>
    +str CAUSED_BY
    +str OBSERVED_AFTER
    +str RELATED_TO
    +current() dict
    +stamp(detail) dict
    +attributed(perturbation_id, relation, causal_parent) contextmanager
    +unattributed() contextmanager
  }
  class topics {
    <<module>>
    +frozenset RETRY_TOPICS
    +frozenset REFUSAL_TOPICS
    +frozenset SWITCH_TOPICS
    +frozenset TROUBLE_TOPICS
  }
  class IdFactory["core.IdFactory"]
  <<external>> IdFactory

  MessageBus o-- Directory : directory
  MessageBus o-- EventLogger : logger
  MessageBus *-- CommunicationLog : log
  MessageBus --> IdFactory : ids
  MessageBus "1" *-- "*" Message : creates, holds until delivered
  MessageBus ..> provenance : current, attributed
  MessageBus ..> EventCategory : uses
  CommunicationLog "1" o-- "*" Message : keeps
  Message --> MessageType : message_type
  Directory "1" *-- "*" AgentRecord : records
  Directory ..> directory : ALLOWED_KINDS
  AgentRecord --> AgentKind : kind
  EventLogger "1" *-- "*" Event : creates, keeps tail
  EventLogger ..> provenance : stamp
  EventLogger ..> taxonomy : classify
  taxonomy "1" *-- "*" Channel : CHANNELS
  taxonomy "1" *-- "*" InteractionType : TYPES
  taxonomy ..> Classification : returns
```

![communication class diagram](img/communication.svg)

## Classes

| Class | Module | Role |
|---|---|---|
| `MessageBus` | `bus.py` | Routes messages between registered agents, refuses what the directory forbids, delivers one tick later and logs every send, refusal, drop and late arrival. |
| `CommunicationLog` | `bus.py` | Bounded store of every accepted message and every refusal, with filtered queries, per-parcel threads and sender-to-receiver interaction counts. |
| `Message` | `message.py` | Immutable envelope of one agent-to-agent interaction; `correlation_id` threads a parcel's whole chain together. |
| `MessageType` | `message.py` | The 32 interaction kinds agents speak (objectives, plans, tasks, sub-tasks, consultations, robot commands, alerts). |
| `Directory` | `directory.py` | Registry of every participant and its place in the tree; `may_send` enforces the routing rules and returns the refusal reason. |
| `AgentRecord` | `directory.py` | The directory's entry for one participant: kind, role, parent, children, creation tick, active flag. |
| `AgentKind` | `directory.py` | A participant's place in the hierarchy: supervisor, planner, expert, sub-agent, robot. |
| `directory` | `directory.py` | `<<module>>`: `ALLOWED_KINDS`, which kinds may address which. |
| `EventLogger` | `events.py` | Writes the JSONL event log for one run, keeps the tail and per-topic counts in memory, stamps provenance and taxonomy, and feeds subscribers (the WebSocket relay, DK-RMM). |
| `Event` | `events.py` | One line of the log, built only by the logger, with the taxonomy's `interaction_type` and `channel`. |
| `EventCategory` | `events.py` | Plain class of category string constants (agent, communication, task, robot, parcel, resource, battery, supervisor, simulation). |
| `events` | `events.py` | `<<module>>`: `read_events`, reads a recorded run back, skipping bad lines. |
| `taxonomy` | `taxonomy.py` | `<<module>>`: the runtime communication taxonomy; `classify` names an event's interaction type and channel, `agent_kind` reads a kind from an id, `table` serves `CHANNELS` and `TYPES` as JSON. |
| `Channel` | `taxonomy.py` | One taxonomy channel (A to E, decision, system) with its label, colour, dash and description. |
| `InteractionType` | `taxonomy.py` | One interaction type, its channel, and the receiver, latency and model hints the page uses. |
| `Classification` | `taxonomy.py` | The result of `classify`: interaction type, channel, and the `fallback` marker read by the completeness test. |
| `provenance` | `provenance.py` | `<<module>>`: `attributed` / `unattributed` context managers and `current` / `stamp`, which put a perturbation's cause into `Event.detail` only where the code knows it. |
| `topics` | `topics.py` | `<<module>>`: `RETRY_TOPICS`, `REFUSAL_TOPICS`, `SWITCH_TOPICS`, `TROUBLE_TOPICS`, the shared meaning of the log's topics. |
