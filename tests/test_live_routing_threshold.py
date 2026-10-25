"""
ROUTING on the live clock asks the model only about a block that is not clearing.

A model takes seconds -- 70 to 100 ticks at the page's 4x -- and the floor does
not stop for it. Blocks clear themselves within a tick or two of the sixth, so
every model answer about one arrived to a block that no longer existed and was
rejected as stale. On the live clock (`async_decisions`) a block younger than
`RoutingAgent.LIVE_PERSISTENT` (30) ticks is noted and answered by the rule; one
that has lasted that long goes to the model. Off the live clock (headless runs,
the studies, a step taken by hand) nothing changes: from the sixth tick the
model is asked, as before.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from post_office.agents.brain import Answer, Brain, DeterministicBrain
from post_office.agents.deferral import Deferral, is_pending
from post_office.agents.routing_agent import RoutingAgent
from post_office.config.settings import normal_config
from post_office.simulation.ecosystem import build


class _Model(Brain):
    """A model with both seams: inline (`answer`) and live (`start_consulting`)."""

    def __init__(self):
        self.fallback = DeterministicBrain()
        self.inline = 0
        self.started = []
        self.last_consultation = None

    def answer(self, question):
        self.inline += 1
        return Answer("WAIT", "model", source="crewai:fake")

    answer_consulting = lambda self, question, trigger: self.answer(question)  # noqa: E731

    def free_to_consult(self, question, trigger):
        return True

    def start_consulting(self, question, trigger):
        self.started.append((question, trigger))
        return {"q": question}

    def finish_consulting(self, handle, give_up=0):
        return None


class _Gate:
    def check(self, proposal):
        return SimpleNamespace(ok=True, stage="ok", violation="")


def _routing(live: bool):
    model = _Model()
    agent = RoutingAgent(brain=model)
    agent.rule_coverage = "authoritative"
    agent.async_decisions = live
    agent.llm_deadline_ticks = 120 if live else 0
    agent.world = SimpleNamespace(tick=50, activity=None, gate=_Gate(),
                                  logger=SimpleNamespace(emit=lambda *a, **k: None))
    return agent, model


def _block(agent, ticks, detour_extra=None, options=("WAIT", "YIELD", "REROUTE")):
    return agent.decide("resolve_block", "R1 is blocked by R4", options=options,
                        robot="R1", blocked_by="R4", ticks_blocked=ticks, direct_distance=4,
                        detour_extra=detour_extra, battery=80,
                        deferral=Deferral(key="R1", apply=lambda a: None))


@pytest.mark.parametrize("ticks,detour", [(6, None), (9, None), (27, None), (6, 10)],
                         ids=["sixth-tick", "ninth-tick", "27-ticks", "long-detour"])
def test_a_young_block_on_the_live_clock_is_the_rules(ticks, detour):
    agent, model = _routing(live=True)
    answer = _block(agent, ticks, detour)
    record = agent.decisions[-1]
    assert not is_pending(answer) and model.started == [] and model.inline == 0
    assert record["mode"] == "deterministic" and record["handling"] == "rule_sufficient"
    assert record["noted"] in ("failed", "conflict")


@pytest.mark.parametrize("ticks", [30, 45])
def test_a_block_that_is_not_clearing_goes_to_the_model_on_the_live_clock(ticks):
    agent, model = _routing(live=True)
    answer = _block(agent, ticks)
    assert is_pending(answer) and len(model.started) == 1
    assert model.started[0][1].condition == "still_blocked"


def test_off_the_live_clock_the_sixth_tick_still_asks_the_model():
    agent, model = _routing(live=False)
    answer = _block(agent, 6)
    assert answer.choice == "WAIT" and model.inline == 1
    assert agent.decisions[-1]["mode"] == "llm"


def test_a_live_normal_run_asks_routing_s_model_only_about_blocks_of_30_ticks():
    """Normal, ROUTING on a model, the live clock: no young block reaches the model."""
    model = _Model()
    eco = build(seed=1, config={**normal_config(), "async_decisions": True,
                                "llm_deadline_ticks": 120}, log_path=os.devnull,
                brains={"ROUTING": model})
    try:
        eco.start()
        for _ in range(1500):
            eco.step()
        summary = eco.summary()
    finally:
        eco.close()
    assert all(q.facts["ticks_blocked"] >= RoutingAgent.LIVE_PERSISTENT
               for q, _ in model.started)
    assert summary["tasks"].get("COMPLETED", 0) > 200
