"""
What the charge point contest is allowed to know about the work.

Four points, five robots: somebody goes without, and RESOURCE decides who.
Until now it decided on two facts -- how low the robot was, and whether it was
carrying anything at all. `carrying` was a parcel id, and nothing ever looked
the parcel up, so a robot holding a paid URGENT parcel argued for the last
point on exactly the same terms as one holding an ordinary one.

That is the hole the paid-service work left open. EXPRESS and URGENT cost the
sender money and jump the dispatch queue, and then a contested plug quietly
treated them as equals again.

The boundary this stays inside: RESOURCE may reason about, allocate, refuse
and negotiate access to resources. It may not change a battery level, move a
robot, invent a point that is not free, or thin the safety margin because a
parcel is expensive. Priority decides *who gets a free point first* and
nothing else -- these tests pin that, and the stranding rules are left exactly
where they were.
"""

from __future__ import annotations

import pytest

from post_office.agents.brain import Question
from post_office.communication.message import Message, MessageType
from post_office.simulation import build


@pytest.fixture
def eco():
    made = build(seed=5, run_id="resource-priority")
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


def ask(rule, options, **facts):
    return rule(Question(kind="allocate_charge_point", asked_by="RESOURCE",
                         prompt="?", options=tuple(options), facts=facts))


def errand(mail_class, ticks_to_deadline=None):
    return {"class": mail_class, "ticks_to_deadline": ticks_to_deadline}


STATIONS = {"CP-1": {"distance": 3}, "CP-2": {"distance": 40}}


# ------------------------------------------------------- the contest itself
def test_an_ordinary_errand_yields_the_last_point_to_an_urgent_one(eco):
    """
    The defect. Both robots are laden, so the old rule never even reached the
    yielding branch -- it went straight to "nearest point wins" and the robot
    that happened to be closer took it, whatever either of them was carrying.
    """
    rule = rule_of(eco.experts["RESOURCE"], "allocate_charge_point")

    answer = ask(rule, ("CP-1", "WAIT"),
                 battery=40, carrying="P-0001", errand=errand("NORMAL"),
                 stations=STATIONS,
                 rivals={"R2": {"battery": 20, "carrying": "P-0002",
                                "errand": errand("URGENT")}})

    assert answer.choice == "WAIT", (
        "an urgent errand, lower than this one, needs the point more")
    assert "URGENT" in answer.reason or "R2" in answer.reason


def test_a_laden_urgent_robot_is_never_made_to_wait_for_an_ordinary_one(eco):
    """The same contest from the other side. It must not be symmetric."""
    rule = rule_of(eco.experts["RESOURCE"], "allocate_charge_point")

    answer = ask(rule, ("CP-1", "WAIT"),
                 battery=40, carrying="P-0002", errand=errand("URGENT"),
                 stations=STATIONS,
                 rivals={"R2": {"battery": 20, "carrying": "P-0001",
                                "errand": errand("NORMAL")}})

    assert answer.choice == "CP-1", "the urgent errand takes the point"


def test_a_rival_that_outranks_but_is_no_lower_does_not_get_the_point(eco):
    """
    Class orders the queue; it does not override the reason for the queue.
    Yielding to a comfortable urgent robot is how this robot strands itself
    holding somebody else's parcel.
    """
    rule = rule_of(eco.experts["RESOURCE"], "allocate_charge_point")

    answer = ask(rule, ("CP-1", "WAIT"),
                 battery=15, carrying="P-0001", errand=errand("NORMAL"),
                 stations=STATIONS,
                 rivals={"R2": {"battery": 80, "carrying": "P-0002",
                                "errand": errand("URGENT")}})

    assert answer.choice == "CP-1", (
        "the urgent robot has plenty; this one is nearly flat")


def test_the_deadline_separates_two_errands_of_the_same_class(eco):
    """
    Within a class the promise is the only thing left to go on. Two ordinary
    parcels, one about to be late.
    """
    rule = rule_of(eco.experts["RESOURCE"], "allocate_charge_point")

    answer = ask(rule, ("CP-1", "WAIT"),
                 battery=40, carrying="P-0001",
                 errand=errand("NORMAL", ticks_to_deadline=900),
                 stations=STATIONS,
                 rivals={"R2": {"battery": 20, "carrying": "P-0002",
                                "errand": errand("NORMAL",
                                                 ticks_to_deadline=30)}})

    assert answer.choice == "WAIT", "the one about to break its promise goes first"


def test_an_idle_robot_still_yields_to_any_laden_one(eco):
    """
    The rule that was already there, and has to survive the change: a robot
    that is merely low and idle can wait for the next point to come free.
    """
    rule = rule_of(eco.experts["RESOURCE"], "allocate_charge_point")

    answer = ask(rule, ("CP-1", "WAIT"),
                 battery=60, carrying="", errand=None,
                 stations=STATIONS,
                 rivals={"R2": {"battery": 12, "carrying": "P-0002",
                                "errand": errand("NORMAL")}})

    assert answer.choice == "WAIT", "laden and nearly flat beats idle and low"


def test_nearest_still_wins_between_equals(eco):
    """Two ordinary errands, nothing to choose between them but the walk."""
    rule = rule_of(eco.experts["RESOURCE"], "allocate_charge_point")

    answer = ask(rule, ("CP-1", "CP-2", "WAIT"),
                 battery=30, carrying="P-0001", errand=errand("NORMAL"),
                 stations=STATIONS,
                 rivals={"R2": {"battery": 28, "carrying": "P-0002",
                                "errand": errand("NORMAL")}})

    assert answer.choice == "CP-1", "three cells away, not forty"


# ------------------------------------------- the facts the contest is given
def test_the_sub_agent_says_what_each_robot_is_carrying_the_class_of(eco):
    """
    Sub-agents report, agents decide. The class of the parcel is a fact about
    the floor, so SUB-CHARGING looks it up; what to do about it is RESOURCE's
    call. Without this the rule above has nothing to read.
    """
    run(eco, 300)
    resource = eco.experts["RESOURCE"]
    sub = eco.subagents["SUB-CHARGING"]

    robot = next((r for r in eco.fleet.all() if r.carrying), None)
    if robot is None:                        # nothing in flight at this tick
        pytest.skip("no robot was carrying anything at tick 300")

    report = sub.perform(Message(
        message_id="m-test", tick=sub.tick, sender="RESOURCE",
        receiver="SUB-CHARGING", message_type=MessageType.SUBTASK_REQUEST,
        content={"operation": "request_station", "robot_id": robot.robot_id}))

    assert report is not None
    if not report.get("ok"):                 # every point busy; still a fact
        pytest.skip(report.get("reason", "no point available"))

    assert report.get("errand"), "it reported no errand for a laden robot"
    assert report["errand"]["class"] in ("NORMAL", "EXPRESS", "URGENT")


def test_the_contest_is_asked_with_the_class_in_hand(eco):
    """
    The fact has to survive the trip from the sub-agent to the decision. A
    fact reported and then dropped on the floor of the agent is the failure
    mode the standing AST test exists to catch.
    """
    resource = eco.experts["RESOURCE"]
    import ast
    import inspect

    source = inspect.getsource(type(resource))
    tree = ast.parse(source.lstrip())
    offered = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "decide"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "allocate_charge_point"):
            offered = {kw.arg for kw in node.keywords if kw.arg}

    assert "errand" in offered, "RESOURCE never passes the errand to the rule"
