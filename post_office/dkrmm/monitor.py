"""
DK-RMM: the Dragon-King Runtime Monitoring Model, watching this facility.

What it is for: to say whether the ecosystem as a whole is having a bad minute
or changing regime, and to say it early enough to be worth saying. A facility
where one robot is stuck is not in trouble. A facility where refusals, retries
and blocking are all climbing together, spreading across the population, with
the statistics of a system that recovers from disturbances more slowly than it
did an hour ago, is in a different condition, and it is that condition -- a
Runtime Critical Transition -- the model exists to name.

**It is an observer and nothing else.** This is the constraint the whole design
answers to, and it is not decoration:

- it is not an agent, is not in the hierarchy, and is not on the message bus
- it never sends a message, so nothing can be waiting on it
- it never writes to the world, the agents, the robots, the tasks or the
  parcels, and holds no reference it could write through
- it subscribes to the event log, which is the same read-only stream the trace
  sink uses, and it is the last subscriber to be told
- since 2026-10-12 it also reads the state of the building at each assessment
  (`operations.snapshot_state`: parcels, robots, charge points, routes,
  storage, the dock, the bus's held messages, the directory), reads only,
  every read guarded, and a read that fails leaves its indicator unread
  rather than filled in
- removing it changes nothing about a run, which is a property the tests hold
  rather than a claim this docstring makes

The reason is not tidiness. A monitor that could act would be part of the
system it is judging, and its readings would be readings of its own influence.
The supervisor governs, the agents decide, and this watches; each of the three
is independent of the other two.

**Discovery, then a person, then action.** Every assessment the monitor makes
is DISCOVERED and means nothing by itself. A person reads it and either
validates it or dismisses it, and only then does it count. Dismissals are kept
alongside validations, because a monitor whose false positives are deleted can
never be shown to have any.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import mean, median
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

from .indicators import (INDICATOR_META, INDICATOR_NAMES,
                         BehaviouralIndicators, compute_indicators,
                         percentile)
from .operations import snapshot_state
from .signals import DragonKing, Precursors, dragon_king, precursors, zscore
from .states import ESCALATED, DiscoveryStatus, OperationalState

#: How often an assessment is made, in ticks. Every tick would be a monitor
#: that costs more than the thing it watches and that reports the noise of
#: individual decisions as collective behaviour.
EVERY = 20

#: How many ticks each assessment looks back over. Longer than `EVERY`, so
#: windows overlap and a short-lived event is seen by more than one of them.
WINDOW = 60

#: How many past windows each indicator's baseline is drawn from. About twenty
#: minutes of simulated time: long enough to describe a normal, short enough
#: that a facility whose normal has genuinely moved is not held to yesterday's.
BASELINE = 24

#: How far off its own baseline an indicator has to be to count as evidence.
#: Two standard deviations, the ordinary convention, and stated here rather
#: than buried so that it can be argued with.
DEVIATION_Z = 2.0

#: How many kinds of evidence make a state. Kinds, not events: the model's
#: claim is that a critical transition shows up as independent signals
#: converging, and three refusals are one signal however many times it repeats.
UNSTABLE_KINDS = 2
RCT_KINDS = 3

#: How much of the active population has to be showing the trouble before it
#: is the population's trouble rather than somebody's.
RCT_PROPAGATION = 0.5

#: Consecutive off-baseline windows after which one kind of evidence is enough
#: on its own. Something that will not settle is a different thing from
#: something that happened.
PERSISTENT = 3

#: How many assessments to keep. At one every twenty ticks this is a long run.
HISTORY = 400

#: Below this many events in a window there is not enough happening to say
#: anything about collective behaviour. In a nearly idle facility every
#: baseline is a handful of numbers, so a single message lands two standard
#: deviations from normal and the monitor reports a crisis in an empty
#: building. Quiet is not the same as calm and it is not the same as unstable;
#: the honest answer is that there is nothing to read yet, and the assessment
#: says so rather than inventing a verdict.
MIN_ACTIVITY = 24

#: Fewest acting agents for activity synchronization to be read. One agent
#: has nobody to be synchronized with; two is the first pair.
MIN_SYNC_AGENTS = 2

#: The percentile the tail metrics are read at. The 95th: the slow fifth of
#: the twentieth, which is where a queue shows before the mean moves.
TAIL_P = 0.95

#: Fewest baseline windows a tail metric needs before its p95 ratio means
#: anything. Four, the same floor `zscore` puts under a baseline.
TAIL_MIN_BASELINE = 4

#: Which assessed states a window may teach the baseline from without
#: question. A window the monitor itself judged UNSTABLE or RCT enters a
#: formed baseline only when none of the operational kinds (delivery,
#: backlog, throughput, saturation) is among its evidence: a monitor that
#: learns its normal from windows in which the operation itself is failing
#: has, after one baseline's worth of them, a normal that is the fault (the
#: way M-S-DROP read STABLE with the dock full). A behavioural spell with no
#: operational consequence (a run of policy refusals, a congested quarter
#: hour) keeps shaping the baseline as it always did, which is what keeps
#: Normal's own busy spells from being held against it for the rest of the
#: run: with every UNSTABLE window excluded, Normal seed 1 over 2800 ticks
#: read UNSTABLE in 38 windows of 140 against 9 before the extension and
#: lost all 6 of its RCTs; with this rule it reads 28 and keeps 8.
BASELINE_LEARNS_FROM = (OperationalState.STABLE, OperationalState.DEVIATING,
                        OperationalState.RECOVERY)


#: The evidence kinds, and which indicators speak for each. Grouped so that
#: three indicators all driven by the same underlying event -- refusals push
#: up guardrail events and propagation together -- cannot be counted as three
#: independent findings, which is exactly how a monitor talks itself into a
#: crisis.
#:
#: The direction a deviation has to go to count is not here: it is the
#: indicator's own `direction` in `INDICATOR_META` ("up", "down" or "both"),
#: so an indicator means the same thing in every kind it belongs to.
EVIDENCE: Dict[str, Tuple[str, ...]] = {
    "refusal": ("guardrail_events",),
    "retry": ("retry_frequency",),
    # The tail statistic sits with congestion rather than in a kind of its
    # own. Its task-wait metric is the 95th percentile of the same sample
    # whose mean is `execution_latency`, so a separate "tail" kind would
    # count one queue twice; the message-delay and zone-backlog metrics are
    # likewise tails of what delivery and backlog already read. Found in
    # validation on Normal (seed 1, ticks 1481 to 1501: congestion and tail
    # together made UNSTABLE out of a single slow queue).
    "congestion": ("execution_latency", "task_switching", "tail_deviation"),
    "chatter": ("message_frequency", "delegation_frequency",
                "tool_call_frequency", "interaction_density"),
    "herding": ("behavioural_similarity", "agent_coupling"),
    "spread": ("propagation_across_agents",),
    "delivery": ("communication_failure_rate",),
    "backlog": ("backlog_growth",),
    "throughput": ("task_completion_rate", "completion_gap"),
    "saturation": ("resource_saturation",),
    "structure": ("dependency_graph_divergence",),
    "synchrony": ("activity_synchronization",),
}

#: The kinds read from parcel events and from the state of the building
#: rather than from the agents' chatter. These are evaluated even in a window
#: too quiet to read collective behaviour, because a facility that has gone
#: silent while its dock fills is not "too quiet to say".
OPERATIONAL_KINDS: Tuple[str, ...] = ("delivery", "backlog", "throughput",
                                      "saturation")
#: The rest: the kinds about how the agents behave, which need enough
#: events to be read at all.
BEHAVIOURAL_KINDS: Tuple[str, ...] = tuple(
    kind for kind in EVIDENCE if kind not in OPERATIONAL_KINDS)

#: The two-sided behavioural indicators whose *fall* is evidence only when
#: something operational is also wrong. A quiet facility with normal output
#: is not deviating; a quiet facility whose parcels are not leaving is. The
#: same holds for fewer agents active and for the agents looking less alike:
#: both are what a quiet afternoon looks like (found in validation on Normal,
#: seed 1, tick 1381: coupling and similarity both fell in a lull and read as
#: herding). A *rise* on any of the four always counts.
CORROBORATED_FALL: Tuple[str, ...] = ("message_frequency", "interaction_density",
                                      "agent_coupling", "behavioural_similarity")

#: The tail metrics and where each window's values come from in the
#: indicators' `detail`: task wait (created to started), message delay
#: (`late_by`), and the backlog of the fullest zone.
TAIL_METRICS: Tuple[str, ...] = ("task_wait", "message_delay", "zone_backlog")


def directional(name: str, z: float) -> float:
    """
    The part of a z-score that counts for this indicator: the rise for an
    "up" indicator, the fall (as a positive number) for a "down" one, and the
    size either way for "both". Zero when it moved the wrong way.
    """
    direction = INDICATOR_META.get(name, {}).get("direction", "up")
    if direction == "down":
        return max(0.0, -z)
    if direction == "both":
        return abs(z)
    return max(0.0, z)


def deviates(name: str, z: float, threshold: float = DEVIATION_Z) -> str:
    """"up", "down" or "none": which way, if any, this indicator deviates."""
    direction = INDICATOR_META.get(name, {}).get("direction", "up")
    if direction in ("up", "both") and z >= threshold:
        return "up"
    if direction in ("down", "both") and z <= -threshold:
        return "down"
    return "none"


def weighted_jaccard(now: Dict[Any, float], base: Dict[Any, float]) -> float:
    """
    sum of min over sum of max, over the union of keys. 1.0 for two empty
    maps (0/0 is read as "nothing differs", so the divergence is 0).
    """
    keys = set(now) | set(base)
    if not keys:
        return 1.0
    top = sum(min(now.get(k, 0.0), base.get(k, 0.0)) for k in keys)
    bottom = sum(max(now.get(k, 0.0), base.get(k, 0.0)) for k in keys)
    return top / bottom if bottom > 0 else 1.0


@dataclass
class Assessment:
    """One reading: the state, why, and everything it was read from."""

    tick: int = 0
    state: OperationalState = OperationalState.STABLE
    previous: Optional[OperationalState] = None
    status: DiscoveryStatus = DiscoveryStatus.DISCOVERED
    indicators: BehaviouralIndicators = field(
        default_factory=BehaviouralIndicators)
    z: Dict[str, float] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)
    kinds: List[str] = field(default_factory=list)
    severity: float = 0.0
    #: Whether the window held enough to read at all.
    enough_activity: bool = True
    precursors: Precursors = field(default_factory=Precursors)
    dragon: DragonKing = field(default_factory=DragonKing)
    #: Per indicator: whether it could be read this window, which way it
    #: deviated ("up", "down", "none"), the kind it fed (or None) and the
    #: mean of its baseline (None with fewer than four points).
    evaluable: Dict[str, bool] = field(default_factory=dict)
    deviation: Dict[str, str] = field(default_factory=dict)
    in_evidence: Dict[str, Optional[str]] = field(default_factory=dict)
    baseline: Dict[str, Optional[float]] = field(default_factory=dict)
    #: Kinds the quiet rule left unread this window.
    not_evaluated: List[str] = field(default_factory=list)
    #: The state of the building at the assessment tick (`operations`).
    snapshot: Dict[str, Any] = field(default_factory=dict)
    #: Who validated or dismissed it, and when. Empty until somebody does.
    decided_by: str = ""
    decided_at: str = ""
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tick": self.tick,
            "state": self.state.value,
            "previous": self.previous.value if self.previous else None,
            "status": self.status.value,
            "indicators": self.indicators.as_dict(),
            "z": {k: round(v, 3) for k, v in self.z.items()},
            "evidence": list(self.evidence),
            "kinds": list(self.kinds),
            "severity": round(self.severity, 4),
            "enough_activity": self.enough_activity,
            "precursors": self.precursors.as_dict(),
            "dragon": self.dragon.as_dict(),
            "evaluable": dict(self.evaluable),
            "deviation": dict(self.deviation),
            "in_evidence": dict(self.in_evidence),
            "baseline": {k: (round(v, 4) if v is not None else None)
                         for k, v in self.baseline.items()},
            "not_evaluated": list(self.not_evaluated),
            "snapshot": _plain(self.snapshot),
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "note": self.note,
        }


def _plain(value: Any) -> Any:
    """A snapshot with tuples as lists and floats rounded, for JSON."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, float):
        return round(value, 4)
    return value


class DKRMM:
    """
    The monitor. Built beside an ecosystem, never inside one.

    It holds the ecosystem only to read the roster and the clock. Everything
    else arrives through `observe`, which the event logger calls.
    """

    def __init__(self, eco, every: int = EVERY, window: int = WINDOW,
                 baseline: int = BASELINE) -> None:
        self._eco = eco
        self.every = int(every)
        self.window = int(window)
        self.baseline = int(baseline)

        #: Recent events, and nothing older. The monitor is a moving window
        #: over the stream, not a second copy of the log.
        self._events: Deque[Any] = deque(maxlen=20000)
        #: When each task appeared, so a task started in this window can be
        #: timed from its creation in an earlier one.
        self._created: Dict[str, int] = {}
        #: Each indicator's own recent past, which is what "off baseline"
        #: is measured against.
        self._series: Dict[str, Deque[float]] = {
            name: deque(maxlen=self.baseline) for name in INDICATOR_NAMES}
        #: The composite severity of each past window, which is the series the
        #: dragon-king test and the precursors are computed on.
        self._severity: Deque[float] = deque(maxlen=max(80, self.baseline * 3))
        self._persistence = 0
        #: The kinds of evidence the last window saw. A kind that appears once
        #: and is gone is a burst, not a deviation: a single parcel arriving
        #: into a quiet facility moves chatter, switching and coupling all at
        #: once, and counting those as three independent findings is how a
        #: monitor talks itself into a crisis over one parcel. So a kind has
        #: to survive into a second window before it counts towards anything
        #: above DEVIATING.
        self._last_kinds: List[str] = []
        self._last_at = -1
        #: The baseline shape of who talks to whom: one edge-weight map per
        #: window the baseline learned from, for the divergence indicator.
        self._edges: Deque[Dict[Tuple[str, str], int]] = deque(
            maxlen=self.baseline)
        #: Each tail metric's past p95s, for the tail-deviation ratio.
        self._tails: Dict[str, Deque[float]] = {
            metric: deque(maxlen=self.baseline) for metric in TAIL_METRICS}
        #: The previous assessment's snapshot and backlog growth, for the
        #: growth and its acceleration.
        self._last_snapshot: Optional[Dict[str, Any]] = None
        self._last_growth: Optional[float] = None
        self._increasing_for = 0

        self.history: List[Assessment] = []
        self.current: Optional[Assessment] = None
        self._unsubscribe = None

    # ------------------------------------------------------------ attaching
    def attach(self) -> "DKRMM":
        """
        Start listening. Subscribing is the only connection to the run.

        `EventLogger.subscribe` hands back the way to stop, and nothing else
        passes between the two: the logger calls, the monitor reads, and no
        path runs the other way.
        """
        self._unsubscribe = self._eco.logger.subscribe(self.observe)
        return self

    def close(self) -> None:
        if self._unsubscribe is not None:
            try:
                self._unsubscribe()
            except Exception:
                pass
            self._unsubscribe = None

    # ------------------------------------------------------------- watching
    def observe(self, event) -> None:
        """
        One event. Called by the logger, and does as little as possible.

        A subscriber that threw or that took a long time would be a subscriber
        that had changed the run, so this appends and returns; the arithmetic
        happens on the assessment tick.
        """
        self._events.append(event)
        if event.topic == "task_created":
            task_id = str(event.detail.get("task_id") or "")
            if task_id:
                self._created.setdefault(task_id, int(event.tick))
                # Bounded, like everything else here.
                if len(self._created) > 4000:
                    for key in list(self._created)[:2000]:
                        self._created.pop(key, None)

    def tick(self, now: Optional[int] = None) -> Optional[Assessment]:
        """
        Make an assessment if one is due. Called once per simulated tick.

        Returns the new assessment, or `None` on the ticks between them, so a
        caller can act on the moment a state changes without polling.
        """
        now = int(self._eco.world.tick if now is None else now)
        if self._last_at >= 0 and now - self._last_at < self.every:
            return None
        self._last_at = now
        return self.assess(now)

    # ------------------------------------------------------------ assessing
    def _window(self, now: int) -> List[Any]:
        floor = now - self.window
        return [e for e in self._events if floor <= int(e.tick) <= now]

    def assess(self, now: int) -> Assessment:
        """Read the window, and say what condition the facility is in."""
        events = self._window(now)
        roster = len(getattr(self._eco, "agents", {}) or {})
        # The state of the building at this tick. Reads only, and a read
        # that is unavailable leaves its indicator not evaluable.
        snapshot = snapshot_state(self._eco)
        indicators = compute_indicators(
            events, ticks=min(self.window, max(1, now)), roster=roster,
            created=self._created, persistence=self._persistence,
            snapshot=snapshot, min_sync_agents=MIN_SYNC_AGENTS)
        # The three the monitor holds the histories for.
        self._fill_backlog_growth(indicators, snapshot)
        edges_now = self._fill_divergence(indicators, snapshot)
        tails_now = self._fill_tail_deviation(indicators, snapshot)

        # Each indicator against its own past, *before* this window joins it:
        # a baseline that already contains the reading is a baseline that has
        # started explaining away the thing it is supposed to detect. An
        # indicator that could not be read is at z = 0: no reading, no
        # distance.
        values = indicators.values()
        evaluable = {name: bool(indicators.evaluable.get(name, True))
                     for name in INDICATOR_NAMES}
        z = {name: (self._signed_z(values[name], self._series[name])
                    if evaluable[name] else 0.0)
             for name in INDICATOR_NAMES}
        baseline = {name: (mean(self._series[name])
                           if len(self._series[name]) >= 4 else None)
                    for name in INDICATOR_NAMES}

        # One number for the window, so the dragon-king test has a series to
        # work on. Each indicator contributes the part of its z-score that
        # counts in its own direction (section 21.3 of the mathematics): the
        # rise for most, the fall for task completion, the size either way
        # for the two-sided ones. Divided by the number of indicator names,
        # evaluable or not, so the scale stays comparable across windows in
        # which a different number could be read.
        severity = sum(directional(name, z[name])
                       for name in INDICATOR_NAMES if evaluable[name]) / len(z)
        self._severity.append(severity)

        state, kinds, evidence = self._classify(indicators, z)
        _kinds, _evidence, hits, not_evaluated = self._evidence(indicators, z)
        self._last_kinds = kinds
        if state is OperationalState.STABLE:
            self._persistence = 0
        else:
            self._persistence += 1

        previous = self.current.state if self.current else None
        if (previous in ESCALATED and state is OperationalState.STABLE):
            # The way out is itself the finding. Without this a facility that
            # came back reads as one that was never in trouble.
            state = OperationalState.RECOVERY
            evidence = [f"back to baseline from {previous.value}"] + evidence

        # Only now does the window join the baselines, and, once a baseline
        # is formed, not if the monitor just called the window UNSTABLE or
        # RCT on operational evidence (BASELINE_LEARNS_FROM and the note on
        # it). Until a baseline holds its
        # full `baseline` windows it learns from every window whatever the
        # state: a handful of start-up windows is not a normal worth
        # protecting, and a monitor that froze on them would hold the whole
        # run to the first hundred ticks (seen on Normal, seed 1: UNSTABLE
        # from tick 101 to the end). `_classify` reads no baseline, so
        # scoring first and learning after changes nothing about the
        # verdict; it changes what the next one is measured against. A
        # value that could not be read teaches nothing.
        learn = (state in BASELINE_LEARNS_FROM
                 or not (set(kinds) & set(OPERATIONAL_KINDS)))
        for name in INDICATOR_NAMES:
            if evaluable[name] and (learn or not self._formed(self._series[name])):
                self._series[name].append(values[name])
        if edges_now is not None and (learn or not self._formed(self._edges)):
            self._edges.append(edges_now)
        for metric, p95 in tails_now.items():
            if p95 is not None and (learn or not self._formed(self._tails[metric])):
                self._tails[metric].append(p95)
        self._remember_backlog(indicators, snapshot)

        assessment = Assessment(
            tick=now, state=state, previous=previous,
            status=DiscoveryStatus.DISCOVERED,
            indicators=indicators, z=z, evidence=evidence, kinds=kinds,
            severity=severity,
            enough_activity=indicators.events >= MIN_ACTIVITY,
            precursors=precursors(list(self._severity)),
            dragon=dragon_king(list(self._severity)),
            evaluable=evaluable,
            deviation={name: (deviates(name, z[name]) if evaluable[name]
                              else "none") for name in INDICATOR_NAMES},
            in_evidence={name: hits.get(name) for name in INDICATOR_NAMES},
            baseline=baseline,
            not_evaluated=not_evaluated,
            snapshot=snapshot,
        )
        self.current = assessment
        self.history.append(assessment)
        if len(self.history) > HISTORY:
            del self.history[:len(self.history) - HISTORY]
        return assessment

    def _formed(self, history: Sequence[Any]) -> bool:
        """Whether a baseline holds its full complement of windows."""
        return len(history) >= self.baseline

    @staticmethod
    def _signed_z(value: float, history: Sequence[float]) -> float:
        """
        `zscore`, with its sign taken from the raw difference.

        `zscore` is unchanged: on a dead-flat baseline that has moved it
        returns +3 whichever way the value went, because the size of the
        move cannot be expressed in standard deviations of nothing. That
        was harmless while only rises counted. Now that a fall is evidence
        for some indicators and not for others, the *direction* has to be
        right, so on that branch the sign comes from the value against the
        baseline mean: a fall from a flat baseline reads -3, a rise +3. On
        every other branch the sign of `zscore` already is that sign.
        """
        z = zscore(value, history)
        if z > 0.0 and len(history) >= 4 and float(value) < mean(history):
            return -z
        return z

    # ------------------------------------------- the monitor-held values
    def _fill_backlog_growth(self, indicators: BehaviouralIndicators,
                             snapshot: Dict[str, Any]) -> None:
        """
        Parcels inside the building, change per tick since the previous
        assessment. Not evaluable on the first assessment, or when either
        reading is missing. `increasing_for` and `acceleration` are facts
        about the sequence of growths, kept by the monitor.
        """
        now = snapshot.get("backlog")
        prev = (self._last_snapshot or {}).get("backlog")
        detail: Dict[str, Any] = {
            "backlog_now": now, "backlog_prev": prev,
            "by_zone": snapshot.get("by_zone"),
            "unfinished_tasks": snapshot.get("unfinished_tasks"),
            "refused_total": snapshot.get("refused_total"),
            "increasing_for": self._increasing_for,
            "acceleration": None, "growth": None,
        }
        ok = now is not None and prev is not None and self.every > 0
        if ok:
            growth = (float(now) - float(prev)) / float(self.every)
            detail["growth"] = growth
            if self._last_growth is not None:
                detail["acceleration"] = growth - self._last_growth
            indicators.backlog_growth = growth
        indicators.evaluable["backlog_growth"] = bool(ok)
        indicators.detail["backlog"] = detail

    def _remember_backlog(self, indicators: BehaviouralIndicators,
                          snapshot: Dict[str, Any]) -> None:
        """After the assessment: this snapshot and growth become the previous."""
        if indicators.evaluable.get("backlog_growth"):
            growth = indicators.backlog_growth
            self._increasing_for = (self._increasing_for + 1
                                    if growth > 0 else 0)
            self._last_growth = growth
            indicators.detail["backlog"]["increasing_for"] = self._increasing_for
        self._last_snapshot = snapshot

    def _fill_divergence(self, indicators: BehaviouralIndicators,
                         snapshot: Dict[str, Any]
                         ) -> Optional[Dict[Tuple[str, str], int]]:
        """
        1 - weighted Jaccard between this window's edge-weight map and the
        per-edge mean of the baseline windows' maps. Returns this window's
        map, for the baseline to learn from if the state allows.
        """
        rows = indicators.detail.get("edges") or []
        now: Dict[Tuple[str, str], int] = {
            (str(a), str(b)): int(n) for a, b, n in rows}
        detail: Dict[str, Any] = {
            "edges_now": len(now), "baseline_windows": len(self._edges),
            "unexpected": [], "missing": [], "weight_change": None}
        declared = snapshot.get("declared_edges")
        declared_set = (set((str(a), str(b)) for a, b in declared)
                        if declared is not None else None)
        if declared_set is not None:
            detail["unexpected"] = sorted(
                [list(e) for e in now if e not in declared_set])
        if not self._edges:
            indicators.evaluable["dependency_graph_divergence"] = False
            indicators.detail["structure"] = detail
            return now
        # Mean weight per edge over the baseline windows; an edge absent
        # from a window weighs 0 there.
        base: Dict[Tuple[str, str], float] = {}
        for window_map in self._edges:
            for edge, n in window_map.items():
                base[edge] = base.get(edge, 0.0) + float(n)
        count = float(len(self._edges))
        base = {edge: total / count for edge, total in base.items()}
        divergence = 1.0 - weighted_jaccard(now, base)
        total_base = sum(base.values())
        l1 = sum(abs(float(now.get(e, 0)) - base.get(e, 0.0))
                 for e in set(now) | set(base))
        detail["weight_change"] = (l1 / total_base) if total_base > 0 else None
        if declared_set is not None:
            detail["missing"] = sorted(
                [list(e) for e in base
                 if e in declared_set and base[e] > 0 and now.get(e, 0) == 0])
        indicators.dependency_graph_divergence = max(0.0, min(1.0, divergence))
        indicators.evaluable["dependency_graph_divergence"] = True
        indicators.detail["structure"] = detail
        return now

    def _fill_tail_deviation(self, indicators: BehaviouralIndicators,
                             snapshot: Dict[str, Any]
                             ) -> Dict[str, Optional[float]]:
        """
        max over the tail metrics of p95_now / p95_baseline, the baseline
        p95 being the median of the past windows' p95s. A metric with no
        values this window is skipped; a metric whose baseline p95 is 0 has
        no ratio (recorded as "baseline zero"). Returns each metric's p95
        now, for the baseline to learn from if the state allows.
        """
        by_zone = snapshot.get("by_zone") or {}
        values: Dict[str, List[float]] = {
            "task_wait": [float(v) for v in indicators.detail.get("waits") or []],
            "message_delay": [float(v) for v in
                              (indicators.detail.get("delivery") or {})
                              .get("late_by") or []],
            "zone_backlog": [float(v) for v in by_zone.values()],
        }
        now: Dict[str, Optional[float]] = {}
        detail: Dict[str, Any] = {}
        ratios: List[float] = []
        for metric in TAIL_METRICS:
            p95_now = percentile(values[metric], TAIL_P)
            now[metric] = p95_now
            history = list(self._tails[metric])
            row: Dict[str, Any] = {
                "p95_now": p95_now, "p95_baseline": None, "ratio": None,
                "baseline_windows": len(history), "note": ""}
            if p95_now is None:
                row["note"] = "no values this window"
            elif len(history) < TAIL_MIN_BASELINE:
                row["note"] = "baseline too short"
            else:
                p95_base = float(median(history))
                row["p95_baseline"] = p95_base
                if p95_base > 0:
                    row["ratio"] = p95_now / p95_base
                    ratios.append(row["ratio"])
                else:
                    row["note"] = "baseline zero"
            detail[metric] = row
        indicators.detail["tail"] = detail
        if ratios:
            indicators.tail_deviation = max(ratios)
            indicators.evaluable["tail_deviation"] = True
        else:
            indicators.evaluable["tail_deviation"] = False
        return now

    # ---------------------------------------------------------- the rules
    def _evidence(self, indicators: BehaviouralIndicators,
                  z: Dict[str, float]):
        """
        Which kinds fired this window, and on which indicators.

        Returns (kinds, evidence lines, hits, not_evaluated): `hits` maps
        each indicator that counted to the kind it fed. Pure: reads the
        window and the z-scores, writes nothing.

        The operational kinds are read first, because a *fall* in message
        frequency or interaction density is evidence only when one of them
        is also present: a quiet facility with normal output is not
        deviating, and a quiet facility whose parcels are not leaving is.
        Below MIN_ACTIVITY events the behavioural kinds are not read at all;
        the operational ones are, because they come from parcel events and
        the state of the building rather than from chatter.
        """
        quiet = indicators.events < MIN_ACTIVITY
        kinds: List[str] = []
        evidence: List[str] = []
        hits: Dict[str, str] = {}
        not_evaluated: List[str] = list(BEHAVIOURAL_KINDS) if quiet else []
        if quiet:
            evidence.append(f"only {indicators.events} events in the window; "
                            "behavioural kinds not evaluated")

        ordered = list(OPERATIONAL_KINDS) + list(BEHAVIOURAL_KINDS)
        operational_present = False
        for kind in ordered:
            if kind in not_evaluated:
                continue
            names = EVIDENCE[kind]
            fired: List[str] = []
            for name in names:
                way = deviates(name, z.get(name, 0.0))
                if way == "none":
                    continue
                if (way == "down" and name in CORROBORATED_FALL
                        and not operational_present):
                    continue
                fired.append(name)
            if fired:
                kinds.append(kind)
                if kind in OPERATIONAL_KINDS:
                    operational_present = True
                for name in fired:
                    hits[name] = kind
                    evidence.append(
                        f"{name.replace('_', ' ')} at {z[name]:+.1f}"
                        f" standard deviations")
        # The kinds in the table's order, so a reader sees the same list
        # whichever rule read them first.
        kinds = [kind for kind in EVIDENCE if kind in kinds]
        return kinds, evidence, hits, not_evaluated

    def _classify(self, indicators: BehaviouralIndicators,
                  z: Dict[str, float]):
        """
        The rules, in words: independent evidence, then how far it has spread,
        then whether the statistics say a transition rather than a bad patch.

        Ordered from the most serious down, and every branch says what made it
        fire. An assessment nobody can argue with is an assessment nobody can
        check.
        """
        kinds, evidence, _hits, not_evaluated = self._evidence(indicators, z)
        if not_evaluated and not kinds:
            # Too quiet to read the agents, and nothing operational is off:
            # there is nothing to read yet, and the assessment says so.
            return OperationalState.STABLE, [], evidence

        # Only the kinds that were also there last time. The window before is
        # the shortest test of persistence there is, and the cheapest.
        confirmed = [kind for kind in kinds if kind in self._last_kinds]

        propagation = indicators.propagation_across_agents
        dragon = dragon_king(list(self._severity))
        warning = precursors(list(self._severity))

        # Three kinds now, at least one of which was already there. The
        # persistence bar is lower here than for UNSTABLE on purpose: during a
        # real regime change the symptoms *rotate* -- refusals give way to
        # congestion, congestion to spread -- and demanding the same three
        # kinds twice running would be demanding that a crisis hold still.
        # What must hold still is that something does, which is what the one
        # confirmed kind asks for.
        if (len(kinds) >= RCT_KINDS and confirmed
                and propagation >= RCT_PROPAGATION
                and (dragon.is_dragon or warning.slowing_down)):
            why = ("an extreme above what the tail predicts"
                   if dragon.is_dragon else "variance and memory both climbing")
            evidence.append(
                f"{len(kinds)} independent kinds of evidence, "
                f"{len(confirmed)} of them holding from the window before, "
                f"{propagation:.0%} of the acting agents affected, and {why}")
            return OperationalState.RCT, kinds, evidence

        if len(confirmed) >= UNSTABLE_KINDS:
            evidence.append(f"{len(confirmed)} independent kinds of evidence, "
                            "each holding from the window before")
            return OperationalState.UNSTABLE, kinds, evidence

        if kinds and self._persistence >= PERSISTENT:
            evidence.append(
                f"off baseline for {self._persistence} windows running")
            return OperationalState.UNSTABLE, kinds, evidence

        if kinds:
            return OperationalState.DEVIATING, kinds, evidence

        return OperationalState.STABLE, kinds, evidence

    # ------------------------------------------------- the human gate
    def validate(self, by: str = "operator", note: str = "") -> Optional[Assessment]:
        """A person agrees with the current reading."""
        return self._decide(DiscoveryStatus.VALIDATED, by, note)

    def activate(self, by: str = "operator", note: str = "") -> Optional[Assessment]:
        """A validated reading is being acted on."""
        if self.current is None or self.current.status is not DiscoveryStatus.VALIDATED:
            return None
        return self._decide(DiscoveryStatus.ACTIVE, by, note)

    def dismiss(self, by: str = "operator", note: str = "") -> Optional[Assessment]:
        """A person disagrees. Kept, because it is evidence about the model."""
        return self._decide(DiscoveryStatus.DISMISSED, by, note)

    def _decide(self, status: DiscoveryStatus, by: str, note: str):
        from datetime import datetime, timezone

        if self.current is None:
            return None
        self.current.status = status
        self.current.decided_by = by or "operator"
        self.current.decided_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds")
        self.current.note = note
        return self.current

    # ---------------------------------------------------------------- state
    def series(self, limit: int = 120) -> Dict[str, Any]:
        """The recent assessments, shaped for drawing."""
        rows = self.history[-int(limit):]
        return {
            "ticks": [row.tick for row in rows],
            "states": [row.state.value for row in rows],
            "severity": [round(row.severity, 4) for row in rows],
            "indicators": {
                name: [round(getattr(row.indicators, name), 4) for row in rows]
                for name in INDICATOR_NAMES},
        }

    def state(self) -> Dict[str, Any]:
        current = self.current
        return {
            "every": self.every, "window": self.window,
            "baseline": self.baseline,
            "assessments": len(self.history),
            "persistence": self._persistence,
            "current": current.as_dict() if current else None,
            "counts": {state.value: sum(1 for row in self.history
                                        if row.state is state)
                       for state in OperationalState},
            "validated": sum(1 for row in self.history
                             if row.status is DiscoveryStatus.VALIDATED),
            "dismissed": sum(1 for row in self.history
                             if row.status is DiscoveryStatus.DISMISSED),
        }
