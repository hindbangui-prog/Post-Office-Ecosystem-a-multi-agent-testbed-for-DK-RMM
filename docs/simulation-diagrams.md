# How the simulation runs: ticks, CrewAI, decisions and robots

Three diagrams, read from the code at the commit this file was added in.
Rendered copies are in `docs/img/sim-*.svg`.

## How ticks are used

A tick is the simulation's only unit of time. The simulated world never reads the
wall clock: every duration (a robot's walk, a van's departure, a deadline, a
DK-RMM window) is counted in ticks.

- **Who advances it.** `PostOfficeEcosystem.step()` (`simulation/ecosystem.py`)
  runs exactly one tick. Two drivers call it:
  - the live UI's `SimulationRunner._watch` (`api/runner.py`) sleeps between
    ticks so the run can be watched. The default `tick_seconds` is 0.25 s and
    can be changed from the UI;
  - `tools/run_normal.py` calls `run_ticks`, which steps back to back with no
    pause (300 ticks by default).
- **Message latency.** The `MessageBus` delivers everything sent during tick
  `t` at the start of tick `t+1`. Every message therefore costs exactly one tick,
  whoever sends it. This is why a request and its answer take at least two ticks.
- **Consultations are inside a tick.** A CrewAI consultation is synchronous: the
  tick waits for it (up to `CONSULT_DEADLINE_S`, 300 s by default). The tick
  number does not move while the model thinks. Only wall-clock time passes.
- **Robots.** One tick moves a robot up to `robot_speed` cells (1 by default).
  It costs 0.12 % battery per cell and 0.01 % per tick standing still. A
  charge point adds 1.2 % per tick.

Periodic work counted in ticks:

| Every | What | Where |
|---|---|---|
| 1 tick | messages delivered, every agent steps, every robot moves | `ecosystem.step`, `bus.deliver` |
| 1 tick | a new parcel arrives with probability 1/40 (`arrival_interval` 40) | `simulation/generator.py` |
| 5 ticks | a waiting robot re-reports `stalled` | `robots/robot.py` |
| 10 ticks | SCHEDULING sends idle robots home (`PARK_EVERY`) | `agents/scheduling_agent.py` |
| 15 ticks | SCHEDULING asks SUB-DEADLINE for overdue work (`DEADLINE_EVERY`) | `agents/scheduling_agent.py` |
| 20 ticks | PLANNER reports status to SUPERVISOR (`status_report_every`) | `agents/planner_agent.py` |
| 20 ticks | DK-RMM assesses, looking back 60 ticks (`EVERY`, `WINDOW`) | `dkrmm/monitor.py` |
| 20 ticks | a flat robot re-reports `battery_empty` | `robots/robot.py` |
| 30 ticks | an unanswered dispatch question is dropped (`DISPATCH_TIMEOUT`) | `agents/scheduling_agent.py` |
| 12 ticks | a recovery crew needs this long to reach a flat robot (`DELAY`) | `simulation/recovery.py` |
| 250 ticks | each route's van leaves (`DEFAULT_INTERVAL`) | `environment/vehicles.py` |

## Diagram 1. The simulation, step by step

![The tick loop](img/sim-1-tick-loop.svg)

```mermaid
flowchart TD
    START(["Start: build the ecosystem<br/>14 parcels already on the dock<br/>supervisor.start, vans open"]) --> LOOP
    LOOP["Driver takes the step lock<br/>api/runner.py _watch<br/>or tools/run_normal.py run_ticks"] --> S1

    subgraph STEP["eco.step(): one tick t"]
        S1["1. clock<br/>world.advance(t), bus.advance(t)"]
        S2["2. bus.deliver()<br/>messages sent during tick t-1<br/>land in the inboxes"]
        S3["3. generator.step(t)<br/>maybe one new parcel<br/>(probability 1/40,<br/>refused if the dock is full)"]
        S4["4. every agent steps, declared order<br/>SUPERVISOR, PLANNER,<br/>INTAKE, SORTING, ROUTING,<br/>SCHEDULING, RESOURCE, DISPATCH,<br/>15 sub-agents, 5 robot agents"]
        S5["5. recovery.step(t)<br/>fetch flat robots that were asked for"]
        S6["6. _depart_vans(t)<br/>a van whose time has come leaves<br/>with every parcel loaded on it"]
        S7["7. snapshot()<br/>the state of tick t"]
        S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7
    end

    S4 -. "for each agent" .-> A1
    subgraph AGENT["inside step 4"]
        A1["read the inbox, handle each message<br/>(CONSULT_* are records only, skipped)"]
        A2["tick_work()<br/>what the agent does unprompted"]
        A3["judgement calls go through<br/>BaseAgent.decide (Diagram 3)"]
        A4["messages sent now<br/>are delivered at tick t+1"]
        A1 --> A2 --> A3 --> A4
    end
    A3 -. "rule insufficient" .-> CREW["CrewAI consultation (Diagram 2)<br/>synchronous, inside this tick<br/>the tick waits, up to<br/>CONSULT_DEADLINE_S = 300 s"]
    CREW -. "Answer or rule fallback" .-> A3

    S7 --> M["DK-RMM monitor.tick()<br/>reads the event stream<br/>assesses every 20 ticks over the last 60<br/>observe/assess only"]
    M --> R["run recorder update<br/>(UI driver)"]
    R --> PUB["publish frame, broadcast 'tick' to the UI<br/>release the lock, sleep until next due time<br/>(tick_seconds, 0.25 s by default,<br/>no sleep in run_normal.py)"]
    PUB -- "tick t+1" --> LOOP
```

## Diagram 2. The role of CrewAI in the post office

CrewAI is used only at the Brain seam of the seven experts (PLANNER, INTAKE,
SORTING, ROUTING, SCHEDULING, RESOURCE, DISPATCH). It does not drive the tick, it
does not move robots and it never writes to the world. It replaces the
implementation of model-backed owner→peer→owner consultation. The peer map
(`discussion/peers.py`) still decides who may be consulted. The policy gate still
checks the answer.

![CrewAI at the Brain seam](img/sim-2-crewai.svg)

```mermaid
sequenceDiagram
    autonumber
    participant AG as Expert agent (owner)<br/>BaseAgent.decide
    participant CB as CrewBrain<br/>crew/brain.py
    participant DB as DeterministicBrain<br/>(the expert's rules)
    participant CS as ConsultationService<br/>crew/consultation.py
    participant PM as peers.py<br/>peer_for
    participant OW as Owner CrewAI Agent<br/>crew/roles.py
    participant PT as Ask / Delegate tool<br/>crew/tools.py
    participant PE as Peer CrewAI Agent<br/>(no tools)
    participant LLM as Shared LLM ollama/qwen3:8b<br/>crew/llm.py + OllamaAudit
    participant OL as Local Ollama<br/>localhost:11434/v1

    Note over AG,OL: At start-up: require_model checks the model is installed, build_agents makes 7 CrewAI agents around one LLM, the ecosystem binds every CrewBrain to one ConsultationService
    AG->>CB: answer(question, trigger) only when the rule is insufficient
    CB->>DB: rule answer first
    DB-->>CB: rule answer (kept as fallback)
    CB->>CS: run(owner, question, trigger, rule answer)
    CS->>PM: peer_for(owner, kind, condition)
    PM-->>CS: one peer, or none
    CS->>CS: consult_opened, CSL id minted
    CS->>OW: execute_task(render(question) + ask for DECISION line) in a worker thread, the tick waits
    OW->>LLM: owner prompt
    LLM->>OL: HTTP request (audit refuses any other host)
    OL-->>LLM: reply, audited (model, latency, tokens)
    LLM-->>OW: text
    opt the owner uses its one tool (bound to this peer only)
        OW->>PT: question or delegated sub-question
        PT->>PE: consult_question / consult_delegation
        PE->>LLM: peer prompt
        LLM->>OL: HTTP request
        OL-->>LLM: reply
        LLM-->>PE: advice
        PE-->>PT: consult_response
        PT-->>OW: advice
        OW->>LLM: owner prompt with the advice
        LLM->>OL: HTTP request
        OL-->>LLM: reply
        LLM-->>OW: final text with DECISION line
    end
    OW-->>CS: final text
    CS->>CS: parse_choice against the allowed options
    alt valid choice before the deadline
        CS-->>CB: Answer(choice, source crewai)
    else no valid choice, timeout, model or peer failed
        CS-->>CB: the rule answer marked fallback
    end
    CS->>CS: consult_closed, CONSULT_CLOSE to the peer
    CB-->>AG: Answer
    AG->>AG: _validate (policy gate), then the agent's own Python applies it
```

## Diagram 3. How agents decide and how robots act

The left half is what every expert does when it reaches a judgement call. The
right half is a robot's life from one command to the next report. The two halves
meet only through messages on the bus. Agents never touch a robot's body and
robots never write to a task or a parcel.

![Decisions and robot actions](img/sim-3-decide-act.svg)

```mermaid
flowchart LR
    subgraph DECIDE["1. An expert decides: BaseAgent.decide (agents/base.py)"]
        direction TB
        D0["a sub-agent's measurement arrives<br/>e.g. SUB-QUEUE ready tasks,<br/>SUB-ASSIGNMENT candidates,<br/>SUB-BATTERY cost, SUB-COLLISION ways out"]
        D1["Question: kind, prompt,<br/>facts, allowed options"]
        D2["triggers.fired(kind, facts)<br/>from install_triggers"]
        D3["rule answer<br/>from install_rules"]
        D4{"rule_insufficient()<br/>agents/reasoning.py<br/>policy 'insufficient'"}
        D5["path: deterministic<br/>the rule's answer"]
        D6["path: llm/trigger<br/>CrewBrain consultation<br/>(Diagram 2), or fallback<br/>to the rule"]
        D7["_validate: PolicyGate<br/>schema, policy, state"]
        D8["'decision' event logged<br/>the agent's Python acts:<br/>it sends messages"]
        D0 --> D1 --> D2 --> D3 --> D4
        D4 -- "None: rule sufficient" --> D5 --> D7
        D4 -- "a reason: no rule, not admissible,<br/>unsure, or an insufficient trigger" --> D6 --> D7
        D7 --> D8
    end

    subgraph CHAIN["2. SCHEDULING's errand chain (each step is a message, one tick)"]
        direction TB
        C1["decide choose_next_task<br/>(after SUB-QUEUE replies)"]
        C2["decide choose_robot<br/>(after SUB-ASSIGNMENT replies)"]
        C3["ROUTE_REQUEST to ROUTING and<br/>RESOURCE_REQUEST to RESOURCE<br/>(sent together)"]
        C4["RESOURCE decides battery_sufficient<br/>APPROVE, CHARGE_FIRST or REFUSE"]
        C5["route and clearance back:<br/>ROBOT_COMMAND transport<br/>(route to pickup and to dropoff)"]
        C1 --> C2 --> C3 --> C4 --> C5
    end

    subgraph ROBOT["3. Robot agent + robot body (agents/robot_agent.py, robots/robot.py)"]
        direction TB
        R1["RobotAgent.handle(ROBOT_COMMAND)<br/>transport, charge, yield, park,<br/>step_aside, set_route, abort"]
        R2["Robot.step(env, t), every tick<br/>drain battery, then by state:<br/>MOVING / DELIVERING: up to 1 cell<br/>PICKING / UNLOADING: one tick<br/>BLOCKED: next cell occupied<br/>WAITING: held, or asked and not answered<br/>CHARGING: +1.2 % per tick<br/>IDLE: nothing to do"]
        R3["ROBOT_REPORT, routed by subject<br/>(REPORT_ROUTING)"]
        R1 --> R2 --> R3
    end

    subgraph BACK["4. Reports go back to the responsible expert"]
        direction TB
        SCH["to SCHEDULING: picked, delivered,<br/>pick_failed, aborted, parked<br/>next errand or task completed<br/>ROBOT_COMMAND park / abort"]
        ROU["to ROUTING: blocked, stalled, route_invalid<br/>SUB-COLLISION measures, then<br/>decide resolve_block: WAIT, REROUTE,<br/>YIELD, PUSH, ABANDON<br/>ROBOT_COMMAND set_route / step_aside / yield<br/>(ABANDON: TASK_FAILED to SCHEDULING)"]
        RES["to RESOURCE: battery_low, battery_empty,<br/>charging_*<br/>decide allocate_charge_point:<br/>nearest free point or WAIT<br/>ROBOT_COMMAND charge"]
    end

    DECIDE == "the decision acts" ==> CHAIN
    CHAIN == "ROBOT_COMMAND" ==> ROBOT
    ROBOT == "ROBOT_REPORT" ==> BACK
    BACK == "next decision (back to 1)<br/>or next ROBOT_COMMAND (back to 3)" ==> DECIDE
```

### Reading Diagram 3

1. A decision always starts from a sub-agent's measurement, which arrives as a
   message one tick after it was asked for.
2. The expert builds a `Question` and runs its triggers and its rule.
3. `rule_insufficient` decides the path:
   - when it returns nothing, the rule's answer is used (`deterministic`);
   - otherwise the CrewBrain consults (`llm/<trigger>`), and the rule's answer
     remains the fallback.
4. The policy gate validates the answer. Only then does the agent's own Python
   send the commands that follow from it.
5. A robot acts only on a `ROBOT_COMMAND`. It moves one cell per tick, and
   reports back what happened. Each report goes to the expert responsible for
   that subject, and that expert's next decision closes the loop.
