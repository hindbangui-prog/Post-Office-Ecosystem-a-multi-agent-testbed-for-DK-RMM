"""
The path a decision takes, from the facts to the floor.

    runtime state -> perception -> routine? -> rule OR brain
                  -> proposal -> schema -> policy -> state -> execution

Two things are being pinned here. The first is conditional automation: the
Python rule answers first, and the brain is consulted only when that answer is
insufficient -- no rule for the case, no admissible answer, or a condition the
agent declared that means its rule cannot be trusted. Pressure alone (more
work than floor) is noted on the decision and the rule stands, which is what
stops an LLM run from being a model call per tick per agent. The second is
that whichever path answered, the answer is validated before it counts -- the
model path is not the unguarded one.

And the whole of it is written down. A run has to be able to say, afterwards,
how many decisions were taken, how many were reasoned about, what triggered
the reasoning, and what the gate did about the result. That record is the
experiment; the simulation is only how it gets produced.
"""

from __future__ import annotations

import pytest

from post_office.agents.brain import Answer, Brain, DeterministicBrain, Question
from post_office.agents.reasoning import REASONS, Trigger
from post_office.communication.events import EventCategory
from post_office.simulation import build


class CountingBrain(Brain):
    """A brain that says what it was asked, and how often."""

    name = "counting"

    def __init__(self, fallback, choice=None):
        self.fallback = fallback
        self.asked = []
        self._choice = choice

    def answer(self, question: Question) -> Answer:
        self.asked.append(question)
        choice = self._choice
        if choice is None:
            choice = question.options[0] if question.options else None
        return Answer(choice, "because I was asked", source="counting")


@pytest.fixture
def eco():
    made = build(seed=11, run_id="pipeline")
    made.start()
    yield made
    made.close()


def fit(agent, choice=None):
    """Put a counting brain in front of the agent's own rules."""
    rules = getattr(agent.brain, "fallback", agent.brain)
    brain = CountingBrain(rules, choice=choice)
    agent.brain = brain
    return brain


# ----------------------------------------------------- routine vs reasoned
def test_a_routine_decision_never_reaches_the_brain(eco):
    planner = eco.planner
    brain = fit(planner)

    answer = planner.decide("release_work", "how many?", options=(0, 1, 2),
                            waiting=1, headroom=8, free_robots=4,
                            open_transports=0, ceiling=8, storage_load=0.1)

    assert brain.asked == [], "the model was consulted about nothing"
    assert answer.source == "deterministic"


def test_pressure_alone_is_noted_and_the_rule_still_answers(eco):
    """
    More waiting than headroom is contention. The planner's rule has a
    definite answer for it, so the model is not asked; the condition is
    written on the decision as `noted`, and the rule's answer stands.
    """
    planner = eco.planner
    brain = fit(planner, choice=0)

    answer = planner.decide("release_work", "how many?", options=(0, 1, 2),
                            waiting=40, headroom=1, free_robots=0,
                            open_transports=8, ceiling=8, storage_load=0.1)

    assert brain.asked == [], "contention is pressure, not a rule that cannot answer"
    assert answer.source == "deterministic"
    last = planner.decisions[-1]
    assert last["mode"] == "deterministic"
    assert last["trigger"] == "" and last["noted"] == REASONS.CONTENTION
    assert planner.noted_counts == {REASONS.CONTENTION: 1} and planner.reasoned == 0


def test_a_case_the_rules_do_not_cover_does_reach_the_brain(eco):
    """A decision kind with no rule has no cheap path: the brain answers."""
    planner = eco.planner
    brain = fit(planner, choice="hold")

    planner.decide("novel_question", "something the rules never saw",
                   options=("hold", "release"), waiting=3)

    assert len(brain.asked) == 1, "no rule for this decision, so the model was asked"
    last = planner.decisions[-1]
    assert last["mode"] == "llm"
    assert last["trigger"] == REASONS.UNKNOWN
    assert planner.reasoned == 1 and planner.trigger_counts == {REASONS.UNKNOWN: 1}


def test_a_rule_that_declares_itself_insufficient_reaches_the_brain(eco):
    """
    A condition that means the rule cannot be trusted -- here the routing
    rule's previous answer did not work: the robot is still blocked after
    six ticks -- sends the decision to the brain, with the reason recorded.
    """
    routing = eco.experts["ROUTING"]
    brain = fit(routing, choice="YIELD")

    routing.decide("resolve_block", "blocked; what now?",
                   options=("WAIT", "REROUTE", "YIELD", "PUSH"),
                   robot="R1", blocked_by="R2", ticks_blocked=6,
                   detour_extra=0, direct_distance=4, battery=90.0)

    assert len(brain.asked) == 1
    last = routing.decisions[-1]
    assert last["mode"] == "llm" and last["trigger"] == REASONS.FAILED


def test_a_tie_on_the_walk_is_the_rules_not_the_brains(eco):
    """
    Two robots the walk does not separate are still separated by the rule
    (charge, then robot id), the same way on every call: the condition is
    noted as contention and the rule answers.
    """
    scheduling = eco.experts["SCHEDULING"]
    brain = fit(scheduling, choice="R1")

    answer = scheduling.decide("choose_robot", "which robot?", options=("R1", "R2"),
                               parcel_id="P-0001", priority="NORMAL", able=["R1", "R2"],
                               robots={"R1": {"distance": 4, "battery": 90},
                                       "R2": {"distance": 5, "battery": 92}},
                               errand_cells=10, slack=600)

    assert brain.asked == [] and answer.choice == "R2"
    last = scheduling.decisions[-1]
    assert last["mode"] == "deterministic" and last["noted"] == REASONS.CONTENTION


def test_a_contention_the_rule_cannot_break_does_reach_the_brain(eco):
    """
    Contention is pressure the rules answer -- except where the agent's own
    condition says the rule cannot: no robot able to finish the errand. That
    condition declares itself, and the decision goes to the brain.
    """
    scheduling = eco.experts["SCHEDULING"]
    brain = fit(scheduling, choice="R2")

    scheduling.decide("choose_robot", "which robot?", options=("R1", "R2"),
                      parcel_id="P-0001", priority="NORMAL", able=[],
                      robots={"R1": {"distance": 4, "battery": 14},
                              "R2": {"distance": 5, "battery": 15}},
                      errand_cells=10, slack=600)

    assert len(brain.asked) == 1, "nobody able is a contention the rule cannot resolve"
    last = scheduling.decisions[-1]
    assert last["mode"] == "llm" and last["trigger"] == REASONS.CONTENTION
    assert last["path"] == "llm/contention"


def test_every_decision_says_where_its_answer_came_from(eco):
    planner = eco.planner
    fit(planner, choice="hold")
    planner.decide("release_work", "how many?", options=(0, 1, 2),
                   waiting=1, headroom=8, free_robots=4,
                   open_transports=0, ceiling=8, storage_load=0.1)
    assert planner.decisions[-1]["path"] == "deterministic"
    planner.decide("novel_question", "something the rules never saw",
                   options=("hold", "release"), waiting=3)
    assert planner.decisions[-1]["path"] == "llm/unknown"
    assert planner.path_counts == {"deterministic": 1, "llm/unknown": 1}
    paths = eco.decision_paths()
    assert paths.get("llm/unknown") == 1 and paths.get("deterministic", 0) >= 1
    assert "decision_paths" in eco.summary()


def test_the_earlier_arrangement_is_still_available_as_a_policy(eco):
    """
    `any_trigger` sends every fired condition to the model, which is how the
    recorded battery was run. It is a configuration, not the default.
    """
    planner = eco.planner
    brain = fit(planner, choice=0)
    planner.consult_policy = "any_trigger"

    planner.decide("release_work", "how many?", options=(0, 1, 2),
                   waiting=40, headroom=1, free_robots=0,
                   open_transports=8, ceiling=8, storage_load=0.1)

    assert len(brain.asked) == 1
    last = planner.decisions[-1]
    assert last["mode"] == "llm" and last["trigger"] == REASONS.CONTENTION
    assert last["noted"] == ""


def test_the_llm_scenario_puts_every_decision_to_the_brain(eco):
    """
    Normal (LLM): the same routine decision the rules answer under Normal goes
    to the brain, recorded with the policy as its reason; the gate still
    validates the answer.
    """
    planner = eco.planner
    brain = fit(planner, choice=0)
    planner.consult_policy = "always"

    answer = planner.decide("release_work", "how many?", options=(0, 1, 2),
                            waiting=1, headroom=8, free_robots=4,
                            open_transports=0, ceiling=8, storage_load=0.1)

    assert len(brain.asked) == 1, "every decision goes to the brain in this scenario"
    last = planner.decisions[-1]
    assert last["mode"] == "llm" and last["trigger"] == REASONS.POLICY
    assert last["path"] == "llm/policy" and last["validation"] == "ok"
    assert answer.source == "counting"


def test_the_policy_comes_from_the_configuration():
    from post_office.simulation import build

    made = build(seed=11, run_id="policy", config={"consult_policy": "any_trigger"})
    try:
        assert made.consult_policy == "any_trigger"
        assert made.planner.consult_policy == "any_trigger"
        assert all(a.consult_policy == "any_trigger" for a in made.experts.values())
        assert made.summary()["consult_policy"] == "any_trigger"
    finally:
        made.close()
    made = build(seed=11, run_id="policy-default")
    try:
        assert made.summary()["consult_policy"] == "insufficient"
    finally:
        made.close()
    with pytest.raises(ValueError, match="consult_policy"):
        build(seed=11, run_id="policy-bad", config={"consult_policy": "never"})


def test_a_routine_decision_is_recorded_as_routine(eco):
    planner = eco.planner
    fit(planner)

    planner.decide("release_work", "how many?", options=(0, 1, 2),
                   waiting=1, headroom=8, free_robots=4,
                   open_transports=0, ceiling=8, storage_load=0.1)

    last = planner.decisions[-1]
    assert last["mode"] == "deterministic"
    assert last["trigger"] == ""


# ------------------------------------------------------------- validation
def test_an_answer_the_gate_refuses_falls_back_to_the_rule(eco):
    """
    The model answers with something it is not allowed to do. The decision
    still has to be made, so the deterministic rule makes it -- and the
    refusal is on the record rather than swallowed.
    """
    planner = eco.planner
    fit(planner, choice=3)                     # more than the headroom allows
    planner.consult_policy = "any_trigger"     # the model path is what is under test

    answer = planner.decide("release_work", "how many?", options=(0, 1, 2, 3),
                            waiting=40, headroom=1, free_robots=0,
                            open_transports=8, ceiling=8, storage_load=0.1)

    last = planner.decisions[-1]
    assert last["validation"] == "policy", "refused at the policy stage"
    assert answer.choice != 3, "the refused answer was not carried out"
    assert answer.source.endswith("rule-after-refusal")


def test_a_permitted_answer_is_carried_out(eco):
    planner = eco.planner
    fit(planner, choice=1)
    planner.consult_policy = "any_trigger"     # the model path is what is under test

    answer = planner.decide("release_work", "how many?", options=(0, 1, 2, 3),
                            waiting=40, headroom=8, free_robots=3,
                            open_transports=0, ceiling=8, storage_load=0.1)

    assert answer.choice == 1
    assert planner.decisions[-1]["validation"] == "ok"


def test_the_deterministic_path_is_validated_too(eco):
    """
    Not only the model. A rule that proposed something forbidden would be a
    bug, and a gate that only watched the model would never see it.
    """
    planner = eco.planner
    planner.decide("release_work", "how many?", options=(0, 1, 2),
                   waiting=1, headroom=8, free_robots=4,
                   open_transports=0, ceiling=8, storage_load=0.1)

    assert planner.decisions[-1]["validation"] == "ok"
    assert eco.gate.checked > 0, "the gate saw the deterministic decision"


# ------------------------------------------------------------------ record
def test_every_decision_is_written_down_with_what_caused_it(eco):
    planner = eco.planner
    fit(planner, choice=0)
    planner.decide("release_work", "how many?", options=(0, 1, 2),
                   waiting=40, headroom=1, free_robots=0,
                   open_transports=8, ceiling=8, storage_load=0.1)

    rows = [e for e in eco.logger.recent(limit=200, actor="PLANNER")
            if e.topic == "decision"
            and e.detail.get("decision") == "release_work"]
    assert rows, "nothing was logged"
    written = rows[-1].detail
    for field in ("mode", "trigger", "trigger_detail", "noted", "validation",
                  "facts", "choice", "reason", "source"):
        assert field in written, f"the log does not record {field}"


def test_the_record_carries_a_rationale_and_not_a_transcript(eco):
    """
    A short reason, in the agent's own words, is what makes a run readable
    afterwards. Anything longer would be the model's working, which is not
    ours to store.
    """
    planner = eco.planner
    fit(planner, choice=0)
    planner.decide("release_work", "how many?", options=(0, 1, 2),
                   waiting=40, headroom=1, free_robots=0,
                   open_transports=8, ceiling=8, storage_load=0.1)

    reason = planner.decisions[-1].get("reason", "")
    assert 0 < len(reason) <= 200, "a rationale, not a transcript"


def test_the_run_can_count_its_own_reasoning(eco):
    """
    The measurement the whole arrangement exists to make. One number per
    agent, available without reading the trace database.
    """
    for _ in range(120):
        eco.step()

    counted = eco.reasoning_summary()
    assert set(counted) >= {"PLANNER", "SORTING", "DISPATCH"}
    for agent_id, row in counted.items():
        assert row["decisions"] >= row["llm"], agent_id
        assert set(row["triggers"]) <= set(REASONS.all()), agent_id
