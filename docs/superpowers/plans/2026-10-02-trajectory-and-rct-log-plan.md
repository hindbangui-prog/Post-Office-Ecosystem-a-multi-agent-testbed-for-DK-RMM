# Implementation plan: Trajectory and RCT log panes

Specification: `docs/superpowers/specs/2026-10-02-trajectory-and-rct-log-design.md`. Source
mirror (read-only): the project owner's `two_agent_test/post_office_discuss`, mirrored at the
build environment's `autodk_work`. Workflow as before: fresh implementer and fresh reviewer per
task; reviewer gates; later tasks re-run earlier tasks' focused tests; full suite and a fresh
final reviewer at the end; hygiene (LF, no em-dash, the removed framework's name only in the
allowed files, pristine output, commit trailers).

## Task 1: observability port (explainer, log, recorder) with carried tests

Files: `post_office/observability/rct_explain.py`, `rct_log.py`, `run_record.py` (adapted from
the source), `tests/test_rct_explain.py`, `tests/test_rct_log.py`, `tests/test_run_record.py`
(carried, adapted), `docs/provenance_classification.json` (three `adapted` entries plus the
three tests).

- Copy the source files, then change only what the spec names (consultation events and
  messages in place of discussion ones; `scenario_of` over `settings`; no `experiments`
  import). Keep every function name and result key.
- Tests: carry the source tests; where they build discussion events, build the consultation
  equivalents (`consult_opened` with `consultation_id`, `peer`, `decision`, `options`;
  `consult_closed` with `outcome`, `choice`; `CONSULT_REQUEST` message); add one test that a
  real fake-model run's consultation appears in `explain()["discussions"]` with its links.

Done when: the three test files pass; `python -c "import post_office.observability.run_record"`
imports nothing from removed modules.

Outcome: commits 22ec649..c9c164c, one review round (one Important: an open consultation's
options pinned by a test; Minor wording, the model in the scenario label, the peerless summary);
`rct_log.py` classed `unchanged` (byte-identical); 24 passed.

## Task 2: recording in the runner and the DK-RMM routes

Files: `post_office/api/runner.py`, `post_office/api/server.py`, `main.py`,
`tests/test_recording.py` (new), `tests/test_api_rcts.py` (new), `tests/test_api_trimmed.py`
(SPEC_ROUTES), `tests/test_runner.py` (if the constructor change needs it).

- Runner: `record_dir`, `recorder`, `_start_recorder`, `update` in the tick guard,
  `record_gate`, reset restarts the recorder. `main.py --api`: `--record-dir` (default
  `results/live`), `--no-record`.
- Server: `/dkrmm/rcts`, `/dkrmm/explain`, `/dkrmm/rct-log`, `/dkrmm/rct-log/item`, the three
  gate POSTs with the `Judgement` model, as spec section 5; the module docstring's route list.
- Re-run: `tests/test_api.py`, `tests/test_api_trimmed.py`, `tests/test_api_taxonomy.py`,
  `tests/test_runner.py`, `tests/test_dkrmm*.py`, `tests/test_run_normal_tool.py`, Task 1 tests.

Outcome: commits 6caae98..a968dcf, two review rounds (the gate without the step lock, the
recorder's own lock, a reset swapping monitor and recorder together, a pinned DK-RMM tree hash);
`tests/test_dkrmm.py`'s gate test back to the source's over-the-wire assertions; 178 passed.

## Task 3: the trajectory and RCT pages

Files: `post_office/ui/trajectory.html` (from the source template), `post_office/ui/rcts.html`
(from the source), `post_office/ui/views.py` (`event_type_for`, `trajectory_row`,
`trajectory_data`, `trajectory_tail`), `post_office/ui/live.py` (`trajectory_html`,
`rcts_html`), `post_office/api/server.py` (`/ui/trajectory`, `/ui/trajectory/tail`,
`/ui/rcts`), `tests/test_trajectory.py` (new), `tests/test_api_trimmed.py` (routes).

- Views first with tests (row shape, type mapping, truncation, tail, seq equality), then the
  template adaptation: lanes mapping, the consultation view (section 6), the "Expert
  consultation" label, `/ui/trajectory/tail` polling unchanged; `rcts.html` wording only.
- Re-run Task 2's tests and `tests/test_api_trimmed.py`.

Outcome: commits ccdee70..eeaffb3, one review round (served model and status in the
consultation turns, truncation read from the rows, the tail's 409 to a page of an earlier run);
ten routes in the 2026-10-01 amendment; 140 passed.

## Task 4: live shell tabs, gate controls, Playwright

Files: `post_office/ui/live.html`, `post_office/ui/live.py` (shell fills), `tests/test_live_ui.py`.

- Two iframe tabs with the source's lazy `src`, `poSuspend`, `restack` behaviour and loading
  box; DK-RMM pane gate controls and "explain this reading"; Playwright tests of spec
  section 10 (trajectory rows and tail, consultation bar, RCT log note and a recorded RCT,
  gate verdict shown). Screenshots to the review package.
- Re-run Task 3's tests and the whole `tests/test_live_ui.py`.

Outcome: commits 564d4bc..d650456, one review round (a reset no longer reloads the page; a
run generation guards every asynchronous path; the loading box above the frame; the RCT log's
sentences in the DK-RMM explanation); 205 passed, Playwright included.

## Task 5: docs, provenance, final verification

Files: `docs/running.md`, `docs/dkrmm.md`, `docs/verification.md`, `docs/limitations.md`,
`docs/events.md`, `docs/provenance*.{md,json}`, `docs/provenance_notes.md`,
`docs/provenance_trimmed_tests.md`, the 2026-10-01 spec's amendments section, README.

- Provenance regenerated (the five adapted files leave the Removed table; the removal record
  `docs/camel-removal.md` unchanged); docs describe what was built; full suite; banned-name
  grep; dependency audit; source tree hash; CRLF; em-dash; a `main.py --api` smoke run in the
  build environment against the fake Ollama showing `results/live/` written.
- Fresh final reviewer over the whole branch; one fix wave; re-review; report.

Outcome: commits 860695e (the explanation's window from tick 0, the gate's run check on the
runner's current run, the RCT log page's comment and the raw-source check of both pages) and
5aa3ec2 (docs as built, the design's amendments, provenance regenerated: 219 files, the Removed
table 160 to 152 rows), then this outcome line; full suite 883 passed, 4 skipped in 526.75s,
Playwright included; a `main.py --api --record-dir --start` smoke run on the fake Ollama wrote
`dkrmm/api.json`. The final review is the step after it.
