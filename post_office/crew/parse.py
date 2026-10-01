"""
How a question is put to a CrewAI expert, and how its reply is read back.

`render` is the source model brain's rendering, unchanged: the decision kind,
the prompt, the facts in sorted order and the allowed answers, one per line.

`parse_choice` finds the one allowed answer in a reply, or returns None. The
hidden reasoning is removed first (`core.visible.visible`). A DECISION line,
when the reply has one, is authoritative (`discussion.prompts.parse_decision`):
if it names an allowed answer that is the answer, and if it names none the
reply is off the list, whatever its reasoning happens to mention. Without a
DECISION line the source model brain's heuristics apply, in its order: the
first visible line, stripped of markdown and punctuation, matched exactly and
case-insensitively; then a token of that line; then the one option the whole
reply mentions, if it mentions exactly one.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from ..agents.brain import Question
from ..core.visible import visible
from ..discussion.prompts import parse_decision

_EDGES = ".:*`"


def render(question: Question) -> str:
    facts = "\n".join(f"- {k}: {v}" for k, v in sorted(question.facts.items()))
    options = "\n".join(f"- {o}" for o in question.options)
    return (f"Decision: {question.kind}\n"
            f"{question.prompt}\n\n"
            f"Facts:\n{facts or '- none'}\n\n"
            f"Allowed answers:\n{options or '- any short string'}\n")


def parse_choice(text: str, options: Sequence[Any]) -> Optional[Any]:
    """The allowed option the reply names (the object from `options`), or None."""
    reply = visible(text)
    if not reply:
        return None
    has_line, chosen = parse_decision(reply, options)
    if has_line:
        return chosen
    first = reply.splitlines()[0].strip().strip(_EDGES + " ")
    if not options:
        return first or None
    lowered = {str(o).strip().lower(): o for o in options}
    if first.lower() in lowered:
        return lowered[first.lower()]
    for token in first.replace(",", " ").split():
        key = token.strip(_EDGES).lower()
        if key in lowered:
            return lowered[key]
    mentioned = [o for key, o in lowered.items() if key in reply.lower()]
    if len(mentioned) == 1:
        return mentioned[0]
    return None


def last_visible_line(text: str) -> str:
    """The last non-empty line of the reply once hidden reasoning is removed."""
    lines = [line.strip() for line in visible(text).splitlines() if line.strip()]
    return lines[-1] if lines else ""
