# Agents and the LLM boundary

The ecosystem has twenty-eight agents: a supervisor, seven experts, fifteen sub-agents and
five robots. Exactly the seven experts can have a model behind them. Everything else,
including DK-RMM, which is not an agent at all, is deterministic Python.

## The seven experts

The expert ids, their rules (`install_rules`), their trigger conditions (`install_triggers`),
their sub-agents, their message vocabulary and their place in the tick order are the
source's. The CrewAI side of each expert is a `RoleSpec` in `post_office/crew/roles.py`.

| Agent id   | CrewAI role | Decision kinds it takes                     | Sub-agents |
|------------|-------------|---------------------------------------------|------------|
| PLANNER    | Planner     | `release_work`                              | none |
| INTAKE     | Intake      | `accept_parcel`                             | SUB-VALIDATION, SUB-REGISTRATION |
| SORTING    | Sorting     | `classify_destination`                      | SUB-BARCODE, SUB-PRIORITY, SUB-DESTINATION |
| SCHEDULING | Scheduling  | `choose_robot`, `choose_next_task`          | SUB-QUEUE, SUB-DEADLINE, SUB-ASSIGNMENT |
| ROUTING    | Routing     | `resolve_block`                             | SUB-ROUTE, SUB-COLLISION |
| RESOURCE   | Resource    | `allocate_charge_point`, `accept_into_storage`, `battery_sufficient` | SUB-BATTERY, SUB-CHARGING, SUB-STORAGE |
| DISPATCH   | Dispatch    | `release_parcel`                            | SUB-MANIFEST, SUB-PACKING |

Each role's goal and backstory are written from the source rather than invented. The opening
sentence of every backstory is the source model brain's system prompt ("You are the {role}
of an automated post office. You will be given a decision to make, some facts, and a list of
allowed answers."), the middle restates the responsibilities in the first docstring of the
corresponding source agent module, and every backstory ends with the source's reply
instruction: one allowed answer on the first line, at most one short sentence of reasoning,
never an answer that is not on the list.

`build_agents(llm, thinking)` makes one `crewai.Agent` per expert around the one shared LLM,
with `allow_delegation=False` (CrewAI must never attach its own all-coworker tools),
`tools=[]` (the only tools an expert ever holds are the two consultation tools bound to one
peer, handed to a single `execute_task` call), `max_iter=4`, `max_retry_limit=1`,
`verbose=False`, `cache=False`, `memory=False` and `respect_context_window=True`. With
`OLLAMA_THINKING=prompt` the backstory, which CrewAI puts in the system message, is prefixed
with `/no_think`. No `Crew` object is built anywhere in the normal path.

## Rules first

An expert asks its model only when its rule is insufficient. NORMAL runs with the source
app's settings, all set in `config/settings.py::normal_config()` and used identically by
`main.py`, `tools/run_normal.py` and the API: `consult_policy="insufficient"`,
`rule_coverage="authoritative"`, `urgent_via_sorting=True`, and `interceptors=[]`.
`rule_insufficient` in the copied `agents/reasoning.py` returns a trigger only when there is
no rule, the rule's answer is not admissible, the rule says it is unsure (confidence below
1), or a condition fired that declares its rule insufficient (`rule_sufficient=False`) or
whose reason (`ambiguity`, `conflict`, `failed`, `unknown`) means the rule cannot be trusted
here; a condition the rule covers is noted on the decision and the rule answers.

On this facility that is not a small share. The source's own rules-only NORMAL run fires a
rule-insufficient trigger on 117 of 689 expert decisions over 400 ticks (seed 1), about 17%,
mostly ROUTING `failed` and SCHEDULING `conflict`/`contention`. With the seven experts on the
fake Ollama of the test suite, 536 of 654 decisions (0.82) were answered by the rule.
`tests/test_rules_first.py` pins the deterministic share at 0.8 or more, checks that every
deterministic decision carries no trigger and every model decision carries one, and checks
that the reasons are the source's `REASONS` other than `policy` (the reason that puts every
decision to the model, which `insufficient` never produces). The rules and the policy are the
source's and were not changed to reach a number.

## The LLM boundary

`config/settings.py::llm_brains(agent_ids, settings, verify, audit)` is the only way to put a
model behind an agent. It raises `ValueError` for any id outside `EXPERTS`, the seven ids
above. With `verify=True` it calls `require_model` first, which raises `ModelUnavailable`
with the installed-model list if the configured model is not on the Ollama server. It returns
one `CrewBrain` per id, each with a fresh `DeterministicBrain` as `fallback`, which the agent
fills through `install_rules()` when the ecosystem builds it, so `BaseAgent.rules()` finds the
rules on a model-backed agent exactly as on a rules-only one. CrewAI is imported inside
`llm_brains`, so a rules-only run never loads it.

Every other agent's brain is a `DeterministicBrain`: the supervisor, the fifteen `SUB-*`
sub-agents, which answer their parent's `SUBTASK_REQUEST` with a measurement, and the five
robots (`RobotAgent`). The environment, the recovery service and the van departures are not
agents and have no brain. `tests/test_roles_preserved.py` asserts that exactly the seven
expert ids are on brains named `crewai`, that the supervisor, sub-agents and robots are not,
and that the CrewAI role strings are the ones in the table. `tests/test_crew_brain_init.py`
asserts that the seven brains have the agent's rules as their `fallback` and report the
configured model.

DK-RMM is outside the boundary in a stronger sense: it is not in the hierarchy, not on the
bus, imports nothing from `crew/` or `agents/` and nothing there imports it
(`tests/test_dkrmm_independence.py`). See [dkrmm.md](dkrmm.md).

## CrewBrain

`post_office/crew/brain.py::CrewBrain(agent_id, fallback, crew_agent, settings)` implements the
duck-typed Brain contract the source agents rely on: `name = "crewai"`, `reads_prompt = True`,
`last_prompt`, `fallback`, `config` (`model_type`, `seed`, `base_url`, `provider="ollama"`),
`answer(question)`, `answer_consulting(question, trigger)`, `stats()` and `close()`. The
consultation service is attached afterwards with `bind(service)`, by the ecosystem once every
agent exists (`_install_crew`).

Every call starts by computing the rule's answer. Without a bound service the rule answers,
marked `source="fallback"` with `[fallback: model layer not installed]`, and no model is
called. With one, the decision goes to `service.run(owner_id, question, trigger,
rule_answer)`; the `ConsultOutcome` it returns carries the answer and the consultation id,
peer and turns, which `BaseAgent.decide` copies onto its `decision` record from
`last_consultation` (reset at the start of every call, so a decision never carries an
earlier one's consultation). A service that raises is caught: the rule answers with
`[fallback: <error>]`, `last_error` says why and `reachable` becomes false.

A model answer has `source="crewai:<model>"` and gives the decision path `llm/<trigger
reason>`; a fallback has `source="fallback"` and gives the path `fallback`, as does a model
answer the policy gate refused and the rule replaced (`source` ending in
`:rule-after-refusal`). `stats()` returns `brain`, `model`, `provider`, `base_url`, `calls`,
`consultations`, `questions`, `delegations`, `fallbacks`, `rejected_answers`,
`parse_failures`, `timeouts`, `retries`, `reachable`, `last_error` and `mean_latency_ms`; the
definition of `retries` is in [events.md](events.md).
