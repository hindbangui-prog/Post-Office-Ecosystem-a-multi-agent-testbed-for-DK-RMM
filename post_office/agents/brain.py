"""
Where an agent's judgement lives, and the seam an LLM slots into.

Every agent in this system takes decisions of two very different kinds.
Bookkeeping -- "which of my sub-agents handles a barcode", "mark this task
IN_PROGRESS" -- is mechanical, and putting a language model anywhere near it
would only make the system slower and less reproducible. Judgement -- "is this
parcel urgent", "which of these three robots should take the job", "should the
plan be reordered" -- is exactly what a language model might do better.

So judgement is asked as a `Question` and answered by a `Brain`. Agents never
branch on whether they have a model; they ask, and they get an `Answer` whose
`choice` is guaranteed to be one of the options they offered.

    DeterministicBrain   rules written in Python. The default, and what
                         `python main.py --rules` runs: no model server, no network,
                         bit-identical between runs.
    CrewBrain            a CrewAI agent behind the same interface.
                         Falls back to the deterministic rule when the model is
                         unreachable or answers with something not on the list,
                         and records that it fell back.

Swapping one agent's brain for the other changes nothing else in the package.
That is design principle 9, made concrete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class Question:
    """
    One judgement call, phrased so that both kinds of brain can answer it.

    `options` is what makes the two interchangeable: a deterministic rule picks
    from the list, and a model's reply is validated against it. An agent
    therefore never has to defend itself against an answer it cannot use.
    """

    kind: str                       # "classify_priority", "choose_robot", ...
    asked_by: str                   # agent id, so the log says who wondered
    prompt: str                     # the natural-language form, for a model
    options: Sequence[Any] = ()     # admissible answers; empty means free-form
    facts: Dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    #: The identity of the decision this question belongs to, as the agent
    #: minted it. Carried here so that anything observing the answer can name
    #: the decision record it will become -- which `(tick, kind)` cannot do,
    #: because one agent can take two decisions of one kind in one tick. It is
    #: empty for a question asked outside `BaseAgent.decide`, and a reader that
    #: needs it must treat empty as "unknown" rather than as a key.
    decision_id: str = ""

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "asked_by": self.asked_by,
            "prompt": self.prompt,
            "options": [str(o) for o in self.options],
            "facts": dict(self.facts),
            "correlation_id": self.correlation_id,
            "decision_id": self.decision_id,
        }


@dataclass(frozen=True)
class Answer:
    """What came back, and where it came from."""

    choice: Any
    reason: str = ""
    source: str = "deterministic"    # "deterministic" | "crewai:<model>" | "fallback"
    confidence: float = 1.0

    def as_dict(self) -> dict:
        return {
            "choice": self.choice if isinstance(self.choice, (str, int, float, bool,
                                                              type(None)))
            else str(self.choice),
            "reason": self.reason,
            "source": self.source,
            "confidence": self.confidence,
        }


class Brain:
    """The interface. Two implementations ship; a third is thirty lines."""

    name = "brain"

    #: Whether this brain reads `Question.prompt` at all.
    #:
    #: A rule-based brain does not: it answers from the facts and the options,
    #: and the prompt is a string nobody looks at. That is fine until a
    #: prompt-borne perturbation is aimed at it, at which point the stimulus is
    #: injected, counted, logged, and completely inert -- a run that perturbs
    #: nobody while looking exactly like a null result. The flag exists so the
    #: perturbation layer can refuse that experiment instead of reporting it.
    reads_prompt = False

    #: The last text this brain actually sent onward, when it sends one.
    #: `None` means "this brain does not compose an outgoing prompt", which is
    #: a different statement from "it sent nothing", and the difference is what
    #: lets an experiment tell an unread stimulus from an unsent one.
    last_prompt: Optional[str] = None

    def answer(self, question: Question) -> Answer:
        raise NotImplementedError

    def close(self) -> None:
        """Release anything held open. A no-op for the deterministic brain."""


Rule = Callable[[Question], Answer]


class DeterministicBrain(Brain):
    """
    Rules written in Python, one per question kind.

    Each agent registers its own rules at construction, so the logic for "how do
    I decide a priority" sits next to the agent that decides it rather than in a
    central rulebook nobody wants to own.
    """

    name = "deterministic"

    def __init__(self, rules: Optional[Dict[str, Rule]] = None) -> None:
        self._rules: Dict[str, Rule] = dict(rules or {})

    def register(self, kind: str, rule: Rule) -> None:
        self._rules[kind] = rule

    def knows(self, kind: str) -> bool:
        return kind in self._rules

    def answer(self, question: Question) -> Answer:
        rule = self._rules.get(question.kind)
        if rule is None:
            # An unanswerable question should be visible, not silently wrong.
            first = question.options[0] if question.options else None
            return Answer(choice=first, reason=f"no rule for {question.kind!r}",
                          source="deterministic", confidence=0.0)
        return rule(question)


class ConstantBrain(Brain):
    """Always answers the same way. Useful in tests, useless in a run."""

    name = "constant"

    def __init__(self, choice: Any = None, reason: str = "constant") -> None:
        self._choice = choice
        self._reason = reason

    def answer(self, question: Question) -> Answer:
        choice = self._choice
        if question.options and choice not in question.options:
            choice = question.options[0]
        return Answer(choice=choice, reason=self._reason, source="constant")
