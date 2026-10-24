"""
Where an event came from, when the code actually knows.

The problem this solves: a perturbation lands at tick 900 and a queue is longer
at tick 940, and the honest question is whether one caused the other. Answering
it by assuming that everything after an injection was caused by it is how a
propagation study proves whatever it set out to prove.

So provenance is recorded only where a code path can name its own cause, and it
is recorded with the strength of the claim attached:

- ``caused_by`` -- this code held this message, rewrote these facts, wrapped
  this answer, changed this shelf. The cause is not inferred; it is the line
  above.
- ``observed_after`` -- this happened during the window of an active
  perturbation and may have nothing to do with it. The analysis is allowed to
  count these; it is not allowed to call them consequences.

The mechanism is a context variable rather than a parameter threaded through
forty call sites, because the alternative is forty chances to pass the wrong
id, and because the seams that inject a perturbation are the only places that
know one is being injected. An injector opens a context, the code inside it
runs exactly as it always does, and every event emitted while it is open
carries the stamp.

Nothing here changes the wire format: the stamp goes in `Event.detail`, which
is a free dict, so every existing reader keeps working and a replay captured
before this existed is still readable.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

#: The claim being made about causation.
CAUSED_BY = "caused_by"
OBSERVED_AFTER = "observed_after"
RELATED_TO = "related_to"

#: What is being attributed right now, if anything. Empty outside an injector,
#: which is the normal state of the whole simulation.
_CURRENT: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "po_provenance", default={})


def current() -> Dict[str, Any]:
    """The stamp in force, or an empty dict. Never None, never shared."""
    return dict(_CURRENT.get() or {})


def stamp(detail: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add the stamp in force to an event's detail, without overwriting.

    Not overwriting matters: a caller that has already said what caused this
    event knows better than the ambient context does.
    """
    mark = _CURRENT.get() or {}
    if not mark:
        return detail
    for key, value in mark.items():
        detail.setdefault(key, value)
    return detail


@contextmanager
def attributed(perturbation_id: str, relation: str = CAUSED_BY,
               causal_parent: Optional[int] = None,
               **extra: Any) -> Iterator[None]:
    """
    Everything logged inside this block is attributed to one perturbation.

    Nested blocks replace rather than merge: the innermost injector is the one
    that touched the code, and an outer context claiming the same events would
    attribute one cause twice.
    """
    mark: Dict[str, Any] = {"perturbation_id": perturbation_id,
                            "relation": relation}
    if causal_parent is not None:
        mark["causal_parent"] = int(causal_parent)
    mark.update(extra)
    token = _CURRENT.set(mark)
    try:
        yield
    finally:
        _CURRENT.reset(token)


@contextmanager
def unattributed() -> Iterator[None]:
    """
    Explicitly no stamp, for code that runs inside an injector but is not its
    doing -- delivering the rest of the post while one message is held.
    """
    token = _CURRENT.set({})
    try:
        yield
    finally:
        _CURRENT.reset(token)
