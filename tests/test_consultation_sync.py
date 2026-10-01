"""
One consultation, start to finish, inside one `decide` call and one tick (spec 8).

The owner's CrewAI loop asks its peer through the tool, the peer's own model
call answers, the owner decides, and only then does `decide` write its
`decision` event: every step of the exchange is in the log, in order, under the
tick the decision was taken in, and the clock has not moved.
"""

import pytest

from tests.consult_helpers import ask, events, scheduling_with_equally_placed_robots
from tests.fake_ollama import consultation_script

pytestmark = pytest.mark.usefixtures("quiet_crewai_console")

ORDER = ("consult_opened", "consult_question", "llm_call:peer", "consult_response",
         "consult_closed", "decision")


def _label(event):
    if event.topic == "llm_call":
        return f"llm_call:{event.detail['phase']}"
    return event.topic


def test_consultation_happens_inside_decide_in_order(fake_ollama):
    fake_ollama.script(consultation_script("R2: its corridor is clear.",
                                           decide=lambda peer: peer.split(":")[0] or "R1"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    tick = eco.world.tick

    answer = ask(sched)

    assert eco.world.tick == tick
    assert answer.choice == "R2" and answer.source == "crewai:qwen3:8b"
    trail = [e for e in events(eco) if e.topic.startswith("consult_")
             or e.topic in ("llm_call", "decision")]
    print("\nordered events:")
    for e in trail:
        print(f"  seq={e.seq} tick={e.tick} {_label(e)} {e.actor} -> {e.target or '-'}")
    labels = [_label(e) for e in trail]
    assert labels == ["consult_opened", "llm_call:owner", "consult_question", "llm_call:peer",
                      "consult_response", "llm_call:owner", "consult_closed", "decision"]
    seq = {label: next(e.seq for e in trail if _label(e) == label) for label in ORDER}
    assert [seq[label] for label in ORDER] == sorted(seq.values())
    assert {e.tick for e in trail} == {tick}

    decision = trail[-1]
    opened = trail[0]
    consultation_id = opened.detail["consultation_id"]
    assert consultation_id == "CSL-0001"
    assert decision.detail["path"].startswith("llm/")
    assert decision.detail["source"] == "crewai:qwen3:8b"
    assert decision.detail["consultation_id"] == consultation_id
    assert decision.detail["peer"] == "ROUTING" and decision.detail["turns"] == 2
    assert decision.detail["call_id"] == opened.detail["decision_id"]
    closed = next(e for e in trail if e.topic == "consult_closed")
    assert closed.detail["outcome"] == "decided" and closed.detail["choice"] == "R2"


def test_service_summary_and_history(fake_ollama):
    fake_ollama.script(consultation_script("R1: nearer the dock.",
                                           decide=lambda peer: peer.split(":")[0] or "R2"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    ask(sched)
    (row,) = eco.crew.recent()
    assert (row["id"], row["owner"], row["peer"], row["kind"], row["condition"]) == (
        "CSL-0001", "SCHEDULING", "ROUTING", "choose_robot", "equally_placed")
    assert row["request"] and row["response"] == "R1: nearer the dock."
    assert (row["decision"], row["outcome"], row["model"]) == ("R1", "decided", "qwen3:8b")
    summary = eco.llm_summary()
    assert summary["consultations"] == 1
    assert summary["by_pair"] == {"SCHEDULING->ROUTING": 1}
    assert summary["outcomes"] == {"decided": 1}
    assert summary["mean_latency_ms"] > 0
    calls = eco.crew.llm_calls()
    assert [(c["agent_id"], c["phase"]) for c in calls] == [
        ("SCHEDULING", "owner"), ("ROUTING", "peer"), ("SCHEDULING", "owner")]
    assert all(c["consultation_id"] == "CSL-0001" and c["status"] == 200 for c in calls)
    stats = sched.brain.stats()
    assert (stats["calls"], stats["consultations"], stats["questions"]) == (1, 1, 1)
    assert stats["reachable"] is True and stats["fallbacks"] == 0
    assert sched.brain.last_prompt.startswith("Decision: choose_robot")
    assert "DECISION: <one allowed answer>" in sched.brain.last_prompt


def test_installing_the_crew_is_logged_and_one_audit_per_ecosystem(fake_ollama):
    eco, _ = scheduling_with_equally_placed_robots(fake_ollama)
    (llm,) = [e for e in events(eco) if e.topic == "llm"]
    assert llm.category == "simulation"
    assert llm.detail["backend"] == "ollama" and llm.detail["model"] == "qwen3:8b"
    assert llm.detail["base_url"] == fake_ollama.base_url
    assert len(llm.detail["agents"]) == 7
    shared = {id(a.brain.crew_agent.llm) for a in eco.agents.values()
              if hasattr(a.brain, "crew_agent")}
    assert len(shared) == 1
    first_audit = eco.crew.audit
    again = eco.reset()
    assert again.crew is not None and again.crew.audit is not first_audit
    assert all(a.brain.service is again.crew for a in again.agents.values()
               if hasattr(a.brain, "crew_agent"))
    again.close()


def test_rules_only_ecosystem_installs_nothing():
    from post_office.config.settings import normal_config
    from post_office.simulation.ecosystem import build

    eco = build(seed=1, config=normal_config())
    assert eco.crew is None and eco.llm_summary() == {}
    assert [e for e in events(eco) if e.topic == "llm"] == []
