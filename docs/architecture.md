# Architecture

Prototype II is the NORMAL post-office ecosystem of the source project with its model
layer replaced. CrewAI replaces the implementation of model-backed peer consultation at
the Brain seam while preserving the existing peer map and consultation semantics. The
simulator, its deterministic rules, the policy gate and DK-RMM were copied from the source;
what is new lives in `post_office/crew/` and `post_office/config/ollama.py`. Where every
file came from is recorded in [provenance.md](provenance.md).

## The layers

```
POST-OFFICE SIMULATOR (authoritative Python)
  environment, parcels, tasks, robots, vans, generator, clock,
  message bus, event logger, policy gate, deterministic rules, recovery
        | state                                   ^ validated action
        v                                         |
SEVEN EXPERT AGENTS  BaseAgent.decide: rules -> triggers -> rule_insufficient -> brain -> gate
        | rules insufficient                      ^ Answer
        v                                         |
CREWBRAIN (post_office/crew/brain.py, the Brain seam)
        | ConsultationService.run (post_office/crew/consultation.py)
        v
CREWAI AGENT (owner) --tool: one question or delegation--> CREWAI AGENT (the one allowed peer)
        |                                                     |
        v                                                     v
OLLAMA, OpenAI-compatible endpoint <OLLAMA_BASE_URL>/v1, model qwen3:8b (one shared LLM)
        |
        v
EVENT LOG: CONSULT_* bus messages, consult_* and llm_call events, decision events
        |
        v
DK-RMM (an EventLogger subscriber): observe and assess only
```

The simulator is the authority. `PostOfficeEcosystem.step` in
`post_office/simulation/ecosystem.py` advances the clock and the bus, delivers the messages
sent in the previous tick, lets the generator add parcels, steps every agent in a fixed
declared order (supervisor, planner, the six other experts, the fifteen sub-agents, the five
robots), runs the recovery service, lets vans depart and writes a snapshot. Nothing in the
model layer writes to the world: an expert's model can only return an `Answer` whose choice
is one of the question's admissible options, the policy gate checks it, and the agent's own
Python applies it (see [consultation.md](consultation.md), section "Simulator authority").

The seven experts keep the source's rules, triggers and decision pipeline. `BaseAgent.decide`
in `post_office/agents/base.py` asks the rule first; only when `rule_insufficient` returns a
trigger does it call the brain, through `answer_consulting(question, trigger)` when the brain
offers it. The source's asynchronous dispatcher and discussion manager are gone: every
decision, the model's included, is answered inside the `decide` call. The roles and the line
between model and deterministic agents are described in [agents.md](agents.md).

`CrewBrain` is the Brain seam adapter. It starts every decision from the rule's answer, hands
the decision to the consultation service the ecosystem binds to it, and returns the
service's answer or the rule's answer marked as a fallback. The service finds the one peer
the copied peer map (`post_office/discussion/peers.py`) allows for the owner, the decision
kind and the trigger condition, gives the owner's CrewAI agent tools bound to that peer
alone, runs `execute_task` in a worker thread joined with the consultation deadline, and
parses the owner's `DECISION:` line. The protocol is in [consultation.md](consultation.md).

All seven CrewAI agents share one `crewai.LLM` built by `post_office/crew/llm.py`: provider
`ollama`, served by CrewAI 1.15's `OpenAICompatibleCompletion` at `<OLLAMA_BASE_URL>/v1`, with
`OllamaAudit` as its transport interceptor. The audit refuses any request to another host and
turns every HTTP round trip into an `llm_call` record. Before any brain is built,
`require_model` asks the Ollama server whether the configured model is installed; nothing is
substituted if it is not. See [crewai-ollama.md](crewai-ollama.md).

All runtime evidence goes through the one existing `EventLogger` and `MessageBus`: the
`CONSULT_REQUEST`, `CONSULT_RESPONSE` and `CONSULT_CLOSE` messages, the `consult_*` events,
one `llm_call` event per model call and the unchanged `decision` record extended with the
consultation id, peer and turns. The inventory and the ordering rules are in
[events.md](events.md).

DK-RMM (`post_office/dkrmm/`, copied unchanged) is attached from the first run. It subscribes
to the event logger and is ticked by whoever drives the run (`main.py`, `tools/run_normal.py`
and `SimulationRunner` in `post_office/api/runner.py`), after each `eco.step()`. It reads,
assesses and keeps its history; nothing reads its state back into the run. See
[dkrmm.md](dkrmm.md).

## Inert seams

Two interception layers sit on every consultation (`post_office/crew/interception.py`), the
message bus keeps its `delay_rule` hook, and `BaseAgent.facts_filter` is still the hook on
what an agent is told. In NORMAL all of them are identity or `None`, and the ecosystem refuses
any configuration that asks for a perturbation before the event logger opens. The seams and
how future perturbations would attach are in [perturbation-seams.md](perturbation-seams.md).

## Process and threads

A run driven from `main.py` or `tools/run_normal.py` is one thread that steps the ecosystem
and ticks DK-RMM. A consultation runs the owner's CrewAI loop in a worker thread; the tick's
thread waits for it in `join` with `CONSULT_DEADLINE_S`, so the simulated clock does not move
while a consultation is open. Under `main.py --api`, `SimulationRunner` ticks in a background
thread under one lock per tick and publishes a frame after every tick; the HTTP and WebSocket
reads answer from that frame or from accessors that do not take the lock, so the page never
waits for a consultation and may show the run one tick behind. See [running.md](running.md).

## Where to read next

How to run it is in [running.md](running.md), how to check that it really used Ollama and
`qwen3:8b` is in [verification.md](verification.md), what the rules-only alignment with the
source covers is in [alignment-baseline.md](alignment-baseline.md), and what is known to be
weak is in [limitations.md](limitations.md).
