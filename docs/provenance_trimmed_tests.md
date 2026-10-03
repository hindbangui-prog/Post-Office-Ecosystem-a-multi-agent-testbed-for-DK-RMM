# Carried tests: trimmed and rewritten

The simulator, rules, gate, peer-map and DK-RMM tests were copied from the source
`tests/` (LF-normalised). This record lists every change made to them in Task 2.

## Trimmed tests

One line per deleted test function: file, test name, reason.

- tests/test_urgent_route.py :: test_an_attack_run_keeps_the_recorded_route_even_if_asked_otherwise :: schedules a perturbation; the perturbation controller is removed
- tests/test_discussion_peers.py :: test_the_three_discussion_messages_exist :: asserts MessageType.DISCUSS_*; replaced by CONSULT_* in this project
- tests/test_decision_pipeline.py :: test_normal_llm_is_the_normal_facility_with_the_always_policy :: the `normal_llm` preset and its scenario are removed (settings has only `default`)
- tests/test_gates.py :: test_both_clerks_are_in_the_catalogue :: uses `observability.tools`, which is removed (only `observability.context` is carried)
- tests/test_dkrmm.py :: test_the_monitor_is_served_and_the_gate_is_a_person_only_door :: needs `post_office.api` (server/runner), which is not part of this task; Task 9 carries the API tests (restored in Task 9, see below)
- tests/test_dkrmm.py :: test_a_run_over_the_api_is_watched_without_being_altered :: needs `post_office.api.runner.SimulationRunner`, not part of this task; Task 9 carries the API tests (restored in Task 9, see below)
- tests/test_agents.py :: test_the_probe_says_plainly_when_the_answer_came_from_the_rules :: exercises the removed model brain's `probe` (removed framework)
- tests/test_agents.py :: test_the_probe_asks_a_question_of_the_shape_the_agents_ask :: exercises the removed model brain's `parse` (removed framework)
- tests/test_discussion_prompts.py :: test_a_single_answer_after_a_closing_reasoning_tag_is_read :: exercises the removed model brain's `parse`/`_reason` (removed framework); Task 5 `crew/parse.py` covers the case

## Listed files not copied

- tests/test_header_digest.py :: whole file :: imports `post_office.api.digest` (Task 9) and `post_office.perturbation.model` (removed) at module level; most of it tests the perturbation digest, which is removed. Its `monitor_digest` cases belong with the Task 9 API tests. (carried in Task 9 without the removed digest's tests, see below)

## Rewritten lines in carried tests

Settings now has only the `default` preset. Lines that named a source preset were rewritten;
nothing else in those files changed. `config("busy")` -> `busy_config()` and `config("normal")` ->
`config("default")` give the same dictionary as the source (`tests/presets.py` holds the source's
`busy` overrides, `arrival_interval` 20.0 and `initial_parcels` 16). `interactive_config(...)` ->
`normal_config()` is equivalent on the rules path only: the new dict drops `llm_async`/`discussions`
and adds `interceptors: []`.

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
- tests/test_urgent_route.py :: `api.runner.interactive_config(config("normal"))` -> `normal_config()` (equivalent on the rules path; the new dict drops `llm_async`/`discussions` and adds `interceptors: []`)
- tests/test_urgent_route.py :: the source alias `config("normal")` -> `config("default")` (same dictionary)
- tests/test_discussion_peers.py :: the source alias `config("normal")` -> `config("default")` (same dictionary)
- tests/test_discussion_briefings.py :: import `normal_config` in place of `api.runner.interactive_config`
- tests/test_discussion_briefings.py :: `api.runner.interactive_config(config("normal"))` -> `normal_config()` (equivalent on the rules path; the new dict drops `llm_async`/`discussions` and adds `interceptors: []`)
- tests/test_discussion_briefings.py :: the source alias `config("normal")` -> `config("default")` (same dictionary)
- tests/test_policy_gate.py :: proposal source label renamed to the CrewAI form (the removed framework's name may not appear)
- tests/test_dkrmm.py :: import `busy_config`
- tests/test_dkrmm.py :: the source preset `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_discussion_peers.py :: added `SOURCE_PEER_MAP` and `test_peer_map_is_the_source_table_verbatim` (brief Step 8)

## Task 9: the API and UI tests

The source `tests/test_api.py`, `tests/test_controls.py` and `tests/test_header_digest.py` were
copied (LF-normalised) and trimmed of the routes spec 16 removes; the two DK-RMM API tests
Task 2 deleted are restored in `tests/test_dkrmm.py`. One line per deleted test function:
file, test name, reason.

- tests/test_api.py :: test_an_operator_command_travels_the_message_bus :: `runner.command_robot` and `POST /robots/{id}/command` are not in spec 16
- tests/test_api.py :: test_commanding_a_robot_that_does_not_exist_is_refused_not_raised :: `runner.command_robot` is not in spec 16
- tests/test_api.py :: test_one_agent_reports_its_children_and_its_recent_messages :: `GET /agents/{id}` is not in spec 16
- tests/test_api.py :: test_one_robot_reports_its_position_battery_and_errands :: `GET /robots/{id}` is not in spec 16
- tests/test_api.py :: test_a_missing_thing_is_a_404_rather_than_a_crash :: `GET /robots/{id}`, `/agents/{id}`, `/tasks/{id}` are not in spec 16
- tests/test_api.py :: test_a_parcel_endpoint_returns_its_whole_conversation :: `GET /parcels`, `/parcels/{id}` are not in spec 16
- tests/test_api.py :: test_communications_can_be_filtered_to_one_parcel :: `GET /parcels`, `/communications` are not in spec 16
- tests/test_api.py :: test_the_simulation_can_be_stepped_over_http :: `POST /simulation/step` is not in spec 16 (the carried tests step with `runner.step`)
- tests/test_api.py :: test_a_policy_change_takes_effect_and_is_recorded :: `POST /simulation/policy` is not in spec 16
- tests/test_api.py :: test_an_empty_policy_change_is_rejected :: `POST /simulation/policy` is not in spec 16
- tests/test_api.py :: test_a_task_can_be_injected_from_outside_the_hierarchy :: `POST /tasks` is not in spec 16
- tests/test_api.py :: test_an_injected_task_for_an_unknown_parcel_is_a_400 :: `POST /tasks` is not in spec 16
- tests/test_api.py :: test_the_settings_never_return_the_key :: `POST /settings` and `/settings/reset` are removed (spec 16)
- tests/test_api.py :: test_a_run_with_no_trace_says_so_rather_than_erroring :: the trace and `/ui/trace`, `/ui/trajectory` are removed
- tests/test_api.py :: test_a_model_can_be_put_behind_agents_over_http :: `POST /settings/agents` is removed; asserts the removed framework's brain name
- tests/test_api.py :: test_changing_the_agents_starts_a_new_run :: `POST /settings/agents` is removed
- tests/test_api.py :: test_the_agents_endpoint_refuses_an_agent_a_model_does_not_belong_behind :: `POST /settings/agents` is removed
- tests/test_api.py :: test_an_empty_list_puts_every_agent_back_on_its_rules :: `POST /settings/agents` is removed; asserts the removed framework's brain name
- tests/test_api.py :: test_a_model_backed_run_keeps_deciding_when_the_provider_is_unreachable :: `POST /settings`, `/settings/agents` are removed and it drives the removed framework's brain; the CrewBrain fallback path is covered by the consultation fallback tests
- tests/test_api.py :: test_the_settings_panel_is_served_and_asks_for_nothing_else :: `GET /settings/ui` (the settings panel) is removed
- tests/test_api.py :: test_anthropic_offers_a_model_without_being_asked_for_a_key :: `GET /settings/providers` is removed
- tests/test_api.py :: test_an_empty_settings_change_is_rejected :: `POST /settings` is removed
- tests/test_api.py :: test_changing_the_settings_is_itself_an_operator_action :: `POST /settings` and `GET /actions` are removed
- tests/test_api.py :: test_the_tools_endpoint_describes_and_counts_them :: `GET /tools` (trace-backed) is removed
- tests/test_api.py :: test_the_trace_can_be_tailed_by_row_id :: `GET /trace` is removed; tailing the log is `GET /events?after=` (test_api_trimmed.py)
- tests/test_api.py :: test_one_parcel_is_one_request :: `GET /trace/{id}` and `/parcels` are removed
- tests/test_api.py :: test_an_operator_action_has_an_owner_and_survives_a_refusal :: `GET /actions`, `POST /robots/{id}/command`, `/simulation/policy` are removed
- tests/test_api.py :: test_a_policy_change_records_both_sides :: `GET /actions`, `POST /simulation/policy` are removed
- tests/test_api.py :: test_a_reset_starts_a_new_run_rather_than_appending_to_the_old_one :: `GET /runs`, `/trace` are removed; a reset's new run id is held by test_runner.py and test_api_trimmed.py
- tests/test_api.py :: test_a_probe_that_names_no_provider_never_echoes_the_key :: `POST /settings/probe` is removed
- tests/test_api.py :: test_the_session_and_the_run_know_about_each_other :: `/sessions`, `/runs` are removed
- tests/test_api.py :: test_the_trace_is_open_before_the_first_tick :: the trace is removed
- tests/test_api.py :: test_a_second_launch_does_not_append_to_the_first_ones_run :: the trace database is removed
- tests/test_api.py :: test_a_run_with_no_trace_keeps_the_name_it_was_given :: the trace is removed
- tests/test_api.py :: test_the_trajectory_tail_returns_rows_the_page_can_append :: `/ui/trajectory/tail` is removed
- tests/test_api.py :: test_the_trajectory_page_follows_the_run_rather_than_photographing_it :: `/ui/trajectory` is removed
- tests/test_api.py :: test_a_new_run_takes_a_free_name_however_many_runs_came_before :: the trace database is removed
- tests/test_api.py :: test_the_trajectory_shows_the_live_run_and_tails_it :: `/ui/trajectory` is removed
- tests/test_api.py :: test_an_old_run_can_be_read_but_is_never_tailed :: `/ui/trajectory` (history replay) is removed
- tests/test_api.py :: test_the_live_run_is_never_served_as_finished :: `/ui/trajectory` is removed
- tests/test_api.py :: test_the_history_lists_every_run_and_marks_the_live_one :: `/ui/history` is removed
- tests/test_api.py :: test_one_broken_extra_does_not_take_out_the_whole_monitor_tab :: reads the removed disturbance schedule and propagation tracer (`eco.propagation`)
- tests/test_api.py :: test_a_pace_a_sleep_can_time_runs_one_tick_at_a_time :: `runner.ticks_per_sleep` (tick batching) is not part of the Task 8 runner
- tests/test_api.py :: test_a_faster_pace_batches_and_keeps_the_rate_it_names :: `ticks_per_sleep`, `MIN_SLEEP` are not part of the Task 8 runner
- tests/test_api.py :: test_a_very_small_pace_is_capped_rather_than_unbounded :: `ticks_per_sleep`, `MAX_BATCH` are not part of the Task 8 runner
- tests/test_api.py :: test_no_pacing_still_runs_one_tick_at_a_time :: `ticks_per_sleep` is not part of the Task 8 runner
- tests/test_api.py :: test_an_rct_reading_can_be_explained_from_the_run_itself :: `GET /dkrmm/explain` and `/ui/dkrmm` are not in spec 16
- tests/test_api.py :: test_every_rct_of_the_run_is_listed_with_when_it_was_detected :: `GET /dkrmm/rcts` and `/ui/dkrmm` are not in spec 16
- tests/test_controls.py :: test_the_scenario_can_be_switched_without_restarting_the_server :: resets to the removed `busy` and `stress` presets; the one preset is `default`, and every other preset is refused (test_api_trimmed.py `test_only_the_default_scenario_can_be_chosen`, test_controls.py `test_an_unknown_scenario_is_refused_rather_than_guessed`)
- tests/test_header_digest.py :: test_every_family_has_an_entry_point_and_a_description :: `SEAM_OF`/`DOES` and the removed `perturbation.model.FAMILIES`
- tests/test_header_digest.py :: test_the_descriptions_promise_a_mechanism_and_not_an_outcome :: `DOES`, part of the removed disturbance digest
- tests/test_header_digest.py :: test_a_facility_with_nothing_scheduled_says_none :: `perturbation_digest` is removed
- tests/test_header_digest.py :: test_due_and_injected_are_not_the_same_sentence :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_the_digest_says_where_the_stimulus_entered :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_provenance_stays_three_answers_rather_than_one_source :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_nothing_measured_yet_is_a_statement_and_not_a_blank :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_a_depth_never_travels_without_its_relation :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_more_than_one_in_force_is_counted :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_the_digest_carries_every_scheduled_disturbance :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_each_row_carries_its_own_phase_and_its_own_consequence :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_the_lead_row_is_one_of_the_rows_and_not_a_fourth_thing :: `perturbation_digest` and the removed `stress` preset
- tests/test_header_digest.py :: test_the_shell_can_open_the_whole_schedule :: the shell's disturbance schedule strip is removed
- tests/test_header_digest.py :: test_the_shell_paints_both_from_the_summary :: renamed `test_the_shell_paints_the_verdict_from_the_summary`; its `paintPerturbation` half removed with the strip
- tests/test_header_digest.py :: test_the_summary_endpoint_offers_both_digests :: renamed `test_the_summary_endpoint_offers_the_monitor_digest`; its `perturbation_digest` half removed with the digest

### Rewritten lines in the Task 9 carried tests

- tests/test_api.py, tests/test_controls.py :: the fixtures set `server.runner = SimulationRunner(..., trace_db=..., session_id=...)`; now `server.use(SimulationRunner(..., rules_only=True))` (the Prototype II runner has no trace, and the module builds no runner at import)
- tests/test_api.py :: every `SimulationRunner(...)` gains `rules_only=True` and drops `trace=`, `trace_db=`, `session_id=` (not parameters of the Task 8 runner)
- tests/test_api.py :: `test_every_read_endpoint_answers_with_json` parametrize list trimmed to the spec 16 routes `/state`, `/events`, `/summary`
- tests/test_api.py :: `test_every_tracking_endpoint_answers_with_json` parametrize list trimmed to `/settings`
- tests/test_api.py :: `test_the_address_people_actually_type_serves_the_ui` asserts `GET /` serves the page (200) instead of redirecting to `/ui` (spec 16: `GET /` is the live page)
- tests/test_api.py :: `test_every_page_of_the_live_ui_is_served` parametrize list trimmed to `/`
- tests/test_api.py :: `test_no_served_page_repeats_an_element_id` scans `/` and the floor page (`live.robots_html`), which the shell carries as an escaped `srcdoc`, instead of `/ui`, `/ui/simple`, `/settings/ui`
- tests/test_api.py :: `test_the_live_shell_names_the_pages_it_mounts` checks the shell names the endpoints it polls (`/frame`, `/consultations`, `/llm/calls`, `/dkrmm/*`, `/settings`, `/ws`, `/summary`) instead of the removed `/ui/*` pages
- tests/test_api.py :: `test_the_floor_follows_the_run_one_frame_at_a_time` reads `/frame` (was `/ui/frame`), its key set adds `run_id`, `roster`, `llm_agents`, `busy`, `in_flight`, and it steps with `server.runner.step(4)` (was `POST /simulation/step`)
- tests/test_api.py :: `test_the_built_file_and_the_served_page_share_their_builders` reads `/frame` and asserts the built frame's keys are a subset of the served one's
- tests/test_api.py :: `test_the_settings_say_whether_any_agent_is_actually_using_a_model` drops the `workspace`, `tools` and `llm_wanted` keys (not in spec 16's `/settings`)
- tests/test_api.py :: `test_the_stream_answers_at_both_of_its_names` connects to `/ws` only (`WS /events` is not in spec 16) and still checks `GET /events`
- tests/test_api.py :: `test_the_websocket_opens_with_the_whole_state_then_streams` steps with `server.runner.step(2)` (was `POST /simulation/step`)
- tests/test_api.py :: `test_the_shell_offers_a_control_for_a_run_that_starts_paused` reads `/` (was `/ui`)
- tests/test_api.py :: `test_the_monitor_tab_renders_normally` and `test_a_failed_monitor_tab_shows_why_rather_than_four_words` read `/` (the DK-RMM pane is part of the shell; `/ui/dkrmm` is not in spec 16), and a failed pane leaves the page a 200 with the pane saying what it lost
- tests/test_api.py :: the pacing tests' comments drop the batching account (the Task 8 runner sleeps once per tick); `test_every_tick_is_broadcast_once_and_in_order`, `test_stopping_during_a_batch_is_not_deferred_to_the_end_of_it` and `test_the_pace_does_not_change_the_run` are otherwise as in the source
- tests/test_controls.py :: `config("busy")` -> `busy_config()` (tests/presets.py, same values)
- tests/test_controls.py :: `test_the_clock_speed_can_be_set_and_read_back` reads `tick_seconds` from `/summary` (`GET /simulation/speed` is not in spec 16)
- tests/test_controls.py :: `test_a_new_run_gets_a_new_seed_and_starts_over` steps with `server.runner.step(30)` (was `POST /simulation/step`)
- tests/test_header_digest.py :: imports `monitor_digest` only (no `perturbation_digest`, `SEAM_OF`, `DOES`, `perturbation.model`)
- tests/test_dkrmm.py :: `test_the_monitor_is_served_and_the_gate_is_a_person_only_door` reads `/dkrmm/state` (was `/dkrmm`), drives the gate over the wire as the source did (`POST /dkrmm/activate` refused before validation, now with 409, then `POST /dkrmm/validate` and `/dkrmm/activate`), also asserts the state reads `ACTIVE` afterwards, and reads `/` for the page (was `/ui/dkrmm`); runner built with `rules_only=True, config=busy_config()`, docstring names the trajectory and RCT log design's section 5. (Task 9 had asserted the three gate POSTs were 404, since spec 16 served no gate; the trajectory and RCT log design serves them, and its Task 2 put the source's assertions back.)
- tests/test_dkrmm.py :: `test_a_run_over_the_api_is_watched_without_being_altered` compares against `build(..., config=busy_config(), scenario="default")` (was `interactive_config(config("busy"))`): the Task 8 runner uses its configuration verbatim and builds with the scenario of its preset

## Trajectory and RCT log, Task 1: the RCT explainer, log and recorder tests

The source `tests/test_rct_explain.py`, `tests/test_rct_log.py` and `tests/test_run_record.py`
were copied (LF) and adapted: discussions are consultations here, Normal is the one preset,
and the runner's recording (`record_dir`, `recorder`, `record_gate`) and the RCT log routes
come in Task 2 of the plan. One line per deleted test function: file, test name, reason.

- tests/test_rct_log.py :: test_the_log_endpoint_lists_this_run_and_earlier_ones :: needs `SimulationRunner(record_dir=...)` and `GET /dkrmm/rct-log`, which Task 2 adds; covered there by `tests/test_api_rcts.py`
- tests/test_rct_log.py :: test_the_log_endpoint_counts_rcts_per_scenario :: needs the runner's recorder and `GET /dkrmm/rct-log` (Task 2); it also asserts the removed `stress` scenario
- tests/test_rct_log.py :: test_the_shell_has_an_rct_log_tab :: needs the shell's RCT log tab and `GET /ui/rcts` (Tasks 3 and 4)
- tests/test_run_record.py :: test_without_a_record_folder_nothing_is_written :: asserts `runner.recorder is None` and calls `runner.record_gate()`, which Task 2 adds; covered there by `tests/test_recording.py`

### Rewritten lines in the Task 1 carried tests

- tests/test_rct_explain.py :: module docstring says "consultations" for "discussions"
- tests/test_rct_explain.py :: imports `pytest`, `tests.consult_helpers` (`ask`, `ecosystem_on`, `equally_placed`, `events`) and `tests.fake_ollama.deciding_script` for the added test
- tests/test_rct_explain.py :: the `discussion(...)` helper builds a consultation as `crew/events.py` writes it: `consult_opened` (actor owner, target peer, correlation the id; detail `consultation_id`, `peer`, `decision`, `options`), a `message` of type `CONSULT_REQUEST` (content `consultation_id`, `decision`, `text`; no options, as in a run), and `consult_closed` (detail `consultation_id`, `decision`, `outcome`, `choice`), in place of `discussion_opened`, `DISCUSS_OPEN` and `discussion_closed`
- tests/test_rct_explain.py :: test_a_discussion_on_the_same_task_is_a_strong_link_and_a_shared_robot_a_weak_one :: two asserts added: `discussion_messages == 2` (the two `CONSULT_REQUEST` messages) and the summary says "strongly linked to a consultation"
- tests/test_rct_explain.py :: added test_an_open_consultation_keeps_the_options_it_was_opened_with: an open consultation (opened with options T-1/T-2, a CONSULT_REQUEST without options, no close) and a trouble event on T-1; the row is `open`, `closed` None, `strong >= 1` (pins reading options from `consult_opened` and the guard that a request without options keeps them)
- tests/test_rct_explain.py :: added test_a_consultation_with_no_peer_names_its_owner_alone: a peerless consultation leading the strong links is named by its owner alone in the summary, with no arrow
- tests/test_rct_explain.py :: added test_a_consultation_of_a_fake_model_run_is_explained_with_its_links: 60 ticks on the fake Ollama (`deciding_script`), a SCHEDULING consultation forced as the live UI tests force it if none arose, and the last consultation's row in `explain(...)["discussions"]` carries its id, owner, peer, decision, outcome, ticks and integer strong/weak counts; `discussion_messages` equals the window's `CONSULT_*` message rows
- tests/test_rct_log.py :: imports `settings.scenario_label` in place of `api.runner.SimulationRunner` and `dkrmm.states.OperationalState` (used only by the deleted fixture's tests)
- tests/test_rct_log.py :: test_each_listed_rct_names_its_scenario :: the Normal label is `scenario_label()` (was "Normal Ecosystem"); the unknown `stress_actorattack` is labelled by its own name (was "Stress-ActorAttack")
- tests/test_rct_log.py :: the `recording_client` fixture deleted with the three tests that used it
- tests/test_run_record.py :: `runner_in` builds a `Recorded` (a NORMAL ecosystem from `build(seed=3, config=normal_config(), run_id="rec", log_path=..., scenario="default")`, `DKRMM(eco).attach()` and a `RunRecorder(root, run_id, scenario, seed=3, config={"llm_agents": []})`, stepped eco, monitor, recorder each tick as the source runner did) in place of `SimulationRunner(record_dir=...)`
- tests/test_run_record.py :: test_the_dkrmm_record_is_written_as_the_run_goes :: asserts `record["control"] is True`
- tests/test_run_record.py :: test_each_rct_says_which_scenario_it_was_detected_in :: runs the Normal preset (was `preset="stress"`): `scenario` is `normal`, `scenario_label` is `scenario_label()` in the RCT file and the record, and the record's `scenario` is the preset `default`
- tests/test_run_record.py :: added test_an_unknown_preset_is_recorded_under_its_own_name: the source's `stress` half of the test above, with `stress` as its own label (there is no stress preset)
- tests/test_run_record.py :: added test_the_normal_label_names_the_model_it_is_given: `scenario_of("default", model=...)` and `RunRecorder(..., model=...)` label Normal with `scenario_label(model)`
- tests/test_run_record.py :: test_a_gate_decision_is_kept_in_the_record :: `runner.recorder.write(runner.monitor)` in place of `runner.record_gate()` (Task 2)

## Trajectory and RCT log, Tasks 2 to 5: the carried tests changed again

- tests/test_dkrmm.py :: the gate test's 404 loop replaced by the source's over-the-wire gate assertions (see the Task 9 entry above)
- tests/test_rct_explain.py :: added test_an_early_readings_window_starts_at_tick_0_whose_events_it_counts: a reading at tick 21 reports the window `[0, 21]` (the source reported `[-38, 21]`) and counts its tick-0 events
- tests/test_rct_explain.py, tests/test_run_record.py :: unchanged otherwise; the tests the Task 1 entries above say were deleted for want of the runner's recorder and routes are covered by the new `tests/test_recording.py` and `tests/test_api_rcts.py`, and the shell's RCT log tab by `tests/test_live_ui.py`

The Task 9 entries above that give `GET /dkrmm/explain`, `GET /dkrmm/rcts`, `/ui/trajectory`
or `/ui/trajectory/tail` as not served record why those source tests were deleted then. The
trajectory and RCT log design serves these routes again. The deleted tests are not restored:
all but one also read the source's trace store or its `/ui/dkrmm` page, which are still not
part of this project, and the one that does not
(`test_the_trajectory_page_follows_the_run_rather_than_photographing_it`) is matched by
`tests/test_trajectory.py::test_the_page_is_the_template_filled_with_the_live_run`.
`tests/test_api_rcts.py` and `tests/test_trajectory.py` cover the routes as served here.
