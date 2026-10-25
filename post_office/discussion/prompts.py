"""
What each side of a discussion is asked, and how the owner's decision is read.

The owner opens and decides; the peer replies from its own facts. Every turn's
prompt carries the discussion so far, so each model call can be asked cold.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Sequence, Tuple

from ..core.visible import visible

MAX_TURN_CHARS = 600

#: A DECISION line, tolerating the markdown a small model wraps it in
#: ("**DECISION:** R2", "- DECISION: `R2`").
_DECISION = re.compile(r"^[\s*_`#>-]*DECISION[\s*_`]*:[\s*_`]*(.+?)\s*$", re.I | re.M)
_EDGES = " \t*_`'\".:;,!?()[]"

Turns = Sequence[Tuple[str, str]]


def clean(text: str) -> str:
    """A turn as it goes on the bus: no hidden reasoning, trimmed, bounded."""
    return visible(text)[:MAX_TURN_CHARS]


def _facts(facts: Dict[str, Any]) -> str:
    rows = [f"- {k}: {v}" for k, v in sorted((facts or {}).items())]
    return "\n".join(rows) or "- none"


def _options(options: Sequence[Any]) -> str:
    return "\n".join(f"- {o}" for o in options) or "- any short answer"


def _transcript(turns: Turns) -> str:
    return "\n".join(f"{who}: {text}" for who, text in turns) or "(nothing yet)"


def opening_prompt(owner: str, peer: str, kind: str, question_prompt: str,
                   facts: Dict[str, Any], options: Sequence[Any], why: str) -> str:
    return (f"You are {owner}. You must decide '{kind}': {question_prompt}\n"
            f"Why this is not routine: {why}\n\n"
            f"Your facts:\n{_facts(facts)}\n\n"
            f"Allowed answers:\n{_options(options)}\n\n"
            f"Write to {peer}, who knows things you do not. In at most three "
            f"sentences, say which answer you lean towards and what you need to "
            f"know from {peer}. Do not write a DECISION line yet.")


def peer_prompt(peer: str, owner: str, kind: str, briefing: Dict[str, Any],
                turns: Turns) -> str:
    return (f"You are {peer}. {owner} is deciding '{kind}' and has asked for "
            f"your view.\n\n"
            f"Your facts, as they are now:\n{_facts(briefing)}\n\n"
            f"The discussion so far:\n{_transcript(turns)}\n\n"
            f"Reply to {owner} in at most three sentences, using only your facts. "
            f"Say whether you agree with its lean and why. You do not make the "
            f"decision.")


def decision_prompt(owner: str, peer: str, kind: str, facts: Dict[str, Any],
                    options: Sequence[Any], turns: Turns, may_ask: bool) -> str:
    ask = (f"If you still need one thing from {peer}, you may instead ask one "
           f"short question and write no DECISION line. " if may_ask else "")
    return (f"You are {owner}, deciding '{kind}'.\n\n"
            f"Your facts:\n{_facts(facts)}\n\n"
            f"The discussion with {peer}:\n{_transcript(turns)}\n\n"
            f"Allowed answers:\n{_options(options)}\n\n"
            f"{ask}Otherwise end with one line exactly like "
            f"'DECISION: <one allowed answer>'.")


def parse_decision(text: str, options: Sequence[Any]) -> Tuple[bool, Any]:
    """
    (a DECISION line was written, the allowed option it names or None).

    Read from the whole reply with hidden reasoning removed -- not from the
    clipped text that goes on the bus -- so a long turn keeps its decision.
    The answer is the text after "DECISION:" if it is on the list, otherwise
    its first word that is ("DECISION: R2 (most charge)" names R2).
    """
    found = _DECISION.findall(visible(text))
    if not found:
        return False, None
    said = found[-1].strip(_EDGES).lower()
    by_name = {str(option).strip().lower(): option for option in options}
    if said in by_name:
        return True, by_name[said]
    for word in re.split(r"[\s,;()\[\]]+", said):
        word = word.strip(_EDGES)
        if word in by_name:
            return True, by_name[word]
    return True, None
