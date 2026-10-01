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
