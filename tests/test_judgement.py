"""
Whether each decision is as good as the facts it is given.

An audit of this system found the same defect in nine places: an agent is handed
a set of facts, passes them to its brain, and answers from two of them. The
worst cases were not close calls -- the queue sub-agent was offered eight tasks
and could only ever return the first, and the departure gate was handed each
parcel's promise under a comment calling it "the fact that makes this a
judgement rather than a timer" and never read it.

That matters more here than it would elsewhere. The deterministic rule is the
baseline a language model is measured against, so a rule that ignores half its
evidence does not make the model look good -- it makes the comparison
meaningless, because the two are not answering the same question.

These tests fix three things in place: that a promise made to a parcel is what
the facility schedules against, that every fact offered to a rule is either read
or not offered, and that choosing a robot for a job is a decision somebody makes
rather than a tuple comparison.
"""

from __future__ import annotations

import pytest

from post_office.agents.brain import Question
from post_office.environment import ParcelStatus
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=3, run_id="judge")
    made.start()
    yield made
    made.close()


def run(eco, ticks):
    for _ in range(ticks):
        eco.step()
    return eco


def rule_of(agent, kind):
    """The deterministic rule an agent would answer `kind` with."""
    brain = agent.brain
    rules = getattr(brain, "fallback", brain)
    return rules._rules[kind]


# ------------------------------------------------- the promise is scheduled
def test_a_task_carries_the_promise_made_to_its_parcel(eco):
    """
    The gap the audit found: the facility computed a timetable-derived deadline
    for every parcel it accepted, and then nothing scheduled against it. A task
    that does not know when its parcel was promised cannot be ordered by it.
    """
    run(eco, 200)
    tasks = [t for t in eco.tasks.open_tasks() if t.parcel_id]
    assert tasks
    with_promise = [t for t in tasks if t.due_by is not None]
    assert with_promise, "no task knows what its parcel was promised"
    for task in with_promise:
        parcel = eco.env.parcel(task.parcel_id)
        assert parcel is not None and task.due_by == parcel.due_by


def test_the_deadline_monitor_measures_the_promise_not_a_timer(eco):
    """
    It was called the deadline monitor and did not know what a deadline was:
    it compared a task's age against a per-priority patience constant and never
    opened the parcel. Two parcels promised departures an hour apart were
    treated identically if they carried the same priority.
    """
    run(eco, 400)
    monitor = eco.subagents["SUB-DEADLINE"]
    report = monitor.perform(_ask(monitor, {}))
    assert report["ok"]
    for row in report["overdue"]:
        assert "due_by" in row and "slack" in row, row
        parcel = eco.env.parcel(row["parcel_id"])
        if parcel is not None and parcel.due_by is not None:
            assert row["slack"] == parcel.due_by - eco.world.tick


def test_the_queue_orders_by_what_is_closest_to_being_broken(eco):
    """
    Earliest deadline first, which is what a facility with cut-offs actually
    does. Priority alone sends an urgent parcel with an hour of slack ahead of
    a standard one about to miss its van.
    """
    run(eco, 400)
    queue = eco.subagents["SUB-QUEUE"]
    result = queue.perform(_ask(queue, {}))
    ordered = result.get("queue") or []
    if len(ordered) < 2:
        pytest.skip("this tick has no queue to order")
    slack = []
    for task_id in ordered:
        task = eco.tasks.get(task_id)
        slack.append(task.due_by if task.due_by is not None else 10 ** 9)
    assert slack == sorted(slack), f"not in deadline order: {ordered}"


def test_the_queue_can_choose_something_other_than_the_head(eco):
    """
    It was offered eight tasks and could only ever return the first, so seven
    of the eight options were unreachable and a model behind it could change
    nothing. The rule now has to justify the head rather than assume it.
    """
    run(eco, 400)
    scheduler = eco.experts["SCHEDULING"]
    rule = rule_of(scheduler, "choose_next_task")
    answer = rule(Question(
        kind="choose_next_task", asked_by="SCHEDULING", prompt="?",
        options=("T-0001", "T-0002", "T-0003"),
        facts={"slack": {"T-0001": 900, "T-0002": 5, "T-0003": 400}}))
    assert answer.choice == "T-0002", "the one closest to being late goes first"


def test_the_departure_gate_reads_the_deadline_it_is_handed(eco):
    """
    The defect this audit started from. Holding a parcel that is about to miss
    its promise, because two others happen to be going the same way, is a
    promise broken for a reason the rule could not see.
    """
    gate = eco.experts["DISPATCH"]
    rule = rule_of(gate, "release_parcel")
    facts = {"priority": "NORMAL", "route": "BRNO", "waiting_ticks": 2,
             "same_route_waiting": 3, "ticks_to_departure": 40,
             "ticks_to_deadline": 30, "van_free_units": 10}
    assert rule(Question(kind="release_parcel", asked_by="DISPATCH", prompt="?",
                         options=("RELEASE", "HOLD"), facts=facts)
                ).choice == "RELEASE", "it is about to be late; it goes"

    roomy = {**facts, "ticks_to_deadline": 5000}
    assert rule(Question(kind="release_parcel", asked_by="DISPATCH", prompt="?",
                         options=("RELEASE", "HOLD"), facts=roomy)
                ).choice == "HOLD", "with a promise far off, wait for company"

    full = {**roomy, "van_free_units": 0}
    assert rule(Question(kind="release_parcel", asked_by="DISPATCH", prompt="?",
                         options=("RELEASE", "HOLD"), facts=full)
                ).choice == "HOLD", "a full van cannot take it anyway"


# ------------------------------------------------ rules read what they get
def test_the_grade_is_not_a_judgement_at_all(eco):
    """
    This used to assert the opposite, and the opposite was wrong.

    The rule read "what the facility actually does about a customer's claim",
    and on a busy day it moved three parcels sold as urgent down to express,
    because a large urgent parcel with ten waiting "would hold up the dock".
    That is not a grading call, it is a refund nobody issued -- the customer
    paid for the urgent departure and the facility's own congestion is not
    their problem. The other branch promoted a standard parcel that had waited,
    which is the same mistake pointing the other way: the class decides which
    bag a parcel travels in and which departure it is owed, so promoting one
    gives away a service nobody bought.

    So there is no rule here any more. The class is read off the label and
    written down, and `test_paid_service.py` holds the facility to it. Urgency
    lives in the schedule instead, where it costs the facility rather than the
    customer: the queue is earliest-deadline-first and an ageing parcel's slack
    shrinks on its own.
    """
    sorting = eco.experts["SORTING"]
    brain = sorting.brain
    rules = getattr(brain, "fallback", brain)
    assert "classify_priority" not in rules._rules
    # The decision sorting does make is still there.
    assert "classify_destination" in rules._rules


def test_no_rule_is_offered_a_fact_it_never_reads(eco):
    """
    The audit's general finding, as a standing check. A fact passed to a rule
    that never reads it is worse than no fact: it reads as evidence the
    baseline weighed, and it is not.

    Facts are permitted to go unread only where they are recorded for the log
    or for a model rather than for the rule, and those are named here one by
    one so that adding a new one is a deliberate act.
    """
    import ast
    import inspect

    allowed = {
        # Identifiers, carried for the trace so a decision can be attributed.
        ("resolve_block", "robot"), ("battery_sufficient", "robot"),
        ("release_parcel", "route"),
        # Inputs the caller already folded into a derived figure it does pass.
        ("release_work", "open_transports"), ("release_work", "ceiling"),
        ("battery_sufficient", "route_length"),
        ("accept_into_storage", "used"), ("accept_into_storage", "capacity"),
    }

    missed = []
    every = (list(eco.subagents.values()) + list(eco.experts.values())
             + [eco.planner])
    for agent in every:
        rules = getattr(agent.brain, "fallback", agent.brain)
        for kind, fn in getattr(rules, "_rules", {}).items():
            source = inspect.getsource(fn)
            read = {node.args[0].value
                    for node in ast.walk(ast.parse(source.strip()))
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and node.args and isinstance(node.args[0], ast.Constant)}
            for fact in _facts_offered(agent, kind):
                if fact not in read and (kind, fact) not in allowed:
                    missed.append(f"{agent.agent_id}.{kind} ignores {fact!r}")
    assert not missed, "\n".join(missed)


# ----------------------------------------------- choosing which robot goes
def test_choosing_a_robot_for_a_job_is_a_decision_somebody_makes(eco):
    """
    The one judgement the project's own `brain.py` names as a canonical example
    of what a model might do better, and it was a tuple comparison inside the
    scheduler: nearest first, most charged to break the tie. Distance, charge
    and how urgent the job is do not reduce to a sort key.
    """
    assert "SUB-ASSIGNMENT" in eco.subagents
    assert eco.directory.parent_of("SUB-ASSIGNMENT") == "SCHEDULING"
    # The clerk costs each robot's errand; the scheduler chooses between them.
    chooser = eco.experts["SCHEDULING"]

    rule = rule_of(chooser, "choose_robot")
    options = ("R1", "R2")

    def chosen(**facts):
        return rule(Question(kind="choose_robot", asked_by="SCHEDULING",
                             prompt="?", options=options, facts=facts)).choice

    # All else equal, the nearer robot.
    assert chosen(robots={"R1": {"distance": 4, "battery": 80},
                          "R2": {"distance": 12, "battery": 80}},
                  priority="NORMAL") == "R1"
    # But not one that would have to charge half way through the errand.
    assert chosen(robots={"R1": {"distance": 4, "battery": 12},
                          "R2": {"distance": 12, "battery": 95}},
                  priority="URGENT") == "R2"


def test_the_scheduler_asks_rather_than_sorting(eco):
    """
    The clerk is consulted on every dispatch, and the decision it feeds is the
    scheduler's own. Both halves matter: a run in which SUB-ASSIGNMENT is never
    asked is the scheduler quietly going back to a sort key, and one in which
    SCHEDULING never decides is the judgement having slipped back down a level.
    """
    run(eco, 300)
    clerk = eco.subagents["SUB-ASSIGNMENT"]
    assert clerk.asked > 0, "the scheduler never consulted it"
    assert not clerk.decisions, "the clerk costs the errand; it does not choose"
    scheduler = eco.experts["SCHEDULING"]
    decisions = [d for d in scheduler.decisions if d["kind"] == "choose_robot"]
    assert decisions, "and the scheduler never made the choice"


def _ask(agent, content):
    from post_office.communication.message import Message, MessageType

    return Message(message_id="m-test", tick=0, sender=agent.parent_id,
                   receiver=agent.agent_id,
                   message_type=MessageType.SUBTASK_REQUEST, content=content)


def _facts_offered(agent, kind):
    """The fact names a `decide(kind, ...)` call in this agent passes."""
    import ast
    import inspect

    try:
        source = inspect.getsource(type(agent))
    except (OSError, TypeError):
        return set()
    tree = ast.parse(source)
    known = {"options", "correlation_id", "prompt", "deferral"}
    out = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "decide"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        if node.args[0].value != kind:
            continue
        out |= {kw.arg for kw in node.keywords
                if kw.arg and kw.arg not in known}
    return out
