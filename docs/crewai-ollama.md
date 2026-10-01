# CrewAI and Ollama

The seven experts reason on a local Ollama server through CrewAI. This document describes how
the one shared LLM is built, how every model call is audited, how the model's identity is
checked before a run, the configuration, and how to switch to another model. The project
pins `crewai>=1.15,<2`; the behaviour below was verified on CrewAI 1.15.23.

## The LLM

`post_office/crew/llm.py::build_llm(settings, interceptor)` asks CrewAI for
`LLM(model="ollama/<OLLAMA_MODEL>", base_url=<OLLAMA_BASE_URL>, api_key="ollama",
temperature=..., seed=..., timeout=..., max_tokens=..., max_retries=0,
interceptor=<the audit>)`. On CrewAI 1.15 that is served by its OpenAI-compatible completion
class: the object returned is an `OpenAICompatibleCompletion` with `provider == "ollama"` and
`base_url == <OLLAMA_BASE_URL>/v1`, so every model call is an HTTP `POST
<OLLAMA_BASE_URL>/v1/chat/completions`. `build_llm` checks the class, the provider, the model,
the base URL and `max_retries` on the object it got and raises `UnexpectedProviderError` if any
of them differs, so a CrewAI change that re-routed the experts would stop the run instead of
running it somewhere else.

The API key is passed explicitly as `"ollama"`, which Ollama ignores, so CrewAI never falls
back to `OLLAMA_API_KEY` or any cloud provider key from the environment. The OpenAI client's
own retries are off (`max_retries=0`): one model call is one HTTP attempt, which keeps the audit
records, the latencies and the consultation deadline predictable. CrewAI's agent-level
`max_retry_limit=1` is the only retry layer left.

All seven CrewAI agents use the same `LLM` instance, so they cannot end up on different
models. The ecosystem rebuilds that instance in `_install_crew` around its own audit and gives
it to every agent, because CrewAI builds its HTTP clients when the LLM is made and an
interceptor set afterwards would never be used; a reset therefore gets a fresh audit too.

## Thinking

`qwen3:8b` can emit hidden reasoning. `OLLAMA_THINKING` chooses how it is switched off.
With `off` (the default) the request carries `reasoning_effort: "none"` in `extra_body`, the
mechanism the source used with Ollama. With `prompt` the request is left alone and
`build_agents` prefixes every backstory with `/no_think`, qwen3's own switch from inside the
prompt. Either way every reply, the owner's and the peer's, is passed through
`core/visible.py::visible()` before it is parsed or shown, which removes `<think>` blocks.
Whether the installed Ollama honours `reasoning_effort` for `qwen3:8b` has not been checked in
this build; `tools/verify_ollama.py` prints how many raw replies contained `<think>` or a
separate reasoning field, and suggests `prompt` when the model reasons despite `off`.

## The transport audit

`post_office/crew/audit.py::OllamaAudit` is CrewAI's supported transport interceptor
(`BaseInterceptor[httpx.Request, httpx.Response]`). `on_outbound` compares the request's
scheme, host and port with the configured Ollama address and raises `UnexpectedProviderError`
for anything else, before the request leaves the process (the refusal is recorded too).
`on_inbound` reads the reply and records the model Ollama says it served, the latency, the
token usage and the HTTP status; it never raises, so an unreadable reply is recorded with
`error` set and passed on unchanged. A request that gets no response at all (timeout, refused
or reset connection) is recorded with `status=None` and `error="no response (transport error or
timeout)"` at the next request on the same thread or at the end of the enclosing `calling`
block, so every attempt leaves exactly one record.

The wire does not say which expert is calling, so the code that runs an agent says so with
`with calling(agent_id, phase)`: the consultation service wraps the owner's `execute_task` in
`calling(owner, "owner")` and the peer's in `calling(peer, "peer")`, and the verify tool uses
`calling(agent, "probe")`. Each record becomes an `llm_call` event while its consultation is
open (see [events.md](events.md)).

## Model identity

`post_office/crew/identity.py::verify_model(settings)` asks the server itself: `GET /api/tags`
for the installed models and the configured model's digest, then `POST /api/show` for its
family, parameter size and quantization. It returns a `ModelIdentity` (`model`, `base_url`,
`digest`, `family`, `parameter_size`, `quantization`, `installed`, `ok`, `problems`) and never
raises for a server problem. `require_model` raises `ModelUnavailable` instead when `ok` is
false. It uses only the standard library and bypasses system proxy settings, since a proxy
answering in Ollama's place would make the identity meaningless.

`llm_brains` calls `require_model` unless told the check was already made; `main.py` (both
the run and `--api`) and `tools/run_normal.py` check first and exit with code 2 when the model
is not there, and `SimulationRunner` serves the run rules-only with `llm_error` saying why.
Nothing is ever substituted. The identity is written to `results/normal/s<seed>/verify.json`
by `tools/run_normal.py` and served by `GET /settings`; the ecosystem's own `simulation`/`llm`
notice records the backend, model, base URL and the experts on the model.

## Configuration

`post_office/config/ollama.py::load_settings()` reads each value from the environment, over
an optional `.env` file in the project root, over the defaults. The `.env` file is read with
python-dotenv's `dotenv_values` and never exported, so it changes nothing else in the
process. Empty values count as unset. `.env.example` lists every variable with its default.

| Variable | Default | Meaning |
|----------|---------|---------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | the bare Ollama server address with its port; no `/v1` (CrewAI appends it) |
| `OLLAMA_MODEL` | `qwen3:8b` | the Ollama model name; a name containing `/` is refused |
| `OLLAMA_TIMEOUT` | `120` | seconds per HTTP request |
| `OLLAMA_SEED` | `42` | the decoding seed; `none`, `null` or `off` sends none |
| `OLLAMA_TEMPERATURE` | `0` | the sampling temperature |
| `OLLAMA_MAX_TOKENS` | `512` | the completion limit per call |
| `OLLAMA_THINKING` | `off` | `off` (`reasoning_effort: none`) or `prompt` (`/no_think` in the backstory) |
| `CONSULT_DEADLINE_S` | `300` | seconds a consultation may take before the rule answers |

Two values are refused rather than interpreted. A model name containing `/` raises
`InvalidModelName`, because CrewAI reads the text before a slash as the provider and
`openai/gpt-4o` would quietly route the experts to a cloud service; the provider is always
`ollama`. A base URL that is not `http` or `https`, names no port, ends in `/v1` or carries a
query or fragment raises `InvalidBaseUrl`, because CrewAI appends `/v1` itself and fills in a
missing port, so the address the experts used would differ from the one written down.

CrewAI's own anonymous telemetry is not configured by the project. The test suite switches it
off (`conftest.py` sets `CREWAI_DISABLE_TELEMETRY=true` and `OTEL_SDK_DISABLED=true`); for
your own runs set those two variables in the shell, since the project's `.env` is not
exported.

## Switching the model

The model is configuration only. To run the experts on `gemma4:26b`, pull it with
`ollama pull gemma4:26b`, set `OLLAMA_MODEL=gemma4:26b` in `.env` (or in the environment), and
run `tools/verify_ollama.py`, which must print seven rows with `served=gemma4:26b` and `ok`.
No agent code changes, and all seven experts move together because they share one LLM.
Every record names the configured model (`source="crewai:gemma4:26b"`, the `model` field of
the consultation events, `served_model` of every `llm_call`, the header badge of the live
page). The scenario selector's label in the live page is fixed text from
`config/settings.py::SCENARIOS` and still reads `Ollama/qwen3:8b`; see
[limitations.md](limitations.md).
