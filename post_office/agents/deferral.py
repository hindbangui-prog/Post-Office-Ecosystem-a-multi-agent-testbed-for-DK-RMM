"""
The decision-telemetry words and the `Deferral` record, kept from the source.

The source simulator could hand a decision to a worker thread and finish it on
a later tick. This prototype consults synchronously, so that machinery is gone;
what remains is the vocabulary a decision record uses for how it ended, and the
`Deferral` record the expert agents still build when they call `decide` (it is
accepted and ignored on the synchronous path, exactly as in the source).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .brain import Answer

#: The telemetry vocabulary, one word per way a decision can end.
DETERMINISTIC = "deterministic"
LLM_PENDING = "llm_pending"
LLM_ACCEPTED = "llm_accepted"
LLM_REJECTED = "llm_rejected"
LLM_FAILED = "llm_failed"
#: The model had not answered by the decision deadline, so the rule decided.
LLM_TIMEOUT = "llm_timeout"

#: The choice a pending placeholder carries. Never a legal option, so no
#: caller can mistake it for an answer and act on it.
PENDING_LLM_DECISION = "PENDING_LLM_DECISION"


def is_pending(answer: Optional[Answer]) -> bool:
    """True for a placeholder answer whose decision has not been taken yet."""
    return answer is not None and answer.source == LLM_PENDING


@dataclass
class Deferral:
    """
    How a caller wants a decision finished if it cannot be finished now.

    `key`         what the decision is about: a robot, a parcel, a task.
    `apply`       carry out an answer; the code that followed `decide` inline.
    `still_valid` given the answer about to be applied, "" if the floor still
                  admits it, otherwise the reason it no longer does.
    `reevaluate`  what to do instead when it does not.
    """

    key: str
    apply: Callable[[Answer], None]
    still_valid: Callable[[Answer], str] = lambda answer: ""
    reevaluate: Callable[[str], None] = lambda why: None
