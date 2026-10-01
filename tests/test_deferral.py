"""The surviving part of the source's asynchronous layer: telemetry words and `Deferral`."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from post_office.agents.brain import Answer  # noqa: E402
from post_office.agents.deferral import (DETERMINISTIC, LLM_ACCEPTED, LLM_FAILED,  # noqa: E402
                                         LLM_PENDING, LLM_REJECTED, LLM_TIMEOUT,
                                         PENDING_LLM_DECISION, Deferral, is_pending)


def test_is_pending_reads_the_answer_source():
    assert is_pending(Answer("x", source="llm_pending"))
    assert not is_pending(Answer("x"))
    assert not is_pending(None)


def test_deferral_defaults_admit_and_ignore():
    d = Deferral("k", apply=lambda a: None)
    assert d.key == "k"
    assert d.still_valid(Answer("x")) == ""
    assert d.reevaluate("why") is None


def test_status_words_are_the_source_literals():
    assert (DETERMINISTIC, LLM_PENDING, LLM_ACCEPTED, LLM_REJECTED, LLM_FAILED, LLM_TIMEOUT) == (
        "deterministic", "llm_pending", "llm_accepted", "llm_rejected", "llm_failed", "llm_timeout")
    assert PENDING_LLM_DECISION == "PENDING_LLM_DECISION"
