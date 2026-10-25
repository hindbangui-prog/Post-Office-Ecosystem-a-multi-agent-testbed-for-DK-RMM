"""
The live page says what became of each model answer.

A consultation closes when the model replies; on the live clock the expert may
act on that reply many ticks later, or not at all because its task or robot has
gone. The expert writes the outcome onto the consultation (`used`, through
`BaseAgent._note_outcome` -> `CrewBrain.note_outcome` ->
`ConsultationService.note_outcome`), the Consultations pane shows it in its
"used?" column, and each expert's card on the roster shows its last one.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from post_office.agents.base import BaseAgent
from post_office.agents.brain import Answer, DeterministicBrain
from post_office.agents.deferral import Deferral
from post_office.agents.reasoning import REASONS, Trigger
from post_office.ui.live import consultation_row, used_text

ROOT = Path(__file__).resolve().parent.parent


class _Model:
    """A slow model behind the async seam that also reports consultations, as CrewBrain does."""

    def __init__(self, choice: str) -> None:
        self.fallback = DeterministicBrain()
        self.choice = choice
        self.notes: List[tuple] = []
        self.last_consultation = None
        self.released = False
        self.n = 0

    def answer(self, question):  # pragma: no cover - the live path never asks inline
        raise AssertionError("asked inline")

    def free_to_consult(self, question, trigger):
        return True

    def start_consulting(self, question, trigger):
        self.n += 1
        return {"q": question, "id": f"CSL-{self.n:04d}"}

    def finish_consulting(self, handle, give_up=0):
        if give_up:
            self.last_consultation = {"consultation_id": handle["id"], "peer": "", "turns": 0}
            return Answer("rule", "the rule's [fallback: no decision within the deadline]",
                          source="fallback")
        if not self.released:
            return None
        self.last_consultation = {"consultation_id": handle["id"], "peer": "", "turns": 0}
        return Answer(self.choice, "model", source="crewai:qwen3:8b")

    def note_outcome(self, consultation_id, used, detail="", choice=None, tick=None):
        self.notes.append((consultation_id, used, detail, choice, tick))


class _Gate:
    def check(self, proposal):
        if proposal.choice == "taken":
            return SimpleNamespace(ok=False, stage="state", violation="taken is no longer free")
        return SimpleNamespace(ok=True, stage="ok", violation="")


class _Expert(BaseAgent):
    def __init__(self, brain):
        super().__init__("EXPERT", "test expert", brain=brain)

    def install_rules(self):
        rules = self.rules()
        if rules is not None:
            rules.register("pick", lambda q: Answer("rule", "the rule's"))

    def install_triggers(self):
        self.triggers.register("pick", lambda facts: Trigger(REASONS.AMBIGUITY, "hard"))


def _run(choice: str, valid: str = "", deadline: int = 0, release: bool = True):
    model = _Model(choice)
    agent = _Expert(model)
    agent.async_decisions, agent.llm_deadline_ticks = True, deadline
    agent.world = SimpleNamespace(tick=10, logger=SimpleNamespace(emit=lambda *a, **k: None),
                                  gate=_Gate(), activity=None)
    agent.decide("pick", "which?", options=("rule", "model", "taken"), correlation_id="P-1",
                 deferral=Deferral(key="P-1", apply=lambda a: None,
                                   still_valid=lambda a: valid))
    model.released = release
    agent.world.tick = 30
    agent._collect_decisions()
    return model.notes


def test_an_applied_answer_is_noted_with_its_tick_and_choice():
    assert _run("model") == [("CSL-0001", "applied", "", "model", 30)]


def test_an_answer_whose_subject_has_gone_is_noted_with_the_reason():
    assert _run("model", valid="R1 is no longer free") == [
        ("CSL-0001", "stale", "R1 is no longer free", "model", 30)]


def test_a_refusal_at_the_gate_is_noted_with_the_violation():
    (note,) = _run("taken")
    assert note[1] == "refused" and note[2] == "taken is no longer free"


def test_a_model_past_its_deadline_is_noted_as_too_late():
    (note,) = _run("model", deadline=5, release=False)
    assert note[1] == "deadline" and note[3] == "rule"


def test_the_used_column_text():
    base: Dict[str, Any] = {"used_choice": "R1", "used_tick": 171, "used_detail": "why"}
    assert used_text({}) == "deciding…"
    assert used_text({**base, "used": "applied"}) == "applied t171 → R1"
    assert used_text({**base, "used": "stale"}) == "not applied: why"
    assert used_text({**base, "used": "refused"}) == "refused by the gate: why"
    assert used_text({**base, "used": "deadline"}) == "too late: rule's R1 used"
    assert used_text({**base, "used": "rule"}) == "rule's R1 used (why)"
    row = consultation_row({"id": "CSL-0001", "tick": 51, "owner": "SCHEDULING", "peer": "",
                            "outcome": "decided", "decision": "R1", "used": "applied",
                            "used_choice": "R1", "used_tick": 131})
    assert 'class="used used-applied"' in row and ">applied t131 → R1</td>" in row
    assert row.index("decided") < row.index("applied t131")


def test_the_page_has_the_column_and_the_roster_shows_the_last_outcome():
    page = (ROOT / "post_office" / "ui" / "live.html").read_text(encoding="utf-8")
    head = page[page.index('<tbody id="consult-rows">') - 900:page.index('<tbody id="consult-rows">')]
    assert head.index("<th>outcome</th>") < head.index(">used?</th>") < head.index("<th>latency</th>")
    assert "usedCell(r)" in page.split("function consultRow(r)")[1][:900]
    assert "function usedText(r)" in page and "LAST_USED[r.owner] = r" in page
    assert "since t${since[id]}" in page                      # how long it has been waiting
