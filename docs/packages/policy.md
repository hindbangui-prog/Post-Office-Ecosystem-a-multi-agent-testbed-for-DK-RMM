# post_office.policy

The layer between what an agent decided and what the facility does. `BaseAgent.decide()` turns every answer, whether it came from a Python rule or a model, into a frozen `Proposal` and hands it to the one `PolicyGate`, which `simulation.PostOfficeEcosystem` creates and places on `core.World.gate`. `PolicyGate.check()` asks three questions in order and stops at the first refusal: schema (is the choice one of the offered options), policy (does the `AUTHORITY` table give this decision kind to this agent, and does the choice stay under the supervisor's ceilings in `core.Policy`), and state (is the chosen charge point, shelf or robot still available on the floor). The result is a frozen `Verdict` naming the stage and the violation, or the shared `PERMITTED`, and refusals are counted per stage in `by_stage` for the run summary. The package depends only on `core.World` (read through its `env`, `fleet` and `policy`) and `environment.Zone`. The rule to know: the gate reads the world and never writes anything, and it never picks between lawful options; when it refuses, the agent's own deterministic rule answers instead.

## Class diagram

```mermaid
classDiagram
  direction LR
  class PolicyGate {
    +World world
    +int checked
    +int refused
    +Dict~str,int~ by_stage
    +check(proposal) Verdict
    +stats() dict
    -_schema(proposal) Verdict
    -_policy(proposal) Verdict
    -_state(proposal) Verdict
  }
  class Proposal {
    <<dataclass>>
    +str kind
    +str agent_id
    +Any choice
    +Sequence options
    +Dict facts
    +str reason
    +str source
    +as_dict() dict
  }
  class Verdict {
    <<dataclass>>
    +bool ok
    +str stage
    +str violation
    +as_dict() dict
  }
  class gate_module["gate (module)"] {
    <<module>>
    +Dict~str,str~ AUTHORITY
    +Verdict PERMITTED
    -_number(value) float
  }
  class World["core.World"]
  <<external>> World
  class Policy["core.Policy"]
  <<external>> Policy
  class Zone["environment.Zone"]
  <<external>> Zone
  class BaseAgent["agents.BaseAgent"]
  <<external>> BaseAgent
  class PostOfficeEcosystem["simulation.PostOfficeEcosystem"]
  <<external>> PostOfficeEcosystem

  PostOfficeEcosystem *-- PolicyGate : creates, puts on world.gate
  PolicyGate o-- World : reads env, fleet, policy
  World --> Policy : policy
  PolicyGate ..> Proposal : checks
  PolicyGate ..> Verdict : returns
  PolicyGate ..> gate_module : AUTHORITY, PERMITTED
  PolicyGate ..> Zone : TEMPORARY_STORAGE
  gate_module ..> Verdict : PERMITTED
  BaseAgent ..> Proposal : builds in decide()
  BaseAgent ..> PolicyGate : check() via world.gate
```

![policy class diagram](img/policy.svg)

## Classes

| Class | Module | Role |
|---|---|---|
| `PolicyGate` | `gate.py` | Validates proposals in three stages (schema, policy, state) against `world.policy` and the live floor; counts checks and refusals by stage; writes nothing. |
| `Proposal` | `gate.py` | Frozen dataclass: what an agent wants to do (decision kind, agent id, choice, offered options, facts, reason, source) before anyone agreed to it. |
| `Verdict` | `gate.py` | Frozen dataclass: permitted, or refused with the stage (`schema`, `policy`, `state`) and the violation text. |
| `gate (module)` | `gate.py` | `AUTHORITY` maps each decision kind (`release_work`, `accept_parcel`, `choose_robot`, ...) to the one agent id allowed to decide it; `PERMITTED` is the shared ok verdict; `_number()` coerces facts to float. |
