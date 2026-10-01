from post_office.discussion.prompts import (clean, decision_prompt, opening_prompt,
                                            parse_decision, peer_prompt)

OPTIONS = ("R1", "R2", "R3")


def test_a_decision_line_is_read_against_the_allowed_answers():
    assert parse_decision("R2 is fine.\nDECISION: R2", OPTIONS) == (True, "R2")
    assert parse_decision("decision: `r3`.", OPTIONS) == (True, "R3")


def test_the_last_decision_line_counts():
    assert parse_decision("DECISION: R1\nactually\nDECISION: R2", OPTIONS) == (True, "R2")


def test_an_answer_off_the_list_is_not_invented():
    assert parse_decision("DECISION: R9", OPTIONS) == (True, None)


def test_prose_without_a_decision_line_is_no_decision():
    assert parse_decision("I would go with R2.", OPTIONS) == (False, None)


def test_non_string_options_come_back_as_themselves():
    assert parse_decision("DECISION: 2", (0, 1, 2, 3)) == (True, 2)


def test_clean_drops_reasoning_and_clips():
    assert clean("<think>long</think> Hello ") == "Hello"
    assert len(clean("x" * 5000)) == 600


def test_prompts_carry_what_each_side_needs():
    opening = opening_prompt("SCHEDULING", "RESOURCE", "choose_robot",
                             "Which robot?", {"slack": 40}, OPTIONS, "nobody able")
    assert "RESOURCE" in opening and "slack: 40" in opening and "- R2" in opening
    assert "DECISION" in opening          # told NOT to decide yet
    turns = [("SCHEDULING", "I lean to R2. Batteries?")]
    reply = peer_prompt("RESOURCE", "SCHEDULING", "choose_robot",
                        {"robots": {"R2": {"battery": 80}}}, turns)
    assert "I lean to R2" in reply and "battery" in reply and "RESOURCE" in reply
    final = decision_prompt("SCHEDULING", "RESOURCE", "choose_robot", {"slack": 40},
                            OPTIONS, turns + [("RESOURCE", "R2 has 80%.")], may_ask=False)
    assert "R2 has 80%." in final and "DECISION: <one allowed answer>" in final
    assert "ask one short question" not in final
    asking = decision_prompt("SCHEDULING", "RESOURCE", "choose_robot", {}, OPTIONS,
                             turns, may_ask=True)
    assert "ask one short question" in asking


def test_a_long_turn_still_has_its_decision_read():
    text = "I weighed it carefully. " * 60 + "\nDECISION: R2"
    assert len(text) > 600
    assert parse_decision(text, OPTIONS) == (True, "R2")


def test_markdown_around_the_decision_is_tolerated():
    assert parse_decision("**DECISION:** R2", OPTIONS) == (True, "R2")
    assert parse_decision("DECISION: **R2**", OPTIONS) == (True, "R2")
    assert parse_decision("- DECISION: `R3`", OPTIONS) == (True, "R3")


def test_a_decision_with_a_short_reason_after_it_is_read():
    assert parse_decision("DECISION: R2 (most charge)", OPTIONS) == (True, "R2")
    assert parse_decision("DECISION: R2, because it is closest", OPTIONS) == (True, "R2")


def test_hidden_reasoning_is_not_read_as_the_decision():
    assert parse_decision("<think>DECISION: R3</think>\nDECISION: R1", OPTIONS) == (True, "R1")


def test_reasoning_with_only_a_closing_tag_is_not_part_of_the_turn():
    # A thinking-only model (qwen3:4b-thinking-2507) has its template open the
    # <think> block, so the reply carries only the closing tag.
    reply = "Okay, let me think. Maybe DECISION: R3?\n</think>\n\nR2 has the charge."
    assert clean(reply) == "R2 has the charge."
    assert parse_decision(reply, OPTIONS) == (False, None)
    assert parse_decision(reply + "\nDECISION: R2", OPTIONS) == (True, "R2")


def test_a_turn_cut_off_inside_its_reasoning_shows_nothing_of_it():
    assert clean("Hello.\n<think>and then I would") == "Hello."
