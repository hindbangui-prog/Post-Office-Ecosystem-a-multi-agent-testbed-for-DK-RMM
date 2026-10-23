"""
The owner's instruction asks it to consult its peer (2026-10-23).

With "You may ask" qwen3:8b decided alone in most consultations (78% in the P7
model-assisted run on seed 11322), so the Consultations pane showed no question
and no answer. The instruction now asks the owner to put one question (or one
delegation) to its peer before deciding. Checked: the sentence is there when a
peer is on offer and absent otherwise; the DECISION demand stays the last line
(the system-override campaign inserts its block before it); a consultation run
through the service carries the new sentence and its exchange.
"""

import pytest

from post_office.agents.brain import Question
from post_office.crew.consultation import DECISION_DEMAND, describe
from tests.consult_helpers import ask, scheduling_with_equally_placed_robots
from tests.fake_ollama import consultation_script

QUESTION = Question(kind="choose_robot", asked_by="SCHEDULING", prompt="Which robot takes T-0001?",
                    options=("R1", "R2"), facts={"task": "T-0001"})


def test_with_a_peer_the_owner_is_asked_to_consult_it_once():
    text = describe(QUESTION, "ROUTING")
    assert "Before you decide, ask " in text and "use one of the two, once" in text
    assert "`Ask question to coworker`" in text and "`Delegate work to coworker`" in text
    assert "the decision is yours" in text and "You may ask" not in text
    assert text.rstrip("\n").split("\n")[-1] == DECISION_DEMAND


def test_without_a_peer_there_is_nobody_to_ask():
    text = describe(QUESTION, None)
    assert "Before you decide" not in text and "coworker" not in text
    assert text.rstrip("\n").split("\n")[-1] == DECISION_DEMAND


@pytest.mark.usefixtures("quiet_crewai_console")
def test_a_consultation_carries_the_sentence_and_its_exchange(fake_ollama):
    fake_ollama.script(consultation_script("R2: its corridor is clear.",
                                           decide=lambda peer: peer.split(":")[0] or "R1"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    ask(sched)
    assert "Before you decide, ask " in sched.brain.last_prompt
    (row,) = eco.crew.recent()
    assert row["request"] and row["response"] == "R2: its corridor is clear."
    assert row["llm_calls"] == 3                      # owner, peer, owner
