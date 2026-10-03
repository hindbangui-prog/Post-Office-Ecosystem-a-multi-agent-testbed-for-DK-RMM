# Post Office Ecosystem Prototype II: design specification

Status: draft for review. No implementation has started.
Date: 2026-10-01
Source project: `C:\Users\hindb\Projects\two_agent_test\post_office_discuss` (read only, never modified)
Target project: `C:\Users\hindb\Projects\post office ecosystem prototype II`

Terminology used throughout: **CrewAI** is the agent/orchestration and consultation
mechanism; **Ollama** is the local model-serving backend; **qwen3:8b** is the baseline
model; the **simulator** is the authoritative industrial world; the **peer map** is the
authoritative interaction topology; **CrewBrain** is the Brain-layer adapter to CrewAI;
**DK-RMM** is the independent runtime monitoring and assessment layer; **perturbation
seams** are the future, inactive stress-insertion points.

The one-sentence description of the change: CrewAI replaces the implementation of
model-backed peer consultation at the Brain seam while preserving the existing peer map
and consultation semantics.

---

## 1. Scope and objective

Prototype II is a new, independent project that reproduces the NORMAL post-office
ecosystem of the source project and replaces its model layer. The simulator (facility,
parcels, tasks, robots, vehicles, generator, clock, bus, event logger, policy gate,
deterministic rules, recovery) is carried over unchanged. The seven expert agents keep
their roles, rules, triggers and decision pipeline; what changes is what happens behind
the `Brain` seam when the rules are insufficient: a CrewAI agent reasons on Ollama's
`qwen3:8b`, may consult exactly the one peer the existing peer map allows for that
decision and condition, incorporates the peer's answer, and returns a decision that the
simulator validates and applies. DK-RMM is attached from the first run as an
observe/assess layer fed by the existing event stream. No perturbation is implemented;
the seams where perturbations will later attach are present, documented and inert.

Out of scope for this phase: any attack or perturbation, experiment batteries,
scenario families other than Normal, the SQLite trace store and replay viewers of the
source, response caching, asynchronous model dispatch.

## 2. Source and provenance

Inspection results (work tree mirrored from the source on 2026-10-01): package
`post_office` with 35,440 lines of Python across 21 sub-packages; 63 test files;
`tools/` with 50 experiment scripts; CAMEL-AI pinned as `camel-ai==0.2.90` with
`mcp<2`; the model layer is `agents/camel_brain.py` (928 lines), `agents/llm_async.py`
(813), `discussion/manager.py` (377), `config/providers.py::create_model`; the
discussion topology is `discussion/peers.py` (24 owner/kind/condition → peer entries).

`docs/provenance.md` in Prototype II records the source identity (the git commit of
`post_office_discuss` if the directory is a repository, otherwise "no git repository",
plus the SHA-256 of the whole source tree at copy time) and lists every file with its
classification (copied unchanged / adapted / replaced / new / removed), the source path,
and the SHA-256 of the source file at copy time, so that any later divergence from the
source can be located. Files copied unchanged are byte-identical to the source except for line
endings, which are normalised to LF in the new project.

### 2.1 File classification (summary; the full list is in the implementation plan)

Copied unchanged: `core/` (ids, rng, visible, world), `environment/` (all),
`state/`, `tasks/`, `robots/`, `policy/gate.py`, `communication/` (bus, directory,
events, message with three added enum members, provenance, topics),
`simulation/generator.py`, `simulation/recovery.py`, `dkrmm/` (all five modules),
`agents/reasoning.py`, `agents/brain.py`, `agents/assignment_metrics.py`,
`agents/robot_agent.py`, `agents/supervisor.py`, `agents/subagents/` (all),
`discussion/peers.py`, `discussion/briefings.py`, `discussion/prompts.py`,
`observability/context.py`, `ui/live.py` helpers that the trimmed page needs,
the simulator/rules/gate/DK-RMM test files.

Adapted: the seven expert modules (one import line each: `Deferral`, `is_pending`
now come from `agents/deferral.py`), `agents/base.py` (async dispatcher and
discussion-manager hooks removed; the sync path hands the fired trigger to a brain
that accepts it), `simulation/ecosystem.py` (no perturbation controller, propagation
trace, async dispatcher or discussion manager; installs CrewBrains and the inert
interception layer), `config/settings.py` (Normal only; `llm_brains` builds
CrewBrains), `api/runner.py`, `api/server.py`, `api/digest.py` (monitor digest only),
`ui/live.html`, `ui/views.py`, `main.py`, `pyproject.toml`, `requirements.txt`,
carried tests that referenced removed machinery.

Replaced: `agents/camel_brain.py` → `crew/brain.py` + `crew/consultation.py` +
`crew/tools.py` + `crew/roles.py`; `config/providers.py` → `crew/llm.py` +
`config/ollama.py`; `discussion/manager.py` → `crew/consultation.py`;
`agents/llm_async.py` → `agents/deferral.py` (the `Deferral` record and decision
status constants only); `ui/discussions.html` → consultation pane in `live.html`;
`ui/settings.html` → model status block in `live.html`.

Removed: `agents/llm_async.py`, `agents/camel_brain.py`, `agents/response_cache.py`,
`discussion/manager.py`, `discussion/bias.py`, `perturbation/` (all), `perturbation.py`,
`stress/` (all), `config/experiments.py`, `api/injections.py`, `observability/`
except `context.py`, `ui/rcts.html`, `ui/settings.html`, `ui/discussions.html`,
`ui/viewer.html`, `run.py`, `run_discuss.bat`, `scripts/`, `results/`, `logs/`,
`docs/async-llm.html`, `docs/2026-09-29-pstar-matched-pilot.md`, all `tools/` except
`normal_fingerprint.py` (adapted), and the CAMEL, async-dispatch, discussion-manager,
perturbation, stress and experiment tests.

## 3. Architecture retained

```
POST-OFFICE SIMULATOR (authoritative Python)
  environment · parcels · tasks · robots · vehicles · generator · clock
  communication bus · event logger · policy gate · deterministic rules · recovery
        │ state                                     ▲ validated action
        ▼                                           │
SEVEN EXPERT AGENTS (BaseAgent.decide: rules → triggers → rule_insufficient → brain → _validate)
        │ consult (rules insufficient)              ▲ Answer
        ▼                                           │
CREWBRAIN (Brain seam adapter)
        │ owner Task (+ AskPeer/DelegateToPeer tool bound to the ONE allowed peer)
        ▼
CREWAI AGENT (owner) ──question/delegation──▶ CREWAI AGENT (allowed peer) ──response──▶ owner
        │                                              │
        ▼                                              ▼
OLLAMA (local, OpenAI-compatible endpoint /v1)  ·  model qwen3:8b
        │
        ▼
runtime evidence: bus messages (CONSULT_*), agent events (consult_*, llm_call, decision)
        │
        ▼
DK-RMM (EventLogger subscriber; indicators · states · RCT): observe/assess only
```

Retained from the source, unchanged in semantics: the tick loop
(`PostOfficeEcosystem.step`: world/bus advance, deliver, generator, agents in tick
order, recovery, van departures, snapshot), the `Question`/`Answer` contract with
admissible `options`, `BaseAgent.decide` with its `decision` event record (`path`,
`status`, `validation`, `trigger`, `latency_ms`), the policy gate (`schema` → `policy`
→ `state`), the message bus with `Directory.may_send`, the event logger with its
`{seq, tick, wall_clock, run_id, category, topic, actor, target, correlation_id,
detail}` rows, and DK-RMM (`DKRMM(eco).attach()`, assessed every 20 ticks over a
60-tick window with a 24-window baseline, six evidence kinds, five states).

Explicitly not done: CrewAI `Flow` as the simulation loop; a Crew per tick; converting
routine decisions into model tasks; letting the model write to world state.

## 4. Seven expert roles

The seven experts and their ids are exactly those of the source:

| Agent id   | CrewAI `role` | Responsibilities (from the source modules, unchanged) |
|------------|---------------|--------------------------------------------------------|
| PLANNER    | Planner       | releases work to the floor, replans under contention/no robots/shelves filling |
| INTAKE     | Intake        | accepts or refuses arriving parcels, dock pressure, destination known |
| SORTING    | Sorting       | classifies destination and priority, shelf choice, paid parcels |
| SCHEDULING | Scheduling    | chooses robots and next tasks, deadlines, competing/promoted work |
| ROUTING    | Routing       | resolves blocks and detours, charge-aware rerouting |
| RESOURCE   | Resource      | charge points, storage acceptance, capacity ceilings |
| DISPATCH   | Dispatch      | releases parcels to vans, promises, van capacity |

Their rule sets (`install_rules`), triggers (`install_triggers`), sub-agent
relationships, message vocabulary and position in the tick order are copied from the
source without change. Each expert's CrewAI `goal` and `backstory` are written from
the source's `SYSTEM_TEMPLATE` ("You are the {role} of an automated post office …
reply with exactly one allowed answer") and the module docstrings of the corresponding
agent, so the behavioural reference is the source, not a new design.

Non-LLM, unchanged: `SUPERVISOR`, the fifteen `SUB-*` sub-agents, the five robots
(`RobotAgent`), the environment, the recovery service, DK-RMM. `llm_brains()` raises
`ValueError` for any id outside the seven.

## 5. LLM boundary

Exactly seven `CrewBrain` instances exist per ecosystem, one per expert id. Every other
agent's `brain` is a `DeterministicBrain`. The test `test_roles_preserved.py` asserts
`sorted(id for id, a in eco.agents.items() if a.brain.name == "crewai") ==
["DISPATCH", "INTAKE", "PLANNER", "RESOURCE", "ROUTING", "SCHEDULING", "SORTING"]` and
that no robot, sub-agent or supervisor brain has `name == "crewai"`. DK-RMM imports
nothing from `crew/`, `agents/` or CrewAI, which `test_dkrmm_independence.py` asserts by
inspecting `sys.modules` dependencies of `post_office.dkrmm`.

The execution path for every model decision is `CrewBrain → crewai.Agent.execute_task →
crewai.LLM (provider "ollama", OpenAICompatibleCompletion) → HTTP POST
{OLLAMA_BASE_URL}/v1/chat/completions → qwen3:8b`. No other component constructs an
LLM, and no code path reads `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or any other
provider key.

## 6. CrewAI Brain integration

### 6.1 CrewBrain (Brain contract)

`post_office/crew/brain.py::CrewBrain(agent_id, fallback: DeterministicBrain,
crew_agent: crewai.Agent, consultation: ConsultationService, config: OllamaSettings)`
implements the duck-typed contract the source agents rely on:

- `name = "crewai"`, `reads_prompt = True`, `last_prompt`.
- `fallback` is the `DeterministicBrain` the agent fills through `install_rules()`
  (`BaseAgent.rules()` depends on this).
- `config.model_type` = the configured model (`qwen3:8b`), `config.seed`.
- `answer(question) -> Answer` (no peer; used when `decide` has no trigger information).
- `answer_consulting(question, trigger) -> Answer`: the entry `BaseAgent.decide` uses
  when a trigger fired. It calls `consultation.run(owner_id, question, trigger)`.
- `stats()` → `{brain: "crewai", model, provider: "ollama", base_url, calls,
  consultations, questions, delegations, fallbacks, rejected_answers, parse_failures,
  timeouts, reachable, last_error, mean_latency_ms}`.
- `close()`.

The `Answer` it returns has `source = f"crewai:{model}"` on success,
`source = "fallback"` with the reason appended to `reason` on any failure (unreachable
Ollama, timeout, no DECISION line, choice not in options). `BaseAgent.decide` records
these exactly as it records the source's `camel:<model>` and `fallback` answers:
`path = "llm/<trigger reason>"` or `"fallback"`, `status` from the same constants.

### 6.2 BaseAgent.decide change (the only change to the decision pipeline)

The async branch (dispatcher, deferral, in-flight join, stale streak, discussion open)
is removed. The sync branch becomes:

```python
started = time.perf_counter()
with bracket():
    if mode == "llm" and hasattr(self.brain, "answer_consulting"):
        answer = self.brain.answer_consulting(question, trigger)
    else:
        answer = self.brain.answer(question)
if mode == "llm":
    latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
```

`deferral` stays an accepted parameter (the seven agents construct `Deferral` records)
and is ignored, as it already is in the source's sync path. Everything after
(`_validate`, refusal → rule-after-refusal, the `decision` event) is unchanged.
`_settle_pending`, `_record_pending`, `_settle`, `_discussion_peer`, and the
`llm_dispatcher`/`discussions` attributes are removed. `step()` drops `CONSULT_*`
messages addressed to the agent without handling them: the exchange they record has
already been completed synchronously inside the consultation.

### 6.3 CrewAI agents

`post_office/crew/roles.py::build_agents(llm) -> dict[str, crewai.Agent]` creates one
agent per expert id with: `role` as in §4, `goal`/`backstory` from the role table,
`llm=llm` (one shared instance), `allow_delegation=False` (CrewAI must never attach its
own all-coworker tools), `tools=[]`, `max_iter=4`, `max_retry_limit=1`,
`verbose=False`, `cache=False`, `memory=False`, `respect_context_window=True`.
Verified on CrewAI 1.15.23: a crew-less `Agent.execute_task(task, context, tools)`
runs the agent's reasoning loop, executes the tools it is given, and returns the final
text (probe run in this design phase: three HTTP calls, owner → peer → owner, with the
peer's reply changing the owner's decision).

## 7. Existing peer-map preservation

`discussion/peers.py` is copied unchanged and remains the only source of truth for who
may be consulted: `peer_for(owner, kind, condition) -> peer id | None`, keyed by the
owner id, the decision kind and the trigger's `condition` (the name of the trigger
condition function, e.g. `equally_placed`, `van_too_small`). The 24 entries are those
of the source (PLANNER→SCHEDULING/RESOURCE, INTAKE→PLANNER/SORTING, SORTING→RESOURCE/
DISPATCH, SCHEDULING→RESOURCE/ROUTING/DISPATCH, ROUTING→RESOURCE/SCHEDULING,
RESOURCE→SCHEDULING/DISPATCH, DISPATCH→SCHEDULING).

`test_peer_map_preserved.py` asserts the table equals the source table verbatim (the
test file carries the 24 tuples). `test_allowed_peer_enforcement.py` asserts that for a
consultation the owner's tool set contains tools bound to exactly `[peer]`, that a
request naming any other coworker is refused with a logged `peer_refused` event and no
model call, and that an owner/kind/condition without a peer gets no tools at all.
CrewAI's own coworker graph is never built: `allow_delegation=False` on every agent and
no `Crew` object exists in the normal path.

## 8. Synchronous consultation protocol

`post_office/crew/consultation.py::ConsultationService(agents, llm, world, bus, logger,
interception, settings)` with `run(owner_id, question, trigger) -> Answer`:

1. `peer = peer_for(owner_id, question.kind, trigger.condition)`; a `consultation_id`
   `CSL-%04d` is minted; `consult_opened` is emitted (owner, peer or none, kind,
   condition, decision_id).
2. The owner `Task` description is `render(question)` (the source format: `Decision:
   <kind>`, prompt, `Facts:` sorted key/values, `Allowed answers:` list), plus, when a
   peer exists, "You may ask <Peer> one question with the tool `Ask question to
   coworker`, or delegate one sub-question with `Delegate work to coworker`; the answer
   is advice, the decision is yours", plus "End with exactly one line `DECISION: <one
   allowed answer>`". `expected_output` is "a DECISION line".
3. Tools (only when a peer exists): `AskPeerTool(agents=[peer_agent])` and
   `DelegateToPeerTool(agents=[peer_agent])`, subclasses of CrewAI's `AskQuestionTool`
   and `DelegateWorkTool`, sharing one `ConsultationContext` that allows one exchange
   per consultation. Each `_run`:
   a. builds `ConsultRequest(consultation_id, tick, sender=owner, receiver=peer,
      interaction_type="question"|"delegation", text, context)`;
   b. passes it through `interception.on_request` (identity in Normal);
   c. emits `consult_question`/`consult_delegation` and sends a bus message
      `CONSULT_REQUEST` (content: consultation_id, decision, condition, text,
      interaction_type) from owner to peer;
   d. calls `super()._run(...)` with `context` = the peer's briefing
      (`briefing_for(peer_agent)` from the copied `briefings.py`, computed at that
      moment from the live world) prefixed with "You are consulted by <Owner>; answer in
      at most three sentences; recommend, do not act"; CrewAI runs
      `peer.execute_task(Task(...))`, which is the peer's own Ollama call(s);
   e. builds `ConsultResponse(... text, latency_ms, model)`, passes it through
      `interception.on_response`, emits `consult_response`, sends `CONSULT_RESPONSE`
      peer → owner, and returns the text into the owner's loop.
   A second tool use in the same consultation returns the string "You have already
   consulted <Peer> for this decision; decide now." and emits `consult_refused`.
4. `owner.execute_task(task, tools=tools)` runs under a wall-clock budget
   `CONSULT_DEADLINE_S` (default 300). The owner's final text is parsed with the copied
   `parse_decision(text, options)`; if it yields no option, the `CamelBrain.parse`
   heuristics (copied into `crew/parse.py`: first visible line match, token match,
   unique mention) are tried; `<think>…</think>` blocks are stripped first
   (`core/visible.py`).
5. Outcome: a valid choice → `Answer(choice, reason=<owner's last visible line>,
   source=f"crewai:{model}", confidence=1.0)`; otherwise `Answer(rule.choice,
   f"{rule.reason} [fallback: <why>]", source="fallback")`. `consult_closed` is
   emitted with outcome ∈ {decided, no_valid_decision, timeout, model_failed,
   peer_failed}, choice, turns, latency_ms, model, and `CONSULT_CLOSE` is sent
   owner → peer when a peer was involved.
6. `BaseAgent.decide` then validates through the gate and emits its `decision` event;
   the deferral's `apply` is the inline code that follows `decide` in the agent, exactly
   as in the source's sync path. The peer never applies anything: `execute_task` of the
   peer runs with no tools.

The tick blocks for the duration of step 4. The clock is logical: `tick_seconds` in the
runner is a lower bound on the wall time per tick.

Causality is tested with a fake Ollama (an OpenAI-compatible HTTP server started by the
test) whose scripted peer reply is varied: with the peer saying "R2: corridor clear"
the owner must decide `R2`; with "R1: corridor clear" the owner must decide `R1`;
the owner's second request to the fake must contain the peer's text in a `tool`
message. The test asserts event order `consult_opened < consult_question <
consult_response < consult_closed < decision` by `seq`, and that the `decision` event
has `path == "llm/<reason>"`, `source == "crewai:qwen3:8b"`.

## 9. Rules-first decision policy

Normal keeps the source's app semantics: `consult_policy = "insufficient"` (the model is
consulted only when `rule_insufficient()` returns a trigger: `ambiguity`, `conflict`,
`failed`, `unknown`, a rule with confidence < 1, a rule choice not among the options,
or a trigger with `rule_sufficient=False`), `rule_coverage = "authoritative"`
(`TriggerSet.fired()` with the rule-sufficiency flags), `urgent_via_sorting = True`.
These three defaults are set in one place, `config/settings.py::normal_config()`, and
used identically by `main.py`, `tools/run_normal.py` and the API. The source's
`NORMAL_LLM_CONFIG` (`consult_policy="always"`) is not carried: it would make every
decision a model call.

`test_rules_first.py` runs 400 ticks of Normal with CrewBrains against the fake Ollama
and asserts `decision_paths["deterministic"] > 0.9 * total` and that every
`llm/*` path has a trigger reason in `RULE_INSUFFICIENT ∪ {policy}`.

## 10. Ollama / qwen3:8b integration

`config/ollama.py::OllamaSettings` (frozen dataclass) reads: `OLLAMA_BASE_URL`
(default `http://localhost:11434`), `OLLAMA_MODEL` (default `qwen3:8b`),
`OLLAMA_TIMEOUT` (120 s), `OLLAMA_SEED` (42), `OLLAMA_TEMPERATURE` (0.0),
`OLLAMA_MAX_TOKENS` (512), `OLLAMA_THINKING` (`off`), `CONSULT_DEADLINE_S` (300),
from the environment and an optional `.env` in the project root. A model string
containing `/` is rejected (it would select another CrewAI provider).

`crew/llm.py::build_llm(settings, interceptor) -> crewai.LLM` returns
`LLM(model=f"ollama/{settings.model}", base_url=settings.base_url,
temperature=settings.temperature, seed=settings.seed, timeout=settings.timeout,
max_tokens=settings.max_tokens, interceptor=interceptor, additional_params=…)`.
Verified on 1.15.23: the result is `OpenAICompatibleCompletion` with
`provider == "ollama"` and `base_url == settings.base_url + "/v1"`; `build_llm`
asserts both and raises otherwise. Thinking is switched off by sending
`reasoning_effort="none"` in `additional_params` when `OLLAMA_THINKING=off` (the
mechanism the source used for Ollama); the implementation verifies against the real
server whether Ollama honours it for qwen3:8b and, if not, appends `/no_think` to the
system prompt. In both cases replies are passed through `visible()` before parsing.

`crew/audit.py::OllamaAudit(BaseInterceptor[httpx.Request, httpx.Response])` is
CrewAI's supported transport interceptor. `on_outbound` records the URL and asserts
its host equals the configured Ollama host (any other host raises
`UnexpectedProviderError`); `on_inbound` reads the response JSON and records the
`model` Ollama reports having served, the latency, token usage and HTTP status. Each
pair becomes an `llm_call` event (see §12) attributed to the agent currently
executing (tracked by a `contextvars` variable set by `ConsultationService` around
each `execute_task`).

`crew/identity.py::verify_model(settings) -> ModelIdentity` GETs `/api/tags` and POSTs
`/api/show` for the configured model, returning `{model, digest, family,
parameter_size, quantization, base_url, ok, problems}`. `llm_brains()` calls it and
raises `ModelUnavailable` with the installed-model list when `ok` is false; nothing is
substituted. The identity is written to `simulation_started.detail.llm` and to
`results/<run>/verify.json`.

`tools/verify_ollama.py` prints, from a live probe through the real integration (one
`Agent.execute_task` with a two-option question per role, through the audit
interceptor):

```
Planner      → Ollama(http://localhost:11434) → qwen3:8b   served=qwen3:8b  812 ms  ok
Dispatch     → …
```

and exits non-zero if any row's served model differs from `OLLAMA_MODEL`.

Switching the model later is `OLLAMA_MODEL=gemma4:26b`; no agent code changes. All
seven agents share the one `LLM` instance, so model heterogeneity cannot arise.

## 11. Simulator authority

The model never touches world state. The only way a consultation influences the world
is the `Answer.choice` returned to `BaseAgent.decide`, which must be one of the
admissible `options`, must pass `world.gate.check(Proposal(...))` (schema, policy,
state), and is then applied by the agent's own Python code (the `Deferral.apply`
closure / inline continuation), which calls the same environment, task-registry and
robot APIs the rules path calls. The peer's `execute_task` is given no tools, so it
cannot call anything. `test_simulator_authority.py` asserts that a consultation whose
owner answers an option outside the list is refused and replaced by the rule answer
(`source` ends with `:rule-after-refusal` or `fallback`), and that no module under
`post_office/crew/` imports `environment`, `tasks`, `robots` or `state` for writing
(static import check: `crew/` may import `discussion.briefings`, which reads).

## 12. Event and communication model

All runtime evidence uses the existing `EventLogger` and `MessageBus`; no second event
system is introduced.

Bus messages (topic `message`, category `communication`, as every expert message):

| MessageType        | from → to    | content |
|--------------------|--------------|---------|
| `CONSULT_REQUEST`  | owner → peer | consultation_id, decision (kind), condition, interaction_type (question/delegation), text |
| `CONSULT_RESPONSE` | peer → owner | consultation_id, text, latency_ms, model |
| `CONSULT_CLOSE`    | owner → peer | consultation_id, outcome, choice |

Because they are ordinary `message` events between two experts, DK-RMM's
`message_frequency`, `interaction_density`, `agent_coupling` and
`behavioural_similarity` see them exactly as they saw the source's `DISCUSS_*`
messages.

Delegation semantics, verified in the source (`dkrmm/indicators.py`, the message
branch): `delegation_frequency` counts messages whose *receiver* is a sub-agent
(expert → sub-agent, "down the hierarchy") and `tool_call_frequency` counts messages
whose *sender* is a sub-agent (the answer coming back). Neither counts expert ↔ expert
traffic, and the source's discussions were therefore counted as messages, not as
delegations. Prototype II keeps that meaning unchanged: an expert-to-expert
`CONSULT_REQUEST` carrying `interaction_type = "delegation"` contributes to
`message_frequency` and coupling, never to `delegation_frequency`. The
`interaction_type` distinction lives in the message metadata and the `consult_*`
events for the UI and the analysis, not in the indicator. **No DK-RMM topic or indicator
registration is needed**, and none is made; `docs/dkrmm.md` records this verification.

Agent events (category `agent`), each with `tick`, `wall_clock` (timestamp), `actor`
(sender), `target` (receiver), `correlation_id`, and in `detail`: `consultation_id`,
`decision_id`, `decision` (kind), `condition`, `interaction_type`, `model`:

| topic               | extra detail |
|---------------------|--------------|
| `consult_opened`    | peer (or ""), options |
| `consult_question`  | text, context |
| `consult_delegation`| text, context |
| `consult_response`  | text, latency_ms |
| `consult_refused`   | reason (second exchange / disallowed coworker) |
| `consult_closed`    | outcome, choice, turns, latency_ms |
| `llm_call`          | agent_role, call_id, url, requested_model, served_model, latency_ms, prompt_tokens, completion_tokens, status, phase (owner/peer) |
| `decision`          | unchanged source record + `consultation_id`, `peer`, `turns` |

`interaction_type` values: `question`, `delegation`, `response`, `decision`,
`llm_call`. `GET /consultations` returns the last N consultations assembled from these
events (id, tick, owner, peer, kind, condition, request, response, decision, outcome,
latency, model).

## 13. DK-RMM integration

`post_office/dkrmm/` is copied unchanged (`monitor.py`, `indicators.py`, `signals.py`,
`states.py`, `record.py`). It is attached from the first run exactly as in the source:
`DKRMM(eco).attach()` subscribes to `eco.logger`; the runner
(`SimulationRunner._watch`) and `tools/run_normal.py` call `monitor.tick()` after each
`eco.step()`. Indicators, thresholds (z ≥ 2, 60-tick window, every 20 ticks, 24-window
baseline), evidence kinds, state transitions and RCT criteria are the source's. The
mode is observe/assess only: the monitor's only output is its `Assessment` history,
read by the API/UI and written to `results/<run>/dkrmm.json`; nothing reads it back
into prompts, messages, agent state, environment state or decisions, and no
intervention path exists in this phase. Test: `test_dkrmm_receives_consultations.py`
(after a fake-Ollama consultation, the monitor's observed events include the three
`CONSULT_*` messages and the `decision`, and `assess()` runs without error).

## 14. DK-RMM independence

DK-RMM consumes the event stream and nothing else. It must not import CrewAI,
`CrewBrain`, agent objects, the consultation service or Ollama settings; `crew/` and
`agents/` must not import `dkrmm`; CrewAI agents do not depend on DK-RMM in any way
(no prompt, tool or context mentions its state). The guarantee is tested two ways in
`test_dkrmm_independence.py`: importing `post_office.dkrmm` in a fresh interpreter
leaves `crewai` and `post_office.crew` out of `sys.modules`, and a static scan of
`post_office/crew/` and `post_office/agents/` finds no `dkrmm` import. The monitor is
driven by the runner, outside the agents' tick work, so a consultation cannot observe
or be affected by an assessment in progress.

## 15. Interception / perturbation seams (inactive)

| Seam | Where | Normal behaviour | Future use |
|------|-------|------------------|-----------|
| Communication (consultation) | `crew/interception.py::CommunicationLayer.on_request(req) -> req \| None`, `on_response(resp) -> resp \| None` | identity | delay (sleep / hold n ticks), loss (`None` → tool returns "no answer"), duplication, reordering, corruption, isolation (refuse), frozen delegation (peer never answers → deadline → fallback), repeated delegation, flooding |
| Communication (bus) | existing `MessageBus.delay_rule` | `None` | message delay/drop on any expert message |
| Agent execution | `crew/interception.py::AgentHooks.before_prompt(agent_id, text) -> text`, `before_llm_call(agent_id)`, `after_answer(agent_id, answer) -> answer`; existing `BaseAgent.facts_filter` | identity | prompt/context perturbation, stale information, forced consultation, agent freeze, abnormal proposals |
| LLM consultation | CrewAI transport interceptor (`crew/audit.py`, chainable) | audit only | response delay, response corruption |
| Environment / resource | existing config knobs and environment API | Normal values | route closure, resource reduction, robot failure, slowdown, surge, timing |

`cfg["interceptors"]` is read by the ecosystem and must be empty in Normal; the
ecosystem emits `simulation` / `interception` `{active: []}` at start, and
`test_seams_noop.py` asserts the identity layer leaves requests, responses and prompts
byte-identical and that Normal's `simulation_started` carries `perturbations: none,
interceptors: []`. The distinction between "agent unavailable", "agent frozen" and
"agent degraded" is documented in `docs/perturbation-seams.md` as three separate future
mechanisms (no peer registered / peer never answers / peer answers late or wrongly).

How a future frozen-delegation experiment would attach, without touching the normal
architecture: a `CommunicationLayer` whose `on_request` holds the request for the
frozen peer past `CONSULT_DEADLINE_S` (frozen), or returns `None` (unavailable), or
delays and then passes it (degraded). The owner's tool then receives the layer's
verdict instead of the peer's text, the consultation closes with `outcome = timeout`
or `peer_failed`, the owner falls back to its rule exactly as it does today on a model
failure, and the events (`consult_refused`/`consult_closed`, the missing
`CONSULT_RESPONSE`) are what DK-RMM sees. None of this is implemented now.

## 16. UI / API scope

FastAPI server (`post_office/api/server.py`, trimmed) endpoints: `GET /` (live page),
`GET /state`, `GET /frame`, `GET /summary`, `GET /events?after=&limit=`,
`GET /consultations?limit=`, `GET /llm/calls?limit=`, `GET /settings` (Ollama settings,
identity, per-agent `llm_stats`), `GET /dkrmm/state`, `GET /dkrmm/series`,
`GET /dkrmm/indicators`, `POST /simulation/start|stop|reset|speed`, `WS /ws` (event
push, as in the source). Removed: every `/experiments`, `/perturbation`, `/injections`,
`/stress*`, `/autodk*`, `/trace*`, `/sessions*`, `/rcts*` route, the settings and
providers UI, `POST /settings*`.

`live.html` keeps the source's shell, facility map and robot cards and gains three
panes: **Consultations** (one row per consultation: tick, owner → peer, kind·condition,
the question, the response, `DECISION`, outcome, latency, model; rows appear live as
the events arrive), **Ollama calls** (agent, phase, served model, latency, tokens; a
busy ring on the roster card of the agent currently inside `execute_task`), and
**DK-RMM** (state, severity, current evidence kinds, the twelve indicators, the state
history strip; the source's `dkrmm_html` adapted). The header shows the model identity
from `/settings` ("Ollama · qwen3:8b · 7/7 experts"). One scenario entry: "NORMAL ·
CrewAI · Ollama/qwen3:8b · DK-RMM". No attack, perturbation, experiment or stress
control exists in the page or the server.

## 17. Project / dependency structure

```
post office ecosystem prototype II/
  README.md  .env.example  pyproject.toml  requirements.txt  pytest.ini  conftest.py
  main.py                      # python main.py [--ticks N] [--seed S] [--rules] [--api]
  post_office/
    __init__.py  core/  environment/  state/  tasks/  robots/  policy/
    communication/  simulation/  dkrmm/  observability/context.py
    agents/  (base, brain, deferral, reasoning, assignment_metrics, 7 experts, robot_agent, supervisor, subagents/)
    discussion/  (peers.py, briefings.py, prompts.py)     # the preserved topology and prompt helpers
    crew/        (llm.py, audit.py, identity.py, roles.py, brain.py, consultation.py, tools.py, parse.py, interception.py, events.py)
    config/      (settings.py, ollama.py)
    api/         (runner.py, server.py, digest.py)
    ui/          (live.html, live.py, views.py)
  tests/  (carried + new; tests/fake_ollama.py fixture server; tests/data/normal_baseline_filtered.json)
  tools/  (run_normal.py, verify_ollama.py, normal_fingerprint.py)
  docs/   (architecture.md, agents.md, crewai-ollama.md, consultation.md, events.md, dkrmm.md,
           perturbation-seams.md, alignment-baseline.md, running.md, verification.md, limitations.md,
           provenance.md, camel-removal.md, superpowers/specs/, superpowers/plans/)
  results/ (git-ignored; one folder per run)
```

Dependencies (`pyproject.toml` `[project]`, Python `>=3.10,<3.14` as CrewAI requires):
`crewai>=1.15,<2` (brings `openai`, `httpx`, `pydantic`), `fastapi>=0.110`,
`uvicorn[standard]>=0.27`, `python-dotenv` (already a CrewAI dependency; listed for
`.env`). Dev: `pytest>=8`, `httpx>=0.27`. Not present: `camel-ai`, `mcp` pins,
`litellm`, `langchain*`. The project runs in its own `.venv` created from the user's
Python 3.12; `README.md` gives the Windows commands (`py -3.12 -m venv .venv`,
`.venv\Scripts\pip install -e .[dev]`). `conftest.py` sets `PYTHONHASHSEED`-independent
seeding as the source does and adds the `fake_ollama` fixture.

## 18. Testing and verification (automated, no local Ollama needed)

Carried from the source (unchanged or trimmed of cases on removed machinery, each
trimming listed in `docs/provenance.md`): simulator and environment tests
(`test_environment`, `test_robots`, `test_communication`, `test_ecosystem`,
`test_vehicles`, `test_packing`, `test_throughput`, `test_dispatch_flow`,
`test_dispatch_priority`, `test_paid_service`, `test_priority`,
`test_queued_assignment`, `test_sorting_process`, `test_recovery`, `test_validation`,
`test_gates`, `test_urgent_route`, `test_policy_gate`), rules-agent tests
(`test_agents` minus CAMEL cases, `test_decision_pipeline`, `test_judgement`,
`test_resource_priority`, `test_where_judgement_lives`, `test_reasoning_trigger`,
`test_charging`), peer-map and briefing tests (`test_discussion_peers`,
`test_discussion_briefings`, `test_discussion_prompts` minus CAMEL cases,
`test_discussion_trigger_names`), DK-RMM tests (`test_dkrmm`, `test_dkrmm_record`,
`test_header_digest`), API tests (`test_api`, `test_controls` minus removed routes).

New:

| Test | Asserts |
|------|---------|
| `test_ollama_settings.py` | env parsing, defaults (`qwen3:8b`, `http://localhost:11434`), rejection of `/` in model |
| `test_crew_llm.py` | `build_llm` returns `OpenAICompatibleCompletion`, `provider == "ollama"`, `base_url` ends with `/v1`, no `OPENAI_API_KEY` read; a non-Ollama host in the interceptor raises |
| `test_model_identity.py` | `verify_model` against the fake: ok when listed, `ModelUnavailable` naming installed models when not; `llm_brains` refuses to build |
| `test_crew_brain_init.py` | seven brains, `name == "crewai"`, `fallback` is the agent's rules, `config.model_type == "qwen3:8b"` |
| `test_roles_preserved.py` | exactly the seven ids are on CrewBrains; supervisor, sub-agents, robots deterministic; CrewAI `role` strings |
| `test_peer_map_preserved.py` | the 24 source entries verbatim |
| `test_allowed_peer_enforcement.py` | tools bound to the one allowed peer; other coworker refused; no peer → no tools; second exchange refused |
| `test_consultation_sync.py` | owner → peer → owner within one `decide`; event order; `decision` after `consult_closed`; tick unchanged during the exchange |
| `test_consultation_causality.py` | two peer scripts → two different owner decisions; the peer text appears in the owner's follow-up request |
| `test_consultation_fallbacks.py` | no DECISION line, Ollama 500, timeout → rule answer, `source == "fallback"`, reason recorded, `consult_closed.outcome` |
| `test_events_consultation.py` | `CONSULT_*` messages on the bus and `consult_*` events carry every §12 field |
| `test_llm_call_logging.py` | one `llm_call` per HTTP round trip with `served_model == "qwen3:8b"`, latency > 0, phase owner/peer |
| `test_rules_first.py` | §9 ratios on a 400-tick fake run |
| `test_simulator_authority.py` | §11 |
| `test_dkrmm_receives_consultations.py`, `test_dkrmm_independence.py` | §13, §14 |
| `test_seams_noop.py` | §15 |
| `test_normal_alignment.py` | rules-only Normal reproduces the source's recorded world: for the four recorded runs (`app_normal_rules_seed11`, `app_normal_rules_seed1`, `default_config_seed11`, `code_defaults_seed1`, 1600 ticks) `snapshots_sha256`, `dkrmm_readings_sha256`, `dkrmm_states`, `rct_ticks` and the parcel/task counts of `summary` equal `tests/data/normal_baseline_filtered.json`, and the event stream equals the source's with the two removed `simulation` notices (`llm_async`, `discussions`) and the removed config keys filtered out of both sides |
| `test_api_trimmed.py` | the §16 routes exist, the removed ones return 404, `/settings` reports `qwen3:8b` |
| `test_no_camel.py` | §22 |

`tests/fake_ollama.py` is an OpenAI-compatible HTTP server (`/api/tags`, `/api/show`,
`/v1/chat/completions`) with a scripted responder keyed on the request's role/content,
echoing `"model": "qwen3:8b"` and emitting native `tool_calls` when a tool is offered;
it exercises the real CrewAI integration path (`LLM` → OpenAI client → HTTP).

`tests/data/normal_baseline_filtered.json` is generated once from the source tree
(deterministic, `PYTHONHASHSEED=0`) by `tools/normal_fingerprint.py --from-source
<path>`; its provenance (source sha, date) is embedded in the file.

### 18.1 The filtered behavioural-alignment baseline (what is filtered and why)

The source's own guard (`tests/data/normal_baseline.json`) hashes the complete event
stream and the complete configuration. Two kinds of rows in that stream exist only
because of the source's model implementation and have no counterpart in Prototype II:
the `simulation` notices `llm_async` and `discussions` emitted at start-up, and the
configuration keys `llm_async`, `llm_deterministic`, `llm_max_pending`,
`llm_timeout_s`, `llm_deadline_ticks`, `llm_det_latency_ticks`, `discussions`,
`discussion_calls`, `discussion_deadline_ticks`, `discussion_max_open`,
`discussion_bias` and `perturbations` echoed inside `simulation_started.detail.config`
(Prototype II adds `interceptors` and the `interception`/`llm` notices, filtered the
same way). A byte-identical event hash is therefore impossible by construction and
is not required. Instead `tools/normal_fingerprint.py` applies the same filter to both
sides: it drops those topics, prunes those keys, removes `wall_clock` and `run_id`,
and hashes what remains. The comparison then covers (1) `snapshots_sha256`, the
per-tick world state (parcels, robots, tasks, shelves, vans, energy), (2)
`dkrmm_readings_sha256`, every DK-RMM assessment record, (3) `dkrmm_states` and
`rct_ticks`, (4) the summary counts (`parcels_created/dispatched/refused/returned/late`,
`vans_departed`, `tasks`, `messages`, `events`, `reroutes`,
`supervisor_interventions`, `robots_recovered`), and (5)
`event_stream_filtered_sha256`, the semantics of every remaining event. Equality on
all five for the four recorded runs is the alignment criterion; `docs/alignment-baseline.md`
carries this list verbatim with the generating command.

## 19. Real-run verification (your machine)

```
cd "C:\Users\hindb\Projects\post office ecosystem prototype II"
py -3.12 -m venv .venv && .venv\Scripts\pip install -e .[dev]
copy .env.example .env
.venv\Scripts\python tools\verify_ollama.py            # seven Role → Ollama → qwen3:8b lines
.venv\Scripts\python tools\run_normal.py --ticks 300 --seed 1
```

`run_normal.py` writes `results/normal/s1/{events.jsonl, consultations.json,
llm_calls.json, dkrmm.json, summary.json, verify.json}` and prints: the model identity,
the count of consultations by owner→peer, the first complete consultation (tick,
sender, receiver, request, response, decision, model, latency, consultation_id), the
decision-path table, and the DK-RMM state history. The implementation report quotes
these from your pasted output or staged files only; until you provide them the report
states that the real run has not been performed.

## 20. Risks and limitations

- `qwen3:8b` under CrewAI's tool-calling loop: CrewAI uses native OpenAI-style tool
  calls (the compatible client reports `supports_function_calling() == True`); Ollama
  supports tool calling for qwen3, but an 8b model may emit malformed calls. These
  surface as CrewAI retries (latency) and, past `max_iter=4`, as recorded `fallback`
  decisions with `outcome = no_valid_decision`. The verify tool reports the fallback
  rate; a contingency (documented, not implemented) is a one-line subclass forcing the
  ReAct text protocol.
- Thinking tokens: if Ollama ignores `reasoning_effort="none"` for qwen3:8b, the
  `/no_think` soft switch is used; hidden reasoning is stripped either way.
- Wall-clock: a consultation is two to four model calls (10 to 60 s on a desktop GPU);
  300 ticks of Normal with roughly one consultation every 10 to 20 ticks is 10 to 30
  minutes.
- Reproducibility: temperature 0 and a fixed seed make Ollama deterministic for a given
  model build and prompt, but the prompt contains wall-clock-free facts only; if seed
  support varies by Ollama version, runs may differ in model text while the rules path
  stays bit-identical. No response cache in this phase.
- The source's SQLite trace store, replay viewer and RCT explainer are not carried; the
  `llm_call` events and `results/` files replace the audit they provided.
- Tick blocking makes the live UI advance in bursts during consultations by design.
- Retries and fallbacks are recorded, never hidden: CrewAI's internal retries appear
  as extra `llm_call` events for the same consultation (`phase` repeats), and
  `CrewBrain.stats()` carries `retries`, `fallbacks`, `parse_failures`, `timeouts`.
  None of these risks is addressed by replacing the model or by making the
  consultation asynchronous; both would change the experimental variable the baseline
  is meant to hold fixed.
- "Real time" in this project means, operationally: at a simulation decision point the
  owner synchronously consults an allowed peer, receives the response before finalising
  its decision, and the resulting decision is then validated and executed by the
  simulator. It does not mean unrestricted continuous conversation between agents.

## 21. Acceptance criteria

1. The project runs from its own `.venv`; `two_agent_test` is byte-identical before and
   after (`docs/provenance.md` records the source tree hash).
2. `pytest` passes in the cloud with no Ollama (fake endpoint only).
3. `test_normal_alignment.py` passes: rules-only Normal reproduces the source's world
   trajectories and DK-RMM readings.
4. `test_roles_preserved.py`, `test_peer_map_preserved.py`,
   `test_allowed_peer_enforcement.py` pass.
5. `test_crew_llm.py`, `test_model_identity.py`, `test_llm_call_logging.py` pass:
   CrewAI's `ollama` provider, `qwen3:8b` verified and recorded per call, one shared
   LLM.
6. `test_consultation_sync.py` and `test_consultation_causality.py` pass: synchronous
   owner → peer → owner with the peer reply changing the decision.
7. `test_events_consultation.py`, `test_dkrmm_receives_consultations.py`,
   `test_dkrmm_independence.py` pass.
8. `test_seams_noop.py` passes; `simulation_started` reports no perturbations and no
   interceptors.
9. `test_api_trimmed.py` passes; the live page shows consultations, Ollama calls with
   model name, and DK-RMM state.
10. `test_no_camel.py` passes and the dependency files contain `crewai` and no
    `camel-ai`.
11. `tools/verify_ollama.py` and `tools/run_normal.py --ticks 300 --seed 1` exist and
    are documented; the real run's evidence is reported only once you have run them.

## 22. CAMEL-AI removal

Nothing CAMEL-related is copied: not `camel_brain.py`, `response_cache.py`
(`camel_version()`), `providers.create_model`, `observability/instrumentation.py`, the
`camel-ai`/`mcp<2` pins, the `PO_MODEL_*` environment variables, or the tests that
assert on `brain.name == "camel"` / `source.startswith("camel:")`. Comments and docs
mentioning CAMEL in copied files are rewritten (`brain.py` docstring, `base.py`,
`planner_agent.py`, `facility.py`, `__init__.py` docstrings, `message.py` comment on
`DISCUSS_*`, which are themselves removed from the enum). `tests/test_no_camel.py`
walks every text file in the project and asserts no case-insensitive match of `camel`,
`camel-ai`, `camelbrain`, `camel_brain`, `camel_agent`. The only files excluded are the
ones whose purpose is to record the removal: `docs/camel-removal.md`,
`docs/provenance.md` and `.json` (they name the removed source files),
`docs/superpowers/` (this spec and the plan), the test itself, and the non-project
directories `.venv`, `results`, `.git`, `__pycache__`. `docs/camel-removal.md` records
the grep performed on the delivered tree, including those excluded files, so the
reader can see that the remaining matches are the removal records themselves.

---

## Self-review against the checklist

- [x] project is independent: §17 (own directory, `.venv`, dependencies, tests, docs, runtime config)
- [x] source is not modified: §2, §21 item 1 (tree hash before and after; the build happens in a separate work tree)
- [x] exact seven roles preserved: §4, `test_roles_preserved.py`
- [x] only seven roles are LLM-based: §5, `llm_brains` refusal
- [x] robots/environment/sub-agents/supervisor/DK-RMM are non-LLM: §4, §5, §13
- [x] source peer map is preserved: §7, `peers.py` copied, verbatim 24-entry test
- [x] no arbitrary CrewAI coworker topology: §6.3 `allow_delegation=False`, tools bound to the one peer, no `Crew`
- [x] CrewAI is integrated at Brain seam: §6.1, §6.2
- [x] synchronous owner→peer→owner consultation exists: §8 steps 3 to 4
- [x] peer response arrives before owner decision: §8 (tool returns into the owner loop), `test_consultation_sync.py`
- [x] peer is consultant, not second simulator controller: §8 step 6 (peer runs with no tools), §11
- [x] rules-first policy preserved: §9
- [x] simulator remains authoritative: §11
- [x] Ollama is actual backend: §10 (`provider == "ollama"`, host assertion in the interceptor)
- [x] qwen3:8b is baseline: §10 defaults
- [x] same qwen3:8b model used by all seven experts: §10 one shared `LLM`
- [x] model usage auditable: §10 interceptor, `llm_call` events, `verify_ollama.py`
- [x] DK-RMM integrated from beginning: §13
- [x] DK-RMM remains independent: §14
- [x] existing DK-RMM semantics preserved: §12, §13 (no registration, no indicator change)
- [x] consultation events enter runtime event stream: §12
- [x] delegation semantics are not silently changed: §12 (expert→sub-agent meaning kept; expert↔expert counted as messages)
- [x] future perturbation seams exist: §15
- [x] no active perturbation machinery: §2.1 removed list, §15 assertions
- [x] frozen delegation can later be implemented through seams: §15 last paragraph
- [x] trimmed UI retained: §16
- [x] CAMEL-AI completely removed: §22
- [x] automated causal consultation test exists: §8, §18 (`test_consultation_causality.py`)
- [x] real local verification command exists: §19
- [x] no fabricated real-run evidence: §19 last sentence, §21 item 11

Ambiguities resolved in this spec (each flagged so you can overrule): (a) Normal uses
the source app's defaults `rule_coverage="authoritative"`, `urgent_via_sorting=True`
with `consult_policy="insufficient"` for CLI, runner and API alike; (b) both a question
tool and a delegation tool are bound to the single allowed peer, the model picks the
interaction type, and one exchange per decision is allowed (the source's three-call
budget); (c) `CONSULT_*` bus messages are the auditable record of an exchange that
travelled through the CrewAI tool call, and receiving agents drop them in `step()`;
(d) the source's trace store and replay viewers are not carried.

---

## Amendments made during implementation

The sections above are the approved design and are left as written. Each paragraph below,
dated 2026-10-01, records where the build departs from them; where they disagree, the
paragraph below and the code govern.

**§7, refusal topic (2026-10-01).** The event written when an owner names a coworker other
than its peer, or tries a second exchange, is `consult_refused`, as §8 step 3 and the §12 table
say; the single mention of `peer_refused` in §7 is superseded. `test_allowed_peer_enforcement.py`
asserts `consult_refused`.

**§9, rules-first share (2026-10-01).** The `> 0.9 * total` deterministic share was an estimate
and does not hold on this facility, for reasons that are the source's own: in the source's
rules-only NORMAL run, 117 of 689 expert decisions over 400 ticks (seed 1) carry a
rule-insufficient trigger, about 17%, mostly ROUTING `failed` and SCHEDULING
`conflict`/`contention`; with the seven experts on the fake Ollama the share is 536 of 654
(0.82). `test_rules_first.py` pins the share at `>= 0.8`, asserts per decision that a
deterministic decision carries no trigger and a model decision carries one, and allows as
`llm/*` reasons the source `REASONS` minus `policy` (which `consult_policy="insufficient"` never
produces), not `RULE_INSUFFICIENT ∪ {policy}`. The rules and the policy are unchanged.

**§15, where "no perturbation" is recorded, and the frozen-peer design (2026-10-01).**
`perturbations: "none"` is carried by the `simulation`/`interception` notice
(`{active: [], perturbations: "none"}`), written when the ecosystem is built, and
`simulation_started.detail.config` carries `interceptors: []`; `simulation_started` has no
`perturbations` key. The ecosystem refuses any configuration with a truthy `perturbations` key
or a non-empty `interceptors` list, with `ValueError`, before the event logger opens.
`CommunicationLayer.on_request`/`on_response` run under the consultation service's lock and
only while the consultation is open (a `closed` check), so a future delay or freeze
perturbation must defer, by returning `None` or by holding the exchange outside the lock,
rather than sleep inside the hook. The frozen-peer path is: the layer withholds, the tool
returns "no answer from <Peer>", the consultation closes `peer_failed` (or `timeout`), the owner
falls back to its rule, and the events show the missing `CONSULT_RESPONSE`.

**§18.1, side effects of the filter (2026-10-01).** Dropping the stripped notice rows also
changes two things that are artefacts of those rows rather than world behaviour, and both are
filtered identically on both sides: `seq` is renumbered densely over the kept rows, and the
`events` counters of the snapshots and of the summary are netted of the dropped rows (so they
count the kept stream). `STRIP` records this as `side_effects`; `docs/alignment-baseline.md`
gives the full account.

**§6.1, CrewBrain constructor (2026-10-01).** The constructor follows the implementation plan:
`CrewBrain(agent_id, fallback, crew_agent, settings)`, and the consultation service is attached
afterwards with `bind(service)`, by the ecosystem once every agent exists (`_install_crew`).
`config` is a `CrewBrainConfig` (`model_type`, `seed`, `base_url`, `provider`), and `stats()`
also carries `retries`.

**§13 and §2.1, `communication/events.py` (2026-10-01).** The file was copied unchanged and
then adapted additively for the API: `EventLogger.recent()` copies the deque before reading it
(so a read cannot race a tick), and `since(after, limit)` is new. Event production is untouched;
the file is classified `adapted` in `docs/provenance.md`.

**§10, other details as built (2026-10-01).** The base URL must be the bare Ollama address with
an explicit port and no `/v1` (`InvalidBaseUrl` otherwise). The OpenAI client's own retries are
off (`max_retries=0`), so one model call is one HTTP attempt. `OLLAMA_THINKING=off` sends
`reasoning_effort: "none"` through `extra_body`; `OLLAMA_THINKING=prompt` prefixes `/no_think`
to each agent's backstory (CrewAI's system message) rather than appending it; whether Ollama
honours `reasoning_effort` for `qwen3:8b` is left to `tools/verify_ollama.py`, which reports
`<think>` content in raw replies. The model identity is written to `verify.json` and served by
`GET /settings`; the event log carries a `simulation`/`llm` notice (backend, model, base URL,
experts) instead of `simulation_started.detail.llm`. `retries` is the owner's model calls beyond
the first and the post-exchange call (it also counts CrewAI's agent-level re-run after an HTTP
error; peer retries are not counted).

**§18, test file names (2026-10-01).** The verbatim 24-entry peer-map test is
`test_peer_map_is_the_source_table_verbatim` in `tests/test_discussion_peers.py`; there is no
separate `test_peer_map_preserved.py`.

**§6.3, no agent-level re-run (2026-10-01).** Every CrewAI agent is built with
`max_retry_limit=0`, not `1`. CrewAI's re-run after an exception restarts the task with fresh
messages, so a peer reply already received was discarded and the owner's second ask was refused
as a second exchange; CrewAI's cumulative `_times_executed` also made the re-run depend on the
agent's run history. With `0`, an HTTP failure, including the owner's post-exchange call, closes
the consultation `model_failed` and the rule answers, recorded. `retries` is now only the extra
owner model calls inside one reasoning loop (e.g. after a malformed tool call); the §10
amendment's "also counts CrewAI's agent-level re-run" no longer applies.
`test_consultation_fallbacks.py::test_a_failure_after_the_exchange_is_not_re_run` and
`test_crew_brain_init.py::test_build_agents_settings` cover it.

**§16 and §19, labels and counts (2026-10-01).** The scenario entry names the configured
model (`config/settings.py::scenario_label`): it reads "NORMAL · CrewAI · Ollama/qwen3:8b ·
DK-RMM" with the baseline model, as §16 states, and follows `OLLAMA_MODEL` otherwise. FastAPI's
generated `/docs`, `/redoc` and `/openapi.json` are not served, so the route table is §16's and
nothing else. In `run_normal.py`'s report the count by owner→peer is of model decisions, with
how many of them were exchanges (the owner actually asked or delegated to its peer), and the
first complete consultation is the first `decided` one with both a request and a response;
`ConsultationService.summary()` gives `model_decisions` and `exchanges`, and `by_pair` counts
exchanges only.

**§16, routes for the RCT log and the trajectory (2026-10-02).** Section 5 of the trajectory
and RCT log design (`2026-10-02-trajectory-and-rct-log-design.md`) adds ten routes to the
served table. Seven are DK-RMM's: `GET /dkrmm/rcts`, `GET /dkrmm/explain?tick=`,
`GET /dkrmm/rct-log`, `GET /dkrmm/rct-log/item?run=&tick=` and `POST /dkrmm/validate`,
`/dkrmm/activate`, `/dkrmm/dismiss` (body `{by, note}`; the monitor's own gate methods, 409
when there is nothing to decide). Three are pages: `GET /ui/trajectory?limit=&run_id=&archived=`
(the live run only: another `run_id` is 404 and the page is never marked finished),
`GET /ui/trajectory/tail?after_id=&started=&limit=&run_id=` (409 to a page of an earlier run)
and `GET /ui/rcts`. The table is §16 plus `GET /taxonomy` plus these ten;
`tests/test_api_trimmed.py` `SPEC_ROUTES` lists them, and `tests/test_api_rcts.py` and
`tests/test_trajectory.py` pin their shapes.
