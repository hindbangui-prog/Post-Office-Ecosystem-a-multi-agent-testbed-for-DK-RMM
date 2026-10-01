"""CrewBrain at the Brain seam, the seven CrewAI roles, and `llm_brains`."""

import pytest

from post_office.agents.brain import Answer, Brain, DeterministicBrain, Question
from post_office.config.settings import EXPERTS, llm_brains, normal_config
from post_office.crew.brain import CrewBrain
from post_office.crew.identity import ModelUnavailable
from post_office.crew.llm import build_llm
from post_office.crew.roles import (BACKSTORY_ENDING, ROLES, agent_id_of, build_agents,
                                    role_of)
from post_office.simulation.ecosystem import build

ROLE_NAMES = {"Planner", "Intake", "Sorting", "Scheduling", "Routing", "Resource", "Dispatch"}


def test_crewai_roles_are_the_source_roles(fake_ollama):
    brains = llm_brains(settings=fake_ollama.settings, verify=False)
    assert {b.crew_agent.role for b in brains.values()} == ROLE_NAMES


def test_llm_brains_refuses_non_experts(fake_ollama):
    with pytest.raises(ValueError):
        llm_brains(["SUPERVISOR"], settings=fake_ollama.settings, verify=False)
    with pytest.raises(ValueError):
        llm_brains(["PLANNER", "R1"], settings=fake_ollama.settings, verify=False)


def test_llm_brains_takes_a_subset_of_the_experts(fake_ollama):
    brains = llm_brains(["SORTING", "DISPATCH"], settings=fake_ollama.settings, verify=False)
    assert sorted(brains) == ["DISPATCH", "SORTING"]


def test_all_brains_share_one_llm_and_model(fake_ollama):
    brains = llm_brains(settings=fake_ollama.settings, verify=False)
    eco = build(seed=1, config=normal_config(), brains=brains)

    def eco_agent_rules(b):
        return eco.agents[b.agent_id].rules()

    assert sorted(brains) == sorted(EXPERTS)
    assert len({id(b.crew_agent.llm) for b in brains.values()}) == 1
    assert all(b.config.model_type == "qwen3:8b" and b.crew_agent.allow_delegation is False
               for b in brains.values())
    assert all(b.fallback is eco_agent_rules(b) for b in brains.values())
    assert len({id(b.fallback) for b in brains.values()}) == 7
    assert all(isinstance(b.fallback, DeterministicBrain) for b in brains.values())


def test_verify_consults_the_model_identity(fake_ollama):
    brains = llm_brains(settings=fake_ollama.settings)          # verify defaults to True
    assert len(brains) == 7
    assert ("GET", "/api/tags") in fake_ollama.calls
    fake_ollama.serve_models(["llama3:8b"])
    with pytest.raises(ModelUnavailable):
        llm_brains(settings=fake_ollama.settings)


def test_no_verify_makes_no_request(fake_ollama):
    llm_brains(settings=fake_ollama.settings, verify=False)
    assert fake_ollama.calls == []


def test_brain_contract_and_config(fake_ollama):
    brain = llm_brains(["ROUTING"], settings=fake_ollama.settings, verify=False)["ROUTING"]
    assert isinstance(brain, Brain)
    assert brain.name == "crewai" and brain.reads_prompt is True
    assert brain.last_prompt is None and brain.last_consultation is None
    assert brain.service is None
    assert brain.config.model_type == "qwen3:8b"
    assert brain.config.seed == 42
    assert brain.config.base_url == fake_ollama.base_url
    assert brain.config.provider == "ollama"
    stats = brain.stats()
    assert set(stats) == {"brain", "model", "provider", "base_url", "calls", "consultations",
                          "questions", "delegations", "fallbacks", "rejected_answers",
                          "parse_failures", "timeouts", "retries", "reachable", "last_error",
                          "mean_latency_ms"}
    assert stats["brain"] == "crewai" and stats["provider"] == "ollama"
    assert stats["model"] == "qwen3:8b" and stats["calls"] == 0
    brain.close()


def _question():
    return Question(kind="choose_robot", asked_by="SCHEDULING", prompt="Which robot?",
                    options=["R1", "R2"], facts={"task": "T1"})


def test_unbound_brain_answers_with_the_rule(fake_ollama):
    brain = llm_brains(["SCHEDULING"], settings=fake_ollama.settings,
                       verify=False)["SCHEDULING"]
    brain.fallback.register("choose_robot", lambda q: Answer("R2", "closest", confidence=0.7))
    brain.last_consultation = {"consultation_id": "old", "peer": "ROUTING", "turns": 3}

    answer = brain.answer(_question())
    assert answer.choice == "R2"
    assert answer.source == "fallback"
    assert answer.reason == "closest [fallback: model layer not installed]"
    assert answer.reason.endswith("[fallback: model layer not installed]")
    assert answer.confidence == 0.7
    assert brain.last_consultation is None

    brain.last_consultation = {"consultation_id": "old", "peer": "ROUTING", "turns": 3}
    again = brain.answer_consulting(_question(), trigger=None)
    assert again.choice == "R2" and again.source == "fallback"
    assert brain.last_consultation is None
    assert brain.stats()["fallbacks"] == 2
    assert fake_ollama.requests == []


class _Outcome:
    def __init__(self, answer):
        self.answer = answer
        self.consultation_id = "C-1"
        self.outcome = "decided"
        self.peer = "ROUTING"
        self.turns = 3
        self.latency_ms = 12.0
        self.model = "qwen3:8b"


class _Service:
    def __init__(self):
        self.runs = []

    def run(self, owner_id, question, trigger, rule_answer):
        self.runs.append((owner_id, question, trigger, rule_answer))
        return _Outcome(Answer("R1", "peer agreed", source="crewai:qwen3:8b"))


def test_bound_brain_hands_the_decision_to_the_service(fake_ollama):
    brain = llm_brains(["SCHEDULING"], settings=fake_ollama.settings,
                       verify=False)["SCHEDULING"]
    brain.fallback.register("choose_robot", lambda q: Answer("R2", "closest"))
    service = _Service()
    brain.bind(service)

    answer = brain.answer_consulting(_question(), trigger="contention")
    owner, question, trigger, rule_answer = service.runs[0]
    assert (owner, trigger, rule_answer.choice) == ("SCHEDULING", "contention", "R2")
    assert question.kind == "choose_robot"
    assert answer.choice == "R1" and answer.source == "crewai:qwen3:8b"
    assert brain.last_consultation == {"consultation_id": "C-1", "peer": "ROUTING", "turns": 3}

    brain.answer(_question())
    assert service.runs[1][2] is None
    stats = brain.stats()
    assert stats["calls"] == 2 and stats["mean_latency_ms"] == 12.0


def test_roles_table_and_lookups():
    assert list(ROLES) == list(EXPERTS)
    for agent_id, spec in ROLES.items():
        assert spec.agent_id == agent_id
        assert role_of(agent_id) == spec.role
        assert agent_id_of(spec.role) == agent_id
        assert spec.goal and spec.backstory.endswith(BACKSTORY_ENDING)
        assert "\u2014" not in spec.goal + spec.backstory
    assert {s.role for s in ROLES.values()} == ROLE_NAMES
    with pytest.raises(KeyError):
        role_of("SUPERVISOR")
    with pytest.raises(KeyError):
        agent_id_of("Supervisor")


def test_build_agents_settings(fake_ollama):
    llm = build_llm(fake_ollama.settings)
    agents = build_agents(llm)
    assert list(agents) == list(EXPERTS)
    for agent_id, agent in agents.items():
        spec = ROLES[agent_id]
        assert (agent.role, agent.goal, agent.backstory) == (spec.role, spec.goal,
                                                             spec.backstory)
        assert agent.llm is llm
        assert agent.allow_delegation is False and agent.tools == []
        assert agent.max_iter == 4 and agent.max_retry_limit == 1
        assert agent.verbose is False and agent.cache is False
        # memory=False is passed; CrewAI resolves "no memory" to None.
        assert agent.memory is None and agent.respect_context_window is True


def test_thinking_prompt_puts_no_think_in_the_backstory(fake_ollama):
    llm = build_llm(fake_ollama.settings)
    off = build_agents(llm)
    prompt = build_agents(llm, thinking="prompt")
    for agent_id in EXPERTS:
        assert "/no_think" not in off[agent_id].backstory
        assert prompt[agent_id].backstory == "/no_think " + ROLES[agent_id].backstory
    with pytest.raises(ValueError):
        build_agents(llm, thinking="loud")
