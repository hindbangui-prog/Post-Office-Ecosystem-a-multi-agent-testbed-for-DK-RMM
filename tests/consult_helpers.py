"""
Shared set-up for the consultation tests: an ecosystem on the fake Ollama.

`scheduling_with_equally_placed_robots` builds a NORMAL ecosystem whose seven
experts are CrewBrains on the fake Ollama, starts it, and makes SCHEDULING's
`choose_robot` fire the `equally_placed` condition for the tests' question.

The tests ask `decide("choose_robot", ..., options=("R1", "R2"), task="T-1")`,
which carries no robot distances. SCHEDULING's own `equally_placed` reads
`able` and `robots` and, without them, stays silent, so the helper registers a
condition of the same name that says what such a question is: two robots the
walk cannot separate, a case the rule does not cover. The condition's name is
what the peer map is keyed by, so `("SCHEDULING", "choose_robot",
"equally_placed") -> "ROUTING"` applies exactly as it does in a run.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Tuple

from post_office.agents.reasoning import REASONS, Trigger
from post_office.config.settings import llm_brains, normal_config
from post_office.simulation.ecosystem import build


def settings_for(fake_ollama, **cfg):
    """The fake's settings with `cfg` (e.g. `consult_deadline_s=0.5`) replaced."""
    return dataclasses.replace(fake_ollama.settings, **cfg)


def active(eco):
    """
    Mark the facility active, for a test that asks a decision before any robot moves.

    The consultation tests put their question to a freshly built ecosystem at
    tick 0, when no robot holds an errand and the idle gate
    (`simulation.activity`) would answer it by the rule. They test the
    consultation, not the start of a run, so they start past the idle phase;
    `tests/test_idle_gate.py` tests the phase itself.
    """
    gate = getattr(eco, "activity", None)
    if gate is not None and gate.idle:
        gate.state = "active"
        gate.activated_at = eco.world.tick
    return eco


def ecosystem_on(fake_ollama, **cfg):
    """A started NORMAL ecosystem whose experts all run on the fake Ollama, past the idle phase."""
    eco = build(seed=1, config=normal_config(),
                brains=llm_brains(settings=settings_for(fake_ollama, **cfg), verify=False))
    eco.start()
    return active(eco)


def equally_placed(facts: Dict[str, Any]) -> Trigger:
    """Two robots offered and no walk given to tell them apart: the rule cannot choose."""
    return Trigger(REASONS.CONTENTION, "two robots no walk separates",
                   rule_sufficient=False)


def scheduling_with_equally_placed_robots(fake_ollama, **cfg) -> Tuple[Any, Any]:
    eco = ecosystem_on(fake_ollama, **cfg)
    sched = eco.agents["SCHEDULING"]
    sched.triggers.register("choose_robot", equally_placed)
    return eco, sched


def ask(sched, options=("R1", "R2")):
    """The tests' question to SCHEDULING."""
    return sched.decide("choose_robot", "Which robot takes T-1?", options=options, task="T-1")


def events(eco, prefix: str = "") -> List[Any]:
    """Every event the ecosystem kept whose topic starts with `prefix`, in `seq` order."""
    return sorted((e for e in eco.logger.recent(limit=100000) if e.topic.startswith(prefix)),
                  key=lambda e: e.seq)
