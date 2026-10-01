"""
Where a judgement lives, and therefore where a model can go.

The rule this file exists to hold: **agents decide, sub-agents report.** An
expert weighs what its clerks found and answers the question; a sub-agent
gathers the facts and hands them up. Nothing below the expert layer ever calls
`decide()`, so nothing below it can have a model behind it.

That was not how the system grew. The first judgements were written into the
sub-agents -- SUB-PRIORITY graded parcels, SUB-QUEUE ordered work, SUB-BATTERY
ruled on errands -- and four of the six experts did nothing but relay their
answers upward. It read strangely on the interaction graph: the agent with the
name and the responsibility had no decision to make, and the tool underneath it
had all of them.

So the judgements moved up. Each sub-agent still does the work only it can do
-- read the address, measure the distance, count the shelves -- and reports; the
expert above it makes the call. The sub-agents are genuinely tools now, which
is what they were always described as.

Two consequences this file pins down:

  * `LLM_CANDIDATES` is exactly the planner and the six experts. A model can
    only be put where there is something to decide.
  * No sub-agent calls `decide()`. Checked by reading the source rather than by
    running it, because a decision on a rare branch would otherwise slip
    through a green run.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from post_office.communication import AgentKind
from post_office.config.settings import LLM_CANDIDATES
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=3, run_id="judgement-lives")
    made.start()
    yield made
    made.close()


#: The planner and the six experts. Everything else in the hierarchy either
#: carries out an instruction (a robot), gathers facts (a sub-agent), or owns
#: the objective rather than the traffic (the supervisor).
DECIDERS = {"PLANNER", "INTAKE", "SORTING", "ROUTING", "SCHEDULING",
            "RESOURCE", "DISPATCH"}


def test_only_the_planner_and_the_experts_may_have_a_model():
    assert set(LLM_CANDIDATES) == DECIDERS
    assert len(LLM_CANDIDATES) == len(set(LLM_CANDIDATES)), "no duplicates"


def test_the_candidates_are_exactly_the_agents_that_decide(eco):
    """
    The list is not a preference. It is the set of agents that call `decide()`,
    and a name on it that decides nothing would be a model nobody ever asks.
    """
    assert set(LLM_CANDIDATES) == set(eco.experts) | {"PLANNER"}
    for agent_id in LLM_CANDIDATES:
        assert agent_id in eco.agents


def test_no_subagent_anywhere_calls_decide():
    """
    Read off the source of every sub-agent class in the package, so a judgement
    hidden on a branch that a green run never reaches still fails this.
    """
    from post_office.agents import subagents

    folder = pathlib.Path(inspect.getfile(subagents)).parent
    sources = sorted(folder.glob("*.py"))
    assert len(sources) > 3, "the sub-agent package moved"

    offenders = []
    for path in sources:
        tree = ast.parse(path.read_text())
        for klass in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for node in ast.walk(klass):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "decide"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "self"):
                    offenders.append(f"{path.name}:{klass.name}")
    assert not offenders, \
        f"sub-agents are tools and do not judge: {sorted(set(offenders))}"


def test_no_subagent_declares_rules_of_its_own():
    """
    The other half of the same rule. A sub-agent with an `install_rules` of its
    own is one whose fallback behaviour lives below the agent that is supposed
    to own the decision -- which is how the judgements ended up down there in
    the first place.
    """
    from post_office.agents.base import SubAgent
    from post_office.agents import subagents

    for name in dir(subagents):
        thing = getattr(subagents, name)
        if not inspect.isclass(thing) or not issubclass(thing, SubAgent):
            continue
        assert "install_rules" not in vars(thing), \
            f"{name} installs its own rules; that belongs on its parent"


def test_every_expert_has_something_to_decide(eco):
    """
    The converse, and the reason this is not just a list edit. An expert with a
    model and no decision is a model nobody ever asks, which would make the
    setting a lie.
    """
    for agent_id, agent in eco.experts.items():
        source = inspect.getsource(type(agent))
        assert "self.decide(" in source, \
            f"{agent_id} is a model candidate but never decides anything"


def test_every_decision_in_the_run_was_made_by_a_decider(eco):
    """
    And the same thing measured rather than read: after four hundred ticks,
    every recorded decision belongs to an agent on the list.
    """
    for _ in range(400):
        eco.step()
    for agent_id, agent in eco.agents.items():
        record = eco.directory.get(agent_id)
        if record is not None and record.kind is AgentKind.SUBAGENT:
            assert not getattr(agent, "decisions", ()), \
                f"{agent_id} made a decision"
    decided = sum(len(getattr(eco.agents[a], "decisions", ())) for a in DECIDERS
                  if a in eco.agents)
    assert decided > 0, "nobody decided anything in four hundred ticks"
