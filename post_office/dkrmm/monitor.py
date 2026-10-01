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
from typing import Any, Deque, Dict, List, Optional, Sequence

from .indicators import (INDICATOR_NAMES, BehaviouralIndicators,
                         compute_indicators)
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


#: The evidence kinds, and which indicators speak for each. Grouped so that
#: three indicators all driven by the same underlying event -- refusals push
#: up guardrail events and propagation together -- cannot be counted as three
#: independent findings, which is exactly how a monitor talks itself into a
#: crisis.
EVIDENCE = {
    "refusal": ("guardrail_events",),
    "retry": ("retry_frequency",),
    "congestion": ("execution_latency", "task_switching"),
    "chatter": ("message_frequency", "delegation_frequency",
                "tool_call_frequency", "interaction_density"),
    "herding": ("behavioural_similarity", "agent_coupling"),
    "spread": ("propagation_across_agents",),
}


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
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "note": self.note,
        }


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
        indicators = compute_indicators(
            events, ticks=min(self.window, max(1, now)), roster=roster,
            created=self._created, persistence=self._persistence)

        # Each indicator against its own past, *before* this window joins it:
        # a baseline that already contains the reading is a baseline that has
        # started explaining away the thing it is supposed to detect.
        values = indicators.values()
        z = {name: zscore(values[name], self._series[name])
             for name in INDICATOR_NAMES}
        for name in INDICATOR_NAMES:
            self._series[name].append(values[name])

        # One number for the window, so the dragon-king test has a series to
        # work on. Only the upside counts: an indicator that has gone quiet is
        # not evidence of a crisis.
        severity = sum(max(0.0, score) for score in z.values()) / len(z)
        self._severity.append(severity)

        state, kinds, evidence = self._classify(indicators, z)
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

        assessment = Assessment(
            tick=now, state=state, previous=previous,
            status=DiscoveryStatus.DISCOVERED,
            indicators=indicators, z=z, evidence=evidence, kinds=kinds,
            severity=severity,
            enough_activity=indicators.events >= MIN_ACTIVITY,
            precursors=precursors(list(self._severity)),
            dragon=dragon_king(list(self._severity)),
        )
        self.current = assessment
        self.history.append(assessment)
        if len(self.history) > HISTORY:
            del self.history[:len(self.history) - HISTORY]
        return assessment

    def _classify(self, indicators: BehaviouralIndicators,
                  z: Dict[str, float]):
        """
        The rules, in words: independent evidence, then how far it has spread,
        then whether the statistics say a transition rather than a bad patch.

        Ordered from the most serious down, and every branch says what made it
        fire. An assessment nobody can argue with is an assessment nobody can
        check.
        """
        if indicators.events < MIN_ACTIVITY:
            return (OperationalState.STABLE, [],
                    [f"only {indicators.events} events in the window; too "
                     "little happening to read collective behaviour"])

        kinds: List[str] = []
        evidence: List[str] = []
        for kind, names in EVIDENCE.items():
            hits = [name for name in names if z.get(name, 0.0) >= DEVIATION_Z]
            if hits:
                kinds.append(kind)
                for name in hits:
                    evidence.append(
                        f"{name.replace('_', ' ')} at {z[name]:+.1f}"
                        f" standard deviations")

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
