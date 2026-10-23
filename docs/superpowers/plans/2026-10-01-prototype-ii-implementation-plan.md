# Prototype II (CrewAI + Ollama/qwen3:8b + DK-RMM) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task: a fresh implementer subagent per task, then a fresh reviewer subagent that checks the task against its "Evidence" line and the spec before the next task starts. Review findings are fixed before moving on. A later task may not change the semantics of an earlier accepted task; if it must touch an earlier file, the reviewer re-runs that earlier task's tests. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `post office ecosystem prototype II`, an independent copy of the source's Normal post-office simulator whose seven expert agents consult Ollama's `qwen3:8b` through CrewAI at the Brain seam, with synchronous peer consultation on the existing peer map and DK-RMM observing the event stream.

**Architecture:** The simulator, rules, policy gate, bus, event logger and DK-RMM are copied from the source. Behind `BaseAgent.decide`, a `CrewBrain` runs a CrewAI `Agent.execute_task` on one shared `crewai.LLM(model="ollama/qwen3:8b")`; when the copied `peers.py` names a peer for (owner, kind, condition), the owner gets one question tool and one delegation tool bound to that peer alone, the peer's own model call happens inside the owner's loop, and the owner's `DECISION:` line is validated by the gate and applied by the simulator. Every hop is an event on the existing logger and a `CONSULT_*` message on the existing bus, which is what DK-RMM reads. CrewAI replaces the implementation of model-backed peer consultation at the Brain seam while preserving the existing peer map and consultation semantics.

**Tech Stack:** Python 3.12 (3.10 to 3.13 allowed), CrewAI 1.15.x (native `ollama` provider = `OpenAICompatibleCompletion`, transport `BaseInterceptor`; verified on 1.15.23 in this environment), Ollama (local), FastAPI + uvicorn, pytest. No LiteLLM, no LangChain, no CAMEL-AI.

**Spec:** `docs/superpowers/specs/2026-10-01-prototype-ii-crewai-ollama-design.md`

## Global Constraints

- The source project `<workspace>\two_agent_test\post_office_discuss` is never written to. The build happens in a cloud work tree; the result is committed to `<workspace>\post office ecosystem prototype II` through the device bridge. Task 11 verifies the source tree hash before and after.
- Package name stays `post_office`; the project runs only from its own `.venv`.
- Dependencies: `crewai>=1.15,<2`, `fastapi>=0.110`, `uvicorn[standard]>=0.27`, `python-dotenv>=1.0`; dev `pytest>=8`, `httpx>=0.27`. Never `camel-ai`, `litellm`, `langchain*`.
- Exactly seven LLM brains: `PLANNER, INTAKE, SORTING, SCHEDULING, ROUTING, RESOURCE, DISPATCH`. CrewAI `role` strings: `Planner, Intake, Sorting, Scheduling, Routing, Resource, Dispatch`.
- Model string `ollama/{OLLAMA_MODEL}`; default `OLLAMA_MODEL=qwen3:8b`, `OLLAMA_BASE_URL=http://localhost:11434`, `OLLAMA_TIMEOUT=120`, `OLLAMA_SEED=42`, `OLLAMA_TEMPERATURE=0`, `OLLAMA_MAX_TOKENS=512`, `OLLAMA_THINKING=off`, `CONSULT_DEADLINE_S=300`. A model string containing `/` is rejected.
- Every CrewAI `Agent`: `allow_delegation=False`, `max_iter=4`, `max_retry_limit=1`, `verbose=False`, `cache=False`. No `Crew` object anywhere in the normal path.
- Normal config: `consult_policy="insufficient"`, `rule_coverage="authoritative"`, `urgent_via_sorting=True`, `interceptors=[]`, no `perturbations`.
- Answer sources: `crewai:<model>` on success, `fallback` otherwise; `brain.name == "crewai"`.
- New event topics (category `agent`): `consult_opened, consult_question, consult_delegation, consult_response, consult_refused, consult_closed, llm_call`. New `MessageType` members: `CONSULT_REQUEST, CONSULT_RESPONSE, CONSULT_CLOSE`. `DISCUSS_*` members are removed. DK-RMM indicator code is not edited; expert ↔ expert consultations count as messages, never as `delegation_frequency` (that indicator keeps its expert → sub-agent meaning).
- Line endings LF throughout the new project. Tests never need a real Ollama. No em-dash sequences in prose.
- Commit after every task (`git init` in Task 1); commit messages end with the attribution lines the session reminder gives.
- No claim about the real local run is made until the user supplies its output (Task 11).

## Review Focus

1. Ollama reachable but `qwen3:8b` not pulled: `llm_brains()` must raise `ModelUnavailable` listing installed models, and `main.py` must exit 2 with that message, never run on another model. Tests in Task 4 (`test_model_identity.py::test_missing_model_refuses_and_names_installed`) and Task 8 (`test_main_exits_when_model_missing`).
2. Ollama answers slowly (call > `OLLAMA_TIMEOUT`, consultation > `CONSULT_DEADLINE_S`): the owner must get the rule answer with `source == "fallback"`, the tick must continue, and `consult_closed.outcome == "timeout"`. Test in Task 6 (`test_consultation_fallbacks.py::test_deadline_falls_back_to_rule`).
3. The model names a coworker that is not the allowed peer, or asks twice: no model call for the disallowed peer, `consult_refused` emitted, owner still decides. Tests in Task 6 (`test_allowed_peer_enforcement.py`).
4. The model's final text has a `DECISION:` line whose value is not an allowed option (or a `<think>` block around it): the parser must strip thinking, try the heuristics, then fall back to the rule; the gate must never see an inadmissible choice. Tests in Task 5 (`test_parse.py::test_think_block_is_stripped`) and Task 6 (`test_consultation_fallbacks.py::test_inadmissible_decision_falls_back`).
5. The live page is opened while a consultation blocks the tick: `/frame`, `/consultations` and `/dkrmm/state` must answer without waiting for the consultation to finish (the runner holds the step lock only around `eco.step()`; the read endpoints read the last published snapshot, not the ecosystem). Test in Task 9 (`test_api_trimmed.py::test_reads_do_not_block_on_consultation`).

---

## File structure (the whole project)

Legend: U = copied unchanged (LF-normalised), A = adapted, R = replaces a source file, N = new, X = removed (not copied). Source paths are relative to `post_office_discuss/`.

**Root**: `pyproject.toml` A · `requirements.txt` A · `README.md` N · `.env.example` N · `.gitignore` N · `pytest.ini` N · `conftest.py` A (drops `PO_NO_DOTENV`, adds `fake_ollama` fixture import) · `main.py` A

**post_office/** `__init__.py` A (docstring without CAMEL) ·
`core/` U (ids, rng, visible, world) · `environment/` U (facility, grid, layout, parcels, receptacles, recovery, vehicles, zones) · `state/` U · `tasks/` U · `robots/` U · `policy/gate.py` U ·
`communication/` bus U, directory U, events U, provenance U, topics U, `message.py` A (enum: `+CONSULT_REQUEST/RESPONSE/CLOSE`, `-DISCUSS_*`) ·
`simulation/` `generator.py` U, `recovery.py` U, `ecosystem.py` A ·
`dkrmm/` U (indicators, monitor, record, signals, states) ·
`observability/__init__.py` N (empty) + `context.py` U · other observability modules X ·
`agents/` `base.py` A, `brain.py` A (docstring), `deferral.py` R (from `llm_async.py`: constants, `is_pending`, `Deferral`), `reasoning.py` U, `assignment_metrics.py` U, `robot_agent.py` U, `supervisor.py` U, `subagents/` U, seven experts A (one import line each), `camel_brain.py` X, `llm_async.py` X, `response_cache.py` X ·
`discussion/` `__init__.py` A (docstring), `peers.py` U, `briefings.py` U, `prompts.py` U, `manager.py` X, `bias.py` X ·
`crew/` N: `__init__.py`, `llm.py`, `audit.py`, `identity.py`, `roles.py`, `brain.py`, `parse.py`, `consultation.py`, `tools.py`, `events.py`, `interception.py` ·
`config/` `settings.py` A, `ollama.py` N, `providers.py` X, `experiments.py` X ·
`api/` `runner.py` A, `server.py` A, `digest.py` A (monitor digest only), `injections.py` X ·
`ui/` `live.html` A, `live.py` A, `views.py` A, `discussions.html` X, `settings.html` X, `rcts.html` X, `viewer.html` X ·
`perturbation/`, `perturbation.py`, `stress/` X

**tests/** carried U/A (lists in Tasks 2 and 9), `fake_ollama.py` N, `consult_helpers.py` N, `data/normal_baseline_filtered.json` N, new tests N (Tasks 3 to 10).

**tools/** `run_normal.py` N · `verify_ollama.py` N · `normal_fingerprint.py` A · `provenance.py` N · everything else X.

**docs/** `architecture.md`, `agents.md`, `crewai-ollama.md`, `consultation.md`, `events.md`, `dkrmm.md`, `perturbation-seams.md`, `alignment-baseline.md`, `running.md`, `verification.md`, `limitations.md`, `provenance.md` + `.json` (generated), `camel-removal.md` (generated) N; `superpowers/specs/`, `superpowers/plans/` (the spec and this plan, already present).

---

### Task 1: Project scaffold and independent environment

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `.env.example`, `.gitignore`, `pytest.ini`, `conftest.py`, `README.md` (skeleton), `post_office/__init__.py`, `tools/provenance.py`
- Test: `tests/test_project_layout.py`

**Interfaces:**
- Produces `tools/provenance.py::record(source_root: Path, target_root: Path, classification: dict[str, str]) -> dict` writing `docs/provenance.md` (source identity block: git commit if `source_root/.git` exists else "no git repository", `source_tree_sha256`, date; then a table: path, class, source path, source sha256) and `docs/provenance.json`; `classification` maps target-relative path → `unchanged|adapted|replaced|new`. `tools/provenance.py::tree_sha(root: Path, ignore=(".venv","results",".git","__pycache__",".pytest_cache","logs",".model_cache")) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project_layout.py
import tomllib, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_dependencies_are_crewai_not_camel():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())
    deps = " ".join(meta["project"]["dependencies"] + meta["project"]["optional-dependencies"]["dev"])
    assert "crewai" in deps and "fastapi" in deps and "uvicorn" in deps
    for banned in ("camel", "litellm", "langchain"):
        assert banned not in deps.lower()
    assert meta["project"]["requires-python"] == ">=3.10,<3.14"

def test_env_example_pins_the_baseline_model():
    text = (ROOT / ".env.example").read_text()
    assert "OLLAMA_MODEL=qwen3:8b" in text and "OLLAMA_BASE_URL=http://localhost:11434" in text
```

- [ ] **Step 2: Run** `pytest tests/test_project_layout.py -v` → FAIL (files missing).
- [ ] **Step 3: Create** `pyproject.toml` (`name = "post-office-ecosystem-prototype-ii"`, version `0.1.0`, dependencies and dev extras from Global Constraints, `[tool.setuptools.packages.find] include = ["post_office*"]`), `requirements.txt` (same pins, one per line), `.env.example` (the eight `OLLAMA_*`/`CONSULT_*` lines with defaults), `.gitignore` (`.venv/ results/ __pycache__/ .pytest_cache/ *.jsonl .env`), `pytest.ini` (`testpaths = tests`), `conftest.py` (`pytest_plugins = ["tests.fake_ollama"]`), `post_office/__init__.py` (one-paragraph docstring), `README.md` headings only.
- [ ] **Step 4: Implement `tools/provenance.py`**; record the source tree sha now and keep it in `docs/provenance.json` as `source_tree_sha256_at_start`.
- [ ] **Step 5: Run** → PASS. **Step 6:** `git init`; commit `chore: scaffold prototype II project`.

**Evidence:** test output; `docs/provenance.json` with the source identity.

### Task 2: Copy/adapt the simulator and source behaviour; run on rules

**Files:**
- Create (copy U): everything marked U in the file structure.
- Create: `post_office/agents/deferral.py`
- Modify (A): `post_office/agents/base.py`, the seven `post_office/agents/*_agent.py` (import line), `post_office/communication/message.py`, `post_office/simulation/ecosystem.py`, `post_office/config/settings.py`, `post_office/discussion/__init__.py`, `post_office/agents/brain.py` (docstring), `main.py`
- Test: carried simulator/rules/gate/DK-RMM tests (list below); `tests/test_deferral.py`; the verbatim peer-map assertion added to `tests/test_discussion_peers.py`

**Interfaces:**
- `post_office/agents/deferral.py`: constants `DETERMINISTIC="deterministic"`, `LLM_PENDING="llm_pending"`, `LLM_ACCEPTED="llm_accepted"`, `LLM_REJECTED="llm_rejected"`, `LLM_FAILED="llm_failed"`, `LLM_TIMEOUT="llm_timeout"`, `PENDING_LLM_DECISION` (same literal as the source), `is_pending(answer: Optional[Answer]) -> bool`, `@dataclass Deferral(key: str, apply: Callable[[Answer], None], still_valid: Callable[[Answer], str] = lambda a: "", reevaluate: Callable[[str], None] = lambda why: None)`.
- `BaseAgent.decide(kind, prompt, options=(), correlation_id="", deferral=None, **facts) -> Answer` (signature unchanged) with the sync path of spec §6.2; the `decision` event gains `consultation_id`, `peer`, `turns` read from `getattr(self.brain, "last_consultation", None)` (dict or None). `step()` drops messages whose `message_type.name.startswith("CONSULT_")`.
- `config/settings.py`: `DEFAULT_CONFIG` (source values), `normal_config() -> dict` (DEFAULT_CONFIG + `consult_policy="insufficient"`, `rule_coverage="authoritative"`, `urgent_via_sorting=True`, `interceptors=[]`), `config(preset: str = "default", **overrides) -> dict` (only `"default"`; `ValueError` otherwise), `SCENARIOS = [("default", "NORMAL · CrewAI · Ollama/qwen3:8b · DK-RMM")]`, `scenario_meta(preset) -> dict`, `EXPERTS = ("PLANNER","INTAKE","SORTING","SCHEDULING","ROUTING","RESOURCE","DISPATCH")`, `LLM_CANDIDATES = EXPERTS`; `llm_brains` stub raising `NotImplementedError` (filled in Task 5).
- `simulation/ecosystem.py::PostOfficeEcosystem(seed=1, config=None, log_path=None, run_id="run", brains=None, scenario="normal")` and `build(...)`; same lifecycle methods as the source minus `llm_async`/`discussions`; `_install_interception()` validates `cfg.get("interceptors", []) == []` (else `ValueError("perturbations are not part of this phase")`) and emits `simulation`/`interception` `{active: []}`; `_install_crew()` placeholder (Task 6); `summary()["llm"] = self.llm_summary()` (`{}` for now).

- [ ] **Step 1: Copy the U files** with a throwaway cloud helper (byte copy, CRLF→LF, classification recorded for `provenance.record`).
- [ ] **Step 2: Write `tests/test_deferral.py`** (`is_pending(Answer("x", source="llm_pending"))` is True; `Deferral("k", apply=lambda a: None).still_valid(Answer("x")) == ""`).
- [ ] **Step 3: Create `agents/deferral.py`**; change the seven experts' `from .llm_async import Deferral, is_pending` to `from .deferral import Deferral, is_pending`; in `base.py` import the constants from `.deferral`.
- [ ] **Step 4: Adapt `base.py`** per spec §6.2: delete the `deferred` branch, `_settle_pending`, `_record_pending`, `_settle`, `_discussion_peer`, `llm_dispatcher`, `discussions`, stale-streak fields; keep `facts_filter`; drop `CONSULT_*` messages in `step()`; rewrite the CAMEL sentence in the module docstring.
- [ ] **Step 5: Adapt `message.py`** (enum members per Global Constraints; comment rewritten).
- [ ] **Step 6: Adapt `ecosystem.py`** per Interfaces (remove the `perturbation` import, `PerturbationController`, `PropagationTrace`, `_install_llm_async`, `_install_discussions`).
- [ ] **Step 7: Write `config/settings.py`**; adapt `main.py` to `--ticks`, `--seed`, `--rules`, `--api`, `--log` (`--rules` is the only working mode until Task 8; without it `main.py` prints "model brains arrive in a later task" and exits 2).
- [ ] **Step 8: Copy the carried tests** `test_environment, test_robots, test_communication, test_ecosystem, test_vehicles, test_packing, test_throughput, test_dispatch_flow, test_dispatch_priority, test_paid_service, test_priority, test_queued_assignment, test_sorting_process, test_recovery, test_validation, test_gates, test_urgent_route, test_policy_gate, test_decision_pipeline, test_judgement, test_resource_priority, test_where_judgement_lives, test_reasoning_trigger, test_charging, test_discussion_peers, test_discussion_briefings, test_discussion_trigger_names, test_dkrmm, test_dkrmm_record, test_header_digest`, plus `test_agents.py` and `test_discussion_prompts.py` with their CAMEL/`probe`/`ScriptedBrain(name="camel")` cases deleted (every deleted test name is listed in `docs/provenance.md` under "trimmed tests"). Add to `test_discussion_peers.py`:

```python
def test_peer_map_is_the_source_table_verbatim():
    assert dict(PEER_MAP) == SOURCE_PEER_MAP   # the 24 (owner, kind, condition) -> peer tuples, copied into the test
```

- [ ] **Step 9: Run** `PYTHONHASHSEED=0 pytest tests -q` → all PASS; `python main.py --rules --ticks 300 --seed 1` prints a summary whose `decision_paths` has only the key `deterministic`.
- [ ] **Step 10: Commit** `feat: copy the normal simulator, rules and DK-RMM from the source; synchronous decide`.

**Evidence:** carried-test count and pass line; the rules-only summary; the trimmed-tests list.

### Task 3: Behavioural alignment baseline

**Files:**
- Create: `tools/normal_fingerprint.py` (A from source), `tests/data/normal_baseline_filtered.json`, `tests/test_normal_alignment.py`, `docs/alignment-baseline.md`

**Interfaces:**
- `normal_fingerprint.STRIP = {"topics": {"llm_async", "discussions", "interception", "llm"}, "config_keys": {"llm_async","llm_deterministic","llm_max_pending","llm_timeout_s","llm_deadline_ticks","llm_det_latency_ticks","discussions","discussion_calls","discussion_deadline_ticks","discussion_max_open","discussion_bias","perturbations","interceptors"}}`.
- `normal_fingerprint.run_one(name, seed, cfg, ticks=1600, strip=STRIP) -> dict` with keys `seed, ticks, events, snapshots_sha256, dkrmm_readings_sha256, dkrmm_states, rct_ticks, event_stream_filtered_sha256, summary` (summary reduced to `parcels_created, parcels_dispatched, parcels_refused, parcels_returned, parcels_late, vans_departed, tasks, messages, events, reroutes, supervisor_interventions, robots_recovered`); rows have `wall_clock`, `run_id` removed and `simulation_started.detail.config` pruned of `config_keys` before hashing.
- `normal_fingerprint.runs(ticks=1600) -> dict` with the four source run names (`app_normal_rules_seed11`, `app_normal_rules_seed1` on `normal_config()`; `default_config_seed11` on `DEFAULT_CONFIG`; `code_defaults_seed1` on `None`).
- `normal_fingerprint.main()`: `--from-source <path>` (same recipe with the source package on `sys.path`, same strip) and `--write <json>`; the JSON embeds `{"source_tree_sha256", "generated_at", "ticks": 1600, "strip": STRIP}`.

- [ ] **Step 1: Generate the baseline from the source** in the cloud: `PYTHONHASHSEED=0 python tools/normal_fingerprint.py --from-source <source mirror> --write tests/data/normal_baseline_filtered.json`.
- [ ] **Step 2: Write `tests/test_normal_alignment.py`**:

```python
@pytest.mark.slow
def test_rules_only_normal_reproduces_the_source_world():
    before = json.loads(BASELINE.read_text())
    after = nf.runs(1600)
    for name, b in before["runs"].items():
        a = after[name]
        for key in ("snapshots_sha256", "dkrmm_readings_sha256", "dkrmm_states", "rct_ticks",
                    "event_stream_filtered_sha256", "summary"):
            assert a[key] == b[key], (name, key)
```

- [ ] **Step 3: Run** `PYTHONHASHSEED=0 pytest tests/test_normal_alignment.py -v` → PASS. A differing hash is a defect in Task 2 (the simulator or rules path changed); fix Task 2, never loosen the test.
- [ ] **Step 4: Write `docs/alignment-baseline.md`** (the STRIP list verbatim, why each item is filtered, the five compared quantities, the generating command).
- [ ] **Step 5: Commit** `test: pin rules-only Normal to the source's recorded world and DK-RMM readings`.

**Evidence:** the passing test; the baseline file's provenance block; the doc.

### Task 4: Ollama/CrewAI dependency and model verification

**Files:**
- Create: `post_office/config/ollama.py`, `post_office/crew/__init__.py`, `post_office/crew/llm.py`, `post_office/crew/audit.py`, `post_office/crew/identity.py`, `tests/fake_ollama.py`
- Test: `tests/test_ollama_settings.py`, `tests/test_crew_llm.py`, `tests/test_model_identity.py`

**Interfaces:**
- `config/ollama.py`: `@dataclass(frozen=True) OllamaSettings(base_url: str, model: str, timeout: int, seed: int | None, temperature: float, max_tokens: int, thinking: str, consult_deadline_s: float)`; `load_settings(env: Mapping[str, str] | None = None, dotenv: bool = True, root: Path | None = None) -> OllamaSettings`; `class InvalidModelName(ValueError)`; properties `model_string` (`f"ollama/{model}"`), `host` (scheme+netloc), `as_dict()`.
- `crew/llm.py`: `build_llm(settings: OllamaSettings, interceptor: BaseInterceptor | None = None) -> crewai.LLM`; `class UnexpectedProviderError(RuntimeError)`. Asserts `type(llm).__name__ == "OpenAICompatibleCompletion"`, `llm.provider == "ollama"`, `llm.base_url == settings.base_url.rstrip("/") + "/v1"`. Uses `additional_params={"extra_body": {"reasoning_effort": "none"}}` when `settings.thinking == "off"`; `settings.thinking == "prompt"` leaves params alone (the `/no_think` prefix is added by `roles.py` in Task 5).
- `crew/audit.py`: `@dataclass LLMCallRecord(call_id: str, agent_id: str, phase: str, url: str, requested_model: str, served_model: str, latency_ms: float, prompt_tokens: int | None, completion_tokens: int | None, status: int | None, error: str)`; `class OllamaAudit(BaseInterceptor[httpx.Request, httpx.Response])` with `__init__(settings, on_call: Callable[[LLMCallRecord], None])`, `on_outbound` (host check → `UnexpectedProviderError`), `on_inbound` (reads JSON `model`, `usage`), `records: list[LLMCallRecord]`; context manager `calling(agent_id: str, phase: str)` setting a `contextvars.ContextVar` read by the interceptor.
- `crew/identity.py`: `@dataclass ModelIdentity(model, base_url, digest, family, parameter_size, quantization, installed: list[str], ok: bool, problems: list[str])` with `as_dict()`; `verify_model(settings, timeout: float = 5.0) -> ModelIdentity`; `class ModelUnavailable(RuntimeError)`; `require_model(settings) -> ModelIdentity`.
- `tests/fake_ollama.py`: fixture `fake_ollama` yielding `FakeOllama` with `.base_url`, `.settings -> OllamaSettings`, `.requests: list[dict]`, `.script(responder: Callable[[dict], dict | str])` (`str` → plain assistant reply; `{"tool": name, "args": {...}}` → native `tool_calls`), `.serve_models(names: list[str])`, `.delay(seconds)`, `.fail_with(status)`; endpoints `/api/tags`, `/api/show`, `/v1/chat/completions`, always echoing `"model": "qwen3:8b"` (or the first served model); helper `consultation_script(peer_reply: str, decide: Callable[[str], str]) -> responder`: owner call with tools and no `tool` message → tool call naming the peer; call whose system prompt contains "consulted by" → `peer_reply`; owner call containing a `tool` message → `f"DECISION: {decide(peer_text)}"`.

- [ ] **Step 1: Write `tests/test_ollama_settings.py`** (defaults; `OLLAMA_MODEL=gemma4:26b` → `model_string == "ollama/gemma4:26b"`; `InvalidModelName` for `openai/gpt-4o`; `.env` read only when `dotenv=True`).
- [ ] **Step 2: Implement `config/ollama.py`**; run → PASS.
- [ ] **Step 3: Write `tests/test_crew_llm.py`**:

```python
def test_build_llm_routes_to_crewai_ollama_provider(fake_ollama):
    llm = build_llm(fake_ollama.settings)
    assert type(llm).__name__ == "OpenAICompatibleCompletion"
    assert llm.provider == "ollama" and llm.model == "qwen3:8b"
    assert llm.base_url == fake_ollama.base_url + "/v1"

def test_no_cloud_key_is_read(monkeypatch, fake_ollama):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-matter")
    assert build_llm(fake_ollama.settings).api_key != "sk-should-not-matter"

def test_audit_refuses_a_foreign_host(fake_ollama):
    audit = OllamaAudit(fake_ollama.settings, on_call=lambda r: None)
    with pytest.raises(UnexpectedProviderError):
        audit.on_outbound(httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))

def test_audit_records_served_model_and_latency(fake_ollama):
    seen = []
    llm = build_llm(fake_ollama.settings, OllamaAudit(fake_ollama.settings, seen.append))
    fake_ollama.script(lambda req: "R1")
    with calling("SCHEDULING", "owner"):
        out = llm.call("Answer R1 or R2")
    assert out.strip() == "R1" and seen[0].served_model == "qwen3:8b" and seen[0].agent_id == "SCHEDULING"
```

- [ ] **Step 4: Implement `tests/fake_ollama.py`, `crew/llm.py`, `crew/audit.py`**; run → PASS.
- [ ] **Step 5: Write `tests/test_model_identity.py`** (`verify_model` ok with the digest from `/api/show`; `serve_models(["qwen3:4b"])` → `ok is False` and `require_model` raises `ModelUnavailable` naming `qwen3:4b` (`test_missing_model_refuses_and_names_installed`); unreachable base_url → `ok is False`, `problems[0]` starts with "cannot reach").
- [ ] **Step 6: Implement `crew/identity.py`**; run → PASS. **Step 7: Commit** `feat: Ollama settings, CrewAI ollama LLM, transport audit, model identity, fake Ollama`.

**Evidence:** the tests; the printed `type(llm).__name__`, `provider`, `base_url` from the first test.

### Task 5: CrewAI roles and CrewBrain at the Brain seam

**Files:**
- Create: `post_office/crew/roles.py`, `post_office/crew/brain.py`, `post_office/crew/parse.py`
- Modify: `post_office/config/settings.py` (`llm_brains`)
- Test: `tests/test_parse.py`, `tests/test_crew_brain_init.py`, `tests/test_roles_preserved.py`

**Interfaces:**
- `crew/roles.py`: `@dataclass(frozen=True) RoleSpec(agent_id: str, role: str, goal: str, backstory: str)`; `ROLES: dict[str, RoleSpec]` for the seven ids, text drawn from the source `SYSTEM_TEMPLATE` and each agent module docstring, every backstory ending "You reply with exactly one allowed answer on the first line, then at most one short sentence of reasoning. You never invent an answer that is not on the list."; `build_agents(llm, thinking: str = "off") -> dict[str, crewai.Agent]` (Global Constraints settings; `thinking == "prompt"` prefixes `/no_think` to the system template); `role_of(agent_id) -> str`, `agent_id_of(role) -> str`.
- `crew/parse.py`: `render(question: Question) -> str` (source `CamelBrain.render` format); `parse_choice(text: str, options: Sequence) -> Any | None` (strip `<think>` via `core.visible.visible`, then `discussion.prompts.parse_decision`, then first-line / token / unique-mention heuristics); `last_visible_line(text) -> str`.
- `crew/brain.py`: `class CrewBrain(Brain)`: `name = "crewai"`, `reads_prompt = True`, `__init__(agent_id: str, fallback: DeterministicBrain, crew_agent: crewai.Agent, settings: OllamaSettings)`, `config` (object with `.model_type`, `.seed`, `.base_url`, `.provider == "ollama"`), `service` (bound later via `bind(service)`), `answer(question) -> Answer`, `answer_consulting(question, trigger) -> Answer`, `last_consultation: dict | None`, `stats() -> dict` (spec §6.1 keys incl. `retries`), `close()`. Unbound service → `Answer(rule.choice, "... [fallback: model layer not installed]", source="fallback")`.
- `config/settings.py::llm_brains(agent_ids: Sequence[str] = (), settings: OllamaSettings | None = None, verify: bool = True, audit: OllamaAudit | None = None) -> dict[str, CrewBrain]`: ids default to `EXPERTS`; other ids → `ValueError`; `verify` → `require_model(settings)`; one `build_llm` shared by all; each brain gets a fresh `DeterministicBrain()` fallback.

- [ ] **Step 1: Write `tests/test_parse.py`** (`render` contains `Decision: choose_robot` and `Allowed answers:`; `parse_choice("<think>R1?</think>\nDECISION: R2", ["R1","R2"]) == "R2"` (`test_think_block_is_stripped`); `parse_choice("I pick R3", ["R1","R2"]) is None`; `parse_choice("r1.", ["R1","R2"]) == "R1"`).
- [ ] **Step 2: Implement `crew/parse.py`**; run → PASS.
- [ ] **Step 3: Write `tests/test_roles_preserved.py` and `tests/test_crew_brain_init.py`**:

```python
def test_exactly_the_seven_experts_are_on_crewai(fake_ollama):
    eco = build(seed=1, config=normal_config(), brains=llm_brains(settings=fake_ollama.settings))
    on_model = sorted(i for i, a in eco.agents.items() if a.brain.name == "crewai")
    assert on_model == ["DISPATCH", "INTAKE", "PLANNER", "RESOURCE", "ROUTING", "SCHEDULING", "SORTING"]
    assert all(a.brain.name == "deterministic" for i, a in eco.agents.items() if i not in on_model)

def test_crewai_roles_are_the_source_roles(fake_ollama):
    assert {b.crew_agent.role for b in llm_brains(settings=fake_ollama.settings).values()} == {"Planner","Intake","Sorting","Scheduling","Routing","Resource","Dispatch"}

def test_llm_brains_refuses_non_experts(fake_ollama):
    with pytest.raises(ValueError):
        llm_brains(["SUPERVISOR"], settings=fake_ollama.settings)

def test_all_brains_share_one_llm_and_model(fake_ollama):
    brains = llm_brains(settings=fake_ollama.settings)
    assert len({id(b.crew_agent.llm) for b in brains.values()}) == 1
    assert all(b.config.model_type == "qwen3:8b" and b.crew_agent.allow_delegation is False for b in brains.values())
    assert all(b.fallback is eco_agent_rules(b) for b in brains.values())   # helper: the agent's rules() after build()
```

- [ ] **Step 4: Implement `crew/roles.py`, `crew/brain.py`, `llm_brains`**; run → PASS.
- [ ] **Step 5: Commit** `feat: CrewAI roles for the seven experts, CrewBrain at the Brain seam, llm_brains`.

**Evidence:** the tests; a printed table of the seven `RoleSpec.role` values.

### Task 6: Peer-map enforcement and synchronous owner → peer → owner consultation

**Files:**
- Create: `post_office/crew/interception.py` (identity classes only in this task), `post_office/crew/events.py`, `post_office/crew/tools.py`, `post_office/crew/consultation.py`, `tests/consult_helpers.py`
- Modify: `post_office/agents/base.py` (decision record fields), `post_office/simulation/ecosystem.py` (`_install_crew`, `llm_summary`)
- Test: `tests/test_allowed_peer_enforcement.py`, `tests/test_consultation_sync.py`, `tests/test_consultation_causality.py`, `tests/test_consultation_fallbacks.py`, `tests/test_events_consultation.py`

**Interfaces:**
- `crew/interception.py`: `@dataclass ConsultRequest(consultation_id, tick, sender, receiver, interaction_type, text, context)`; `@dataclass ConsultResponse(consultation_id, tick, sender, receiver, text, latency_ms, model)`; `class CommunicationLayer` with `on_request(req) -> ConsultRequest | None`, `on_response(resp) -> ConsultResponse | None` (identity); `class AgentHooks` with `before_prompt(agent_id, text) -> str`, `before_llm_call(agent_id) -> None`, `after_answer(agent_id, answer) -> Answer` (identity); `@dataclass Interception(communication: CommunicationLayer, agent: AgentHooks)` with classmethod `inert()`. (`from_config` arrives in Task 7.)
- `crew/events.py`: `class ConsultEvents(logger, bus, model: str)` with `opened(ctx, peer, options)`, `question(req)`, `delegation(req)`, `response(resp)`, `refused(ctx, reason)`, `closed(ctx, outcome, choice, turns, latency_ms)`, `llm_call(record: LLMCallRecord, tick: int)`; each emits the spec §12 event; question/delegation/response/closed also send the matching `CONSULT_*` bus message via `bus.send(sender, receiver, MessageType.X, content, correlation_id=consultation_id, text=...)`.
- `crew/tools.py`: `@dataclass ConsultationContext(consultation_id, owner_id, peer_id, tick, decision_id, kind, condition, options, exchanges_used: int = 0, max_exchanges: int = 1, turns: list = field(default_factory=list))`; `class AskPeerTool(AskQuestionTool)`, `class DelegateToPeerTool(DelegateWorkTool)`; `make_tools(ctx, peer_agent, service) -> list[BaseTool]`; `_run` implements spec §8 step 3 and returns the peer text, or "You have already consulted {Peer} for this decision; decide now.", or "{Name} is not available to you for this decision; only {Peer} is."; private attributes via `pydantic.PrivateAttr`.
- `crew/consultation.py`: `@dataclass ConsultOutcome(answer: Answer, consultation_id: str, outcome: str, peer: str, turns: int, latency_ms: float, model: str)`; `class ConsultationService(agents: dict[str, crewai.Agent], world, bus, logger, interception: Interception, settings: OllamaSettings, audit: OllamaAudit, briefing_source: Callable[[str], Any])` with `run(owner_id, question, trigger, rule_answer) -> ConsultOutcome`, `recent(limit=50) -> list[dict]`, `summary() -> dict` (`consultations, by_pair, outcomes, mean_latency_ms`), `llm_calls(limit=100) -> list[dict]`. Deadline: `execute_task` runs in a worker thread joined with `settings.consult_deadline_s`; on timeout the outcome is `timeout`, the late result is discarded, late audit records carry `phase="late"`.
- `ecosystem._install_crew()`: for CrewBrains among `self.agents`, build `OllamaAudit`, `ConsultEvents`, `ConsultationService` with `Interception.inert()` for now (`from_config` in Task 7), `brain.bind(service)`; emit `simulation`/`llm` `{backend: "ollama", model, base_url, agents: [...]}`; `self.crew = service`; `llm_summary()` → `service.summary()`.
- `tests/consult_helpers.py::scheduling_with_equally_placed_robots(fake_ollama, **cfg) -> (eco, scheduling_agent)`: builds `build(seed=1, config=normal_config(), brains=llm_brains(settings=..., verify=False))`, starts it, and makes SCHEDULING's `choose_robot` fire the `equally_placed` condition deterministically (two idle robots at equal distance to the task, or a registered trigger whose condition function is named `equally_placed`).

- [ ] **Step 1: Write `tests/test_consultation_causality.py`** (the central test):

```python
@pytest.mark.parametrize("peer_reply, expected", [
    ("R2: its corridor is clear; R1's path crosses the dock queue.", "R2"),
    ("R1: its corridor is clear; R2's path crosses the dock queue.", "R1"),
])
def test_peer_reply_changes_owner_decision(fake_ollama, peer_reply, expected):
    fake_ollama.script(consultation_script(peer_reply, decide=lambda peer: "R2" if peer.startswith("R2") else "R1"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    answer = sched.decide("choose_robot", "Which robot takes T-1?", options=("R1", "R2"), task="T-1")
    assert answer.choice == expected and answer.source == "crewai:qwen3:8b"
    owner_follow_up = [r for r in fake_ollama.requests if any(m["role"] == "tool" for m in r["messages"])][-1]
    assert peer_reply in json.dumps(owner_follow_up["messages"])
    peer_call = [r for r in fake_ollama.requests if "consulted by Scheduling" in json.dumps(r["messages"])][0]
    assert not peer_call.get("tools")
```

- [ ] **Step 2: Write** `tests/test_consultation_sync.py` (event order by `seq`: `consult_opened < consult_question < llm_call(peer) < consult_response < consult_closed < decision`, all with the same `tick`; `decision.detail.path` starts with `llm/`; `decision.detail.consultation_id` equals the consultation's; `eco.world.tick` unchanged across `decide`), `tests/test_allowed_peer_enforcement.py` (tools bound to `[peer]`; a scripted tool call naming `Resource` where the peer is `Routing` → `consult_refused` and no fake request contains "consulted by Resource"; a scripted second ask → refusal string and `consult_refused`; owner/kind/condition without a peer → `execute_task` called with `tools=[]`), `tests/test_consultation_fallbacks.py` (no DECISION line → `fallback`, `outcome == "no_valid_decision"`; `fake_ollama.fail_with(500)` → `outcome == "model_failed"`; `consult_deadline_s=0.5` with `fake_ollama.delay(2)` → `outcome == "timeout"` and `decide` returns within 1.5 s (`test_deadline_falls_back_to_rule`); `DECISION: R9` with options R1/R2 → `fallback` and `gate.check` never sees `R9` (`test_inadmissible_decision_falls_back`)), `tests/test_events_consultation.py` (three `CONSULT_*` bus messages with the §12 content keys; every `consult_*` event carries `consultation_id, decision_id, decision, condition, interaction_type, model`, `actor`/`target` as sender/receiver, `wall_clock` set).
- [ ] **Step 3: Run** the five files → FAIL (modules missing).
- [ ] **Step 4: Implement `crew/interception.py` (identity classes), `crew/events.py`, `crew/tools.py`, `crew/consultation.py`, `ecosystem._install_crew`, the `base.py` record fields, `tests/consult_helpers.py`**.
- [ ] **Step 5: Run** the five files and the whole suite → PASS. **Step 6: Commit** `feat: synchronous peer consultation through CrewAI on the preserved peer map`.

**Evidence:** the parametrised causality test passing for both scripts; the printed ordered event list from `test_consultation_sync.py`.

### Task 7: Communication/event interception seams and the DK-RMM boundary

**Files:**
- Modify: `post_office/crew/interception.py` (`from_config`), `post_office/simulation/ecosystem.py` (pass `from_config(cfg)` to the service), `post_office/crew/consultation.py` (route `llm_call` records to `ConsultEvents.llm_call` with the current tick)
- Test: `tests/test_seams_noop.py`, `tests/test_llm_call_logging.py`, `tests/test_dkrmm_receives_consultations.py`, `tests/test_dkrmm_independence.py`, `tests/test_rules_first.py`, `tests/test_simulator_authority.py`

**Interfaces:**
- `crew/interception.py::from_config(cfg: dict) -> Interception` (`cfg.get("interceptors", [])` empty → `Interception.inert()`; otherwise `NotImplementedError("perturbations are not part of this phase")`).
- `ConsultationService` calls `interception.communication.on_request/on_response` around every tool exchange and `interception.agent.before_prompt/before_llm_call/after_answer` around `execute_task`; a `None` from `on_request`/`on_response` makes the tool return "no answer from {Peer}" and the consultation close with `outcome = peer_failed`.

- [ ] **Step 1: Write `tests/test_seams_noop.py`** (identity on a `ConsultRequest`, a `ConsultResponse` and a prompt string; `from_config({"interceptors": []})` is inert; `from_config({"interceptors": ["delay"]})` raises; Normal `simulation_started.detail` has no `perturbations` and the `interception` notice has `active == []`; a consultation run through `Interception.inert()` produces byte-identical `CONSULT_REQUEST.text` and tool input).
- [ ] **Step 2: Write `tests/test_llm_call_logging.py`** (three `llm_call` events for one consultation with `phase` in `owner, peer, owner`, `served_model == "qwen3:8b"`, `latency_ms > 0`, `url` ending `/v1/chat/completions`, `tick` equal to the consultation tick; a CrewAI retry caused by a malformed scripted tool call appears as an extra `llm_call` and `stats()["retries"] == 1`).
- [ ] **Step 3: Write `tests/test_dkrmm_receives_consultations.py`** (`DKRMM(eco).attach()` before the consultation; afterwards the monitor's event deque contains three `message` events whose `detail.message_type` are the `CONSULT_*` types and one `decision`; `monitor.assess(now)` returns; `indicators` from the window count the consultation under `messages` and not under `delegations`), `tests/test_dkrmm_independence.py` (subprocess importing `post_office.dkrmm` leaves `crewai` and `post_office.crew` out of `sys.modules`; static scan: no `dkrmm` import under `post_office/crew/` or `post_office/agents/`), `tests/test_rules_first.py` (400 ticks of `build(... brains=llm_brains(...))` with a script answering every question with its first option: `paths["deterministic"] >= 0.9 * sum(paths.values())`; every `llm/*` suffix is in the source `REASONS` set and `policy` never appears), `tests/test_simulator_authority.py` (static: no module in `post_office/crew/` imports `post_office.environment`, `tasks`, `robots`, `state`; dynamic: with `gate.check` wrapped, an out-of-list owner choice never reaches it; the peer's `execute_task` is invoked with `tools=None` or `[]`).
- [ ] **Step 4: Implement `from_config`, the ecosystem wiring, the `llm_call` routing**; run the six files and the whole suite → PASS.
- [ ] **Step 5: Commit** `feat: inert interception seams, llm_call events, DK-RMM boundary tests`.

**Evidence:** the six test files passing; the `simulation_started` and `interception` notices printed from a Normal run.

### Task 8: Normal runner and verification tools

**Files:**
- Modify: `post_office/api/runner.py`, `main.py`
- Create: `tools/run_normal.py`, `tools/verify_ollama.py`
- Test: `tests/test_runner.py`, `tests/test_run_normal_tool.py`

**Interfaces:**
- `api/runner.py::SimulationRunner(seed=1, config=None, log_path=None, run_id="api", tick_seconds=0.25, llm_agents: Sequence[str] = (), preset="default", settings: OllamaSettings | None = None, verify_model: bool = True)`; `start()`, `stop(reason)`, `reset(seed=None, config=None, preset="")`, `snapshot()`, `tick_seconds`, `llm_agents` (ids whose `brain.name == "crewai"`), `llm_error`, `llm_stats() -> dict` (sum of `CrewBrain.stats()` + `identity`), `consultations(limit)`, `llm_calls(limit)`, `monitor`, `last_frame: dict`; `_watch`: lock → `eco.step()` → `monitor.tick()` → publish `last_frame` → unlock → sleep to `tick_seconds`.
- `main.py`: `python main.py [--ticks N=600] [--seed S=1] [--rules] [--api] [--log PATH]`; model mode (default) calls `require_model` first and exits 2 with its message on failure.
- `tools/run_normal.py --ticks 300 --seed 1 [--out results/normal] [--rules]`: `build(...)` + `DKRMM`, steps `ticks`, writes `results/normal/s<seed>/{events.jsonl, consultations.json, llm_calls.json, dkrmm.json, summary.json, verify.json}`, prints the spec §19 report (identity; consultations by owner→peer; the first `decided` consultation as tick/sender/receiver/request/response/decision/model/latency/consultation_id; decision-path table; DK-RMM state history and RCT ticks; fallback and retry counts). Exit 0 only if `verify.json.ok` and at least one `llm_call` has `served_model == settings.model`.
- `tools/verify_ollama.py`: per expert, one `Agent.execute_task` on a two-option question through the audit interceptor; prints `f"{role:<12} → Ollama({base_url}) → {model}   served={served}  {latency} ms  {status}"`; exit 1 if any served model differs or any call fails; also prints whether any reply contained `<think>` (to settle `OLLAMA_THINKING`).

- [ ] **Step 1: Write `tests/test_runner.py`** (runner on `fake_ollama` settings starts, steps 50 ticks at `tick_seconds=0`, `llm_agents` is the seven ids, `llm_stats()["identity"]["model"] == "qwen3:8b"`, `monitor.state()` has `state`; `reset()` rebuilds with fresh brains) and `tests/test_run_normal_tool.py` (subprocess with `OLLAMA_BASE_URL` = fake, `--ticks 60`: the six files exist and `consultations.json` is a list; `test_main_exits_when_model_missing`: `serve_models(["qwen3:4b"])`, `main.py --ticks 1` exits 2 and stderr names `qwen3:4b`).
- [ ] **Step 2: Implement** the runner, `main.py`, the two tools; run → PASS. **Step 3: Commit** `feat: runner, CLI, run_normal and verify_ollama tools`.

**Evidence:** the tests; the `run_normal.py` console report from a fake-Ollama run (clearly labelled as fake in the task log).

### Task 9: Trimmed FastAPI server and live UI

**Files:**
- Modify: `post_office/api/server.py`, `post_office/api/digest.py`, `post_office/ui/live.html`, `post_office/ui/live.py`, `post_office/ui/views.py`
- Test: `tests/test_api_trimmed.py`, `tests/test_live_ui.py`; carried `tests/test_api.py`, `tests/test_controls.py` trimmed of removed routes

**Interfaces:**
- Routes exactly as spec §16. `GET /settings` → `{ollama, identity, llm_agents, llm_candidates, llm_error, llm_stats}`; `GET /consultations?limit=`; `GET /llm/calls?limit=`; `GET /dkrmm/state|series|indicators` from `digest.monitor_digest(monitor)` (no `perturbation` import, no `perturbation_digest`); `POST /simulation/reset?seed=&preset=` accepts only `default`.
- `live.py::shell_html()`, `frame_json(runner)`, `dkrmm_html(runner)`, `consultations_html(runner, limit=40)`, `llm_calls_html(runner, limit=40)`; `views.py` keeps `frame_of`, `static_of`, `dkrmm_catalogue`; trace/history/replay functions removed.
- `live.html` panes: Consultations (tick, owner → peer, kind · condition, question, response, DECISION, outcome, latency, model), Ollama calls (agent, phase, served model, latency, tokens; busy ring on the active roster card), DK-RMM (state, severity, evidence kinds, twelve indicators, history strip); header badge from `/settings`; one scenario option; no attack/perturbation/experiment/stress/settings controls.

- [ ] **Step 1: Write `tests/test_api_trimmed.py`** (each §16 route 200 on a `fake_ollama` runner; `/experiments`, `/perturbation`, `/injections`, `/stress`, `/autodk/experiments`, `/trace/models`, `/settings/ui`, `/rcts` → 404; `/settings` reports `ollama.model == "qwen3:8b"`; `test_reads_do_not_block_on_consultation`: `fake_ollama.delay(2)`, runner started, `/frame` and `/dkrmm/state` answer within 0.5 s during the delay) and `tests/test_live_ui.py` (Playwright headless; page loads; after a scripted consultation the Consultations pane contains the peer text and `DECISION: R2`; the Ollama pane shows `qwen3:8b`; the DK-RMM pane shows a state; the page text contains none of `attack, perturb, stress, inject, experiment, autodk, OpenRT`).
- [ ] **Step 2: Adapt the server, digest and UI files; copy and trim `test_api.py`/`test_controls.py`**; run → PASS. **Step 3: Commit** `feat: trimmed API and live UI with consultations, Ollama calls and DK-RMM`.

**Evidence:** the tests; a headless screenshot of the page after a fake consultation.

### Task 10: Documentation, provenance, perturbation seams, CAMEL proof

**Files:**
- Create: `docs/architecture.md`, `docs/agents.md`, `docs/crewai-ollama.md`, `docs/consultation.md`, `docs/events.md`, `docs/dkrmm.md`, `docs/perturbation-seams.md`, `docs/running.md`, `docs/verification.md`, `docs/limitations.md`, `docs/provenance.md` + `.json` (generated), `docs/camel-removal.md` (generated), `README.md` (complete)
- Test: `tests/test_no_camel.py`, `tests/test_docs_present.py`

- [ ] **Step 1: Write `tests/test_no_camel.py`** (walk the project excluding `.venv`, `results`, `.git`, `__pycache__`, `docs/superpowers/`, `docs/camel-removal.md`, `docs/provenance.md`, `docs/provenance.json` and the test itself; for every `.py .md .html .toml .txt .ini .json .cfg .example` file assert no case-insensitive `camel`; a second test asserts the excluded removal records are the only matching files in the whole tree) and `tests/test_docs_present.py` (the thirteen docs exist; `provenance.md` lists every `post_office/**/*.py`).
- [ ] **Step 2: Write the docs** (prose; the §12 event table and §15 seam table may be tables), covering: architecture; source provenance; the seven roles; the LLM boundary; CrewAI integration and configuration; the peer map; synchronous consultation with the operational definition of "real time" (spec §20 last item); Ollama/`qwen3:8b` configuration and how to switch models; simulator authority; the event stream; DK-RMM integration, observe/assess mode and the verified delegation semantics; future perturbation seams with the unavailable/frozen/degraded distinction and the frozen-delegation path; the UI; running the baseline; verifying Ollama usage, `qwen3:8b`, and that DK-RMM receives events; limitations and risks (spec §20 verbatim).
- [ ] **Step 3: Generate `docs/provenance.md`/`.json`** with `tools/provenance.py` and `docs/camel-removal.md` (the grep command and its result).
- [ ] **Step 4: Run** `pytest -q` → all PASS. **Step 5: Commit** `docs: architecture, running, verification, provenance, CAMEL removal`.

**Evidence:** the two tests; `docs/camel-removal.md` showing only the removal records match.

### Task 11: Full verification and final delivery

- [ ] **Step 1: Full suite** `PYTHONHASHSEED=0 pytest -q` in the project venv → PASS; record counts.
- [ ] **Step 2: Repository-wide grep** `grep -ril camel --exclude-dir=.venv --exclude-dir=results --exclude-dir=.git .` → only the removal records; `pip list` shows `crewai`, no `camel-ai`, no `litellm`, no `langchain`.
- [ ] **Step 3: Source unchanged**: `tools/provenance.py tree_sha` of a fresh staging of the source equals `source_tree_sha256_at_start`; `device_list_dir` mtimes of `post_office_discuss` unchanged.
- [ ] **Step 4: Deliver the tree to the device** at `<workspace>\post office ecosystem prototype II` (all files except `.venv`, `results`), verify by re-staging a sample and byte comparison.
- [ ] **Step 5: Handoff commands** (spec §19): create the venv, `verify_ollama.py` (if it reports `<think>` content or Ollama rejects `reasoning_effort`, set `OLLAMA_THINKING=prompt` in `.env` and rerun), then `run_normal.py --ticks 300 --seed 1`; the user pastes the console output or lets `results/normal/s1/` be staged.
- [ ] **Step 6: Implementation report**, written only after the real-run output is available: what was copied/changed, role and LLM-boundary confirmation, which components use CrewAI and Ollama, the `qwen3:8b` baseline confirmation, one real consultation (tick, sender, receiver, request, response, decision, model, latency, consultation_id) with its `CONSULT_*`/`consult_*`/`llm_call` events, DK-RMM normal-baseline states and indicators, test results, the CAMEL grep, limitations. Until then the report states plainly that the real run has not been performed.

**Evidence:** the pasted real-run output; nothing is asserted about the real run before it exists.

---

## Plan self-review

Spec coverage: §1 to §3 (Tasks 2, 3), §4 to §5 (Task 5 tests), §6 (Tasks 2, 5, 6), §7 (Task 2 verbatim table test, Task 6 enforcement), §8 (Task 6), §9 (Task 7 `test_rules_first`), §10 (Tasks 4, 8), §11 (Task 7), §12 (Tasks 6, 7), §13 and §14 (Task 7), §15 (Task 7), §16 (Task 9), §17 (Task 1), §18 (every task; §18.1 Task 3), §19 (Tasks 8, 11), §20 (Task 10 docs; retries counted in Task 7), §21 (Task 11), §22 (Task 10). No gaps found after the split of consultation (Task 6) from seams/boundary (Task 7).

Type consistency: `OllamaSettings` (Task 4) is taken by `build_llm`, `OllamaAudit`, `verify_model`, `llm_brains` (Task 5), `ConsultationService` (Task 6), the runner and tools (Task 8); `ConsultOutcome.answer` is the `Answer` returned by `CrewBrain.answer_consulting`; `LLMCallRecord` flows from `OllamaAudit.on_call` into `ConsultEvents.llm_call` (Task 7 routing); `Interception` is built by `from_config(cfg)` (Task 7) and consumed by the service (Task 6 signature).

Review Focus: each of the five lines has its test in the owning task (4 and 8, 6, 6, 5 and 6, 9).

Proportion: the plan is shorter than the spec plus the code it describes; code appears only for tests that pin exact behaviour.
