"""
The Consultations pane's tokens column (2026-10-23).

Each consultation row carries its token use: `llm_calls`, and prompt and
completion tokens summed over every model call made for it (the owner's and
the peer's), as the transport audit reported them. Checked: the sums equal the
audit's own call rows (`/llm/calls`) for that consultation id, with and without
an exchange with the peer; the cell reads "P + C tok", is empty when no model
call was made and "-" for counts the server did not report; the page has the
column.
"""

from pathlib import Path

import pytest

from post_office.ui.live import consultation_row, consultation_tokens
from tests.consult_helpers import ask, scheduling_with_equally_placed_robots
from tests.fake_ollama import consultation_script

pytestmark = pytest.mark.usefixtures("quiet_crewai_console")
ROOT = Path(__file__).resolve().parents[1]


def _calls_for(eco, consultation_id):
    return [c for c in eco.crew.llm_calls(2000) if c["consultation_id"] == consultation_id]


def test_the_tokens_are_the_sum_of_the_consultations_own_calls(fake_ollama):
    fake_ollama.script(consultation_script("R2: its corridor is clear.",
                                           decide=lambda peer: peer.split(":")[0] or "R1"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    ask(sched)
    (row,) = eco.crew.recent()
    calls = _calls_for(eco, row["id"])
    assert len(calls) >= 2 and {c["phase"] for c in calls} >= {"owner", "peer"}
    assert row["llm_calls"] == len(calls)
    assert row["prompt_tokens"] == sum(c["prompt_tokens"] for c in calls) > 0
    assert row["completion_tokens"] == sum(c["completion_tokens"] for c in calls) > 0
    assert consultation_tokens(row) == f'{row["prompt_tokens"]} + {row["completion_tokens"]} tok'


def test_a_decision_without_an_exchange_counts_its_one_call(fake_ollama):
    fake_ollama.script(lambda body: "DECISION: R2")
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    assert ask(sched).choice == "R2"
    (row,) = eco.crew.recent()
    (call,) = _calls_for(eco, row["id"])
    assert row["llm_calls"] == 1
    assert (row["prompt_tokens"], row["completion_tokens"]) == (call["prompt_tokens"], call["completion_tokens"])


def test_the_cell_is_empty_without_a_call_and_a_dash_when_not_reported():
    assert consultation_tokens({"llm_calls": 0, "prompt_tokens": None, "completion_tokens": None}) == ""
    assert consultation_tokens({}) == ""
    assert consultation_tokens({"llm_calls": 1, "prompt_tokens": None, "completion_tokens": None}) == "-"
    assert consultation_tokens({"llm_calls": 2, "prompt_tokens": 410, "completion_tokens": None}) == "410 + - tok"
    html = consultation_row({"id": "CSL-0001", "tick": 7, "owner": "ROUTING", "peer": "SCHEDULING",
                             "outcome": "decided", "decision": "WAIT", "latency_ms": 290.4,
                             "llm_calls": 2, "prompt_tokens": 812, "completion_tokens": 61, "model": "qwen3:8b"})
    assert '<td class="t">290 ms</td>' in html and ">812 + 61 tok</td>" in html
    assert html.index("812 + 61 tok") < html.index("qwen3:8b")


def test_the_page_has_the_column():
    page = (ROOT / "post_office" / "ui" / "live.html").read_text(encoding="utf-8")
    head = page[page.index('<tbody id="consult-rows">') - 600:page.index('<tbody id="consult-rows">')]
    assert head.index("<th>latency</th>") < head.index(">tokens</th>") < head.index("<th>model</th>")
    assert "function consultTokens(r)" in page and "consultTokens(r)" in page.split("function consultRow(r)")[1][:900]
