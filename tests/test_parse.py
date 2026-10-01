"""How a question is put to a CrewAI expert, and how its reply is read back."""

from post_office.agents.brain import Question
from post_office.crew.parse import last_visible_line, parse_choice, render


def _question():
    return Question(kind="choose_robot", asked_by="SCHEDULING",
                    prompt="Which robot should take task T7?",
                    options=["R1", "R2"], facts={"task": "T7", "battery_R1": 40})


def test_render_has_the_source_layout():
    text = render(_question())
    assert "Decision: choose_robot" in text
    assert "Allowed answers:" in text
    assert text == ("Decision: choose_robot\n"
                    "Which robot should take task T7?\n\n"
                    "Facts:\n- battery_R1: 40\n- task: T7\n\n"
                    "Allowed answers:\n- R1\n- R2\n")


def test_render_marks_empty_facts_and_options():
    text = render(Question(kind="k", asked_by="PLANNER", prompt="p"))
    assert "Facts:\n- none\n" in text
    assert "Allowed answers:\n- any short string\n" in text


def test_think_block_is_stripped():
    assert parse_choice("<think>R1?</think>\nDECISION: R2", ["R1", "R2"]) == "R2"


def test_an_answer_off_the_list_is_none():
    assert parse_choice("I pick R3", ["R1", "R2"]) is None


def test_first_line_is_matched_case_insensitively():
    assert parse_choice("r1.", ["R1", "R2"]) == "R1"


def test_the_option_object_is_returned():
    class Opt:
        def __init__(self, name):
            self.name = name

        def __str__(self):
            return self.name

    options = [Opt("EXPRESS"), Opt("STANDARD")]
    assert parse_choice("express\nit is late", options) is options[0]


def test_token_and_unique_mention_heuristics():
    assert parse_choice("**R2**, it has most charge", ["R1", "R2"]) == "R2"
    assert parse_choice("Well.\nOn balance R1 is better.", ["R1", "R2"]) == "R1"
    assert parse_choice("Well.\nR1 or R2, hard to say.", ["R1", "R2"]) is None


def test_a_decision_line_off_the_list_is_not_rescued_by_its_reasoning():
    assert parse_choice("R1 looked tempting.\nDECISION: R3", ["R1", "R2"]) is None


def test_an_empty_or_reasoning_only_reply_is_none():
    assert parse_choice("", ["R1"]) is None
    assert parse_choice("<think>R1</think>", ["R1"]) is None


def test_last_visible_line():
    assert last_visible_line("<think>x</think>\nR1\nbecause it is close\n\n") == \
        "because it is close"
    assert last_visible_line("<think>only thought</think>") == ""
