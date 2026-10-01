"""
Whether a decision is worth thinking about.

Every expert in this facility takes the same kind of decision dozens of times
a run, and almost all of those decisions are dull. A legible label for a town
on the network is registered; a robot that is the only one free takes the job;
a parcel goes on the van that is sitting at its door with room on it. Asking a
language model to confirm any of that costs a network round trip, makes the
run unreproducible, and teaches nothing about how an LLM agent behaves -- the
interesting behaviour is in the hard cases, and the hard cases drown.

So each expert declares, next to the rules it already owns, the conditions
under which one of its decisions stops being dull. The conditions are ordinary
Python predicates over the facts the decision was already given: no model, no
heuristics about model confidence, nothing that itself needs explaining. If
none of them fires the deterministic rule answers and the tick costs nothing.
If one fires it is named, and the name is written into the log beside the
decision.

The naming matters more than it looks. The experiment this simulation exists
for is to watch an ecosystem under rising stress and see reasoning spread
through it -- so "how many decisions were reasoned about, and because of
what" has to be a countable quantity, comparable across seven agents that
otherwise have nothing in common. Hence one fixed vocabulary, below, rather
than each agent inventing its own words.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Optional


class REASONS:
    """
    Why an agent stopped to think. One word each, fixed across all agents.

    These are the causes named in the architecture: ambiguity, conflict,
    contention, a changed environment, a previous attempt that failed,
    deadline pressure, an unexpected message, and the need to replan. The last
    one, `unknown`, is what a broken condition reports -- see `TriggerSet`.
    """

    AMBIGUITY = "ambiguity"          # the information is incomplete or unclear
    CONFLICT = "conflict"            # two sources disagree, or two goals do
    CONTENTION = "contention"        # more claimants than there is to go round
    ENVIRONMENT = "environment"      # conditions have moved since last time
    FAILED = "failed"                # the previous attempt did not work
    DEADLINE = "deadline"            # a promise is close to breaking
    MESSAGE = "message"              # something arrived that was not expected
    REPLAN = "replan"                # the current plan no longer fits
    UNKNOWN = "unknown"              # the condition itself could not be judged
    POLICY = "policy"                # the scenario puts every decision to the model

    @classmethod
    def all(cls) -> List[str]:
        return [v for k, v in sorted(vars(cls).items())
                if k.isupper() and isinstance(v, str)]


@dataclass(frozen=True)
class Trigger:
    """
    One named cause, with the detail that made it fire.

    `detail` is a short phrase about this decision -- "3 robots for 1 free
    point" -- and it is what a human reads when asking why the agent thought
    about this one. It is not reasoning, and nothing downstream branches on
    it; only `reason` is counted.
    """

    reason: str
    detail: str = ""
    #: Whether the agent's rule still answers this case sufficiently. Left
    #: unset, the reason decides (see `RULE_INSUFFICIENT`); a condition that
    #: knows better says so -- a contention that is a dead tie between two
    #: robots is one the ranking rule cannot resolve, and the agent that
    #: declared the condition is the one that knows that.
    rule_sufficient: Optional[bool] = None
    #: Which declared condition fired, by its function name ("contention",
    #: "no_robots"). Two conditions can report the same reason; the name is
    #: what tells them apart (the discussion peer map is keyed by it). Left
    #: out of `as_dict` and of equality, so decision records are unchanged.
    condition: str = field(default="", compare=False)

    def as_dict(self) -> dict:
        return {"reason": self.reason, "detail": self.detail,
                "rule_sufficient": self.rule_sufficient}


#: A condition over the facts of one decision. Returns a `Trigger` when the
#: situation is not routine, and None when it is.
Condition = Callable[[Dict[str, Any]], Optional[Trigger]]


class TriggerSet:
    """
    The conditions one agent has declared, by decision kind.

    Several conditions may be registered for the same kind and are tried in
    the order they were registered. The first to fire wins, so an agent lists
    its conditions most-specific first and every decision has exactly one
    recorded cause -- a decision counted twice is a decision that cannot be
    counted at all.
    """

    def __init__(self) -> None:
        self._conditions: Dict[str, List[Condition]] = {}

    def register(self, kind: str, condition: Condition) -> None:
        self._conditions.setdefault(kind, []).append(condition)

    def knows(self, kind: str) -> bool:
        return bool(self._conditions.get(kind))

    def kinds(self) -> List[str]:
        return sorted(self._conditions)

    def check(self, kind: str, facts: Dict[str, Any]) -> Optional[Trigger]:
        """
        The cause to reason about this decision, or None to take the rule.

        A kind with no conditions declared is routine by definition: an agent
        that has not said when a decision is hard is saying it never is.
        """
        for condition in self._conditions.get(kind, ()):
            try:
                fired = condition(facts or {})
            except Exception as error:
                # A condition is an optimisation, never a gate. When the
                # condition itself cannot be judged -- a fact missing because
                # something upstream was perturbed, most likely, which is
                # exactly the circumstance where the cheap path is least
                # trustworthy -- the decision still has to happen, and it goes
                # the careful way.
                return Trigger(REASONS.UNKNOWN,
                               f"condition failed: {type(error).__name__}")
            if fired is not None:
                return _named(fired, condition)
        return None

    def fired(self, kind: str, facts: Dict[str, Any]) -> List[Trigger]:
        """
        Every condition that fires for this decision, in registration order.

        `check` stops at the first, which is right when the first cause is the
        one to record. It is wrong when the first cause is one the rule is
        known to cover: stopping there would hide a later condition the rule
        does not cover -- a paid errand noticed first would mask two robots
        tied on distance -- and that later one is the reason to think.
        """
        out: List[Trigger] = []
        for condition in self._conditions.get(kind, ()):
            try:
                found = condition(facts or {})
            except Exception as error:
                out.append(Trigger(REASONS.UNKNOWN,
                                   f"condition failed: {type(error).__name__}"))
                continue
            if found is not None:
                out.append(_named(found, condition))
        return out


def _named(trigger: Trigger, condition) -> Trigger:
    """The trigger, carrying the name of the condition that produced it."""
    if trigger.condition:
        return trigger
    return replace(trigger, condition=getattr(condition, "__name__", ""))


# ------------------------------------------------------------- the policy
#: When the model is consulted, given that a rule has already answered.
#:
#: Conditional automation: every expert is LLM-based, and every decision
#: goes to its Python rule first. The model is invoked only when that rule
#: is *insufficient* -- and the triggers above are how a rule says so. The
#: reasons split in two:
#:
#:   RULE_INSUFFICIENT   the rule's answer cannot be trusted or does not exist:
#:                       the facts are incomplete (ambiguity), two goals or
#:                       sources the rule cannot arbitrate (conflict), the
#:                       rule's previous answer did not work (failed), the
#:                       condition itself could not be judged (unknown)
#:   pressure            the rule has a definite answer, the floor is merely
#:                       busy: contention, deadline, environment, message,
#:                       replan. Recorded on the decision as `noted`, the rule
#:                       stands, and no call is made -- unless the condition
#:                       itself says `rule_sufficient=False`, as a contention
#:                       the ranking rule cannot break (two robots equally
#:                       placed; no robot able at all) does.
#:
#: A rule that returns no admissible answer, or one it marks with a
#: confidence below 1, is insufficient whatever the triggers say.
#:
#: `any_trigger` is the earlier arrangement, in which every fired trigger
#: went to the model. The recorded battery (results/battery, results/hybrid)
#: was run under it, and a run that wants to be compared with those sets
#: `consult_policy: "any_trigger"` in its configuration.
POLICY_INSUFFICIENT = "insufficient"
POLICY_ANY_TRIGGER = "any_trigger"
#: Every decision goes to the model, whatever the rules could have said. This
#: is the "Normal (LLM)" scenario: the same facility, the same seven experts,
#: with the rules used only as the brain's fallback when a reply is empty or
#: not on the list. It exists so a run with the rules answering and a run
#: with the model answering can be watched side by side; the gate validates
#: both the same way.
POLICY_ALWAYS = "always"
POLICIES = (POLICY_INSUFFICIENT, POLICY_ANY_TRIGGER, POLICY_ALWAYS)
DEFAULT_POLICY = POLICY_INSUFFICIENT

RULE_INSUFFICIENT = frozenset({REASONS.AMBIGUITY, REASONS.CONFLICT,
                               REASONS.FAILED, REASONS.UNKNOWN})


def rule_insufficient(answer: Optional[Any], options: Any, trigger: Optional[Trigger],
                      policy: str = DEFAULT_POLICY) -> Optional[Trigger]:
    """
    Why the rule's answer is not enough, or None when it is.

    `answer` is what the rule returned (None when there is no rule for this
    kind), `options` the admissible choices the question carried, `trigger`
    what the agent's own conditions noticed about the facts.
    """
    if policy == POLICY_ALWAYS:
        # Whatever the rule said, the model answers; the reason recorded is
        # the condition that fired, or the policy itself.
        return trigger or Trigger(REASONS.POLICY, "every decision goes to the model in this scenario")
    if answer is None:
        return trigger or Trigger(REASONS.UNKNOWN, "no rule for this decision")
    choice = getattr(answer, "choice", None)
    if choice is None or (options and choice not in tuple(options)):
        return Trigger(REASONS.AMBIGUITY, "the rule returned no admissible answer")
    if float(getattr(answer, "confidence", 1.0) or 0.0) < 1.0:
        return Trigger(REASONS.AMBIGUITY,
                       f"the rule is unsure ({float(answer.confidence):.2f}): "
                       f"{getattr(answer, 'reason', '') or 'no reason given'}")
    if trigger is not None:
        if policy == POLICY_ANY_TRIGGER:
            return trigger
        if trigger.rule_sufficient is not None:
            return None if trigger.rule_sufficient else trigger
        if trigger.reason in RULE_INSUFFICIENT:
            return trigger
    return None
