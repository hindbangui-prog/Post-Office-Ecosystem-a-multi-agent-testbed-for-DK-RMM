"""
CrewBrain: a CrewAI expert behind the `Brain` interface (spec 6.1).

The agent's rules stay where `BaseAgent.rules()` looks for them, on
`fallback`, a `DeterministicBrain` the agent fills through `install_rules()`.
Every answer starts from the rule's answer. When a consultation service is
bound (`bind`, done by the ecosystem once every agent exists), the decision is
handed to it as `service.run(owner_id, question, trigger, rule_answer)`, and
the `ConsultOutcome` it returns carries the answer and the consultation's id,
peer and turns, which `BaseAgent.decide` reads from `last_consultation`.
Without a service the rule answers, marked `source="fallback"` with the reason
`[fallback: model layer not installed]`, and no model is called.

`last_consultation` is reset at the start of every call, so a decision never
carries an earlier decision's consultation. After a service run, `last_prompt`
is the owner task description the model was given, and the outcome's `counts`
(consultations, questions, delegations, timeouts, retries, parse_failures,
rejected_answers) are added to the stats. A service that raises is caught: the
rule answers with `[fallback: <error>]`, `last_error` says why and `reachable`
is False. A rule that raises is caught too: the decision goes on with no rule
answer (`rule_answer=None`, which `BaseAgent._fallback` turns into "no rule to
fall back on") and `last_error` says why.

CrewAI replaces the implementation of model-backed peer consultation at the
Brain seam while preserving the existing peer map and consultation semantics:
the brain never applies anything. Its answer goes back to `BaseAgent.decide`,
whose `_validate` (the policy gate) checks it before the agent's own Python
applies it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from crewai import Agent

from ..agents.brain import Answer, Brain, DeterministicBrain, Question
from ..config.ollama import OllamaSettings

NOT_INSTALLED = "model layer not installed"

#: The counters a `ConsultOutcome.counts` may add to.
COUNTED = ("consultations", "questions", "delegations", "timeouts", "retries",
           "parse_failures", "rejected_answers")


@dataclass(frozen=True)
class CrewBrainConfig:
    """What the UI and the runner read about a brain's model."""

    model_type: str
    seed: Optional[int]
    base_url: str
    provider: str = "ollama"


class CrewBrain(Brain):
    name = "crewai"
    reads_prompt = True

    def __init__(self, agent_id: str, fallback: DeterministicBrain, crew_agent: Agent,
                 settings: OllamaSettings) -> None:
        self.agent_id = agent_id
        self.fallback = fallback
        self.crew_agent = crew_agent
        self.settings = settings
        self.config = CrewBrainConfig(model_type=settings.model, seed=settings.seed,
                                      base_url=settings.base_url)
        self.service: Any = None
        self.last_prompt: Optional[str] = None
        self.last_consultation: Optional[Dict[str, Any]] = None
        self.calls = 0
        self.consultations = 0
        self.questions = 0
        self.delegations = 0
        self.fallbacks = 0
        self.rejected_answers = 0
        self.parse_failures = 0
        self.timeouts = 0
        self.retries = 0
        self.reachable: Optional[bool] = None
        self.last_error = ""
        self._latencies: List[float] = []

    def bind(self, service: Any) -> None:
        """Attach the consultation service that runs this expert's model decisions."""
        self.service = service

    def answer(self, question: Question) -> Answer:
        return self._decide(question, None)

    def answer_consulting(self, question: Question, trigger: Any) -> Answer:
        return self._decide(question, trigger)

    def start_consulting(self, question: Question, trigger: Any) -> Any:
        """
        Start this decision's consultation without waiting for the model.

        Returns an `Answer` when there is nothing to wait for (no service, a
        service that raised, an expert still busy) -- the same answer
        `answer_consulting` would have given -- and otherwise a handle for
        `finish_consulting` on later ticks.
        """
        self.last_consultation = None
        if self.service is None or not hasattr(self.service, "start"):
            return self._decide(question, trigger)
        rule_answer = self._rule_answer(question)
        self.calls += 1
        try:
            started = self.service.start(self.agent_id, question, trigger, rule_answer)
        except Exception as exc:  # the service must never stop a tick
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.reachable = False
            return self._fall_back(rule_answer, self.last_error)
        if hasattr(started, "answer"):            # closed at once: a ConsultOutcome
            return self._absorb(started)
        return started

    def free_to_consult(self, question: Question, trigger: Any) -> bool:
        """Whether this expert's model (and its peer's) could take the question now."""
        if self.service is None or not hasattr(self.service, "free_for"):
            return True
        return bool(self.service.free_for(self.agent_id, question.kind, trigger))

    def finish_consulting(self, pending: Any, give_up: int = 0) -> Optional[Answer]:
        """
        The answer of a started consultation, or None while the model is still at it.

        `give_up` is the decision's deadline in ticks when it has passed: the
        consultation is then closed as `timeout` and the rule's answer comes
        back, marked as the model's stand-in.
        """
        self.last_consultation = None
        if give_up:
            pending.gave_up = int(give_up)
        try:
            outcome = self.service.poll(pending, give_up=bool(give_up))
        except Exception as exc:  # the service must never stop a tick
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.reachable = False
            return self._fall_back(pending.rule_answer, self.last_error)
        if outcome is None:
            return None
        return self._absorb(outcome)

    def note_outcome(self, consultation_id: str, used: str, detail: str = "",
                     choice: Any = None, tick: Optional[int] = None) -> None:
        """Tell the service what became of a consultation's answer (the live page shows it)."""
        note = getattr(self.service, "note_outcome", None)
        if callable(note) and consultation_id:
            note(consultation_id, used, detail, choice, tick)

    def _rule_answer(self, question: Question) -> Optional[Answer]:
        try:
            return self.fallback.answer(question)
        except Exception as exc:  # a rule that raises must not stop the tick either
            self.last_error = f"rule raised {type(exc).__name__}: {exc}"
            return None

    def _decide(self, question: Question, trigger: Any) -> Answer:
        self.last_consultation = None
        rule_answer = self._rule_answer(question)
        if self.service is None:
            return self._fall_back(rule_answer, NOT_INSTALLED)
        self.calls += 1
        try:
            outcome = self.service.run(self.agent_id, question, trigger, rule_answer)
        except Exception as exc:  # the service must never stop a tick
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.reachable = False
            return self._fall_back(rule_answer, self.last_error)
        return self._absorb(outcome)

    def _absorb(self, outcome: Any) -> Answer:
        """Count a closed consultation and return its answer."""
        self.last_prompt = getattr(outcome, "prompt", None)
        self.last_consultation = {"consultation_id": outcome.consultation_id,
                                  "peer": outcome.peer, "turns": outcome.turns}
        if outcome.latency_ms is not None:
            self._latencies.append(float(outcome.latency_ms))
        for name, count in (getattr(outcome, "counts", None) or {}).items():
            if name in COUNTED:
                setattr(self, name, getattr(self, name) + int(count))
        kind = getattr(outcome, "outcome", "")
        error = getattr(outcome, "error", "")
        if kind == "model_failed":
            self.reachable = False
        if error:
            self.last_error = error
        answer = outcome.answer
        if answer.source == "fallback":
            self.fallbacks += 1
        elif str(answer.source).startswith("crewai:"):
            self.reachable = True
        return answer

    def _fall_back(self, rule_answer: Optional[Answer], why: str) -> Answer:
        from ..agents.base import BaseAgent

        self.fallbacks += 1
        # Nothing reached a model, so no prompt counts as one the model saw.
        self.last_prompt = None
        return BaseAgent._fallback(rule_answer, why)

    def stats(self) -> Dict[str, Any]:
        """
        This expert's model decisions, counted.

        `calls` = model decisions handed to the service (every consultation
        opened for this expert); `consultations` = those in which the owner
        actually asked or delegated to its peer (an exchange), so it is at most
        `calls`; `questions` and `delegations` split the exchanges.
        `retries` = owner model calls beyond the first call and the
        post-exchange call, summed over its consultations: each is CrewAI's
        executor asking the model again because the owner's previous reply
        could not be used as it stood (a tool call whose arguments did not
        parse, a coworker or tool not on offer, a second exchange refused).
        It is measured from the transport audit's record of the owner's calls,
        not inferred from the reply. No HTTP-level retry exists to count: the
        SDK's own retries are off.
        """
        mean = (round(sum(self._latencies) / len(self._latencies), 1)
                if self._latencies else None)
        return {"brain": self.name, "model": self.config.model_type,
                "provider": self.config.provider, "base_url": self.config.base_url,
                "calls": self.calls, "consultations": self.consultations,
                "questions": self.questions, "delegations": self.delegations,
                "fallbacks": self.fallbacks, "rejected_answers": self.rejected_answers,
                "parse_failures": self.parse_failures, "timeouts": self.timeouts,
                "retries": self.retries, "reachable": self.reachable,
                "last_error": self.last_error, "mean_latency_ms": mean}

    def close(self) -> None:
        """Nothing to release: the LLM and the service are shared and owned elsewhere."""
