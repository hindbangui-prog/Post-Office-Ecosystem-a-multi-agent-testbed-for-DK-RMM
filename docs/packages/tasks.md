# post_office.tasks

Work as data: every unit of work in the facility is a `Task` with a type, an owner, a status and a written history, so a dependency between agents can be read off the data instead of inferred from a call stack. `Task` moves through the six states of `TaskStatus` only along the edges listed in `ALLOWED_TRANSITIONS`; `transition()` raises `IllegalTransition` on any other move, and the helpers `assign()`, `start()`, `complete()`, `fail()`, `cancel()` and `release()` are named wrappers around it. `TaskRegistry` creates tasks with ids from the shared `IdFactory`, keeps every task ever made, and answers the queue queries (`unassigned()`, `ready()`, `blocked()`, `for_robot()`) in the single ordering defined by `Task.sort_key`: deadline first, then priority, then age. The planner, the expert agents and their sub-agents create and query tasks through the registry held on `core.World`, and the ecosystem builds the registry with an event sink so each creation or recorded transition becomes a TASK event. The package depends only on `environment` (for `Zone` and `ParcelPriority`) and `core` (for `IdFactory`). The rule to know: the registry is a record, not an authority; it never decides who gets a task, and tasks are never deleted.

## Class diagram

```mermaid
classDiagram
  direction LR
  class TaskRegistry {
    -dict _tasks
    -list _live
    -IdFactory _ids
    +create(task_type, tick, created_by, ...) Task
    +adopt(task) Task
    +get(task_id) Task
    +open_tasks() List~Task~
    +unassigned(task_type) List~Task~
    +ready() List~Task~
    +blocked() List~Task~
    +for_robot(robot_id, open_only) List~Task~
    +counts() dict
    +record_transition(task, tick, topic) None
    ...
  }
  class Task {
    <<dataclass>>
    +str task_id
    +TaskType task_type
    +str parcel_id
    +Zone source
    +Zone destination
    +str assigned_agent
    +str assigned_robot
    +ParcelPriority priority
    +TaskStatus status
    +int due_by
    +str correlation_id
    +List~str~ depends_on
    +List~dict~ history
    +int MAX_HISTORY$
    +transition(status, tick, actor, note) None
    +assign(agent_id, tick, actor, robot_id) None
    +release(tick, actor, reason) None
    +bool is_open
    +tuple sort_key
    ...
  }
  class TaskType {
    <<enumeration>>
    CLASSIFY
    TRANSPORT
    STORE
    DISPATCH
    CHARGE
  }
  class TaskStatus {
    <<enumeration>>
    CREATED
    ASSIGNED
    IN_PROGRESS
    COMPLETED
    FAILED
    CANCELLED
  }
  class IllegalTransition
  class task_rules["task (module)"] {
    <<module>>
    +frozenset TERMINAL_STATUSES
    +dict ALLOWED_TRANSITIONS
  }
  class RuntimeError["builtins.RuntimeError"]
  <<external>> RuntimeError
  class IdFactory["core.IdFactory"]
  <<external>> IdFactory
  class Zone["environment.Zone"]
  <<external>> Zone
  class ParcelPriority["environment.ParcelPriority"]
  <<external>> ParcelPriority

  RuntimeError <|-- IllegalTransition
  TaskRegistry "1" *-- "*" Task : creates, keeps
  TaskRegistry o-- IdFactory : ids
  Task --> TaskType : task_type
  Task --> TaskStatus : status
  Task --> Zone : source, destination
  Task --> ParcelPriority : priority
  Task ..> task_rules : checks ALLOWED_TRANSITIONS
  Task ..> IllegalTransition : raises
  task_rules ..> TaskStatus
```

![tasks class diagram](img/tasks.svg)

## Classes

| Class | Module | Role |
|---|---|---|
| `TaskRegistry` | `registry.py` | Every task by id, a live index of open ones, and the deterministic queue queries the agents use; emits task events through an optional sink. |
| `Task` | `task.py` | Dataclass for one unit of work: owner, state, dependencies, route, capped history, and the shared `sort_key` ordering. |
| `TaskType` | `task.py` | Enumeration of work kinds: classify, transport, store, dispatch, charge. |
| `TaskStatus` | `task.py` | Enumeration of the six task states. |
| `IllegalTransition` | `task.py` | `RuntimeError` raised when a task is moved along an edge not in `ALLOWED_TRANSITIONS`. |
| `task` (module) | `task.py` | Constants `TERMINAL_STATUSES` (completed, failed, cancelled) and `ALLOWED_TRANSITIONS` (the legal state graph). |
