# Carried tests: trimmed and rewritten

The simulator, rules, gate, peer-map and DK-RMM tests were copied from the source
`tests/` (LF-normalised). This file records every change made to them in Task 2.

## Trimmed tests

One line per deleted test function: file, test name, reason.

- tests/test_urgent_route.py :: test_an_attack_run_keeps_the_recorded_route_even_if_asked_otherwise :: schedules a perturbation; the perturbation controller is removed
- tests/test_discussion_peers.py :: test_the_three_discussion_messages_exist :: asserts MessageType.DISCUSS_*; replaced by CONSULT_* in this project
- tests/test_decision_pipeline.py :: test_normal_llm_is_the_normal_facility_with_the_always_policy :: the `normal_llm` preset and its scenario are removed (settings has only `default`)
- tests/test_gates.py :: test_both_clerks_are_in_the_catalogue :: uses `observability.tools`, which is removed (only `observability.context` is carried)
- tests/test_dkrmm.py :: test_the_monitor_is_served_and_the_gate_is_a_person_only_door :: needs `post_office.api` (server/runner), which is not part of this task; Task 9 carries the API tests
- tests/test_dkrmm.py :: test_a_run_over_the_api_is_watched_without_being_altered :: needs `post_office.api.runner.SimulationRunner`, not part of this task; Task 9 carries the API tests
- tests/test_agents.py :: test_the_probe_says_plainly_when_the_answer_came_from_the_rules :: exercises the removed model brain's `probe` (removed framework)
- tests/test_agents.py :: test_the_probe_asks_a_question_of_the_shape_the_agents_ask :: exercises the removed model brain's `parse` (removed framework)
- tests/test_discussion_prompts.py :: test_a_single_answer_after_a_closing_reasoning_tag_is_read :: exercises the removed model brain's `parse`/`_reason` (removed framework); Task 5 `crew/parse.py` covers the case

## Listed files not copied

- tests/test_header_digest.py :: whole file :: imports `post_office.api.digest` (Task 9) and `post_office.perturbation.model` (removed) at module level; most of it tests the perturbation digest, which is removed. Its `monitor_digest` cases belong with the Task 9 API tests.

## Rewritten lines in carried tests

Settings now has only the `default` preset. Lines that named a source preset were rewritten to the
same dictionary; nothing else in those files changed. `tests/presets.py` holds the source's `busy`
overrides (`arrival_interval` 20.0, `initial_parcels` 16).

- tests/test_ecosystem.py :: import `busy_config`
- tests/test_ecosystem.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_vehicles.py :: import `busy_config`
- tests/test_vehicles.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_throughput.py :: import `busy_config` in place of the now unused `config`
- tests/test_throughput.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_paid_service.py :: import `busy_config` in place of the now unused `config`
- tests/test_paid_service.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_queued_assignment.py :: import `busy_config` in place of the now unused `config`
- tests/test_queued_assignment.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_dispatch_priority.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_priority.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_urgent_route.py :: import `normal_config` in place of `api.runner.interactive_config`
- tests/test_urgent_route.py :: drop the `perturbation` import (used only by the trimmed attack-run test)
- tests/test_urgent_route.py :: `api.runner.interactive_config(config("normal"))` -> `normal_config()` (its replacement; the dropped `llm_async`/`discussions` keys are inert on rules)
- tests/test_urgent_route.py :: the source alias `config("normal")` -> `config("default")` (same dictionary)
- tests/test_discussion_peers.py :: the source alias `config("normal")` -> `config("default")` (same dictionary)
- tests/test_discussion_briefings.py :: import `normal_config` in place of `api.runner.interactive_config`
- tests/test_discussion_briefings.py :: `api.runner.interactive_config(config("normal"))` -> `normal_config()` (its replacement; the dropped `llm_async`/`discussions` keys are inert on rules)
- tests/test_discussion_briefings.py :: the source alias `config("normal")` -> `config("default")` (same dictionary)
- tests/test_policy_gate.py :: proposal source label renamed to the CrewAI form (the removed framework's name may not appear)
- tests/test_dkrmm.py :: import `busy_config`
- tests/test_dkrmm.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_discussion_peers.py :: added `SOURCE_PEER_MAP` and `test_peer_map_is_the_source_table_verbatim` (brief Step 8)
