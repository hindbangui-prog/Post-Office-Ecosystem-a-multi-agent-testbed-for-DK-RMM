"""A fired trigger says which declared condition produced it."""
from post_office.agents.reasoning import REASONS, Trigger, TriggerSet


def test_check_names_the_condition_that_fired():
    triggers = TriggerSet()

    def quiet(facts):
        return None

    def crowded(facts):
        return Trigger(REASONS.CONTENTION, "two robots")

    triggers.register("pick", quiet)
    triggers.register("pick", crowded)
    assert triggers.check("pick", {}).condition == "crowded"
    assert [t.condition for t in triggers.fired("pick", {})] == ["crowded"]


def test_a_condition_that_names_itself_keeps_its_name():
    triggers = TriggerSet()

    def outer(facts):
        return Trigger(REASONS.CONTENTION, "x", condition="inner")

    triggers.register("pick", outer)
    assert triggers.check("pick", {}).condition == "inner"


def test_the_name_stays_out_of_the_record_and_out_of_equality():
    named = Trigger(REASONS.CONTENTION, "x", condition="crowded")
    assert named.as_dict() == {"reason": REASONS.CONTENTION, "detail": "x",
                               "rule_sufficient": None}
    assert named == Trigger(REASONS.CONTENTION, "x")
