# Limitations and risks

This document restates the risks of the design (specification section 20) as they stand in
what was built, and adds the known weaknesses found during implementation that affect users.
None of these risks is addressed by replacing the model or by making the consultation
asynchronous: both would change the experimental variable the baseline is meant to hold fixed.

## One real run

Every automated check runs against the fake Ollama of the test suite. One real run exists:
300 ticks at seed 1 on the project owner's machine against a real `qwen3:8b`, recorded in
[real-run-2026-10-02.md](real-run-2026-10-02.md). It showed no model failure (all fallback,
retry, parse-failure, rejected-answer and timeout counters 0, every call served by `qwen3:8b`,
median call 307 ms), so the failure paths below were exercised only by the fake. One run at
one seed says nothing about variance between runs, other seeds, longer runs or thinking on;
those remain to be measured with `tools/run_normal.py` ([verification.md](verification.md)).

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
call with an exchange, more when CrewAI's executor asks the owner again within its reasoning
loop. The rule decides most decisions, but not as
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

The source's SQLite trace store, its history page and its replay viewer are not carried, so
there is no store of finished runs to browse or replay. The `llm_call` events, the consultation
events and the `results/` files replace the audit they provided. The source's trajectory page
and its RCT explainer are back, over the event log rather than a trace store: the Trajectory tab
shows the live run only, and the RCT log reads the files the API server saves at detection
([running.md](running.md)).

The Trajectory holds only what the event logger holds in memory, the newest 8000 events
(`keep_events`). On a longer run the older events are gone from the page; they are kept only in
the event log file, and only when the server was started with `--log`. A page left open across a
reset stops at the old run and must be reopened. In its Expert consultation view, a
consultation's Reason shows its question and its response (`consult_question`,
`consult_response`); the text of a delegation (`consult_delegation`) is not shown there, though
it is a row of the Events view.

Saving an RCT goes over the run's whole event log (the log file, read on from where it last
stopped, or the logger's memory) and explains the reading, once per RCT, inside the tick that
detected it (under the step lock): about 25 ms per RCT on a run without a log file, and up to
about 170 ms measured after 1000 busy ticks with an 8.8 MB log file. While the run has an RCT,
`GET /dkrmm/rcts` goes over the whole log again on every request to put a clock time on each
RCT, and the live page asks for it about every 1.5 s while the DK-RMM pane is showing;
`GET /dkrmm/explain` does the same once per request. Without a log file an explanation is
computed from the logger's in-memory events (`source: memory`), so a task named before the
newest 8000 events cannot be tied to its parcel.

The recorder sees a new reading by DK-RMM's history growing, as the source's did. DK-RMM keeps
its last 400 readings, so from the 401st (about tick 8000) the history no longer grows and the
on-disk record stops growing with it: the record is rewritten only when an RCT is saved or a
gate verdict is given, and the readings made since then carry no clock time (`detected_at` is
empty). An RCT is still saved to its own file when it is detected.

A gate verdict and a reset can cross. A verdict decided on the old run's monitor just before a
reset swaps the monitor and the recorder is not written to the old run's record: the write
that follows it is made after the swap, to the new run's record. The window is a few
instructions wide. In model mode a reset checks the model (a request to Ollama) while it holds
the runner's record lock, so a gate click during that reset waits for the model check before
it is answered.

An explanation's window is the 60 ticks up to the reading; for a reading before tick 60 it
starts at tick 0 and counts the events of tick 0 (the source reported a negative first tick
there). The links between trouble events and consultations are the source's rule, which says
little for most consultations here ([dkrmm.md](dkrmm.md)); a link is evidence, not proof of
cause.

## Tick blocking

A tick that holds a consultation waits for it, so the live page advances in bursts during
consultations, by design. The page reads the last published frame and never waits, so it may
show the run one tick behind; the roster's ring shows which expert is being waited on.

## Recorded, never hidden

Retries and fallbacks are recorded. CrewAI's internal re-asks within one reasoning loop appear
as extra owner `llm_call` events in the same consultation and in `retries`; peer retries are not
counted in `retries` (their `llm_call` events are still written). CrewAI never re-runs a task
after an exception (`max_retry_limit=0`), so an HTTP failure, even one after the peer has
answered, closes the consultation `model_failed` and the rule answers; the peer's answer stays
in the record but does not reach the decision. Fallbacks, parse failures, rejected answers and
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

## DK-RMM sees the model layer's bookkeeping

The `consult_*` and `llm_call` agent events enter DK-RMM's window and actor profiles and move
its indicator values: in a 400-tick fake-model probe, 19 of 20 assessments differed from those
of a monitor fed the same stream without those events (at tick 381 `behavioural_similarity`
0.3046 against 0.3107, the window's events 821 against 688), while the states were identical
in all 20 ([dkrmm.md](dkrmm.md)). DK-RMM is not changed in this phase. Whether these events
should count as agent behaviour, or be kept out of the monitor's window, is a design question
for the researcher; until it is settled, a model run's indicator values are not directly
comparable with a rules-only run's, which has none of these events.

## What "real time" means here

"Real time" in this project means, operationally: At a simulation decision point, the owner
synchronously consults an allowed peer, receives the response before finalizing its decision,
and the resulting decision is then validated and executed by the simulator. It does not mean
unrestricted continuous conversation between agents; the streaming of events to the live page
is observability only.
