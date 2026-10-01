# Verification

There are two kinds of evidence. The automated test suite runs anywhere, with no Ollama: it
starts a fake, OpenAI-compatible Ollama inside the test process and drives the real
integration path through it (CrewAI's `LLM`, the OpenAI client, HTTP). The real-run evidence
comes from your machine, against your Ollama, with the two tools described below.

Nothing in this build has been run against a real Ollama server. The real-run evidence is
produced by you with `tools/verify_ollama.py` and `tools/run_normal.py --ticks 300 --seed 1`;
until you run them and keep their output, no claim about a real run is made anywhere in this
project.

## Running the tests

```
.venv\Scripts\python -m pytest -q
```

Set `PYTHONHASHSEED=0` first (`set PYTHONHASHSEED=0` on Windows; on Linux or macOS
`PYTHONHASHSEED=0 .venv/bin/python -m pytest -q`), as the recorded baselines were made with it.
The suite needs the `dev` extra. `tests/test_live_ui.py` drives the live page in a headless Chromium and
needs the optional `ui-test` extra (`pip install -e ".[ui-test]"` and `python -m playwright
install chromium`); without Playwright its module is skipped. A few carried simulator tests
skip themselves when the seeded run has nothing of the kind they check at that tick.
`conftest.py` switches CrewAI's telemetry off for the run and loads `tests/fake_ollama.py` as a
plugin, which provides the `fake_ollama` fixture: a stdlib HTTP server on a free port serving
`/api/tags`, `/api/show` and `/v1/chat/completions`, echoing `"model": "qwen3:8b"`, answering
with native `tool_calls` when a test scripts it, and recording every request it received.

## Verifying Ollama usage and qwen3:8b

`tools/verify_ollama.py` probes the configured server through the project's own integration:

```
.venv\Scripts\python tools\verify_ollama.py
```

It first prints the model identity as the server reports it (`verify_model`: base URL, model,
digest, family, parameter size, quantization, installed models, the thinking mode). If the
configured model is not installed, it prints the problems and exits 1 without probing. Then,
for each of the seven experts, the CrewAI agent that `build_agents` makes, on the shared LLM
from `build_llm` with an `OllamaAudit` as its transport interceptor, executes one two-option
task, and one row is printed:

```
Planner      → Ollama(http://localhost:11434) → qwen3:8b   served=qwen3:8b  812 ms  ok
```

(the figures in this row are an illustration of the format, not a measurement). `served` is the
model name the server put in its reply, as the audit read it, and the latency is the sum over
the agent's calls for the task. The exit code is 1 if any row's served model differs from
`OLLAMA_MODEL` or any call failed, 2 for invalid settings, and 0 otherwise. A last line says how
many raw replies contained `<think>` or a separate reasoning field, so you can settle
`OLLAMA_THINKING` (see [crewai-ollama.md](crewai-ollama.md)). The rows report what the tool
saw at the configured address; they do not by themselves establish which server answered.

In every run the same facts are recorded per call: every `llm_call` event and every row of
`llm_calls.json` carries the `url`, the `requested_model` and the `served_model`, and the audit
refuses any request to a host other than the configured one before it leaves the process.
`GET /settings` shows the settings, the identity and the experts actually on the model.

## Verifying that DK-RMM receives the events

In a run, `dkrmm.json` holds the monitor's final state and its run record, and the report of
`tools/run_normal.py` prints its state history and RCT ticks, which exist only if the monitor
was attached and ticked over the event stream. In the live page the DK-RMM pane shows the
current state and indicators from `GET /dkrmm/state` and `/dkrmm/indicators`. In the suite,
`tests/test_dkrmm_receives_consultations.py` asserts that the monitor's own window holds the
three `CONSULT_*` messages and the `decision` of a consultation and that an assessment runs over
it; `tests/test_dkrmm_independence.py` asserts that it is fed by nothing else. See
[dkrmm.md](dkrmm.md).

## The real-run command

```
.venv\Scripts\python tools\run_normal.py --ticks 300 --seed 1
```

In model mode the tool loads the settings, checks the identity (exit 2, writing only
`verify.json`, if the model is not there), builds the seven CrewBrains, attaches DK-RMM, steps
300 ticks and writes `results\normal\s1\`:

| File | Contents |
|------|----------|
| `events.jsonl` | the run's whole event log |
| `consultations.json` | every consultation: id, tick, owner, peer, kind, condition, request, response, decision, source, outcome, latency, model |
| `llm_calls.json` | every model call as the transport audit saw it, with its consultation id and tick |
| `dkrmm.json` | DK-RMM's final state and its run record (state series, transitions, RCT events) |
| `summary.json` | the ecosystem's summary, the per-expert reasoning summary and each brain's `stats()` |
| `verify.json` | the settings, the identity, the served models seen in the calls, and `ok` |

The printed report begins with the header `MODEL-MODE RUN EVIDENCE` and the disclaimer that
the output shows the configured base URL and the served model names the replies carried and
does not establish which server answered. It then gives the model identity and the served
models with their counts, the consultations by owner and peer with their outcomes, the first
decided consultation (tick, sender, receiver, request, response, decision, model, latency,
consultation id), the decision-path table with shares, DK-RMM's state history and RCT ticks,
and each brain's counters (calls, consultations, fallbacks, retries, parse failures, rejected
answers, timeouts) with the fallback and retry totals. The exit code is 0 only when the
identity check passed, no call was served by another model, and at least one call was served by
the configured model. With `--rules` the header is `RULES-ONLY RUN EVIDENCE`, no model is
asked, the same six files are written and `verify.json` says it was a rules-only run.

## The test inventory

| Test file | What it holds |
|-----------|---------------|
| `test_ollama_settings.py` | environment and `.env` parsing, the defaults (`qwen3:8b`, `http://localhost:11434`), refusal of `/` in the model name and of a base URL with `/v1` or no port |
| `test_crew_llm.py` | `build_llm` gives CrewAI's `ollama` provider (`OpenAICompatibleCompletion`, base URL ending in `/v1`) and refuses anything else; no cloud key is read; the thinking switch; the audit refuses a foreign host and records the served model, latency, usage, status, phase, server errors and unanswered attempts |
| `test_model_identity.py` | `verify_model` against the fake: identified when installed; `ModelUnavailable` naming the installed models when not; unreachable or malformed servers reported |
| `test_fake_ollama.py` | the fake server itself |
| `test_crew_brain_init.py` | seven CrewBrains on one shared LLM, `name == "crewai"`, the agent's rules as `fallback`, the configured model, non-experts refused, the CrewAI agent settings, `/no_think` with `OLLAMA_THINKING=prompt` |
| `test_roles_preserved.py` | exactly the seven experts on the model; supervisor, sub-agents and robots deterministic; the role strings |
| `test_discussion_peers.py` | the peer map equals the source's 24 entries verbatim |
| `test_allowed_peer_enforcement.py` | tools bound to the one peer; another coworker refused without a model call; one exchange; no peer, no tools; no CrewAI coworker graph |
| `test_consultation_sync.py` | owner, peer, owner inside one `decide`; event order; same tick; service summary |
| `test_consultation_causality.py` | two peer replies give two owner decisions; the peer's text in the owner's follow-up request |
| `test_consultation_fallbacks.py` | no DECISION line, HTTP 500, deadline, busy expert, off-list answer, withheld request, raising service: the rule answers with the reason recorded |
| `test_events_consultation.py` | the `CONSULT_*` messages and the `consult_*` events carry their fields |
| `test_llm_call_logging.py` | one `llm_call` per HTTP round trip; a malformed tool call counted as a retry |
| `test_parse.py` | rendering and reading the reply, `<think>` removed |
| `test_rules_first.py` | NORMAL on the model is rules first (share 0.8 or more; reasons) |
| `test_simulator_authority.py` | nothing off the list reaches the gate; the gate's refusal replaced by the rule; no world-writing imports in `crew/` |
| `test_seams_noop.py` | the inert seams and the NORMAL notices |
| `test_dkrmm_receives_consultations.py`, `test_dkrmm_independence.py` | see [dkrmm.md](dkrmm.md) |
| `test_normal_alignment.py` | rules-only NORMAL reproduces the source's world and DK-RMM readings (see [alignment-baseline.md](alignment-baseline.md)) |
| `test_base_sync_decide.py`, `test_deferral.py`, `test_ecosystem_normal_guards.py` | the synchronous `decide` path, the kept `Deferral` record, the perturbation refusal |
| `test_runner.py`, `test_api.py`, `test_api_trimmed.py`, `test_controls.py`, `test_header_digest.py` | the runner and the API routes (removed routes answer 404) |
| `test_live_ui.py` | the live page in a headless browser (optional `ui-test` extra) |
| `test_run_normal_tool.py` | `tools/run_normal.py`, `main.py` and `tools/verify_ollama.py` against the fake |
| `test_project_layout.py` | the dependencies, `.env.example`, the provenance tool |
| the removed-framework test, `test_docs_present.py` | no project file names the source's removed model framework, and only the removal records do (the test's own file name is one of them; see [provenance.md](provenance.md)); the documents exist and the provenance record covers every package file |
| the carried simulator, rules, gate and DK-RMM tests | `test_environment`, `test_robots`, `test_communication`, `test_ecosystem`, `test_vehicles`, `test_packing`, `test_throughput`, `test_dispatch_flow`, `test_dispatch_priority`, `test_paid_service`, `test_priority`, `test_queued_assignment`, `test_sorting_process`, `test_recovery`, `test_validation`, `test_gates`, `test_urgent_route`, `test_policy_gate`, `test_agents`, `test_decision_pipeline`, `test_judgement`, `test_resource_priority`, `test_where_judgement_lives`, `test_reasoning_trigger`, `test_charging`, `test_discussion_briefings`, `test_discussion_prompts`, `test_discussion_trigger_names`, `test_dkrmm`, `test_dkrmm_record` |

Every change made to a carried test is listed in [provenance.md](provenance.md), section
"Trimmed tests".
