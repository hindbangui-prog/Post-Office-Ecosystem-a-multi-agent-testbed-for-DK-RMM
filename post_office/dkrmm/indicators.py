"""
The twelve behavioural indicators, computed off the event stream.

The model names twelve: message frequency, interaction density, delegation
frequency, retry frequency, guardrail events, tool-call frequency, task
switching, execution latency, agent coupling, behavioural similarity,
persistence of deviation, and propagation across agents. What follows is each
of them defined against what this facility actually emits, because an
indicator that cannot be computed from the log is not an indicator, it is a
wish.

Three properties are deliberate and worth stating, because they are what make
the numbers comparable across runs of different lengths and loads:

*Rates, not counts.* Everything that can be a rate is divided by the ticks in
the window. A count rises when you watch for longer, which would make the
length of the window an indicator in its own right.

*Content-agnostic.* Nothing here reads what a parcel is or where it is going.
The model is about the shape of collective behaviour, and an indicator that
knew about parcels would work here and nowhere else. The cost of that is real
and is recorded in the sibling prototype's notes: a deviation that spreads
through the *content* of the work is invisible to indicators that only see its
shape.

*Computed from what is already logged.* The monitor adds no instrumentation to
the agents, because an observer that required the observed to cooperate would
not be an independent observer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: The twelve, in the order the model lists them, with what each one is for.
#: Read by the page as well as by people, so the wording is the wording.
INDICATORS: Tuple[Tuple[str, str], ...] = (
    ("message_frequency",
     "messages exchanged per tick, of any kind"),
    ("interaction_density",
     "how much of the possible conversation is actually happening"),
    ("delegation_frequency",
     "work handed down to sub-agents per tick"),
    ("retry_frequency",
     "attempts abandoned and begun again per tick"),
    ("guardrail_events",
     "refusals per tick: the policy gate, the intake gate, a full shelf"),
    ("tool_call_frequency",
     "answers coming back up from sub-agents per tick"),
    ("task_switching",
     "how often work changes hands, per tick"),
    ("execution_latency",
     "mean ticks from a task being created to it being started"),
    ("agent_coupling",
     "share of the population involved in anything this window"),
    ("behavioural_similarity",
     "how alike the agents' activity is; high means they are herding"),
    ("persistence_of_deviation",
     "consecutive windows the facility has been off its baseline"),
    ("propagation_across_agents",
     "share of the acting agents showing the deviation, not just feeling it"),
)

INDICATOR_NAMES: Tuple[str, ...] = tuple(name for name, _ in INDICATORS)

# The log's vocabulary, defined in the communication package rather than here.
# The perturbation tracer needs the same answer to "what does an agent in
# difficulty look like", and two definitions of that would mean the spread it
# measures is not the spread these indicators detect. Importing them commits
# this package to nothing: they are frozen sets of strings.
from ..communication.topics import (REFUSAL_TOPICS, RETRY_TOPICS,   # noqa: F401
                                    SWITCH_TOPICS, TROUBLE_TOPICS)


@dataclass
class BehaviouralIndicators:
    """One window's worth of the twelve, plus what they were computed from."""

    ticks: int = 0
    events: int = 0
    active_agents: int = 0
    acting_agents: int = 0
    roster: int = 0

    message_frequency: float = 0.0
    interaction_density: float = 0.0
    delegation_frequency: float = 0.0
    retry_frequency: float = 0.0
    guardrail_events: float = 0.0
    tool_call_frequency: float = 0.0
    task_switching: float = 0.0
    execution_latency: float = 0.0
    agent_coupling: float = 0.0
    behavioural_similarity: float = 0.0
    persistence_of_deviation: float = 0.0
    propagation_across_agents: float = 0.0

    #: Counts kept beside the rates, because "0.04 refusals a tick" is a fact
    #: about the model and "two refusals" is a fact about the afternoon, and a
    #: person reading the page wants the second one.
    counts: Dict[str, int] = field(default_factory=dict)

    def values(self) -> Dict[str, float]:
        return {name: float(getattr(self, name)) for name in INDICATOR_NAMES}

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "ticks": self.ticks, "events": self.events,
            "active_agents": self.active_agents,
            "acting_agents": self.acting_agents, "roster": self.roster,
            "counts": dict(self.counts),
        }
        out.update({name: round(getattr(self, name), 4)
                    for name in INDICATOR_NAMES})
        return out


def _is_subagent(agent_id: str) -> bool:
    return str(agent_id).startswith("SUB-")


def _cosine(left: Dict[str, int], right: Dict[str, int]) -> float:
    shared = set(left) & set(right)
    if not shared:
        return 0.0
    dot = sum(left[k] * right[k] for k in shared)
    ll = math.sqrt(sum(v * v for v in left.values()))
    rr = math.sqrt(sum(v * v for v in right.values()))
    return dot / (ll * rr) if ll and rr else 0.0


def _latency(events: Sequence[Any], created: Dict[str, int]) -> float:
    """
    Mean ticks from a task being created to it being started.

    `created` is the monitor's running memory of when each task appeared,
    because a task started in this window was very often created in an earlier
    one and the window would otherwise only ever see the fast ones. Tasks that
    started before the monitor was watching are skipped rather than guessed at.
    """
    waits: List[int] = []
    for event in events:
        if event.topic != "task_started":
            continue
        task_id = str(event.detail.get("task_id") or "")
        born = created.get(task_id)
        if born is None:
            continue
        waits.append(max(0, int(event.tick) - int(born)))
    return sum(waits) / len(waits) if waits else 0.0


def compute_indicators(events: Sequence[Any], ticks: int, roster: int = 0,
                       created: Optional[Dict[str, int]] = None,
                       persistence: int = 0) -> BehaviouralIndicators:
    """
    The twelve, over one window of events.

    `ticks` is the span the window covers, `roster` the number of agents that
    exist (not the number that did something), `created` the monitor's memory
    of when each task appeared, and `persistence` how many consecutive windows
    the facility has already been off its baseline -- that last one is a fact
    about the sequence rather than about this window, so it is passed in rather
    than discovered here.
    """
    span = max(1, int(ticks))
    created = created or {}

    counts: Dict[str, int] = {
        "messages": 0, "delegations": 0, "tool_calls": 0, "retries": 0,
        "refusals": 0, "switches": 0, "blocked": 0,
        # Decisions the gate rejected because the proposed answer was not one
        # of the options. Kept apart from `refusals` because it is a fact about
        # the proposer -- a model that answered off-list, or a rule that
        # offered an action the situation did not have -- and not about the
        # facility being governed. Counting it as a guardrail event would make
        # a parser failure look like the policy gate doing its job.
        "malformed_decisions": 0,
    }
    pairs = set()
    actors: Dict[str, Dict[str, int]] = {}
    in_trouble = set()
    #: Agents that did something besides answer a question. The denominator of
    #: propagation, and not the same as the active population: a sub-agent is
    #: asked and replies, and has no way to emit a refusal, a retry or a block.
    #: Measuring spread against everyone who spoke would divide by a crowd that
    #: structurally cannot appear in the numerator, which puts a ceiling on the
    #: indicator well below 1 and makes any threshold above that ceiling
    #: unreachable -- a rule that can never fire, which is worse than no rule.
    acting = set()

    for event in events:
        actor = str(event.actor or "")
        target = str(event.target or "")
        topic = event.topic

        if actor:
            actors.setdefault(actor, {})
            actors[actor][topic] = actors[actor].get(topic, 0) + 1
            if topic not in ("message", "subagent_message"):
                acting.add(actor)

        if topic in ("message", "subagent_message"):
            counts["messages"] += 1
            if actor and target:
                pairs.add((actor, target))
            # Down the hierarchy is delegation; back up it is the answer. The
            # two are counted apart because a facility that delegates more than
            # it hears back is a facility with work piling up inside it.
            #
            # The log's own distinction is about the *sender*: a message from a
            # sub-agent is filed as `subagent_message` and everything else as
            # `message`, so the direction has to be read off the parties rather
            # than off the topic. Reading it off the topic is what the first
            # version of this did, and delegation came out as a flat zero for
            # the whole run.
            if _is_subagent(actor):
                counts["tool_calls"] += 1
            elif _is_subagent(target):
                counts["delegations"] += 1

        if topic in RETRY_TOPICS:
            counts["retries"] += 1
        if topic in SWITCH_TOPICS:
            counts["switches"] += 1
        if topic == "blocked":
            counts["blocked"] += 1

        # The policy gate is the guardrail that sits over every agent decision,
        # so a refused decision counts alongside the refusals at the doors.
        #
        # What the log actually carries is the *stage* that refused it --
        # "schema", "policy" or "state", with "ok" when it passed. This used
        # to compare against the literal string "refused", which the agents
        # have never written: `BaseAgent.decide` records `verdict.stage`. The
        # comparison was therefore always false, and every gate refusal by an
        # expert was invisible here.
        #
        # The three stages are not one thing. `schema` means the answer was
        # not among the options, which says the proposer malfunctioned;
        # `policy` and `state` mean a well-formed choice was refused, which is
        # the guardrail exercising authority. Only the latter two belong in an
        # indicator named `guardrail_events`.
        stage = str(event.detail.get("validation") or "") if topic == "decision" else ""
        governed = stage in ("policy", "state")
        malformed = stage == "schema"

        if topic in REFUSAL_TOPICS:
            counts["refusals"] += 1
        elif governed:
            counts["refusals"] += 1
        if malformed:
            counts["malformed_decisions"] += 1

        if topic in TROUBLE_TOPICS or governed:
            if actor:
                in_trouble.add(actor)

    active = len(actors)
    possible = active * (active - 1)
    similarities: List[float] = []
    profiles = list(actors.values())
    # Pairwise over the active population. Capped, because this is quadratic
    # and a window with a hundred actors would cost more than the tick it is
    # describing; the sample is the busiest ones, which is where herding shows.
    busiest = sorted(profiles, key=lambda p: -sum(p.values()))[:16]
    for i, left in enumerate(busiest):
        for right in busiest[i + 1:]:
            similarities.append(_cosine(left, right))

    return BehaviouralIndicators(
        ticks=span,
        events=len(events),
        active_agents=active,
        acting_agents=len(acting),
        roster=int(roster or active),
        message_frequency=counts["messages"] / span,
        interaction_density=(len(pairs) / possible) if possible else 0.0,
        delegation_frequency=counts["delegations"] / span,
        retry_frequency=counts["retries"] / span,
        guardrail_events=counts["refusals"] / span,
        tool_call_frequency=counts["tool_calls"] / span,
        task_switching=counts["switches"] / span,
        execution_latency=_latency(events, created),
        agent_coupling=(active / roster) if roster else 0.0,
        behavioural_similarity=(sum(similarities) / len(similarities)
                                if similarities else 0.0),
        persistence_of_deviation=float(persistence),
        propagation_across_agents=((len(in_trouble & acting) / len(acting))
                                   if acting else 0.0),
        counts=counts,
    )
