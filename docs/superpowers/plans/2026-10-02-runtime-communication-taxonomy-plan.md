# Implementation plan: runtime communication taxonomy and visualization

Specification: `docs/superpowers/specs/2026-10-02-runtime-communication-taxonomy-design.md`.
Workflow: one fresh implementer and one fresh reviewer per task; a task is complete only when
its reviewer finds nothing open; later tasks that touch earlier files re-run the earlier
tasks' focused tests; the full suite runs at the end; a final reviewer who implemented
nothing inspects the whole change. Hygiene as before: LF, no em-dash, the removed framework's
name only in the allowed files, pristine test output, commit trailers.

## Task 1: taxonomy module and classifier tests

Files: `post_office/communication/taxonomy.py` (new), `tests/test_taxonomy.py` (new),
`tests/test_taxonomy_completeness.py` (new).

- Write the tests first from spec section 3: one test per precedence case, missing fields,
  determinism, every type reachable, `table()` shape.
- Completeness: run a 300-tick rules-only ecosystem (the existing build helpers,
  `PYTHONHASHSEED=0`, seed 1) and a fake-model run (the `fake_ollama` fixture and the
  `llm_brains` configuration the consultation tests use, 120 ticks) and classify every
  logged event through `classify`; assert no fallback; keep the expectation table of observed
  (category, topic, message_type) triples in the test so a new source event names itself.
- Implement `taxonomy.py` as a pure module; the classification result is a small frozen
  dataclass with `interaction_type`, `channel`, `fallback`.

Done when: focused tests pass; the module imports nothing from the simulator.

Outcome: commits dc9cb8e..8e53851, one review round (two Important, six Minor; `content_type`,
hints, read-only tables); 63 passed.

## Task 2: stamping, bus `in_reply_to`, fingerprint, DK-RMM invariance

Files: `post_office/communication/events.py`, `post_office/communication/bus.py`,
`tools/normal_fingerprint.py`, `tests/test_event_stamping.py` (new),
`tests/test_dkrmm_stamping_invariance.py` (new).

- Tests first: fields present on every event in a run's `events.jsonl` and in
  `logger.since()`; removing the two keys and `detail.in_reply_to` yields the pre-change
  record (compare with the recorded alignment baseline through the fingerprint tool);
  DK-RMM invariance by running the same seeded ecosystem with the classifier stubbed to empty
  strings and normally (monkeypatch `taxonomy.classify` in `events.py`).
- Implement: `Event` slots and `as_dict`; `emit` computes the classification once; the bus
  adds `in_reply_to`; the fingerprint strips the keys.
- Re-run: `tests/test_normal_alignment.py`, `tests/test_communication.py`,
  `tests/test_dkrmm*.py`, `tests/test_events_consultation.py`, `tests/test_llm_call_logging.py`,
  `tests/test_run_normal_tool.py`.

Done when: all of the above pass and the four baseline runs still match.

Outcome: commits 18746c4..a6bcb8c, review clean with two Minor follow-ups; 211 passed on the
listed files, DK-RMM invariance byte-identical, alignment 4 of 4 with the baseline unchanged.

## Task 3: API

Files: `post_office/api/server.py`, `post_office/ui/views.py`, `post_office/ui/feed.py` (new),
`tests/test_api_taxonomy.py` (new), `tests/test_feed_integrity.py` (new),
`tests/test_api_trimmed.py` (route table).

- `GET /taxonomy` returns `taxonomy.table()`; `/frame` `m` rows gain channel and type; the
  route-table test lists the new route; `/events` unchanged apart from the stamped fields.
- `post_office/ui/feed.py`: pure helpers mirrored by the page's JavaScript: `receiver_of`,
  `edge_of`, `pair_requests` (by `in_reply_to` and `consultation_id`), `latency_of`
  (`ms` / `ticks` / none), `model_of`, `texts_of` (request/response/decision strings, each
  asserted to be a field of the event), `chain_keys` and `chain_select`. Tests pin the
  integrity rules of spec section 2 on a fake-model run's events.
- Re-run Task 2's focused tests plus `tests/test_api.py`, `tests/test_runner.py`.

Done when: focused tests pass; `/taxonomy` and the docs table are the same object.

Outcome: commits 8a86a18..2dc6be6, one review round (model never parsed from `source`, bus
consult pairing by `correlation_id`, `paired_seq`); 124 passed.

## Task 4: live page

Files: `post_office/ui/live.html`, `post_office/ui/floor.html`, `post_office/ui/live.py`,
`tests/test_live_ui.py`.

- Runtime communication pane per spec 6.1, built from `/taxonomy` at load, fed by the
  WebSocket, backfilled from `/events`; filters; chain follow; id box; the JavaScript
  pairing/latency/model rules copied from `feed.py` line for line in behaviour.
- Floor graph per spec 6.2: channel colours and dashes from `/taxonomy` (passed into the
  iframe once), ENVIRONMENT node, no edge without a receiver, node pulses for decision /
  robot report / environment update, legend, highlighted chain via `postMessage`.
- Playwright test additions per spec section 8 (optional extra; the module skips without it).
- Re-run Task 3's focused tests and the existing UI test.

Done when: Playwright passes locally in the build environment (Chromium is installed there)
and a manual screenshot of the page in a fake-model run is saved to the review package.

Outcome: commits 99f585e..02032f8, two review rounds (the log tailed on connect, the legend in
the graph header, the graph fitted to the pane); 139 passed, the page's mirror of `feed.py`
compared over 2000 rows with 0 differences, screenshots in the review package.

## Task 5: documentation, provenance, final verification

Files: `docs/events.md`, `docs/running.md`, `docs/dkrmm.md`, `docs/provenance_classification.json`,
regenerated `docs/provenance.md/.json`, `tests/test_docs_present.py` (table check).

- Docs per spec section 9; the taxonomy table in `docs/events.md` is generated from
  `taxonomy.table()` by a small helper in `tools/` or written by hand and checked equal.
- Full suite; banned-name grep; dependency audit; source tree hash; CRLF; em-dash.
- Final reviewer (fresh) inspects: taxonomy semantics, precedence, event invariance,
  receiver/edge integrity, DK-RMM invariance, real-event UI rendering, no synthetic dialogue,
  no architecture change, no perturbation machinery. One fix wave, re-review, report.
