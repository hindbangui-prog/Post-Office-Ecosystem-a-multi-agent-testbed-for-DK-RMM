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
