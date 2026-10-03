# Trajectory and RCT log panes, ported from the source (NORMAL scenario)

Date: 2026-10-02. Status: approved in conversation by the project owner ("from the source
project, use the same trajectory and RCT log"), with three choices made there: the Trajectory
reads the event stream (no trace database), its discussion view becomes a consultation view
drawn the same way, and the RCT log records to disk with the gate routes. The specification
of 2026-10-01 and the taxonomy specification of 2026-10-02 remain authoritative for
everything not named here.

## 1. Goal and non-goals

Two tabs of the source's live page come back with the same behaviour and look:

- **Trajectory**: the per-event stream viewer (`tools/trajectory_template.html` in the source):
  four density lanes (operator, agents, tools, robots), the event list grouped by correlation
  thread with search, follow and paging, the inspector (summary, preview, raw), a 1 s tail
  poll while the run is live, and the second mode that drew one bar per discussion with its
  turns, now drawn per consultation.
- **RCT log**: the cross-run list of RCTs saved at detection (`post_office/ui/rcts.html` in
  the source) with scenario and run filters, the detail view (what DK-RMM saw, the gate line,
  the cause as saved at detection), its own 3 s poll, and the on-disk recording that feeds it.

Not in scope: the source's SQLite trace store, replay viewer, history page, sessions and
actions; perturbations, attack controls, stress batteries, OpenRT; any change to DK-RMM's
indicators, thresholds, transitions or RCT criteria; any change to the seven roles, the Brain
seam, CrewBrain, the peer map, the consultation protocol or the Ollama integration.

## 2. Invariants (each pinned by a test)

1. DK-RMM code is unchanged (`post_office/dkrmm/` diff empty). The gate routes call the
   monitor's existing `validate`, `activate`, `dismiss`, which record a person's verdict on a
   reading and never alter an assessment, an indicator or a state.
2. The simulator and the agents are untouched; recording and the trajectory read the event
   logger and the monitor only. If the recorder fails, the run continues (the runner guards it
   as the source did).
3. No synthetic events or text: every trajectory row is one `Event`; every RCT file's reading
   is `Assessment.as_dict()` and its explanation is computed from the run's own events.
4. The event stream is not changed: no new topic, no changed detail (the taxonomy invariants
   hold; the filtered alignment baseline still matches).
5. The source project is not modified.

## 3. Observability package (`post_office/observability/`)

Three source files come back as `adapted` (their `source_sha256` recorded in provenance):

- `rct_explain.py`: `explain(events, tick, window=WINDOW, every=EVERY, baseline=BASELINE)`
  exactly as the source, except that discussions are consultations: `_discussions` reads
  `consult_opened` (detail `consultation_id`, `peer`, `decision`, `options`; owner = actor),
  `consult_closed` (`outcome`, `choice`), and the bus message `CONSULT_REQUEST`
  (content `consultation_id`); `discussion_messages` counts `message_type` starting
  `CONSULT_`; the result keys keep the source's names (`discussions`, `discussion_messages`)
  so `rcts.html` reads them unchanged, and the summary text says "consultation(s)" where the
  source said "discussion(s)". Kinds, subjects, links (strong = shared task or parcel, weak =
  shared robot), the baseline windows and `events_from_log`/`wall_clock_at` are unchanged.
- `rct_log.py`: unchanged apart from `scenario_of` coming from `run_record`.
- `run_record.py`: `RunRecorder(root, run_id, scenario, seed, config)` as the source
  (unique name, `root/dkrmm/<name>.json`, `root/rct/<name>/<tick>.json`, atomic writes,
  `detected_at` stamped the tick the recorder first sees a reading, `update(monitor, eco)`
  each tick, `write(monitor)` with the record, `readings` and gate changes). `scenario_of`
  reads `post_office.config.settings.SCENARIOS` / `scenario_label` (Normal is the only
  preset; the label is the one the live page shows). The record is `dkrmm.record.build_record`
  with `control=True` for Normal.

Tests: the source's `test_rct_explain.py`, `test_rct_log.py`, `test_run_record.py` carried and
adapted (consultation events in place of discussion events; recorded in provenance_trimmed_tests).

## 4. Recording in the runner

`SimulationRunner` gains `record_dir: Optional[Path]` (constructor argument; `None` = no
recording) and `self.recorder`. `_start_recorder()` runs at init and on reset; `_tick` calls
`monitor.tick()` then `recorder.update(monitor, eco)` inside the same exception guard the
monitor has; `record_gate()` writes after a gate verdict. `main.py --api` records to
`results/live/` by default (`--record-dir PATH`, `--no-record`); `tools/run_normal.py` is
unchanged (it already writes `dkrmm.json`; it does not write per-RCT files). Tests do not
record unless they pass a `tmp_path`.

## 5. Routes (added to the served table; spec 16 of 2026-10-01 is amended in section 9)

| Route | Returns |
|---|---|
| `GET /dkrmm/rcts` | the current run's RCTs from `monitor.history`, newest first: tick, detected_at (`wall_clock_at` over the run's events), severity, kinds, evidence, status; plus `assessments`, `run_id` |
| `GET /dkrmm/explain?tick=` | `explain(events, tick)` over the run's events (log file if the logger has a path, else `recent()`), plus `source: log|memory` |
| `GET /dkrmm/rct-log` | `list_rcts(root)` rows each with `current`, plus `current_run`, `recording`, `folder`, `current_scenario`, `current_scenario_label`, `scenarios` (every preset of `settings.SCENARIOS` with its count, plus any other scenario found) |
| `GET /dkrmm/rct-log/item?run=&tick=` | the saved file whole; 404 when not recording or absent; 400 on a bad run name |
| `POST /dkrmm/validate`, `/dkrmm/activate`, `/dkrmm/dismiss` | body `Judgement {by, note}`; the monitor's method; 409 when there is nothing to decide; `runner.record_gate()`; returns `as_dict()` |
| `GET /ui/trajectory?limit=&run_id=&archived=` | the trajectory page (section 6); `run_id`/`archived` are accepted for compatibility and only the live run is served (there is no store of finished runs) |
| `GET /ui/trajectory/tail?after_id=&started=&limit=` | `{rows, last_id, total}` over `logger.since(after_id)` |
| `GET /ui/rcts` | `rcts.html`, no-store |

When the runner has no recorder, `/dkrmm/rct-log` answers `recording: false` with an empty
list (the page shows the source's "not saving RCTs" note) and `/dkrmm/rct-log/item` is 404.

## 6. Trajectory over the event stream

`post_office/ui/trajectory.html` is the source's `tools/trajectory_template.html`, adapted;
`live.trajectory_html(runner, limit)` fills `/*__TRAJECTORY_DATA__*/null` with
`views.trajectory_data(runner, limit)`; `views.trajectory_row(event, base)` keeps the source's
positional row:

```
[id, tick, ms, type, actor, target, correlation, duration, text, payload]
```

- `id` = `seq`; `ms` = wall_clock offset from the first row shown; `type` = `event_type_for
  (category, topic)` with the source sink's rules ((agent, decision) -> `agent/decision`;
  (communication, message | subagent_message) -> `agent/message`; (communication,
  message_refused) -> `agent/refused`; else `category/topic`); `duration` = `detail.latency_ms`
  when present (llm_call, consult_response, consult_closed, llm decisions) else null; `text` =
  `views.describe(event, 200)`; `payload` = the source's KEEP keys plus `interaction_type`,
  `channel`, `consultation_id`, `phase`, `served_model`, `latency_ms`, `outcome`, `options`,
  `in_reply_to`, `message_id`, trimmed as the source trims.
- `trajectory_data` returns `events`, `started`, `span`, `ticks`, `truncated` (when the logger
  holds more than `limit`, the newest `limit`), `total` (`logger.total`), `run_id`,
  `archived: false`, `run` (run_id, seed, preset `normal`, model from settings, started_at from
  `simulation_started`, ticks), `summary` (events, started, last_event, ticks, actors,
  correlations, `model_requests` = llm_call count, `tool_calls` = SUBTASK_REQUEST count,
  `tool_errors` = 0, `user_actions` = 0, finished = `simulation_stopped` seen) and `log` (the
  pretty JSON string the page shows under "Run log").
- `trajectory_tail(runner, after_id, started, limit)` = rows for `since(after_id)`.
- Lanes: `familyOf` as the source, with two mappings for rows the source only had in its
  store: `interaction_type` `subagent_request`/`subagent_response` -> tools; `simulation/*`
  -> operator. Robots: `robot/*`, `battery/*`, actor `R<n>`. Agents: `agent/*`, `supervisor/*`.
  Everything else is world (no lane), as the source.
- Consultation view ("Expert consultation", the source's "LLM-Agent Discussion" renamed):
  one bar per `consultation_id` from `consult_opened` to `consult_closed` on the wall-clock
  axis; turn segments are the `llm_call` rows of that consultation, `[at - latency_ms, at]`,
  filled with the agents colour for `phase: owner` and the tools colour for `phase: peer`;
  bar border by outcome: decided = ok, timeout = warn, no_valid_decision and model_failed =
  bad, peer_failed = other, open = dashed; the summary line counts outcomes, mean call seconds,
  mean consultation seconds and the share of time waiting, as the source computed them; the
  row inspector shows Decision, Owner, Peer, Outcome, Choice, Reason (the question text and
  the response text from `consult_question`/`consult_response`), Took, and the calls.
- Polling, follow, search, paging (1200), the 14000-row cap, `poSuspend`, keyboard: unchanged.

## 7. RCT log page

`post_office/ui/rcts.html` is the source file, adapted only where it names discussions
("Discussion" column heading becomes "Consultation"; the sentence "of them between experts
discussing" becomes "of them between experts consulting"). Scenario select, run filter,
detail view, 3 s poll and `poSuspend` unchanged.

## 8. Live shell

`live.html` gains two iframe tabs beside the existing five: `Trajectory <em>this run,
live</em>` (`#tab-trajectory`, `#pane-trajectory`, `src` set lazily to `/ui/trajectory` on
first open; rebuilt by `restack()` on reset/new run; `poSuspend` when hidden; the source's
"building trajectory from the run so far..." loading box) and `RCT log <em>detected RCTs</em>`
(`#tab-rcts`, `#pane-rcts`, `src /ui/rcts`, skipped by `restack()`, polls on its own). The
DK-RMM pane gains the gate controls the source's DK-RMM pane had (Validate / Activate / Dismiss
with a `by` and `note` field) posting to the gate routes and refreshing the pane, and a link
"explain this reading" that fetches `/dkrmm/explain?tick=` and shows the summary.

## 9. Amendments to earlier specifications

- Spec 2026-10-01 section 16: the served route table is spec 16 plus `GET /taxonomy` (taxonomy
  spec) plus the eight routes of section 5 here; `tests/test_api_trimmed.py` SPEC_ROUTES
  updated.
- Spec 2026-10-01 section 2.1 / provenance: `observability/rct_explain.py`, `rct_log.py`,
  `run_record.py`, `ui/rcts.html`, `ui/trajectory.html` (from `tools/trajectory_template.html`)
  move from `removed` to `adapted`; their removal rows leave the Removed table and
  `docs/camel-removal.md`'s inventory is unchanged (none of them is model-layer code).
- `docs/limitations.md` "Audit trail": the replay viewer and trace store remain absent; the
  trajectory and the RCT explainer are back over the event log.

## 10. Tests

- Carried and adapted: `test_rct_explain.py`, `test_rct_log.py`, `test_run_record.py`.
- `tests/test_recording.py` (new): the runner with `record_dir=tmp_path` writes
  `dkrmm/<run>.json` every tick and `rct/<run>/<tick>.json` at a detection (drive a detection
  by feeding the monitor a scripted trouble window as `tests/test_dkrmm.py` does, or by
  monkeypatching `monitor.history` with a synthetic RCT assessment and calling
  `recorder.update`); the file's `reading` equals `as_dict()`; gate verdict rewrites it; a
  recorder that raises does not stop the run.
- `tests/test_api_rcts.py` (new): the eight routes (shapes, 404/400/409 cases, `recording:
  false` without a recorder); DK-RMM diff empty against main (static check of the tree hash
  of `post_office/dkrmm/` recorded in the test).
- `tests/test_trajectory.py` (new): `trajectory_row` shape and `event_type_for`; `trajectory_data`
  truncation and summary counts on a seeded run; `trajectory_tail` after a cut; every row is
  one logger event (seq set equality); the page carries `/ui/trajectory/tail`.
- `tests/test_live_ui.py`: the two tabs open, the Trajectory shows rows and lanes and tails
  (row count grows after ticks), its consultation view draws a bar after `_consult`, the RCT
  log page loads with the "not saving" note when not recording and lists an RCT when the
  fixture records to `tmp_path` and a detection is forced; gate buttons post and the pane
  shows the verdict.

## 11. Files

New (adapted from source): `post_office/observability/rct_explain.py`, `rct_log.py`,
`run_record.py`, `post_office/ui/rcts.html`, `post_office/ui/trajectory.html`, three carried
tests. Changed: `post_office/api/runner.py`, `post_office/api/server.py`, `post_office/ui/views.py`,
`post_office/ui/live.py`, `post_office/ui/live.html`, `main.py`, `tests/test_api_trimmed.py`,
`tests/test_live_ui.py`, docs (`running.md`, `dkrmm.md`, `verification.md`, `limitations.md`,
`events.md` one paragraph, provenance files, `camel-removal.md` unchanged). Untouched: everything
under `post_office/agents/`, `crew/`, `dkrmm/`, `robots/`, `environment/`, `simulation/`,
`discussion/`, `policy/`, `communication/`.

## 12. Amendments made during implementation

What was built differs from the sections above in the points below. The code is authoritative;
each point names the ruling or finding it came from (the build ledger's Task 1 to 5 lines).

- 2026-10-02, Task 1 (observability port):
  - Section 3: `rct_log.py` is `unchanged`, not `adapted`. The source file already imports
    `scenario_of` from `.run_record`, so the one change the spec allowed is a no-op and the file
    is byte-identical; provenance classes a byte-identical file `unchanged`.
  - Section 3: `scenario_of(preset, model=None)` and `RunRecorder(..., model=None)` take an
    optional model, so the Normal label names the runner's model (`scenario_label(model)`). The
    runner passes `settings.model`. There is no `settings.SCENARIOS` in this project:
    `/dkrmm/rct-log`'s `scenarios` are `settings.scenarios(model)` (Normal alone) plus any other
    scenario found among saved RCTs.
  - Section 3: a consultation's options come from its `consult_opened` event; a
    `CONSULT_REQUEST` that names none (as every run's does) leaves them. A lead consultation
    with no peer is named by its owner alone in the summary, with no arrow. The module's and
    the recorder's comments name consultations and the record builder, not discussions, a
    battery or trace files.
  - Section 3: `control=True` is passed unconditionally (the runner refuses any preset other
    than Normal, so it is Normal's).
- 2026-10-02, Task 2 (recording and the DK-RMM routes):
  - Section 5: the gate POSTs do not take the runner's step lock, as in the source: the monitor
    is resolved at call time, and if a reset replaced it before the verdict was decided, the
    verdict is asked again of the new one (409 while it has nothing). A verdict posted while a
    reset is between monitors answers 503 ("no runtime monitor attached").
  - Section 4: the recorder's writes are serialised by the runner's record lock
    (`_record_lock`), taken around `recorder.update` in the tick and around the gate's write;
    a reset swaps the monitor, the ecosystem and the recorder inside it (lock order: step, then
    record). `record_gate` skips a recorder of another run than the runner's current one
    (Task 5 reads the run as `eco.run_id` under the record lock; Task 2 had read the monitor's
    private `_eco`). The recorder's `update` sits in its own exception guard after
    `monitor.tick()` and sets `record_error`; a recorder that cannot be built sets it too.
  - Section 5: `/dkrmm/rct-log` also answers `record_error`; `/dkrmm/rcts` reads the run's
    events only when the history holds an RCT; `Judgement` bounds `by` to 80 and `note` to 500
    characters as the source did; the recorder's `config.llm_agents` is the experts actually on
    the model.
  - Section 10: the DK-RMM check is a pinned tree hash of `post_office/dkrmm/`
    (`test_dkrmm_is_unchanged`), with the git diff against `main` kept as a second test that
    skips when git cannot say. `tests/test_dkrmm.py`'s gate test, outside section 11's list,
    was changed back from asserting 404 to the source's over-the-wire gate assertions.
- 2026-10-02, Task 3 (the pages):
  - Sections 5 and 9: the feature adds ten routes, not eight: section 5's table lists the three
    gate POSTs on one row. The 2026-10-01 amendment names all ten.
  - Section 5: `GET /ui/trajectory/tail` also takes `run_id` and answers 409 to a page of an
    earlier run (its `run_id` is not the live run's, or its `started` is before the live run's
    first event); the page then stops following, its badge reads `finished` and its button
    "run ended - reopen the tab". A `run_id` other than the live run's on `GET /ui/trajectory`
    is 404.
  - Section 6: `truncated` is read from the rows (the first row shown is not `seq` 1) and
    `total` is never less than the last row's `seq`. A consultation's turn rows in the
    inspector show the call's served model, and its HTTP status and error when it failed, from
    the `llm_call` row's own payload. The Reason shows the question and the response, not a
    delegation's text. The legend's grey outline reads "peer failed / closed". The source's
    "all runs" link to its history page is removed; the em-dashes of both pages became hyphens.
  - Section 7: besides the two named strings, every user-visible "discussion" of `rcts.html`
    says "consultation".
- 2026-10-02, Task 4 (the shell):
  - Section 8: a reset no longer reloads the shell. A run generation counter, bumped by
    `restack`, guards every asynchronous path (an answer for an earlier run is dropped), the
    Runtime communication buffer keeps only events of the page's run id, the explanation cache
    is keyed by run and tick, and the shell's own panes are emptied and refilled for the new
    run; the Trajectory frame is rebuilt as the source did, and the RCT log frame is left.
  - Section 8: the loading box sits above the frame it stands for until that frame has loaded.
    The gate has a `by` field (the source wrote "operator"), is drawn before any reading so the
    server's 409 can be shown, shows the server's `detail` on an error, and disables its buttons
    while a verdict is posted. "explain this reading" explains the current reading and shows
    the RCT log page's sentences (messages, links with their caveat, baseline). The DK-RMM pane
    also lists this run's RCTs from `/dkrmm/rcts`, read while the pane is showing.
- 2026-10-03, Task 5 (leftovers and documentation):
  - Section 3: `explain` reports its window as `[max(0, T - WINDOW + 1), T]`; the source
    reported a negative first tick for a reading before a full window, whose tick-0 events it
    already counted.
  - Section 7: `rcts.html`'s leading comment no longer names a removed scenario family or
    discussions; the raw sources of `/ui/rcts` and `/ui/trajectory` are checked for removed
    families alongside the shell's.
  - Section 4: the recorder is looked at after every tick and writes the record when DK-RMM has
    made a new reading (every 20 ticks), as the source's did.
