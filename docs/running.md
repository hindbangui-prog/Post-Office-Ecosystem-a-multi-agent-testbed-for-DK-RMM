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
telemetry is switched off by the project: `main.py`, `tools/run_normal.py` and
`tools/verify_ollama.py` set `CREWAI_DISABLE_TELEMETRY=true` and `OTEL_SDK_DISABLED=true`
before CrewAI is imported, and `crew/console.py::quiet()` (used by the API server too) does the
same. Both are set only when the environment does not already name them, so a value of your own
is kept.

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
substituted. A model-mode run also prints the number of model decisions and how many of them
were exchanges (the owner actually asked or delegated to its peer), and the first complete
consultation: the first `decided` one with both a request and a response, if there was one.
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
ring marks the expert currently inside a model call. Below it are five panes. Robots and
agents is the facility floor, the robot cards and, under the floor, the Runtime communication
list, following the run tick by tick from `GET /frame`. Consultations has one row per
consultation (tick, owner and peer, kind and condition, the question, the response, the
decision, the outcome, the latency, the model), from `GET /consultations`. Ollama calls has one
row per model call (tick, agent, phase, served model, latency, tokens, status, consultation),
from `GET /llm/calls`. DK-RMM shows the state, severity, current evidence, the twelve
indicators and the state history, from `GET /dkrmm/*`. Runtime communication has one row per
event, described below. The panes refresh on a heartbeat and at once when the WebSocket
`WS /ws` reports an event.

### The Runtime communication tab

The tab holds every event of the run as one row, oldest first, built in the page from the
`event` messages of `WS /ws` and from `GET /events`: on connect the page reads the newest
sequence number and fetches the last 2000 events, a gap in the sequence of live events is
filled from `GET /events?after=`, and a run reset empties the buffer. The buffer keeps the last
2000 events; the head says how many of them the filters leave ("412 of 2000 buffered (the
last 2000)") and the tab's count says the same. The columns are tick, sender, receiver, type,
class, request, response, decision, latency, model and edge. Sender and receiver are the
event's `actor` and `target`, or `(none)`; the type cell shows the interaction type with the
event's topic dimmed under it and the bus message type as its tooltip; the class cell is the
channel badge in the channel's colour; request, response and decision are the event's own
fields as [events.md](events.md) defines them; latency is `N ms` or `N ticks`; model is named
only where [events.md](events.md) allows one; edge reads `A -> B` only when the event has
both ends. A paired row's response cell carries the other row's sequence number as its
tooltip.

The filter bar is built from `GET /taxonomy` at load. One chip per channel (`A governance`,
`B llm_expert`, `C deterministic`, `D robot`, `E environment`, `decision`, `system`) toggles
that channel: with no chip pressed every row is shown, pressed chips show the union of their
channels, and pressing a chip again releases it. The "types" summary opens a popover with one
chip per interaction type, grouped under its channel and coloured by it, with the same
semantics; it reads "types N" while N are pressed. The id box takes a parcel, task or
consultation id (Enter, or a 300 ms pause, applies it; "clear" empties it) and lights every
row whose `correlation_id`, `consultation_id`, `message_id`, `in_reply_to`, `parcel_id` or
`task_id` equals it, plus the rows of any consultation a lit `decision` row names. "Follow
newest", on by default, keeps the newest row in view and switches itself off when you scroll
up or select a row. The legend under the bar lists the five classes with their colour and
dash, then "decision (node pulse, no edge)" and "(none) = no receiver, no edge".

Clicking a row selects it and lights its chain: every row sharing one of its ids
(`correlation_id`, `consultation_id`, `message_id`, `in_reply_to`, `parcel_id`, `task_id`),
closed once over the consultations the lit `decision` rows name; clicking the row again
clears it, and selecting a row empties the id box. The chain summary reads "chain: <key> ·
N rows · M edges", where the key is the row's `correlation_id`, else its consultation id,
else its message id, else `seq N`, or the typed id when the box is in use, and the counts are
taken among the rows the filters leave. The floor's graph receives the chain's edges and
nodes and draws them thicker.

### The typed floor graph

On the Robots and agents tab the graph "Who is talking to whom" keeps its hierarchy
(SUPERVISOR, PLANNER, the experts, the sub-agents, the robots) and gains an ENVIRONMENT node
as a sixth tier below the robots, the author of the parcel and resource events nobody sent;
the canvas is sized to the pane so all six tiers are on screen. A live edge, a bus message of
the current tick, is drawn in the colour and dash of its channel as the frame row carries it
(A amber, B teal dashed, C purple, D red, E grey-green); the cumulative traffic stays grey.
Events of the newest tick that are not bus messages reach the graph from the page: an event
with a target pulses an edge between its two nodes, in its channel's colour, for 600 ms, and
an event without one (a `decision`, a robot's report, a floor update) pulses a ring on its
actor's node, or on ENVIRONMENT, and draws no edge. The graph's header lists the five classes
with their line and dash, "decision = node pulse" and "(none) = no edge"; the node-kind key
under the canvas is as before. The chain selected in the Runtime communication tab is drawn
with a thicker stroke in the class of the most recent message on that edge, and its nodes are
ringed, until the selection is cleared. Under the floor, the list that was "Latest messages"
is "Runtime communication": the newest forty events of the tab's buffer, unfiltered and
newest first, each with a left border in its class's colour and the text `tick  sender ->
receiver  type: request`; following a robot or an agent narrows it to that id's rows as
before.

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
| `GET /taxonomy` | the runtime communication taxonomy, `taxonomy.table()`: the channels and the interaction types with their hints ([events.md](events.md)) |
| `GET /dkrmm/state`, `GET /dkrmm/series`, `GET /dkrmm/indicators` | DK-RMM's assessment, its recent series, its digest and the twelve indicators |
| `POST /simulation/start`, `/stop`, `/reset`, `/speed` | the controls |
| `WS /ws` | every event live, and a payload per tick |
