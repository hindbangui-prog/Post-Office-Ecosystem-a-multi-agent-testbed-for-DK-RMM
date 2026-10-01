# Limitations and risks

This document restates the risks of the design (specification section 20) as they stand in
what was built, and adds the known weaknesses found during implementation that affect users.
None of these risks is addressed by replacing the model or by making the consultation
asynchronous: both would change the experimental variable the baseline is meant to hold fixed.

## No real run yet

Every automated check runs against the fake Ollama of the test suite. Nothing has been run
against a real Ollama server or a real `qwen3:8b` in this build, so no latency, fallback rate,
retry rate or decision quality of the real model is known. The evidence for those comes from
`tools/verify_ollama.py` and `tools/run_normal.py --ticks 300 --seed 1` on your machine
([verification.md](verification.md)).

## qwen3:8b under CrewAI's tool-calling loop

CrewAI's OpenAI-compatible client uses native OpenAI-style tool calls, and Ollama supports
tool calling for qwen3, but an 8b model may format a tool call badly (arguments that do not
parse, a coworker name that is not on offer, a second exchange). CrewAI's executor then asks
the model again: that costs latency and is counted in `retries` (measured from the transport
audit, see [events.md](events.md)). At `max_iter=4` CrewAI asks the owner for a final answer;
if that names no allowed answer the decision is a recorded fallback (`no_valid_decision`,
counted under `parse_failures` or `rejected_answers`), and if CrewAI raises it is a
`model_failed` fallback. The fake model formats its calls perfectly, so the test suite cannot show
how often this happens; the run report's brain table shows it for a real run. A contingency,
documented and not implemented, is a small subclass of the LLM whose
`supports_function_calling()` returns false, which makes CrewAI's executor use its text (ReAct)
protocol instead of native tool calls.

## Thinking tokens

`OLLAMA_THINKING=off` sends `reasoning_effort: "none"`; whether Ollama honours it for
`qwen3:8b` has not been verified here. `tools/verify_ollama.py` reports how many raw replies
carried `<think>` or a reasoning field, and `OLLAMA_THINKING=prompt` switches to the `/no_think`
prefix in the backstory instead. Hidden reasoning is stripped by `visible()` either way, but a
model that reasons spends tokens and time, and `OLLAMA_MAX_TOKENS=512` may then cut a reply
short of its `DECISION:` line.

## Wall-clock cost

A consultation is one owner call without a peer, and two owner calls plus at least one peer
call with an exchange, more when CrewAI retries. The rule decides most decisions, but not as
many as the design estimated: in the fake-model run of `tests/test_rules_first.py`, 118 of 654
expert decisions over 400 ticks went to the model, roughly one every three or four ticks. At
the design's estimate of 10 to 60 s per consultation on a desktop GPU, a 300-tick model run
(about 90 model decisions at that rate) would take roughly a quarter of an hour to an hour and a
half; this is an extrapolation from the fake-model count, not a measurement. The deadline `CONSULT_DEADLINE_S` (300 s) bounds a single consultation.

## Reproducibility

Temperature 0 and a fixed seed make Ollama deterministic for a given model build and prompt,
and the prompts contain no wall-clock values. If seed support varies by Ollama version or the
model build changes, runs may differ in model text, and through it in decisions and the
facility's trajectory. The rules path stays bit-identical to the source
([alignment-baseline.md](alignment-baseline.md)). There is no response cache in this phase.

## Audit trail

The source's SQLite trace store, its replay viewer and its RCT explainer are not carried. The
`llm_call` events, the consultation events and the `results/` files replace the audit they
provided.

## Tick blocking

A tick that holds a consultation waits for it, so the live page advances in bursts during
consultations, by design. The page reads the last published frame and never waits, so it may
show the run one tick behind; the roster's ring shows which expert is being waited on.

## Recorded, never hidden

Retries and fallbacks are recorded. CrewAI's internal re-asks appear as extra owner `llm_call`
events in the same consultation and in `retries`; peer retries are not counted in `retries`
(their `llm_call` events are still written). Fallbacks, parse failures, rejected answers and
timeouts are each counted in `CrewBrain.stats()`, and every fallback's reason is in its decision
record.

## Known weaknesses that affect users

Closing or resetting a run may wait up to the consultation deadline. When a consultation is
abandoned at its deadline its CrewAI worker cannot be cancelled, so `PostOfficeEcosystem.close()`
(and therefore a reset, `SimulationRunner.reset` and the end of `main.py`) waits for it with
`drain(CONSULT_DEADLINE_S)` before the CrewAI agents are reused. Meanwhile a new consultation
that needs the busy owner or peer falls back at once and is recorded as `timeout`, although no
deadline passed for that consultation itself.

CrewAI's console panels are silenced. CrewAI's global event listener prints rich panels (tool
execution, "LLM Error", ...) for every agent whatever its `verbose`, some of them from an
event-bus thread. `crew/console.py::quiet()` switches that formatter off around model runs in
`main.py`, `tools/run_normal.py`, `tools/verify_ollama.py` and the API server, and the test
fixture does the same. Nothing is lost from the record, but CrewAI's own console diagnostics are
not shown.

CrewAI's anonymous telemetry is not switched off by the project outside the test suite; set
`CREWAI_DISABLE_TELEMETRY=true` and `OTEL_SDK_DISABLED=true` in the shell if you do not want it
([running.md](running.md)).

The live page's scenario label is fixed text and names `qwen3:8b` even after `OLLAMA_MODEL` has
been changed; the model badge, the records and `/settings` name the configured model
([crewai-ollama.md](crewai-ollama.md)).

## What "real time" means here

"Real time" in this project means, operationally: At a simulation decision point, the owner
synchronously consults an allowed peer, receives the response before finalizing its decision,
and the resulting decision is then validated and executed by the simulator. It does not mean
unrestricted continuous conversation between agents; the streaming of events to the live page
is observability only.
