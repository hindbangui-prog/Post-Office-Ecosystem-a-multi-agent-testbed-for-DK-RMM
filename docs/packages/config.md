# post_office.config

Every dial of a run and the switch that puts a model behind an expert. `settings` holds `DEFAULT_CONFIG` (arrivals, fleet, storage, plan, brains and log sizes, with battery and charge figures taken from `robots.robot` and `environment.layout`), `normal_config()` for the one NORMAL scenario, `config(preset, **overrides)`, the scenario label and metadata helpers, the tick-to-time conversion and `EXPERTS`, the seven agents a model may sit behind. `ollama` builds the frozen `OllamaSettings` from the environment over an optional `.env` over `DEFAULTS` with `load_settings`, and the dataclass validates itself, raising `InvalidModelName` or `InvalidBaseUrl`. `llm_brains` ties the two together: it loads the settings, checks the model with `crew.identity.require_model`, builds the shared LLM and agents with `crew.llm` and `crew.roles`, and returns one `crew.CrewBrain` per expert with a fresh `DeterministicBrain` fallback, importing CrewAI only when called. `main.py`, `api.runner`, `api.server`, `ui`, `simulation.ecosystem`, `observability.run_record` and the tools read it, and the `crew` modules that reach the model (`brain`, `consultation`, `llm`, `audit`, `identity`) read `OllamaSettings`. The rule to know: the provider is always Ollama, so a model name containing "/" or a base URL without a port or ending in `/v1` is refused rather than silently routed elsewhere.

## Class diagram

```mermaid
---
config:
  layout: elk
---
classDiagram
  direction TB
  class ValueError["builtins.ValueError"]
  <<external>> ValueError
  class CrewBrain["crew.CrewBrain"]
  <<external>> CrewBrain
  class DeterministicBrain["agents.DeterministicBrain"]
  <<external>> DeterministicBrain
  class crewidentity["crew.identity"]
  <<external>> crewidentity
  class crewllm["crew.llm"]
  <<external>> crewllm
  class crewroles["crew.roles"]
  <<external>> crewroles

  class OllamaSettings {
    <<dataclass>>
    +str base_url
    +str model
    +int timeout
    +Optional~int~ seed
    +float temperature
    +int max_tokens
    +str thinking
    +float consult_deadline_s
    +str model_string
    +str host
    +as_dict() dict
  }
  class InvalidModelName
  class InvalidBaseUrl
  class ollama {
    <<module>>
    +Path ROOT
    +tuple THINKING_MODES
    +dict DEFAULTS
    +load_settings(env, dotenv, root) OllamaSettings
  }
  class settings {
    <<module>>
    +dict DEFAULT_CONFIG
    +dict PRESETS
    +tuple EXPERTS
    +config(preset, overrides) dict
    +normal_config() dict
    +llm_brains(agent_ids, settings, verify, audit) dict
    +scenario_label(model) str
    +scenarios(model) list
    +scenario_name(preset) str
    +scenario_meta(preset) dict
    +ticks_to_seconds(ticks) float
    +ticks_to_minutes(ticks) float
  }

  ValueError <|-- InvalidModelName
  ValueError <|-- InvalidBaseUrl
  OllamaSettings ..> InvalidModelName : raises
  OllamaSettings ..> InvalidBaseUrl : raises
  ollama ..> OllamaSettings : creates
  settings ..> ollama : load_settings
  settings ..> OllamaSettings : uses
  settings ..> crewidentity : require_model
  settings ..> crewllm : build_llm
  settings ..> crewroles : build_agents
  settings ..> CrewBrain : creates
  settings ..> DeterministicBrain : creates
```

![config class diagram](img/config.svg)

## Classes

| Class | Module | Role |
|---|---|---|
| `OllamaSettings` | `ollama.py` | Frozen, self-validating Ollama settings: base URL, model, timeout, seed, temperature, max tokens, thinking mode, consultation deadline. |
| `InvalidModelName` | `ollama.py` | Raised when the model name would select a CrewAI provider other than Ollama. |
| `InvalidBaseUrl` | `ollama.py` | Raised when the base URL is not the bare Ollama server address with its port. |
| `ollama` (module) | `ollama.py` | `ROOT`, `THINKING_MODES`, `DEFAULTS`, `load_settings`: settings from environment over `.env` over defaults. |
| `settings` (module) | `settings.py` | `DEFAULT_CONFIG`, `PRESETS`, `EXPERTS`, `config`, `normal_config`, `llm_brains`, scenario helpers and tick conversion. |
