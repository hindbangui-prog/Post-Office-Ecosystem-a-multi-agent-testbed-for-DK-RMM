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

Extended on 2026-10-12 with eight operational and early-warning indicators
(communication failure rate, backlog growth, task completion rate, completion
gap, resource saturation, dependency-graph divergence, activity
synchronization, tail deviation). The ones that need the world's state read
it from a snapshot taken by `operations.snapshot_state` at assessment time,
read-only; the ones that need a history are filled in by the monitor. The
content-agnostic property above is relaxed for them on purpose: they read
what a parcel is doing, not what it is or where it is going. The formulas
are in docs/dkrmm-mathematics.md, section 21.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: The registry: the model's twelve first, in the order the model lists them,
#: then the eight operational and early-warning indicators added on
#: 2026-10-12 (docs/dkrmm-mathematics.md, section 21). Each entry is
#: (name, kind, direction, about):
#:
#: - kind: "base" is computed from one window's events and one state
#:   snapshot; "derived" is computed from histories the monitor keeps.
#: - direction: which way a deviation from baseline is evidence. "up" means
#:   only a rise counts, "down" only a fall, "both" either way. The monitor
#:   reads this when it tests z against DEVIATION_Z and when it folds the
#:   twenty into one severity.
#: - about: what it is for. Read by the page as well as by people, so the
#:   wording is the wording.
_REGISTRY: Tuple[Tuple[str, str, str, str], ...] = (
    ("message_frequency", "base", "both",
     "messages attempted per tick, of any kind; a fall counts when the "
     "facility's output is also off"),
    ("interaction_density", "base", "both",
     "how much of the possible conversation is actually happening"),
    ("delegation_frequency", "base", "up",
     "work handed down to sub-agents per tick"),
    ("retry_frequency", "base", "up",
     "attempts abandoned and begun again per tick"),
    ("guardrail_events", "base", "up",
     "refusals per tick: the policy gate, the intake gate, a full shelf"),
    ("tool_call_frequency", "base", "up",
     "answers coming back up from sub-agents per tick"),
    ("task_switching", "base", "up",
     "how often work changes hands, per tick"),
    ("execution_latency", "base", "up",
     "mean ticks from a task being created to it being started"),
    ("agent_coupling", "base", "both",
     "share of the roster that emitted any event this window; an "
     "active-agent fraction, not a coupling measure"),
    ("behavioural_similarity", "base", "both",
     "how alike the agents' activity is; a move away from its normal "
     "similarity, in either direction, is the signal"),
    ("persistence_of_deviation", "derived", "up",
     "consecutive windows the facility has been off its baseline"),
    ("propagation_across_agents", "derived", "up",
     "share of the acting agents showing the deviation, not just feeling it"),
    # ---- the extension (2026-10-12) ----
    ("communication_failure_rate", "base", "up",
     "share of attempted messages that were dropped or delivered late"),
    ("backlog_growth", "derived", "up",
     "parcels inside the building, change per tick since the last reading"),
    ("task_completion_rate", "base", "down",
     "parcels that left on vans per tick; a fall is the signal"),
    ("completion_gap", "base", "up",
     "parcels arriving per tick minus parcels leaving per tick"),
    ("resource_saturation", "base", "up",
     "the tightest of robots, charge points, routes, storage and the dock, "
     "as a share of its capacity"),
    ("dependency_graph_divergence", "derived", "up",
     "how far this window's who-talks-to-whom is from its baseline shape"),
    ("activity_synchronization", "base", "both",
     "how much the acting agents' activity rises and falls together"),
    ("tail_deviation", "derived", "up",
     "the worst-case waits and backlogs against their own baseline p95"),
)

#: (name, about) pairs, which is the shape every consumer reads
#: (`for name, about in INDICATORS`). Kept so the page, the views and the
#: tests written against the twelve keep working against the twenty.
INDICATORS: Tuple[Tuple[str, str], ...] = tuple(
    (name, about) for name, _kind, _direction, about in _REGISTRY)

INDICATOR_NAMES: Tuple[str, ...] = tuple(name for name, _ in INDICATORS)

#: The same registry by name, for the monitor and the page: `kind`,
#: `direction` and `about` for each indicator.
INDICATOR_META: Dict[str, Dict[str, str]] = {
    name: {"kind": kind, "direction": direction, "about": about}
    for name, kind, direction, about in _REGISTRY}

BASE_INDICATORS: Tuple[str, ...] = tuple(
    name for name, kind, _d, _a in _REGISTRY if kind == "base")
DERIVED_INDICATORS: Tuple[str, ...] = tuple(
    name for name, kind, _d, _a in _REGISTRY if kind == "derived")

#: Fewest ticks a window must span for activity synchronization to be read.
#: A Pearson correlation over two or three points is a sign, not a measure.
SYNC_MIN_TICKS = 4

#: The split of `counts["refusals"]` into where the refusal came from. Every
#: member of REFUSAL_TOPICS is in exactly one bucket; the policy and state
#: stages of the decision gate are the fourth bucket (`gate_rejections`).
#: The total is unchanged; the split is recorded beside it.
INTAKE_REJECTION_TOPICS = frozenset({"parcel_refused", "arrival_refused",
                                     "parcel_returned"})
RESOURCE_DENIAL_TOPICS = frozenset({"charge_refused", "charge_unavailable",
                                    "storage_refused"})
MESSAGE_REFUSAL_TOPICS = frozenset({"message_refused"})

# The log's vocabulary, defined in the communication package rather than here.
# The perturbation tracer needs the same answer to "what does an agent in
# difficulty look like", and two definitions of that would mean the spread it
# measures is not the spread these indicators detect. Importing them commits
# this package to nothing: they are frozen sets of strings.
from ..communication.topics import (REFUSAL_TOPICS, RETRY_TOPICS,   # noqa: F401
                                    SWITCH_TOPICS, TROUBLE_TOPICS)


def _all_evaluable() -> Dict[str, bool]:
    return {name: True for name in INDICATOR_NAMES}


@dataclass
class BehaviouralIndicators:
    """One window's worth of the twenty, plus what they were computed from."""

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

    # The extension (2026-10-12). The four that need a history or a state
    # snapshot (backlog_growth, resource_saturation,
    # dependency_graph_divergence, tail_deviation) are 0.0 and not evaluable
    # until the monitor, or a snapshot, fills them in.
    communication_failure_rate: float = 0.0
    backlog_growth: float = 0.0
    task_completion_rate: float = 0.0
    completion_gap: float = 0.0
    resource_saturation: float = 0.0
    dependency_graph_divergence: float = 0.0
    activity_synchronization: float = 0.0
    tail_deviation: float = 0.0

    #: Counts kept beside the rates, because "0.04 refusals a tick" is a fact
    #: about the model and "two refusals" is a fact about the afternoon, and a
    #: person reading the page wants the second one.
    counts: Dict[str, int] = field(default_factory=dict)
    #: Everything else the page shows beside a value: the per-category
    #: resources, the throughput split, the observed edges, the p95s, the
    #: raw waits and delays the tail metrics are read from.
    detail: Dict[str, Any] = field(default_factory=dict)
    #: Whether each indicator could be computed this window. A value whose
    #: flag is False is 0.0 by convention and must be shown as "n/a", never
    #: as a number: a facility whose dock could not be read is not a facility
    #: with an empty dock. The original twelve are always evaluable.
    evaluable: Dict[str, bool] = field(default_factory=_all_evaluable)

    def values(self) -> Dict[str, float]:
        return {name: float(getattr(self, name)) for name in INDICATOR_NAMES}

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "ticks": self.ticks, "events": self.events,
            "active_agents": self.active_agents,
            "acting_agents": self.acting_agents, "roster": self.roster,
            "counts": dict(self.counts),
            "detail": _jsonable(self.detail),
            "evaluable": {name: bool(self.evaluable.get(name, True))
                          for name in INDICATOR_NAMES},
        }
        out.update({name: round(getattr(self, name), 4)
                    for name in INDICATOR_NAMES})
        return out


def _jsonable(value: Any) -> Any:
    """The detail dict with tuples turned into lists, for `json.dump`."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float):
        return round(value, 4)
    return value


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


def _waits(events: Sequence[Any], created: Dict[str, int]) -> List[int]:
    """
    Ticks from a task being created to it being started, one per task started
    in the window.

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
    return waits


def _latency(events: Sequence[Any], created: Dict[str, int]) -> float:
    """Mean ticks from a task being created to it being started."""
    waits = _waits(events, created)
    return sum(waits) / len(waits) if waits else 0.0


def percentile(values: Sequence[float], p: float = 0.95) -> Optional[float]:
    """
    Nearest-rank percentile: the value at index ceil(p * n) - 1 of the sorted
    list. None for an empty list, because a percentile of nothing is not 0.
    """
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return None
    rank = max(1, min(len(ordered), math.ceil(p * len(ordered))))
    return ordered[rank - 1]


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """
    Pearson correlation of two equal-length series, or None when either has
    no variance (a flat series is correlated with nothing, and dividing by
    its zero spread would say otherwise).
    """
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 1e-12 or syy <= 1e-12:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))


def _synchronization(events: Sequence[Any], acting: Sequence[str],
                     min_agents: int, min_ticks: int):
    """
    Mean pairwise Pearson correlation of the acting agents' per-tick event
    counts over the window's ticks. Returns (value, evaluable, detail).

    The ticks are the closed range from the earliest to the latest tick seen
    in the window (every event, not only the acting agents'), zero-filled, so
    an agent that was silent on a tick contributes a 0 there rather than
    being absent. Each agent's series counts every event it was the actor
    of, messages included: the question is whether activity rises and falls
    together, and a message is activity. A pair in which either series is
    flat is skipped, because its correlation is undefined, not zero.
    """
    agents = sorted(acting)
    ticks = [int(e.tick) for e in events]
    detail: Dict[str, Any] = {"agents": len(agents), "pairs": 0, "ticks": 0}
    if not ticks or len(agents) < min_agents:
        return 0.0, False, detail
    low, high = min(ticks), max(ticks)
    span = high - low + 1
    detail["ticks"] = span
    if span < min_ticks:
        return 0.0, False, detail
    series: Dict[str, List[float]] = {a: [0.0] * span for a in agents}
    for event in events:
        actor = str(event.actor or "")
        if actor in series:
            series[actor][int(event.tick) - low] += 1.0
    correlations: List[float] = []
    for i, left in enumerate(agents):
        for right in agents[i + 1:]:
            r = _pearson(series[left], series[right])
            if r is not None:
                correlations.append(r)
    detail["pairs"] = len(correlations)
    if not correlations:
        return 0.0, False, detail
    return sum(correlations) / len(correlations), True, detail


def compute_indicators(events: Sequence[Any], ticks: int, roster: int = 0,
                       created: Optional[Dict[str, int]] = None,
                       persistence: int = 0, *,
                       snapshot: Optional[Dict[str, Any]] = None,
                       min_sync_agents: int = 2) -> BehaviouralIndicators:
    """
    The twenty, over one window of events, less the three the monitor holds.

    `ticks` is the span the window covers, `roster` the number of agents that
    exist (not the number that did something), `created` the monitor's memory
    of when each task appeared, and `persistence` how many consecutive windows
    the facility has already been off its baseline -- that last one is a fact
    about the sequence rather than about this window, so it is passed in rather
    than discovered here.

    `snapshot` is the read-only state snapshot from `operations.snapshot_state`
    taken at the same tick; without it the indicators that need the world's
    state (resource_saturation, and `held_now` in the counts) are marked not
    evaluable. `backlog_growth`, `dependency_graph_divergence` and
    `tail_deviation` need histories this function does not have; they come
    back 0.0 and not evaluable, and the monitor fills them in.
    `min_sync_agents` mirrors `monitor.MIN_SYNC_AGENTS`.
    """
    span = max(1, int(ticks))
    created = created or {}
    snapshot = snapshot or {}

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
        # The split of `refusals` by where the refusal came from. The four
        # add up to `refusals`; the rate is unchanged.
        "gate_rejections": 0, "intake_rejections": 0,
        "resource_denials": 0, "message_refusals": 0,
        # Delivery: what was attempted on the bus and what became of it.
        "attempted": 0, "delivered": 0, "dropped": 0, "late": 0,
        # Throughput: parcels in and out, tasks finished.
        "parcels_in": 0, "arrivals_refused": 0, "parcels_out": 0,
        "tasks_completed": 0,
    }
    pairs = set()
    #: Ordered (sender, receiver) -> attempted messages, the observed
    #: dependency graph of the window. Exposed in `detail["edges"]`; the
    #: divergence from its baseline is the monitor's to compute.
    edges: Dict[Tuple[str, str], int] = {}
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
    late_by: List[int] = []

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
            counts["attempted"] += 1
            if actor and target:
                pairs.add((actor, target))
                edges[(actor, target)] = edges.get((actor, target), 0) + 1
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

        # Delivery failures. The bus logs `message` at send and
        # `message_dropped` at delivery, with the sender as actor, so the
        # sender of a dropped message is in trouble (and, since the topic is
        # not a message topic, it is also acting by the rule above). A late
        # delivery is logged as `agent_message_received` with the sender as
        # actor and the receiver as target; the receiver is the one left
        # waiting, so the *target* is in trouble. A late receiver that did
        # nothing else this window is not in `acting`, and propagation stays
        # |in_trouble & acting| / |acting|, so it counts only if it acted.
        if topic == "message_dropped":
            counts["dropped"] += 1
            if actor:
                in_trouble.add(actor)
        elif topic == "agent_message_received":
            waited = int(event.detail.get("late_by") or 0)
            if waited > 0:
                counts["late"] += 1
                late_by.append(waited)
                if target:
                    in_trouble.add(target)

        # Throughput. `van_departed` carries how many parcels left on it;
        # `parcel_arrived` and `arrival_refused` together are the demand.
        if topic == "van_departed":
            counts["parcels_out"] += int(event.detail.get("parcels") or 0)
        elif topic == "parcel_arrived":
            counts["parcels_in"] += 1
        elif topic == "arrival_refused":
            counts["arrivals_refused"] += 1
        elif topic == "task_completed":
            counts["tasks_completed"] += 1

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
            if topic in INTAKE_REJECTION_TOPICS:
                counts["intake_rejections"] += 1
            elif topic in RESOURCE_DENIAL_TOPICS:
                counts["resource_denials"] += 1
            elif topic in MESSAGE_REFUSAL_TOPICS:
                counts["message_refusals"] += 1
            else:
                # Every member of REFUSAL_TOPICS is in one of the three sets
                # above as of 2026-10-12; a topic added later lands here.
                counts["other_refusals"] = counts.get("other_refusals", 0) + 1
        elif governed:
            counts["refusals"] += 1
            counts["gate_rejections"] += 1
        if malformed:
            counts["malformed_decisions"] += 1

        if topic in TROUBLE_TOPICS or governed:
            if actor:
                in_trouble.add(actor)

    counts["delivered"] = counts["attempted"] - counts["dropped"]

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

    waits = _waits(events, created)
    evaluable = _all_evaluable()
    detail: Dict[str, Any] = {}

    # Communication failure rate: of the messages attempted this window, the
    # share that were dropped or arrived late. A dropped message has no late
    # event, so each is counted once. Nothing attempted, nothing to rate.
    #
    # The bus logs the attempt at send and the drop at delivery, a tick
    # later, so at the edges of a window a drop can be inside it while its
    # send is just outside (and the other way round). The raw ratio can
    # therefore pass 1 by a few percent under a total drop; the indicator is
    # clamped to its range [0, 1] and the raw ratio is kept in the detail.
    attempted = counts["attempted"]
    evaluable["communication_failure_rate"] = attempted > 0
    raw_rate = ((counts["dropped"] + counts["late"]) / attempted
                if attempted else 0.0)
    failure_rate = max(0.0, min(1.0, raw_rate))
    held_now = snapshot.get("held_now")
    if held_now is not None:
        counts["held_now"] = int(held_now)
    detail["delivery"] = {
        "attempted": attempted, "delivered": counts["delivered"],
        "dropped": counts["dropped"], "late": counts["late"],
        "held_now": held_now, "late_by": list(late_by),
        "raw_rate": raw_rate}

    # Throughput: parcels that left on vans per tick, and the demand they
    # are set against. Both are values whatever the window held: zero
    # parcels leaving is a reading, not a missing one.
    completed_per_tick = counts["parcels_out"] / span
    incoming_per_tick = (counts["parcels_in"] + counts["arrivals_refused"]) / span
    detail["throughput"] = {
        "completed_per_tick": completed_per_tick,
        "incoming_per_tick": incoming_per_tick,
        "tasks_completed_per_tick": counts["tasks_completed"] / span,
        "completion_gap": incoming_per_tick - completed_per_tick}

    # Resource saturation is read off the snapshot, which already holds the
    # per-category utilisations and the bottleneck among them.
    resources = snapshot.get("resources")
    saturation = snapshot.get("resource_saturation")
    evaluable["resource_saturation"] = (resources is not None
                                        and saturation is not None)
    detail["resources"] = resources if resources is not None else {}

    sync, sync_ok, sync_detail = _synchronization(
        events, sorted(acting), min_sync_agents, SYNC_MIN_TICKS)
    evaluable["activity_synchronization"] = sync_ok
    detail["synchronization"] = sync_detail

    # The observed dependency graph, as JSON-safe rows; the divergence from
    # its baseline is computed by the monitor, which holds the baseline.
    detail["edges"] = [[a, b, n] for (a, b), n in sorted(edges.items())]
    # The raw values the tail metrics are read from, and the p95 of the
    # waits beside the mean the latency indicator reports.
    detail["waits"] = list(waits)
    detail["execution_latency_p95"] = percentile(waits)

    # Held by the monitor: 0.0 and not evaluable until it fills them in.
    for name in ("backlog_growth", "dependency_graph_divergence",
                 "tail_deviation"):
        evaluable[name] = False

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
        execution_latency=(sum(waits) / len(waits)) if waits else 0.0,
        agent_coupling=(active / roster) if roster else 0.0,
        behavioural_similarity=(sum(similarities) / len(similarities)
                                if similarities else 0.0),
        persistence_of_deviation=float(persistence),
        propagation_across_agents=((len(in_trouble & acting) / len(acting))
                                   if acting else 0.0),
        communication_failure_rate=failure_rate,
        task_completion_rate=completed_per_tick,
        completion_gap=incoming_per_tick - completed_per_tick,
        resource_saturation=(float(saturation)
                             if evaluable["resource_saturation"] else 0.0),
        activity_synchronization=sync if sync_ok else 0.0,
        counts=counts,
        detail=detail,
        evaluable=evaluable,
    )
