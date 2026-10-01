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
path. These were adapted from a file elsewhere in the source tree, so their
source path is recorded here.

- post_office/ui/floor.html :: adapted from the source `tools/replay_template.html`
  (the floor, the interaction graph, the robot cards and the message feed that the
  source's `ui/live.py::robots_html` served at `/ui/robots`). The discussion strip,
  links, bubbles and log are removed (Prototype II consults through CrewAI and its
  frames carry no discussion rows), consultation messages (`CONSULT_*`) take the
  feed's highlight that discussion turns had, and the run line no longer claims
  every decision is deterministic. It is served inside the live page as an
  escaped `srcdoc`, so it needs no route of its own.
