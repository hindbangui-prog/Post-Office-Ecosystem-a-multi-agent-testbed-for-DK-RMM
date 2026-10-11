# Post Office Ecosystem Prototype II

## Overview

Prototype II is a multi-agent simulation of an automated post office: a facility with parcels,
shelves, charge points, vans and five robots, run by a supervisor, seven expert agents and
fifteen sub-agents, and watched by DK-RMM, a runtime monitor that reads the event stream. It
reproduces the NORMAL ecosystem of its source project and replaces only the model layer:
CrewAI replaces the implementation of model-backed peer consultation at the Brain seam while
preserving the existing peer map and consultation semantics.

The seven experts (Planner, Intake, Sorting, Scheduling, Routing, Resource, Dispatch) decide by
their deterministic rules first. Only when a rule is insufficient does the expert's CrewAI agent
reason on a local Ollama model, `qwen3:8b` by default, and it may consult exactly the one peer
the source's peer map allows for that decision. The peer's advice comes back before the owner
decides, and the decision is then validated by the policy gate and executed by the simulator.
Every exchange and every model call is written to the one event log, which DK-RMM observes and
assesses without influencing anything. No perturbation is implemented; the seams where
perturbations will later attach exist and are inert.

## Quick start

On Windows, in the project directory, with Python 3.12 and Ollama installed:

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env
ollama pull qwen3:8b
.venv\Scripts\python tools\verify_ollama.py
.venv\Scripts\python tools\run_normal.py --ticks 300 --seed 1
.venv\Scripts\python main.py --api
```

`tools/verify_ollama.py` prints one row per expert showing the model the server served;
`tools/run_normal.py` runs NORMAL on the model and writes its evidence to `results\normal\s1\`;
`main.py --api` serves the live page at `http://127.0.0.1:8000/`. Its Trajectory tab follows the
run's events as they are logged, with an Expert consultation view of each consultation's model
calls, and its RCT log tab lists the RCTs DK-RMM detected, which `main.py --api` saves with their
cause under `results/live/` (`--no-record` to save nothing). Without Ollama, `main.py
--rules` and `tools/run_normal.py --rules` run every expert on its rules. Details are in
[docs/running.md](docs/running.md).

## Switching the model

The model is configuration only: set `OLLAMA_MODEL` in `.env` or the environment, for example
`OLLAMA_MODEL=gemma4:26b` after `ollama pull gemma4:26b`, and run `tools/verify_ollama.py` to
confirm that all seven rows show the new served model. No code changes, and all seven experts
move together because they share one LLM. The provider is always Ollama; a model name
containing `/` is refused. See [docs/crewai-ollama.md](docs/crewai-ollama.md).

## Running the tests

```
set PYTHONHASHSEED=0
.venv\Scripts\python -m pytest -q
```

(on Linux or macOS: `PYTHONHASHSEED=0 .venv/bin/python -m pytest -q`). The suite needs no
Ollama: it starts a fake OpenAI-compatible Ollama server in the test process and drives the real
CrewAI integration through it. The browser test of the live page needs the optional `ui-test`
extra (`pip install -e ".[ui-test]"`, then `python -m playwright install chromium`) and is
skipped without it. The inventory is in [docs/verification.md](docs/verification.md).

## Documentation

[docs/architecture.md](docs/architecture.md) describes the layers, from the authoritative
simulator through the experts, CrewBrain and CrewAI to Ollama and DK-RMM.
[docs/dkrmm-mathematics.md](docs/dkrmm-mathematics.md) reconstructs the mathematics DK-RMM actually
computes, from event collection to RCT detection, with code and test references for every formula.
[docs/dkrmm-sequences.md](docs/dkrmm-sequences.md) shows one assessment as a sequence diagram for each
outcome: STABLE, DEVIATING, UNSTABLE, RCT and the dragon-king flag.
[docs/simulation-diagrams.md](docs/simulation-diagrams.md) explains how ticks are used and draws the
tick loop, the role of CrewAI, and how agents decide and robots act.
[docs/c2-near-system-override.md](docs/c2-near-system-override.md) reports the
C2-NEAR-SYSTEM-OVERRIDE experiment: an isolated, collapse-only run of the Normal facility under a
workload surge, two closed routes, one remaining charge point and a System Override campaign,
with its own driver and results directory. It leaves the Normal scenario unchanged: N and C0 build
from `normal_config()` as it is, nothing under `results/normal/` is read or written, and the
300-tick Normal event stream is identical before and after the change.
[docs/packages/README.md](docs/packages/README.md) has one page per package of `post_office`,
each with a short description and a class diagram, and the dependencies between packages.
[docs/agents.md](docs/agents.md) covers the seven roles, the rules-first policy and the line
between model-backed and deterministic agents. [docs/crewai-ollama.md](docs/crewai-ollama.md)
explains how the shared LLM is built, the transport audit, the model identity check and every
configuration variable. [docs/consultation.md](docs/consultation.md) gives the peer map, the
synchronous consultation protocol, its outcomes, the operational meaning of "real time", and
why the simulator stays in charge. [docs/events.md](docs/events.md) lists every event and
message a consultation writes, their order, the `llm_call` record and the definition of
`retries`, and gives the runtime communication taxonomy: the `interaction_type` and `channel`
stamped on every event, the channels and types `GET /taxonomy` serves, the precedence of the
classifier and the receiver, pairing, latency and model rules of the live page's Runtime
communication view. [docs/dkrmm.md](docs/dkrmm.md) describes how DK-RMM is attached, why it only
observes and assesses, the person-only gate, the recorder and the RCT explainer, the verified
delegation semantics, the independence tests and why the taxonomy's stamp is metadata to it.
[docs/perturbation-seams.md](docs/perturbation-seams.md) documents the inert seams, the future
perturbations they would carry, and the frozen-delegation path.
[docs/alignment-baseline.md](docs/alignment-baseline.md) explains how rules-only NORMAL is shown
to reproduce the source's world and DK-RMM readings. [docs/running.md](docs/running.md) covers
installation, the command line and the live page, including the Trajectory and RCT log tabs, the
DK-RMM gate and recording. [docs/verification.md](docs/verification.md)
says how to verify Ollama usage, `qwen3:8b` and DK-RMM's input, and what the real-run report
contains; [docs/real-run-2026-10-02.md](docs/real-run-2026-10-02.md) records the first real
run against a local `qwen3:8b`. [docs/limitations.md](docs/limitations.md) lists the risks and
known weaknesses.
[docs/provenance.md](docs/provenance.md) records the source identity and the origin of every
file. Next to it in `docs/` is the removal record, the grep and the dependency audit showing
that the source's model framework is gone; this README does not link it by name, because that
framework's name may appear only in the removal records themselves. The approved design and the implementation plan are under
`docs/superpowers/`.

## Provenance

The source project was only read, never modified. `docs/provenance.md` (and `.json`, generated
by `tools/write_provenance.py`) gives the source tree's SHA-256 at the start and at the end, and
every file of this project with its class (unchanged, adapted, replaced, new) and the SHA-256 of
its source counterpart, plus the source files that were removed and why.
