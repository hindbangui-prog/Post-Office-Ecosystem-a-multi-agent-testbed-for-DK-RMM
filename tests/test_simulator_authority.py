"""
The model never touches the world (spec 11).

Static: no module of the model layer imports the environment, the task
registry, the robots or the world state (it may import
`discussion.briefings`, which only reads). Dynamic: an owner's answer outside
the allowed answers never reaches the policy gate, whether the model wrote it
or an agent hook put it there; the rule answers instead, marked as a
fallback. The peer's own CrewAI task runs with no tools, so the peer can only
return advice.
"""

import ast
import pathlib

import pytest
from crewai import Agent

import post_office
from post_office.agents.brain import Answer
from post_office.crew.interception import AgentHooks
from tests.consult_helpers import ask, events, scheduling_with_equally_placed_robots
from tests.fake_ollama import consultation_script

pytestmark = pytest.mark.usefixtures("quiet_crewai_console")

ROOT = pathlib.Path(post_office.__file__).resolve().parent
FORBIDDEN = ("environment", "tasks", "robots", "state")
RULE_CHOICE = "R1"


def _imported_packages(path):
    """The `post_office` subpackage each import of `path` names (relative ones resolved)."""
    out = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "post_office" and len(parts) > 1:
                    out.append(parts[1])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                parts = (node.module or "").split(".")
                if parts[0] == "post_office":
                    if len(parts) > 1:
                        out.append(parts[1])
                    else:  # `from post_office import a, b`: every name is a subpackage
                        out.extend(alias.name for alias in node.names)
            elif node.level == 1:
                continue  # inside post_office/crew itself
            elif node.level == 2:
                if node.module:
                    out.append(node.module.split(".")[0])
                else:  # `from .. import a, b`: every name is a subpackage
                    out.extend(alias.name for alias in node.names)
    return out


def test_the_import_scan_sees_every_name(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("from .. import agents, robots\nfrom post_office import discussion, state\n"
                     "import post_office.tasks\nfrom ..environment.layout import X\n")
    assert _imported_packages(probe) == ["agents", "robots", "discussion", "state", "tasks",
                                         "environment"]


def test_the_model_layer_imports_nothing_that_writes_the_world():
    seen = set()
    for path in sorted((ROOT / "crew").glob("*.py")):
        for package in _imported_packages(path):
            seen.add(package)
            assert package not in FORBIDDEN, (path.name, package)
    # It does read the briefings, and does reach the agents' Answer/Question.
    assert {"agents", "discussion"} <= seen


@pytest.fixture
def gate_sees(monkeypatch):
    def install(eco):
        seen = []
        check = eco.world.gate.check

        def watching(proposal):
            seen.append(proposal.choice)
            return check(proposal)

        monkeypatch.setattr(eco.world.gate, "check", watching)
        return seen
    return install


@pytest.fixture
def executed(monkeypatch):
    """Every `Agent.execute_task` call: (role, tools), in order."""
    seen = []
    original = Agent.execute_task

    def spy(self, task, context=None, tools=None):
        seen.append((self.role, tools))
        return original(self, task, context, tools)

    monkeypatch.setattr(Agent, "execute_task", spy)
    return seen


def test_an_off_list_owner_answer_never_reaches_the_gate(fake_ollama, gate_sees, executed):
    fake_ollama.script(consultation_script("Take R7.", decide=lambda peer: "R7"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    seen = gate_sees(eco)
    answer = ask(sched)

    assert seen == [RULE_CHOICE] and "R7" not in seen
    assert answer.choice == RULE_CHOICE and answer.source == "fallback"
    decision = events(eco, "decision")[-1]
    assert decision.detail["path"] == "fallback" and decision.detail["choice"] == RULE_CHOICE
    # The peer was asked, with no tools of its own.
    assert executed[0][0] == "Scheduling" and len(executed[0][1]) == 2
    assert executed[1][0] == "Routing" and executed[1][1] in (None, [])


class _OffList(AgentHooks):
    """A hook that rewrites the owner's valid answer into one that is not allowed."""

    def after_answer(self, agent_id, answer):
        return Answer("R9", answer.reason, source=answer.source, confidence=answer.confidence)


def test_an_off_list_answer_from_a_hook_never_reaches_the_gate(fake_ollama, gate_sees):
    fake_ollama.script(consultation_script("R2: clear.", decide=lambda peer: "R2"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    eco.crew.interception.agent = _OffList()
    seen = gate_sees(eco)
    answer = ask(sched)

    assert seen == [RULE_CHOICE]
    assert answer.choice == RULE_CHOICE and answer.source == "fallback"
    assert "not among the allowed answers" in answer.reason
    (closed,) = events(eco, "consult_closed")
    assert closed.detail["outcome"] == "no_valid_decision" and closed.detail["choice"] is None
    assert sched.brain.stats()["rejected_answers"] == 1


def test_an_admissible_answer_the_world_refuses_is_replaced_by_the_rule(fake_ollama, gate_sees):
    """The gate, not the model, has the last word: a refused choice gives way to the rule."""
    from post_office.policy.gate import Verdict

    fake_ollama.script(consultation_script("R2: clear.", decide=lambda peer: "R2"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    seen = gate_sees(eco)
    check = eco.world.gate.check

    def refuse_r2(proposal):
        if proposal.choice == "R2":
            check(proposal)
            return Verdict(False, "state", "R2 is busy")
        return check(proposal)

    eco.world.gate.check = refuse_r2
    answer = ask(sched)
    # The rule's replacement is applied by the agent's own code, not re-proposed.
    assert seen == ["R2"]
    assert answer.choice == RULE_CHOICE
    assert answer.source == "crewai:qwen3:8b:rule-after-refusal"
    assert events(eco, "decision")[-1].detail["validation"] == "state"
