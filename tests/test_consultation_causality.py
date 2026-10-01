"""
The acceptance test of the project: the peer's reply causes the owner's decision.

The fake Ollama answers the peer with one of two scripted replies and has the
owner decide on whatever the tool message it was handed says. If the peer's
text did not reach the owner's loop through CrewAI's tool call, both
parametrisations could not pass.
"""

import json

import pytest

from tests.consult_helpers import scheduling_with_equally_placed_robots
from tests.fake_ollama import consultation_script

pytestmark = pytest.mark.usefixtures("quiet_crewai_console")


@pytest.mark.parametrize("peer_reply, expected", [
    ("R2: its corridor is clear; R1's path crosses the dock queue.", "R2"),
    ("R1: its corridor is clear; R2's path crosses the dock queue.", "R1"),
])
def test_peer_reply_changes_owner_decision(fake_ollama, peer_reply, expected):
    fake_ollama.script(consultation_script(peer_reply, decide=lambda peer: "R2" if peer.startswith("R2") else "R1"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    answer = sched.decide("choose_robot", "Which robot takes T-1?", options=("R1", "R2"), task="T-1")
    assert answer.choice == expected and answer.source == "crewai:qwen3:8b"
    owner_follow_up = [r for r in fake_ollama.requests if any(m["role"] == "tool" for m in r["messages"])][-1]
    assert peer_reply in json.dumps(owner_follow_up["messages"])
    peer_call = [r for r in fake_ollama.requests if "consulted by Scheduling" in json.dumps(r["messages"])][0]
    assert not peer_call.get("tools")
