"""
DK-RMM sees a consultation as ordinary expert traffic (spec 12 and 13).

The monitor is attached exactly as a run attaches it, before the
consultation. Afterwards its window holds the three `CONSULT_*` messages and
the `decision`, an assessment runs over it, and the indicators count the
consultation as three messages between two experts: never as delegations,
which keep their expert -> sub-agent meaning, whatever the request's
`interaction_type` says.
"""

import pytest

from post_office.dkrmm import DKRMM, compute_indicators
from tests.consult_helpers import ask, scheduling_with_equally_placed_robots
from tests.fake_ollama import consultation_script

pytestmark = pytest.mark.usefixtures("quiet_crewai_console")

CONSULT_TYPES = ["CONSULT_REQUEST", "CONSULT_RESPONSE", "CONSULT_CLOSE"]


def _delegating(body):
    """The owner delegates rather than asks; everything else as in a plain consultation."""
    tools = body.get("tools") or []
    if tools and not any(m.get("role") == "tool" for m in body["messages"]):
        delegate = next(t for t in tools if "delegate" in t["function"]["name"])
        return {"tool": delegate["function"]["name"],
                "args": {"task": "Check both corridors.", "context": "T-1 is waiting.",
                         "coworker": "Routing"}}
    return consultation_script("R2: corridor clear.", decide=lambda peer: "R2")(body)


def _consult_messages(seen):
    return [e for e in seen if e.topic == "message"
            and str(e.detail.get("message_type", "")).startswith("CONSULT_")]


@pytest.mark.parametrize("interaction_type", ["question", "delegation"])
def test_the_monitor_sees_the_consultation_as_messages(fake_ollama, interaction_type):
    fake_ollama.script(_delegating if interaction_type == "delegation" else
                       consultation_script("R2: corridor clear.", decide=lambda peer: "R2"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    monitor = DKRMM(eco).attach()
    answer = ask(sched)
    assert answer.choice == "R2" and answer.source == "crewai:qwen3:8b"

    seen = list(monitor._events)
    messages = _consult_messages(seen)
    assert [e.detail["message_type"] for e in messages] == CONSULT_TYPES
    assert [(e.actor, e.target) for e in messages] == [
        ("SCHEDULING", "ROUTING"), ("ROUTING", "SCHEDULING"), ("SCHEDULING", "ROUTING")]
    assert messages[0].detail["content"]["interaction_type"] == interaction_type
    decisions = [e for e in seen if e.topic == "decision"
                 and e.detail.get("consultation_id") == "CSL-0001"]
    assert len(decisions) == 1 and decisions[0].actor == "SCHEDULING"

    now = eco.world.tick
    assessment = monitor.assess(now)
    assert assessment is not None and assessment.tick == now
    assert monitor.current is assessment

    # The consultation alone: three messages between two experts, no
    # delegation down the hierarchy, no answer coming back up it.
    ours = [e for e in seen if e.correlation_id == "CSL-0001"
            or e.detail.get("consultation_id") == "CSL-0001"]
    alone = compute_indicators(ours, ticks=1, roster=len(eco.agents))
    assert alone.counts["messages"] == 3
    assert alone.counts["delegations"] == 0 and alone.counts["tool_calls"] == 0
    assert alone.delegation_frequency == 0.0

    # The window the assessment read, with and without the consultation:
    # it adds three messages and not one delegation.
    window = [e for e in seen if now - monitor.window <= int(e.tick) <= now]
    without = [e for e in window if e not in messages]
    ticks = min(monitor.window, max(1, now))
    full = compute_indicators(window, ticks=ticks, roster=len(eco.agents))
    rest = compute_indicators(without, ticks=ticks, roster=len(eco.agents))
    assert full.counts["messages"] - rest.counts["messages"] == 3
    assert full.counts["delegations"] == rest.counts["delegations"]
    assert full.counts["tool_calls"] == rest.counts["tool_calls"]
    assert assessment.indicators.counts["messages"] == full.counts["messages"]
    assert assessment.indicators.counts["delegations"] == full.counts["delegations"]
    monitor.close()
    eco.close()
