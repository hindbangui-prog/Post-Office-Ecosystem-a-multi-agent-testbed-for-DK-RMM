# Provenance notes

Facts about files classified `unchanged` that a reader of the copied text
should know, recorded here rather than by editing the copied file.

- post_office/discussion/briefings.py :: copied unchanged from the source, but its
  module docstring's claim "Read on the peer's tick ..., never from a worker
  thread" no longer holds in Prototype II. A consultation's owner runs in a
  worker thread (`crew/consultation.py`), and the peer's briefing is read from
  that worker, inside the owner's tool use (`crew/tools.py`), while the tick's
  thread is blocked in `join` waiting for it. It is still the floor as it is
  at the moment of the consultation, because the tick is not moving; and the
  read is made under the consultation service's lock and only while the
  consultation is open, so a worker abandoned at its deadline never reads the
  live world while the tick has moved on.

## Adapted from a different source path

`tools/provenance.py` pairs a file with the source file at the same relative
path unless `tools/write_provenance.py::SOURCE_PATHS` names another one; that
map gives the `replaced` files the source file each takes over from (spec 2.1)
and gives the file below the source it was adapted from, so the Files table
shows those source paths and hashes. What was changed is recorded here.

- post_office/ui/floor.html :: adapted from the source `tools/replay_template.html`
  (the floor, the interaction graph, the robot cards and the message feed that the
  source's `ui/live.py::robots_html` served at `/ui/robots`). The discussion strip,
  links, bubbles and log are removed (Prototype II consults through CrewAI and its
  frames carry no discussion rows), consultation messages (`CONSULT_*`) take the
  feed's highlight that discussion turns had, and the run line no longer claims
  every decision is deterministic. It is served inside the live page as an
  escaped `srcdoc`, so it needs no route of its own.

## The runtime communication taxonomy (2026-10-02)

The second iteration added a labelling layer over the event log (the design
`docs/superpowers/specs/2026-10-02-runtime-communication-taxonomy-design.md` and
its plan). Its files, and the one class that changed:

- post_office/communication/taxonomy.py :: new; the taxonomy (channels, types,
  `classify`, `table()`), a pure module with no source counterpart.
- post_office/ui/feed.py :: new; the Runtime communication pane's rules as pure
  functions over event dicts, mirrored by `ui/live.html`'s JavaScript.
- tools/taxonomy_table.py :: new; prints the interaction type table of
  `docs/events.md` from `taxonomy.table()`.
- tests/test_taxonomy.py, tests/test_taxonomy_completeness.py,
  tests/test_event_stamping.py, tests/test_dkrmm_stamping_invariance.py,
  tests/test_api_taxonomy.py, tests/test_feed_integrity.py :: new; the tests of
  the taxonomy design's section 8.
- post_office/communication/bus.py :: was `unchanged`, now `adapted`: the
  `message` / `subagent_message` event's detail gains `in_reply_to` (the
  message's own field, or ""); nothing else in the file differs from the source.
- post_office/communication/events.py, post_office/ui/views.py,
  post_office/api/server.py, post_office/ui/live.html, post_office/ui/floor.html,
  post_office/ui/live.py, tools/normal_fingerprint.py :: `adapted` before and
  after; changed again for the stamp (`Event` slots, `emit`), the `/frame` rows,
  `GET /taxonomy`, the Runtime communication tab and the typed graph, and the
  stamp filter beside `STRIP`.

## The trajectory and RCT log panes (2026-10-02)

The third iteration brought back the source's trajectory page, its RCT log page and the three
observability modules behind them (the design
`docs/superpowers/specs/2026-10-02-trajectory-and-rct-log-design.md` and its plan). Their five
source files leave the Removed table, and so do the three source tests carried with them:

- post_office/observability/rct_explain.py :: adapted; discussions are consultations
  (`consult_opened`, `consult_closed`, the `CONSULT_REQUEST` message, `CONSULT_*` messages
  counted), a consultation's options are kept from its opening when its request names none, a
  peerless lead consultation is named by its owner alone, and the reported window starts at
  tick 0 at the earliest (`[max(0, T - WINDOW + 1), T]`; the source reported a negative first
  tick for an early reading, whose tick-0 events it counted). `events_from_log` holds a module
  lock over its read and cache update and returns a copy of the cached list (the source's
  unlocked cache let two threads reading one log append its events twice). The result keys,
  kinds, links and baseline are the source's.
- post_office/observability/rct_log.py :: unchanged; the design called it adapted, but the one
  change it allowed (`scenario_of` from `.run_record`) is already the source's import, so the
  file is byte-identical.
- post_office/observability/run_record.py :: adapted; `scenario_of` reads Normal from
  `config.settings` (with an optional model for the label), the record is built with
  `control=True`, and two comments no longer name removed machinery.
- post_office/ui/rcts.html :: adapted; every user-visible "discussion" reads "consultation",
  em-dashes became hyphens, the leading comment no longer names a removed scenario family
  or discussions, and a consultation with no peer is shown by its owner alone, with no arrow.
- post_office/ui/trajectory.html :: adapted from the source `tools/trajectory_template.html`
  (paired in `tools/write_provenance.py::SOURCE_PATHS` and `ELSEWHERE`, as `ui/floor.html` is);
  the lanes map sub-agent requests and replies to tools and `simulation/*` to the operator, the
  discussion view is the Expert consultation view drawn from consultation and `llm_call` rows,
  the tail sends the page's run and stops on a 409, the link to the source's history page is
  removed, em-dashes and a literal NUL became a hyphen and `\u0000`, and a consultation with
  no peer is labelled by its owner alone, with no arrow.
- tests/test_rct_explain.py, tests/test_rct_log.py, tests/test_run_record.py :: adapted;
  carried and changed as `docs/provenance_trimmed_tests.md` lists.
- tests/test_recording.py, tests/test_api_rcts.py, tests/test_trajectory.py :: new.
- post_office/observability/__init__.py :: new; the package docstring.
- post_office/api/runner.py, post_office/api/server.py, post_office/ui/views.py,
  post_office/ui/live.py, post_office/ui/live.html, main.py, tests/test_dkrmm.py ::
  `adapted` before and after; changed again for the recorder, the seven DK-RMM routes and the
  three page routes, the trajectory rows, the two tabs and the gate, `--record-dir` and
  `--no-record`, and the gate test's over-the-wire assertions.
- tests/test_api_trimmed.py, tests/test_live_ui.py :: `new` before and after; the route table
  gains the ten routes, and the browser tests cover the two tabs, the gate and the explanation.
- post_office/dkrmm/ :: unchanged, and pinned by its tree hash in `tests/test_api_rcts.py`.

## The C2-NEAR-SYSTEM-OVERRIDE experiment (2026-10-11)

A collapse-only experiment isolated from the Normal scenario (the design
`docs/superpowers/specs/2026-10-11-c2-near-system-override-design.md`, the report
`docs/c2-near-system-override.md`). Its files, and the two files that changed:

- post_office/stress/__init__.py, post_office/stress/c2near_system_override.py,
  post_office/stress/operational.py, post_office/stress/system_override.py,
  post_office/stress/measure.py, post_office/stress/collapse.py,
  post_office/stress/analysis.py :: new; the experiment definition, the scheduled
  faults, the System Override campaign, the per-tick measurement, the collapse
  criterion and the attack-outcome join. `__init__.py` and `collapse.py` share a
  relative path with files of the source's removed `stress` package (experiment
  tooling), so the Files table shows the same-path source file's hash beside them and
  those two source paths no longer appear under Removed; the code is new and reads
  nothing from the source.
- tools/run_c2near_system_override.py, tests/test_c2near_system_override.py,
  docs/c2-near-system-override.md :: new; the driver, the 41 tests of the brief, the report.
- post_office/crew/interception.py :: `new` before and after; `from_config` returns
  the campaign as the agent hooks when a configuration carries a non-empty
  `c2near_system_override` block, and `Interception.inert()` as before otherwise.
- post_office/simulation/ecosystem.py :: `adapted` before and after; `_install_crew`
  calls `bind(eco)` on agent hooks that have one (the Normal `AgentHooks` has none), and
  `_install_interception` lists the key under the `interception` event's `active` when
  it is present (`[]` otherwise, as before).
- post_office/stress/report.py, post_office/ui/c2near_report.html, tools/c2near_report.py,
  tests/test_c2near_report.py :: new; the experiment's results page, one standalone
  HTML file made from a results directory (no server, no network; nothing under
  `results/normal` read or written), and its tests.
- post_office/observability/zone_backlog.py,
  post_office/observability/decision_trace.py,
  post_office/observability/experiment.py, tests/test_live_experiment.py :: new; the
  live M-S-DROP experiment's instrumentation: the backlog by zone per tick, the
  decision-to-action traces linked by identifiers only, and the run directory kept by
  the live runner under `--experiment-dir` (the layout
  `tools/run_collapse_scenarios.py` writes), with their tests. Read-only: no event is
  emitted, and a run's event stream is the same with them as without.
- post_office/communication/bus.py :: `adapted` before and after; `watch_inbox` adds
  read-only observers of `inbox` (called with the receiver, the tick and the messages
  taken; an empty list costs one `if`), used by the decision traces as the evidence
  that a message reached its receiver on time.
- post_office/api/runner.py, post_office/api/server.py, post_office/ui/live.py,
  post_office/ui/live.html, main.py, tests/test_api_trimmed.py :: `adapted` (the test:
  `new`) before and after; changed again for `stop_at` and `experiment_dir`
  (`--stop-at`, `--experiment-dir`), the zone series and the tracer beside every run,
  `GET /zones`, `GET /decision-traces` and `/summary`'s `kept`, the zone chart in the
  DK-RMM pane, the Decision to action table under the consultations and the kept-run
  line on the study strip; the route table gains the two routes.
- docs/ms-drop-model-enabled-v1.md, docs/img/ms-drop-crewai-v3.svg,
  docs/img/ms-drop-zone-backlog-rules.svg, tools/zone_backlog_figure.py :: new;
  version 1 of the M-S-DROP model-enabled report kept as it was when version 2
  replaced `docs/ms-drop-model-enabled.md`, the version 3 schema, the per-seed zone
  figure of the rules-only live runs and the script that draws it (standard library
  only).
- docs/img/ms-drop-zone-backlog-model.svg :: new; the per-seed zone figure of the
  model-enabled live runs (made through the page on the user's machine), drawn by
  `tools/zone_backlog_figure.py`.
- docs/dkrmm-backlog-level-deviation.md :: new; the report of `backlog_level_deviation`, a
  DK-RMM indicator added and withdrawn on 2026-10-13, kept as the record of what was measured.
- tests/test_dk_view.py :: new; the live page's DK word (an RCT reading whose
  dragon-king test held), on the study strip, the badges, the DK-RMM tab and the
  API fields behind them.
- tests/test_ms_stall.py :: new; M-S-STALL, the fifth collapse scenario (every message
  held from 1800 and all delivered at 2100): the registry, the rule, the four scenarios
  unchanged, one rules-only run on seed 13 with what DK-RMM read, and the live page.
- docs/img/ms-stall-dk-seed13-model.svg, tools/ms_stall_dk_figure.py :: new; the schema of why
  the live page shows DK on the user's model-enabled M-S-STALL seed 13 run (record
  results/live/dkrmm/api-6-8.json) and the script that draws it from that record (standard
  library only).
- docs/img/ms-stall-steps-seed13-model.svg, tools/ms_stall_steps_figure.py :: new; the
  step-by-step schema of the user's model-enabled M-S-STALL seed 13 run and the script that
  draws it from results/live/dkrmm/api-6-8.json (standard library only).
