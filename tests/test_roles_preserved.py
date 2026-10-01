"""The LLM boundary (spec 5): exactly the seven experts are on CrewAI."""

from post_office.config.settings import llm_brains, normal_config
from post_office.simulation.ecosystem import build


def test_exactly_the_seven_experts_are_on_crewai(fake_ollama):
    eco = build(seed=1, config=normal_config(),
                brains=llm_brains(settings=fake_ollama.settings, verify=False))
    on_model = sorted(i for i, a in eco.agents.items() if a.brain.name == "crewai")
    assert on_model == ["DISPATCH", "INTAKE", "PLANNER", "RESOURCE", "ROUTING",
                        "SCHEDULING", "SORTING"]
    assert all(a.brain.name == "deterministic" for i, a in eco.agents.items()
               if i not in on_model)
