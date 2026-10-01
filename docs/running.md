# Running

The project runs from its own virtual environment on Python 3.10 to 3.13 (CrewAI's range) and
needs a local Ollama server only for model runs. The commands below are for Windows
(`cmd.exe`) in the project directory; on Linux or macOS use `python3 -m venv .venv` and
`.venv/bin/python` in place of `.venv\Scripts\python`.

## Install

```
cd "C:\Users\hindb\Projects\post office ecosystem prototype II"
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env
ollama pull qwen3:8b
```

The `dev` extra adds `pytest` and `httpx` for the tests. The optional `ui-test` extra adds
Playwright for the browser test of the live page: `.venv\Scripts\python -m pip install -e
".[ui-test]"` and then `.venv\Scripts\python -m playwright install chromium`.

`.env` holds the Ollama settings (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT`,
`OLLAMA_SEED`, `OLLAMA_TEMPERATURE`, `OLLAMA_MAX_TOKENS`, `OLLAMA_THINKING`,
`CONSULT_DEADLINE_S`); the environment overrides it, and it is read without being exported.
Every variable is explained in [crewai-ollama.md](crewai-ollama.md). CrewAI's anonymous
telemetry is on unless you switch it off in the shell, for example `set
CREWAI_DISABLE_TELEMETRY=true` and `set OTEL_SDK_DISABLED=true` before running.

## Command line

`main.py` runs the NORMAL scenario, watched by DK-RMM, and prints the summary and the monitor's
state as JSON at the end.

```
.venv\Scripts\python main.py --ticks 300 --seed 1          the seven experts on CrewAI/Ollama
.venv\Scripts\python main.py --rules --ticks 300 --seed 1  every expert on its Python rules
.venv\Scripts\python main.py --rules --log run.jsonl       the same, with the event log on disk
.venv\Scripts\python main.py --api                         the live page and API on 127.0.0.1:8000
.venv\Scripts\python main.py --api --rules --port 8001     the same, every expert on its rules
```

`--ticks` defaults to 600 and `--seed` to 1. In model mode (the default) the settings are
loaded and `require_model` must find the configured model on the server first; if it does not,
or the settings are invalid, the reason goes to stderr, the exit code is 2, and nothing is
substituted. A model-mode run also prints the first decided consultation, if there was one.
CrewAI's console panels are silenced (`crew/console.py::quiet`) for model runs, the tools and the
server; nothing is hidden from the record, since every model call is still an `llm_call` event.

A model run is slow by design: every tick that holds a consultation waits for it, and a
consultation is one to several model calls (see [limitations.md](limitations.md)).

## The baseline run and its evidence

`tools/run_normal.py` is the run whose files you keep:

```
.venv\Scripts\python tools\run_normal.py --ticks 300 --seed 1
.venv\Scripts\python tools\run_normal.py --ticks 300 --seed 1 --rules
```

It writes `results\normal\s<seed>\` (`events.jsonl`, `consultations.json`, `llm_calls.json`,
`dkrmm.json`, `summary.json`, `verify.json`; `--out` changes the folder) and prints a report.
What the report contains, and how to read it as evidence, is in
[verification.md](verification.md). The rules-only alignment of this project with the source,
which is checked by the test suite rather than run by hand, is in
[alignment-baseline.md](alignment-baseline.md).

## The live page

`main.py --api` starts the FastAPI server over one run that starts paused at tick 0 (`--start`
sets it going at once); open `http://127.0.0.1:8000/`. In model mode the same `require_model`
check runs first and a missing model refuses to start. `--rules` serves a rules-only run.

The header shows the model badge from `GET /settings` ("Ollama · qwen3:8b · 7/7 experts", or
"rules only"), the run line, the one scenario entry ("NORMAL · CrewAI · Ollama/qwen3:8b ·
DK-RMM"), Start and Reset, a speed selector (seconds of wall clock per tick, from 1x to 512x;
the simulation itself is the same at every speed), and a roster of the seven experts, where a
ring marks the expert currently inside a model call. Below it are four panes. Robots and
agents is the facility floor, the robot cards and the message feed, following the run tick by
tick from `GET /frame`. Consultations has one row per consultation (tick, owner and peer, kind
and condition, the question, the response, the decision, the outcome, the latency, the model),
from `GET /consultations`. Ollama calls has one row per model call (tick, agent, phase, served
model, latency, tokens, status, consultation), from `GET /llm/calls`. DK-RMM shows the state,
severity, current evidence, the twelve indicators and the state history, from `GET /dkrmm/*`.
The panes refresh on a heartbeat and at once when the WebSocket `WS /ws` reports an event.

The page reads the frame the runner publishes after every tick, so it never waits for a
consultation in progress: during one, the floor pauses on the last finished tick and the ring
shows who is being waited on. The server has no perturbation, experiment or stress control.

| Route | What it serves |
|-------|----------------|
| `GET /` | the live page |
| `GET /state`, `GET /frame`, `GET /summary` | the runtime state, the floor's frame and who is inside a model call, the run summary with the monitor's digest |
| `GET /events?after=&limit=` | the event log after a sequence number |
| `GET /consultations?limit=`, `GET /llm/calls?limit=` | recent consultations, recent model calls |
| `GET /settings` | the Ollama settings, the model identity, the experts on the model, the brains' counters |
| `GET /dkrmm/state`, `GET /dkrmm/series`, `GET /dkrmm/indicators` | DK-RMM's assessment, its recent series, its digest and the twelve indicators |
| `POST /simulation/start`, `/stop`, `/reset`, `/speed` | the controls |
| `WS /ws` | every event live, and a payload per tick |
