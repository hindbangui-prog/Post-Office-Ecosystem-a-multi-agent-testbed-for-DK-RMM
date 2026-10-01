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
carries an earlier decision's consultation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from crewai import Agent

from ..agents.brain import Answer, Brain, DeterministicBrain, Question
from ..config.ollama import OllamaSettings

NOT_INSTALLED = "model layer not installed"


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

    def _decide(self, question: Question, trigger: Any) -> Answer:
        self.last_consultation = None
        rule_answer = self.fallback.answer(question)
        if self.service is None:
            return self._fall_back(rule_answer, NOT_INSTALLED)
        self.calls += 1
        outcome = self.service.run(self.agent_id, question, trigger, rule_answer)
        self.last_consultation = {"consultation_id": outcome.consultation_id,
                                  "peer": outcome.peer, "turns": outcome.turns}
        if outcome.latency_ms is not None:
            self._latencies.append(float(outcome.latency_ms))
        answer = outcome.answer
        if answer.source == "fallback":
            self.fallbacks += 1
        elif str(answer.source).startswith("crewai:"):
            self.reachable = True
        return answer

    def _fall_back(self, rule_answer: Answer, why: str) -> Answer:
        self.fallbacks += 1
        # Nothing reached a model, so no prompt counts as one the model saw.
        self.last_prompt = None
        return Answer(choice=rule_answer.choice, reason=f"{rule_answer.reason} [fallback: {why}]",
                      source="fallback", confidence=rule_answer.confidence)

    def stats(self) -> Dict[str, Any]:
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
