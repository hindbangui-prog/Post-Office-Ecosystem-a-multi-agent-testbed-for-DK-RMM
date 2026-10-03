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
.venv\Scripts\python main.py --api --record-dir D:\runs    the live page, recording under D:\runs
.venv\Scripts\python main.py --api --no-record             the live page, writing no record
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
ring marks the expert currently inside a model call. Below it are seven panes. Robots and
agents is the facility floor, the robot cards and, under the floor, the Runtime communication
list, following the run tick by tick from `GET /frame`. Consultations has one row per
consultation (tick, owner and peer, kind and condition, the question, the response, the
decision, the outcome, the latency, the model), from `GET /consultations`. Ollama calls has one
row per model call (tick, agent, phase, served model, latency, tokens, status, consultation),
from `GET /llm/calls`. DK-RMM shows the state, severity, current evidence, the gate on the
current reading, the state history with this run's RCTs under it, and the twelve indicators,
from `GET /dkrmm/*`. Runtime communication has one row per event, described below. Trajectory
(`this run, live`) and RCT log (`detected RCTs`) are the source's two pages in frames, also
described below. The panes refresh on a heartbeat and at once when the WebSocket `WS /ws`
reports an event. A reset, from the page or from another client, starts the shell's own panes
again in place for the new run without reloading the page: every request the page made for the
old run is dropped when it answers, the Runtime communication buffer keeps only the new run's
events, and the Trajectory frame is rebuilt (the RCT log frame is left as it is, since it lists
every run).

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
fields, or its paired row's, as [events.md](events.md) defines them (a reply row shows the
request it answers in the request column and its own text in the response column); latency
is `N ms` or `N ticks`; model is named
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
receiver  type: text`, where the text is the row's own: the response column on a reply row
(a paired reply, or a response-kind row), the request column on every other row; following
a robot or an agent narrows it to that id's rows as before.

The page reads the frame the runner publishes after every tick, so it never waits for a
consultation in progress: during one, the floor pauses on the last finished tick and the ring
shows who is being waited on. The server has no perturbation, experiment or stress control.

### The Trajectory tab

The Trajectory tab frames the source's trajectory page (its `tools/trajectory_template.html`,
adapted as `post_office/ui/trajectory.html`). The frame's address is set to `/ui/trajectory`
the first time the tab is opened, and a box reading "building trajectory from the run so far"
covers it until the page has loaded. `GET /ui/trajectory` fills the page with the newest events
the run's event logger holds (at most `limit`, 9000 by default), one row per event
([events.md](events.md), "The trajectory"), and the page then follows the run by asking
`GET /ui/trajectory/tail` for the rows logged since its last one, once a second while the tab
is showing; a hidden tab stops asking (`poSuspend`) and asks again when it is shown.

The toolbar has the two modes, Events (the default) and Expert consultation, a thread
selector, a badge with the run's name (`live`, or `finished` once the run has ended), the row
count, a search box, the Following button and a "Run log" link that opens the run's summary as
JSON (run id, seed, preset, model, start, ticks; the counts of events, actors, threads, model
requests and sub-agent requests; which rows are shown; rows per actor).

Events mode is the source's event stream. Four density lanes over the run sit above the list:
operator (the run's own `simulation/*` events), agents (`agent/*` and `supervisor/*`), tools (a
sub-agent request or its reply, by the taxonomy's `subagent_request` and `subagent_response`)
and robots (`robot/*`, `battery/*`, and any event whose actor is a robot `R<n>`); everything
else is the world and has no lane. The list groups the rows by thread (their
`correlation_id`: a parcel, a task, a consultation; the rest under "not threaded"), and the
search box matches a row's type, actor, target, thread and text. The list is drawn 1200 rows at
a time with "Show more" and "Show earlier" buttons, and the page keeps at most 14000 rows,
dropping the oldest 2000 when it passes that. Following keeps the newest rows in view; it
switches off when you scroll up and on again at the bottom. Clicking a row opens the inspector
(Summary, Preview and Raw tabs over the row and its payload); the up and down arrows move the
selection and Escape closes the inspector.

Expert consultation mode draws one bar per consultation, from its `consult_opened` to its
`consult_closed` on the wall-clock axis. The segments in a bar are the consultation's
`llm_call` rows, each drawn over its own latency, in the agents colour for the owner's calls and
the tools colour for the peer's. The bar's outline gives the outcome: decided green, timeout
amber, `no_valid_decision` and `model_failed` red, `peer_failed` grey, and dashed blue while
the consultation is open. The summary line counts the outcomes and gives the mean model call
("mean turn"), the mean closed consultation, and "waiting": the share of the closed
consultations' time not covered by their own model calls (queued behind other calls, or
waiting for the other side). Selecting a bar shows
the Decision, Owner, Peer, Outcome, Choice, the Reason (the question and the response, from
`consult_question` and `consult_response`), how long it took, and the calls, each with its
served model and, when it failed, its HTTP status or error.

The page holds only what the logger holds. The event logger keeps the newest 8000 events in
memory (`keep_events`) and there is no store of older ones, so on a longer run the page opens
on the newest 8000 it can get, the Run log says "the newest N of M rows", and the older events
are gone from the page (they are in the log file only if the server was started with `--log`).
After a reset the tab is rebuilt on the new run: at once if it is showing, otherwise the next
time it is opened. A Trajectory page left open on a run that has since been reset is refused by
the tail with 409, stops following, and its badge reads `finished` and its button "run ended -
reopen the tab".

### The RCT log tab

The RCT log tab frames the source's RCT log page (`post_office/ui/rcts.html`, `GET /ui/rcts`):
every RCT DK-RMM detected in this app's runs, the current one and earlier ones, read from the
files saved at detection (see Recording below). The scenario selector (Normal is the only
scenario; a scenario found among saved RCTs from elsewhere is listed with its own name) and
the All runs / This run filter choose the rows; each row gives when it was detected, the run,
the tick, the evidence kinds, the severity and the gate's status. Selecting one shows its cause
as it was saved at detection: the events of its window by evidence kind, topic and agent, the
messages in the window and how many were between experts consulting, the expert consultations
near it with their strong and weak links (see [dkrmm.md](dkrmm.md) for what a link means), and
the window against the baseline DK-RMM compared it with. The page reads `GET /dkrmm/rct-log`
every 3 seconds on its own while it is showing, across runs: a reset neither reloads nor
empties it. When the server is not recording, the page says "This app is not saving RCTs, so
there is nothing to list."

### The DK-RMM gate and explanation

Under the current reading the DK-RMM pane has the source's gate: the reading's status, who
decided it and when, a `by` field (default `operator`), an optional note, and Validate,
Activate and Dismiss. Validate and Dismiss are offered while the reading is undecided (and
before there is one, when the server's 409 answer is shown), Activate once it is validated;
each posts to `POST /dkrmm/validate`, `/activate` or `/dismiss` with `{by, note}` and the pane
shows the reading as the server returns it. The verdict is a person's; it changes the reading's
status, who decided it, when and the note, and nothing DK-RMM assesses (see
[dkrmm.md](dkrmm.md)). "explain this reading" fetches `GET /dkrmm/explain?tick=` for the
current reading and shows the explanation as the RCT log shows a saved cause. Under the history
strip, "Detected RCTs" lists this run's RCTs from `GET /dkrmm/rcts` (tick, clock time, kinds,
status), read while the pane is showing.

### Recording

`main.py --api` records the served run by default under `results/live/` in the project
directory; `--record-dir PATH` puts it elsewhere and `--no-record` writes nothing. The
recorder (`observability/run_record.py`, the source's) writes DK-RMM's run record to
`dkrmm/<run>.json` (the record `dkrmm.record.build_record` writes, with each reading and the
clock time it was first seen; it is looked at after every tick and rewritten at every new
reading DK-RMM makes, every 20 ticks, while DK-RMM's history, its last 400 readings, is still
filling: [limitations.md](limitations.md) says what happens after that) and, when a reading is
an RCT, the file
`rct/<run>/<tick>.json` with the reading as DK-RMM gave it and the explanation of its window
computed then from the run's own events. A gate verdict rewrites both. `<run>` is the run id,
with `-2`, `-3` and so on added when that name is already taken in the folder, so earlier runs
are never overwritten; a reset starts a new run and a new record. If the recorder fails, the run
carries on and `GET /dkrmm/rct-log` says why in `record_error`. `tools/run_normal.py` does not
use the recorder: it writes its own `dkrmm.json` and no per-RCT files.

### Routes

The server serves the routes below and no others: section 16 of the 2026-10-01 design,
`GET /taxonomy`, and the ten routes of the trajectory and RCT log design (seven DK-RMM routes
and three pages).

| Route | What it serves |
|-------|----------------|
| `GET /` | the live page |
| `GET /state`, `GET /frame`, `GET /summary` | the runtime state, the floor's frame and who is inside a model call, the run summary with the monitor's digest |
| `GET /events?after=&limit=` | the event log after a sequence number |
| `GET /consultations?limit=`, `GET /llm/calls?limit=` | recent consultations, recent model calls |
| `GET /settings` | the Ollama settings, the model identity, the experts on the model, the brains' counters |
| `GET /taxonomy` | the runtime communication taxonomy, `taxonomy.table()`: the channels and the interaction types with their hints ([events.md](events.md)) |
| `GET /dkrmm/state`, `GET /dkrmm/series`, `GET /dkrmm/indicators` | DK-RMM's assessment, its recent series, its digest and the twelve indicators |
| `GET /dkrmm/rcts` | this run's RCTs from the monitor's history, newest first, with the clock time each was detected |
| `GET /dkrmm/explain?tick=` | the explanation of the reading at that tick, over the run's events (`source`: `log` or `memory`) |
| `GET /dkrmm/rct-log` | every saved RCT of this app's runs, with the scenarios, the current run, whether the server is recording, the folder and `record_error` |
| `GET /dkrmm/rct-log/item?run=&tick=` | one saved RCT file whole (404 when absent or not recording, 400 for a bad run name) |
| `POST /dkrmm/validate`, `/activate`, `/dismiss` | a person's verdict `{by, note}` on the current reading, through the monitor's own method (409 when there is nothing to decide) |
| `GET /ui/trajectory?limit=&run_id=&archived=` | the Trajectory page over the live run (another `run_id` is 404; `archived` is accepted and ignored) |
| `GET /ui/trajectory/tail?after_id=&started=&limit=&run_id=` | the rows logged since `after_id`, as `{rows, last_id, total}` (409 to a page of an earlier run) |
| `GET /ui/rcts` | the RCT log page |
| `POST /simulation/start`, `/stop`, `/reset`, `/speed` | the controls |
| `WS /ws` | every event live, and a payload per tick |
