"""
Which sub-agent invocation the current thread is inside.

A sub-agent with its own model produces three streams that are really one
thing. The expert's request arrives and is bracketed by `observability/tools.py`;
the brain inside it asks a language model, which `instrumentation.py` records;
and the answer comes back out as an `agent/decision`. Read separately they are
three unrelated lists. Read together they are a conversation: *SUB-PRIORITY was
asked about parcel P-12, here is what it asked its model, here is what came
back, and here is what it did with it.*

Joining them after the fact does not work. Agent and tick is not a key -- one
decision can take two requests when the first answer is not on the allowed
list, and two parcels can be graded in the same tick. The invocation has an id
already; it just needs to be in scope when the model request is logged.

So this holds it, in a `ContextVar`: set by the sub-agent wrapper around
`perform`, read by the model tracer. A `ContextVar` rather than a global or a
`threading.local` because it is correct under threads *and* under async, and the
model backend's `arun` is reached through the second -- a global would attribute
a request to whichever invocation happened to start last.

Nothing in `agents/` knows this exists, and a run with tracing off never sets
it. When nothing is set -- a model request made by an expert rather than a
sub-agent, or by a script -- the answer is an empty invocation, which is the
truthful one: that request did not happen inside a sub-agent call.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Any, Dict, Iterator

#: `{"call_id": ..., "correlation_id": ..., "agent_id": ...}`, or empty.
_current: ContextVar[Dict[str, Any]] = ContextVar("po_current_call",
                                                  default={})

EMPTY: Dict[str, Any] = {}


def current_call() -> Dict[str, Any]:
    """The invocation in scope, or an empty mapping outside one."""
    return _current.get() or EMPTY


@contextlib.contextmanager
def inside(call_id: str, correlation_id: str = "",
           agent_id: str = "") -> Iterator[None]:
    """
    Mark everything logged in this block as part of one sub-agent invocation.

    Restores the previous value rather than clearing it, so a sub-agent that
    somehow calls another nests correctly instead of leaving the outer call
    unattributed for the rest of the tick.
    """
    token = _current.set({"call_id": call_id, "correlation_id": correlation_id,
                          "agent_id": agent_id})
    try:
        yield
    finally:
        _current.reset(token)
