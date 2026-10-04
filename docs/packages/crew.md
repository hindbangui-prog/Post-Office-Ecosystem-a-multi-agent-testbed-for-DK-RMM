# post_office.crew

The CrewAI side of the prototype: the seven experts as CrewAI agents on one shared Ollama-backed LLM, and the synchronous owner, peer, owner consultation that runs a model decision. `CrewBrain` sits behind the `agents.Brain` interface and always asks its `DeterministicBrain` rule first; once the ecosystem has bound a `ConsultationService`, it hands the decision over as `service.run(owner_id, question, trigger, rule_answer)` and reads back a `ConsultOutcome`. The service picks the peer from `discussion.peers.peer_for`, opens a `ConsultationContext` (`CSL-0001`, ...), runs the owner's CrewAI task in a worker thread under a deadline, gives the owner the `AskPeerTool` and `DelegateToPeerTool` bound to that one peer, and parses the closing `DECISION:` line with `parse_choice`. Every model call goes through `OllamaAudit`, the transport interceptor that refuses any host but the configured Ollama and records an `LLMCallRecord`; `ConsultEvents` writes the `consult_*` and `llm_call` events and the `CONSULT_*` messages through the ecosystem's `EventLogger` and `MessageBus`, and `Interception` holds the identity `CommunicationLayer` and `AgentHooks` seams. The package is built by `config.settings.llm_brains` and wired by `simulation.PostOfficeEcosystem`; `api.runner` and `api.server`, `main.py` and the command-line tools use `identity.require_model` and `console.quiet`, and it depends on `agents.brain`, `config.ollama`, `discussion`, `communication` and `core.visible`. The rule to know: the brain never applies anything and the peer is a consultant, not a second controller; only the owner's parsed answer, checked again against the question's options, goes back to `BaseAgent.decide`, whose policy gate checks it before the agent's own Python acts, and nothing here writes to the world.

## Class diagram

### Brain and consultation

```mermaid
---
config:
  layout: elk
---
classDiagram
  direction TB
  class Brain["agents.Brain"]
  <<external>> Brain
  class DeterministicBrain["agents.DeterministicBrain"]
  <<external>> DeterministicBrain
  class CrewAgent["crewai.Agent"]
  <<external>> CrewAgent
  class AskQuestionTool["crewai.AskQuestionTool"]
  <<external>> AskQuestionTool
  class DelegateWorkTool["crewai.DelegateWorkTool"]
  <<external>> DelegateWorkTool
  class peers["discussion.peers"]
  <<external>> peers
  class OllamaAudit["OllamaAudit (part 2)"]
  class ConsultEvents["ConsultEvents (part 2)"]
  class Interception["Interception (part 2)"]

  class CrewBrainConfig {
    <<dataclass>>
    +str model_type
    +Optional~int~ seed
    +str base_url
    +str provider
  }
  class CrewBrain {
    +str name
    +str agent_id
    +DeterministicBrain fallback
    +Agent crew_agent
    +CrewBrainConfig config
    +Any service
    +Optional~dict~ last_consultation
    +bind(service) None
    +answer(question) Answer
    +answer_consulting(question, trigger) Answer
    +stats() dict
    ...
  }
  class ConsultOutcome {
    <<dataclass>>
    +Answer answer
    +str consultation_id
    +str outcome
    +str peer
    +int turns
    +float latency_ms
    +str model
    +dict counts
    +str error
    +Optional~str~ prompt
  }
  class ConsultationService {
    +dict agents
    +Interception interception
    +OllamaSettings settings
    +OllamaAudit audit
    +ConsultEvents events
    +Callable briefing_source
    -dict _open
    +run(owner_id, question, trigger, rule_answer) ConsultOutcome
    +guarded(ctx, write) bool
    +inside(ctx) contextmanager
    +busy(agent_id) bool
    +in_flight() list
    +drain(timeout) bool
    +recent(limit) list
    +llm_calls(limit) list
    +summary() dict
  }
  class ConsultationContext {
    <<dataclass>>
    +str consultation_id
    +str owner_id
    +Optional~str~ peer_id
    +int tick
    +str kind
    +str condition
    +Sequence options
    +int exchanges_used
    +list turns
    +bool peer_failed
    +bool closed
    +bool timed_out
    ...
  }
  class PeerTool["_PeerTool"] {
    <<mixin>>
    -ConsultationContext _ctx
    -Any _service
    -_step(write, no_answer) Optional~str~
    -_consult(interaction_type, text, context, coworker, kwargs, ask_peer) str
  }
  class AskPeerTool {
    -_run(question, context, coworker) str
  }
  class DelegateToPeerTool {
    -_run(task, context, coworker) str
  }
  class RoleSpec {
    <<dataclass>>
    +str agent_id
    +str role
    +str goal
    +str backstory
  }
  class consultation {
    <<module>>
    +join_until(worker, timeout_s, step_s) None
    +expected_owner_calls(ctx) int
    +describe(question, peer_id) str
  }
  class tools {
    <<module>>
    +make_tools(ctx, peer_agent, service) list
  }
  class parse {
    <<module>>
    +render(question) str
    +parse_choice(text, options) Any
    +last_visible_line(text) str
  }
  class roles {
    <<module>>
    +ROLES dict
    +role_of(agent_id) str
    +agent_id_of(role) str
    +build_agents(llm, thinking) dict
  }

  Brain <|-- CrewBrain
  CrewBrain *-- CrewBrainConfig : config
  CrewBrain o-- DeterministicBrain : fallback
  CrewBrain o-- CrewAgent : crew_agent
  CrewBrain o-- ConsultationService : service via bind
  CrewBrain ..> ConsultOutcome : reads
  ConsultationService ..> ConsultOutcome : returns
  ConsultationService "1" *-- "*" ConsultationContext : _open
  ConsultationService o-- "*" CrewAgent : agents
  ConsultationService o-- OllamaAudit : audit
  ConsultationService o-- ConsultEvents : events
  ConsultationService o-- Interception : interception
  ConsultationService ..> peers : peer_for
  ConsultationService ..> parse : parse_choice
  ConsultationService ..> tools : make_tools
  ConsultationService ..> consultation : uses
  PeerTool <|-- AskPeerTool
  PeerTool <|-- DelegateToPeerTool
  AskQuestionTool <|-- AskPeerTool
  DelegateWorkTool <|-- DelegateToPeerTool
  PeerTool o-- ConsultationContext : _ctx
  PeerTool o-- ConsultationService : _service
  tools ..> AskPeerTool : creates
  tools ..> DelegateToPeerTool : creates
  roles "1" *-- "7" RoleSpec : ROLES
  roles ..> CrewAgent : build_agents
```

![crew class diagram, brain and consultation](img/crew-1.svg)

### Model access and audit

```mermaid
---
config:
  layout: elk
---
classDiagram
  direction TB
  class BaseInterceptor["crewai.BaseInterceptor"]
  <<external>> BaseInterceptor
  class OllamaSettings["config.OllamaSettings"]
  <<external>> OllamaSettings
  class EventLogger["communication.EventLogger"]
  <<external>> EventLogger
  class MessageBus["communication.MessageBus"]
  <<external>> MessageBus
  class RuntimeError["builtins.RuntimeError"]
  <<external>> RuntimeError
  class ValueError["builtins.ValueError"]
  <<external>> ValueError

  class UnexpectedProviderError
  class OllamaAudit {
    +OllamaSettings settings
    +Callable on_call
    +list records
    +list callback_errors
    +on_outbound(message) Request
    +aon_outbound(message) Request
    +on_inbound(message) Response
    +aon_inbound(message) Response
    +flush_pending(error) Optional~LLMCallRecord~
    -_emit(url, requested, served, ...) LLMCallRecord
  }
  class LLMCallRecord {
    <<dataclass>>
    +str call_id
    +str agent_id
    +str phase
    +str url
    +str requested_model
    +str served_model
    +float latency_ms
    +Optional~int~ prompt_tokens
    +Optional~int~ completion_tokens
    +Optional~int~ status
    +str error
    +as_dict() dict
  }
  class ModelUnavailable {
    +ModelIdentity identity
  }
  class ModelIdentity {
    <<dataclass>>
    +str model
    +str base_url
    +str digest
    +str family
    +str parameter_size
    +str quantization
    +list installed
    +bool ok
    +list problems
    +as_dict() dict
  }
  class Unexpected["_Unexpected"]
  class ConsultEvents {
    +Any logger
    +Any bus
    +str model
    -dict _open
    +opened(ctx, peer, options) Event
    +question(req) Event
    +delegation(req) Event
    +response(resp) Event
    +refused(ctx, reason, interaction_type, target) Event
    +closed(ctx, outcome, choice, turns, latency_ms, error) Event
    +llm_call(record, tick, ctx) Event
  }
  class ConsultRequest {
    <<dataclass>>
    +str consultation_id
    +int tick
    +str sender
    +str receiver
    +str interaction_type
    +str text
    +str context
  }
  class ConsultResponse {
    <<dataclass>>
    +str consultation_id
    +int tick
    +str sender
    +str receiver
    +str text
    +float latency_ms
    +str model
  }
  class CommunicationLayer {
    +on_request(req) Optional~ConsultRequest~
    +on_response(resp) Optional~ConsultResponse~
  }
  class AgentHooks {
    +before_prompt(agent_id, text) str
    +before_llm_call(agent_id) None
    +after_answer(agent_id, answer) Answer
  }
  class Interception {
    <<dataclass>>
    +CommunicationLayer communication
    +AgentHooks agent
    +inert()$ Interception
    +bool active
  }
  class llm {
    <<module>>
    +build_llm(settings, interceptor) LLM
  }
  class audit {
    <<module>>
    +calling(agent_id, phase) contextmanager
    +current_call() tuple
  }
  class identity {
    <<module>>
    +verify_model(settings, timeout) ModelIdentity
    +require_model(settings, timeout) ModelIdentity
  }
  class interception {
    <<module>>
    +from_config(cfg) Interception
  }
  class console {
    <<module>>
    +no_telemetry() None
    +quiet() contextmanager
    +utf8_stdout() None
  }

  RuntimeError <|-- UnexpectedProviderError
  RuntimeError <|-- ModelUnavailable
  ValueError <|-- Unexpected
  BaseInterceptor <|-- OllamaAudit
  OllamaAudit o-- OllamaSettings : settings
  OllamaAudit "1" *-- "*" LLMCallRecord : records
  OllamaAudit ..> UnexpectedProviderError : raises
  audit ..> OllamaAudit : flush_pending
  llm ..> OllamaSettings : reads
  llm ..> UnexpectedProviderError : raises
  identity ..> OllamaSettings : reads
  identity ..> ModelIdentity : creates
  identity ..> ModelUnavailable : raises
  identity ..> Unexpected : raises
  ModelUnavailable o-- ModelIdentity : identity
  ConsultEvents o-- EventLogger : logger
  ConsultEvents o-- MessageBus : bus
  ConsultEvents ..> ConsultRequest : writes
  ConsultEvents ..> ConsultResponse : writes
  ConsultEvents ..> LLMCallRecord : writes
  Interception *-- CommunicationLayer : communication
  Interception *-- AgentHooks : agent
  CommunicationLayer ..> ConsultRequest : passes
  CommunicationLayer ..> ConsultResponse : passes
  interception ..> Interception : inert
```

![crew class diagram, model access and audit](img/crew-2.svg)

## Classes

| Class | Module | Role |
|---|---|---|
| `CrewBrainConfig` | `brain.py` | Frozen record of a brain's model: type, seed, base URL, provider. |
| `CrewBrain` | `brain.py` | `Brain` that starts from the rule's answer and hands the decision to the bound consultation service; counts calls, fallbacks, retries. |
| `ConsultOutcome` | `consultation.py` | What one consultation returns to the brain: answer, id, outcome, peer, turns, latency, counts, error, prompt. |
| `ConsultationService` | `consultation.py` | Runs one owner, peer, owner consultation per model decision in a worker thread under a deadline; keeps history, LLM calls and summary counts. |
| `ConsultationContext` | `tools.py` | Mutable state of one open consultation: ids, peer, turns, exchanges used, peer failure, closed and timed-out flags. |
| `_PeerTool` | `tools.py` | Mixin with the guarded request, peer call and response steps shared by the two peer tools. |
| `AskPeerTool` | `tools.py` | CrewAI `Ask question to coworker` bound to the one allowed peer. |
| `DelegateToPeerTool` | `tools.py` | CrewAI `Delegate work to coworker` bound to the one allowed peer. |
| `RoleSpec` | `roles.py` | Frozen role, goal and backstory of one expert as a CrewAI agent. |
| `UnexpectedProviderError` | `llm.py` | Raised when a model call would go, or went, anywhere but the configured Ollama. |
| `LLMCallRecord` | `audit.py` | One model call as the wire saw it: agent, phase, URL, requested and served model, latency, tokens, status, error. |
| `OllamaAudit` | `audit.py` | CrewAI transport interceptor: refuses foreign hosts, records every request and reply, reports each record to `on_call`. |
| `ModelUnavailable` | `identity.py` | Raised by `require_model` when the configured model is not usable; carries the `ModelIdentity`. |
| `ModelIdentity` | `identity.py` | What the Ollama server reports about the configured model: digest, family, size, quantization, installed list, problems. |
| `_Unexpected` | `identity.py` | Internal error for a JSON reply that is not shaped as Ollama's. |
| `ConsultEvents` | `events.py` | Writes `consult_*` and `llm_call` events through the `EventLogger` and `CONSULT_*` messages through the `MessageBus`. |
| `ConsultRequest` | `interception.py` | One owner-to-peer message: a question or a delegated sub-question. |
| `ConsultResponse` | `interception.py` | The peer's advice on its way back to the owner. |
| `CommunicationLayer` | `interception.py` | Seam on each request and response between owner and peer; identity in this phase, `None` means withheld. |
| `AgentHooks` | `interception.py` | Seam around the owner's model: before the prompt, before the call, after the answer; identity in this phase. |
| `Interception` | `interception.py` | The pair of seams a consultation service uses; `inert()` is the NORMAL arrangement. |
| `consultation` (module) | `consultation.py` | `join_until`, `expected_owner_calls`, `describe`: the deadline join, the retry baseline and the owner's task text. |
| `tools` (module) | `tools.py` | `make_tools`: the ask and delegate tools for one consultation, bound to one peer. |
| `parse` (module) | `parse.py` | `render`, `parse_choice`, `last_visible_line`: how a question is put to an expert and how the reply is read. |
| `roles` (module) | `roles.py` | `ROLES`, `role_of`, `agent_id_of`, `build_agents`: the seven experts as CrewAI agents on one LLM. |
| `llm` (module) | `llm.py` | `build_llm`: the one Ollama LLM, checked for class, provider, model, endpoint and retries. |
| `audit` (module) | `audit.py` | `calling`, `current_call`: attribute model calls to an agent and phase through a context variable. |
| `identity` (module) | `identity.py` | `verify_model`, `require_model`: ask the Ollama server whether the configured model is installed. |
| `interception` (module) | `interception.py` | `from_config`: the inert interception for an empty `interceptors` list, anything else refused. |
| `console` (module) | `console.py` | `no_telemetry`, `quiet`, `utf8_stdout`: silence CrewAI's console panels and telemetry, UTF-8 output. |
