# Post Office Ecosystem: a multi-agent testbed for DK-RMM

The post-office ecosystem serves as a testbed for evaluating runtime monitoring in a multi-agent environment. It comprises five operational zones—intake, sorting, storage, charging, and dispatch—and five robots. Its operations are coordinated by a supervisor, seven expert agents (one planner and six specialists), and fifteen sub-agents. Each expert first attempts to make decisions using predefined rules. When these rules are insufficient, its CrewAI agent consults a local Ollama model (Qwen3:8B by default) and, where permitted by the peer map, consults one peer before deciding. The simulator retains execution control, requiring every decision to pass through a policy gate before execution.

All runtime activity is recorded in a unified event log. The Dragon-King Runtime Monitoring Model (DK-RMM) processes this log and evaluates twenty behavioral and operational indicators against their respective baselines. It classifies the ecosystem as STABLE, DEVIATING, UNSTABLE, or undergoing a Runtime Critical Transition (RCT), while using critical slowing down (CSD) and Dragon-King tests to identify potential warning signals. DK-RMM is observational; its findings are subject to human validation rather than automatically triggering interventions.

<p align="center">
  <img src="docs/img/interaction-graph.png" alt="The agent hierarchy: supervisor, planner, six experts with their sub-agents, and the five robots" width="820">
  <br><em>The agents: supervisor, planner, the six experts with their sub-agents, and the robots each expert can task.</em>
</p>

<p align="center">
  <img src="docs/img/floor.png" alt="The facility floor: zones, parcels in intake, five robots at the charging zone, six van routes" width="620">
  <br><em>The floor, live: zones, parcels, robots shaded by charge, and the van bays.</em>
</p>

## Scenarios

The live page offers five scenarios. All run on the same facility.

| Scenario | What happens |
|---|---|
| **Normal** | Ordinary operation with its own variability; experts on rules first, the model when a rule is insufficient. |
| **M-S-DROP** | From tick 400, every message on the bus is dropped at delivery. |
| **M-S-DELAY** | From tick 400, routing messages are delayed by 10 ticks. |
| **ON-OFF, rules only** | ROUTING and SCHEDULING alternate between their rules (OFF) and deliberate violations (ON) in four phases from tick 1200 to 3800, while a consignment of 20 urgent hospital parcels arrives. Every expert on its rules. |
| **ON-OFF, model** | The same, with the experts on rules first and the model when a rule is insufficient. Needs Ollama. |

Further presets (the C2-NEAR conditions, C-S-STARVE, C-S-PARTITION and
M-S-STALL) are kept for the batch drivers in `tools/` and the API
(`POST /simulation/reset?preset=...`).

## DK-RMM: indicators and evidence kinds

DK-RMM computes twenty indicators per window, from the event log and a
read-only snapshot of the facility (`post_office/dkrmm/indicators.py`). The
first twelve describe how the agents behave; the last eight, added later, are
operational and early-warning indicators. *Window* indicators come from one window's events and snapshot;
*history* indicators from histories the monitor keeps. An indicator counts as
deviating when its z-score against its baseline reaches 2.0 in the direction
shown.

| # | Indicator | Group | From | Counts on | Evidence kind | What it measures |
|---|---|---|---|---|---|---|
| 1 | `message_frequency` | behavioural | window | rise or fall¹ | chatter | Messages attempted per tick, of any kind |
| 2 | `interaction_density` | behavioural | window | rise or fall¹ | chatter | How much of the possible conversation is actually happening |
| 3 | `delegation_frequency` | behavioural | window | rise | chatter | Work handed down to sub-agents per tick |
| 4 | `retry_frequency` | behavioural | window | rise | retry | Attempts abandoned and begun again per tick |
| 5 | `guardrail_events` | behavioural | window | rise | refusal | Refusals per tick: the policy gate, the intake gate, a full shelf |
| 6 | `tool_call_frequency` | behavioural | window | rise | chatter | Answers coming back up from sub-agents per tick |
| 7 | `task_switching` | behavioural | window | rise | congestion | How often work changes hands, per tick |
| 8 | `execution_latency` | behavioural | window | rise | congestion | Mean ticks from a task being created to it being started |
| 9 | `agent_coupling` | behavioural | window | rise or fall¹ | herding | Share of the roster that emitted any event this window (an active-agent fraction) |
| 10 | `behavioural_similarity` | behavioural | window | rise or fall¹ | herding | How alike the agents' activity is |
| 11 | `persistence_of_deviation` | behavioural | history | rise | —² | Consecutive windows the facility has been off its baseline |
| 12 | `propagation_across_agents` | behavioural | history | rise | spread | Share of the acting agents showing the deviation |
| 13 | `communication_failure_rate` | operational / early-warning | window | rise | delivery | Share of attempted messages that were dropped or delivered late |
| 14 | `backlog_growth` | operational / early-warning | history | rise | backlog | Parcels inside the building, change per tick since the last reading |
| 15 | `task_completion_rate` | operational / early-warning | window | fall | throughput | Parcels that left on vans per tick |
| 16 | `completion_gap` | operational / early-warning | window | rise | throughput | Parcels arriving per tick minus parcels leaving per tick |
| 17 | `resource_saturation` | operational / early-warning | window | rise | saturation | The tightest of robots, charge points, routes, storage and the dock, as a share of its capacity |
| 18 | `dependency_graph_divergence` | operational / early-warning | history | rise | structure | How far this window's who-talks-to-whom is from its baseline shape |
| 19 | `activity_synchronization` | operational / early-warning | window | rise or fall | synchrony | How much the acting agents' activity rises and falls together |
| 20 | `tail_deviation` | operational / early-warning | history | rise | congestion | The worst-case waits and backlogs against their own baseline p95 |

¹ A fall counts only when something operational is also off: a quiet facility
with normal output is not deviating.
² Not an evidence kind of its own: the monitor's persistence count feeds the
state directly (see below).

Indicators are grouped into twelve evidence kinds
(`EVIDENCE` in `post_office/dkrmm/monitor.py`), so that several indicators
driven by the same underlying events count as one finding, not several. The
four operational kinds are read even in a window too quiet to read the agents.

| Evidence kind | Type | Indicators | What it signals |
|---|---|---|---|
| refusal | behavioural | `guardrail_events` | Decisions and requests being refused by the gates |
| retry | behavioural | `retry_frequency` | Work being abandoned and started again |
| congestion | behavioural | `execution_latency`, `task_switching`, `tail_deviation` | Work queuing: longer waits, more hand-offs, worse tails |
| chatter | behavioural | `message_frequency`, `delegation_frequency`, `tool_call_frequency`, `interaction_density` | The volume of communication moving away from normal |
| herding | behavioural | `behavioural_similarity`, `agent_coupling` | The agents acting more (or less) alike than usual |
| spread | behavioural | `propagation_across_agents` | The deviation reaching a growing share of the agents |
| structure | behavioural | `dependency_graph_divergence` | Who talks to whom changing shape |
| synchrony | behavioural | `activity_synchronization` | The agents' activity rising and falling together |
| delivery | operational | `communication_failure_rate` | Messages dropped or delivered late |
| backlog | operational | `backlog_growth` | Parcels accumulating inside the building |
| throughput | operational | `task_completion_rate`, `completion_gap` | Fewer parcels leaving than arriving |
| saturation | operational | `resource_saturation` | A resource close to its capacity |

The state follows from the kinds present:

- **DEVIATING**: at least one kind.
- **UNSTABLE**: at least two kinds that also held in the previous window, or
  any kind while the facility has been off its baseline for three windows
  running.
- **RCT**: at least three kinds, one of them held from the previous window,
  at least half of the acting agents affected, and either a dragon-king
  extreme or critical slowing down (variance and memory both climbing).

## The live page

`python main.py --api` serves it at `http://127.0.0.1:8000/`:

- **Robots & agents**: the floor and the interaction graph, following the run tick by tick.
- **Consultations**: each model consultation, the question and the peer's answer, the decision, latency and tokens.
- **DK-RMM**: the state, the indicators with their z-scores, CSD and the dragon-king test, the RCT explainer and the human gate (validate, activate, dismiss).
- **Runtime communication**: every message and event, classified by channel and interaction type.
- **Consultation trajectory** and **Event trajectory**: the run so far, as consultations on a clock and as events in order.
- **RCT log**: every RCT DK-RMM detected, with what drove it, saved under `results/live/` (`--no-record` to save nothing).
- **ON–OFF** (on the two ON-OFF scenarios): the phases, the robots' blockages, the hospital consignment and the run's summary.

## Quick start

Python 3.10 to 3.13 (3.12 recommended) and, for the model-backed experts,
[Ollama](https://ollama.com).

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                 # Windows: copy .env.example .env
ollama pull qwen3:8b
python tools/verify_ollama.py        # one row per expert, with the model Ollama served
python tools/run_normal.py --ticks 300 --seed 1   # evidence in results/normal/s1/
python main.py --api                 # the live page
```

Without Ollama, `python main.py --api --rules` and `python tools/run_normal.py --rules`
run every expert on its rules.

## Switching the model

The model is configuration only: set `OLLAMA_MODEL` in `.env`, for example
`OLLAMA_MODEL=gemma4:26b` after `ollama pull gemma4:26b`, and run
`tools/verify_ollama.py` to confirm that all seven rows show the new served
model. All seven experts share one LLM, so they move together. The provider is
always Ollama.

## Tests

```bash
PYTHONHASHSEED=0 python -m pytest -q
```

The suite needs no Ollama: it starts a fake OpenAI-compatible server in the test
process and drives the real CrewAI integration through it. The browser tests of
the live page need the `ui-test` extra (`pip install -e ".[ui-test]"`, then
`python -m playwright install chromium`) and are skipped without it.

## Repository layout

```
post_office/          the simulation
  simulation/ core/ state/ environment/ robots/ tasks/   the facility and its clock
  agents/ crew/ discussion/ policy/ communication/       experts, CrewAI and Ollama, peer consultation, the gate
  dkrmm/              the runtime monitor (indicators, signals, states)
  observability/      event log, run records, RCT recorder, decision traces
  stress/             the scenarios (collapse, ON-OFF, C2-NEAR)
  api/ ui/            FastAPI server and the live page
tools/                batch drivers, analyses, figures, Ollama check
tests/                pytest suite (fake Ollama, Playwright for the page)
docs/packages/        one page per package
main.py               command line: run, or serve the live page
```

## Documentation

- [docs/packages/README.md](docs/packages/README.md): one page per package.
