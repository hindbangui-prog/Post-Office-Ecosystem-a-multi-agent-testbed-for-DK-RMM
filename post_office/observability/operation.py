"""
The operation watch: the fleet's and the work's condition as facts, read
beside DK-RMM on the monitor's own clock, with the monitor's state words applied to those facts.

Why it exists. DK-RMM's evidence is behavioural: an indicator two standard
deviations off a rolling baseline. A failure that lasts becomes the baseline
(seed 11977 of the Phase 7 scenario: two robots locked head to head from tick
1210 to the horizon, DK-RMM back to STABLE from 2601 while they stand), and
the monitor's propagation counts actors, not robots, so two of five robots
is two of about thirteen actors, below the half the RCT rule asks for. This
watch reports what the fleet is doing in terms that cannot drift: a robot is
blocked for so many consecutive ticks, with or without an errand, by whom.
Nothing in `dkrmm` is read for its state words' sake or changed; the monitor's
own propagation and state are quoted beside the fleet's figures so that the
two accounts can be compared on the same reading.

The facts (`KINDS`), one per kind of evidence, present or not at each
assessment:

    blocked    a robot has been BLOCKED for BLOCK_TICKS consecutive ticks or
               more and holds an errand
    orphaned   the same, holding no errand
    deadlock   two robots have each been blocked by the other for BLOCK_TICKS
               ticks or more
    fleet      the robots in such a block, or in unintentional blockage, number
               FLEET_LOST or more (on a fleet of five: three or fewer available)
    overdue    a parcel is inside the building past the departure the intake
               gate promised it (`due_by`) and has not been bagged or loaded:
               work the building has not finished, in intake, sorting, storage
               or on a robot (a parcel in a bag is committed to the outbound
               stream and waits for the timetable, not for the fleet)
    unintentional
               unintentional blockage: a robot not in a block itself whose way
               ahead has been held, at some tick of the last BLOCK_TICKS, by a
               robot that is in one. It is third in line behind a closed
               pair, its status churning (BLOCKED, WAITING, IDLE, MOVING) as
               it re-plans and shuffles, so no streak of its own ever reaches
               20 ticks; the errand it nominally holds is not in progress and
               it is counted as having no errand, unavailable to the fleet.
               Normal has none by construction (no Normal robot is ever in a
               block, so nothing can be queued behind one); on seed 11977 R5
               is in it at 69 of 220 readings that no streak rule classifies,
               the last 100 ticks to the horizon among them.

`blocked`, `orphaned`, `deadlock`, `fleet` and `unintentional` are facts about
the robots; `overdue` is the fact about the work, and the one the robot facts cannot see: on seed 11977 the fleet's block
begins at 1210, the first promise is missed at 1542, and by tick 2941 fifteen
parcels stand in intake past their departure, nine of them the hospital's.
Normal (seeds 1 and 11, 3,000 ticks) never has one, so presence is the
threshold. The count of parcels in intake is reported in the reading for the
words but is not a kind: Normal peaks at 15, the trapped seed crosses that
only at 2077, some 850 ticks after the block, and the level follows the
arrival rate as much as the fleet.

`BLOCK_TICKS` is 20, one monitor cadence: over 2,000 ticks of Normal on seeds
1 and 11 the longest blocked streak of any robot is 15 ticks, and ROUTING
re-asks about a block at 1, 3, 6 and 9 ticks, so by 20 its rules have had
every look they take.

The states, the paper's words applied to facts (`classify`): STABLE when no
kind is present; DEVIATING when one or more is; UNSTABLE by the paper's
equation (3), two kinds persisting from the previous assessment, or one kind
present with the three preceding assessments non-STABLE; PERSISTENT when a
kind has been present for PERSISTENT_ASSESSMENTS consecutive assessments
(fifteen: 300 ticks, the project's trap definition). A state holds exactly
as long as its condition does; there is no baseline and nothing to habituate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..dkrmm.monitor import EVERY

#: A robot blocked this many consecutive ticks is a fact worth a kind.
BLOCK_TICKS = 20
#: This many robots in such a block is the fleet's fact.
FLEET_LOST = 2
#: A kind present this many consecutive assessments is persistent (300 ticks).
PERSISTENT_ASSESSMENTS = 15
#: The paper's equation (3): two kinds persisting, or one kind with this many
#: preceding non-STABLE assessments.
UNSTABLE_PERSISTING = 2
UNSTABLE_STREAK = 3

KINDS: Tuple[str, ...] = ("blocked", "orphaned", "deadlock", "fleet", "overdue", "unintentional")
#: A blocked streak this long is the Phase 7 trap (`stress.onoff_attack.TRAP_TICKS`),
#: PERSISTENT_ASSESSMENTS readings: the words say "trapped" from here.
TRAP_TICKS = 300
STATES: Tuple[str, ...] = ("STABLE", "DEVIATING", "UNSTABLE", "PERSISTENT")
#: How many assessments are kept in the sequence.
HISTORY = 400


def classify(kinds: Set[str], previous: Set[str], non_stable_streak: int,
             kind_streaks: Dict[str, int]) -> str:
    """
    The state for one assessment: `kinds` present now, `previous` the kinds of
    the assessment before, `non_stable_streak` the consecutive preceding
    non-STABLE assessments (the paper's nu), `kind_streaks` the consecutive
    assessments each kind has been present including this one.
    """
    if not kinds:
        return "STABLE"
    if any(kind_streaks.get(k, 0) >= PERSISTENT_ASSESSMENTS for k in kinds):
        return "PERSISTENT"
    if len(kinds & previous) >= UNSTABLE_PERSISTING or non_stable_streak >= UNSTABLE_STREAK:
        return "UNSTABLE"
    return "DEVIATING"


@dataclass
class RobotStreak:
    robot: str
    ticks: int = 0
    since: Optional[int] = None
    blocked_by: Optional[str] = None
    pair_ticks: int = 0          # consecutive ticks blocked by a robot that is blocked by this one
    #: The last tick at which the way ahead was held by a robot in a block of
    #: BLOCK_TICKS or more, and by whom; the first tick of the current spell.
    behind_at: Optional[int] = None
    behind: Optional[str] = None
    behind_since: Optional[int] = None

    def reset(self) -> None:
        self.ticks, self.since, self.blocked_by, self.pair_ticks = 0, None, None, 0


@dataclass
class Reading:
    tick: int
    state: str
    kinds: List[str]
    robots: List[Dict[str, Any]]
    pairs: List[List[str]]
    fleet_total: int
    fleet_available: int
    rho_fleet: float
    dkrmm_state: Optional[str] = None
    dkrmm_rho: Optional[float] = None
    non_stable_streak: int = 0
    kind_streaks: Dict[str, int] = field(default_factory=dict)
    #: The work: parcels past their promised departure and not yet bagged or
    #: loaded (by zone, and how many are URGENT), and the parcels in intake.
    overdue: int = 0
    overdue_urgent: int = 0
    overdue_by_zone: Dict[str, int] = field(default_factory=dict)
    overdue_oldest: int = 0       # ticks past the earliest missed departure
    intake: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {"tick": self.tick, "state": self.state, "kinds": list(self.kinds), "robots": list(self.robots),
                "pairs": [list(p) for p in self.pairs], "fleet_total": self.fleet_total,
                "fleet_available": self.fleet_available, "rho_fleet": round(self.rho_fleet, 3),
                "overdue": self.overdue, "overdue_urgent": self.overdue_urgent,
                "overdue_by_zone": dict(self.overdue_by_zone), "overdue_oldest": self.overdue_oldest,
                "intake": self.intake,
                "dkrmm_state": self.dkrmm_state,
                "dkrmm_rho": None if self.dkrmm_rho is None else round(self.dkrmm_rho, 3),
                "non_stable_streak": self.non_stable_streak, "kind_streaks": dict(self.kind_streaks)}


class OperationWatch:
    """
    Reads the fleet every tick (the streaks), assesses every `every` ticks on
    the monitor's clock (ticks 1, 21, 41, ...), keeps the sequence. `monitor`
    is DK-RMM, read only for the state and propagation it reports at the same
    moment; None is fine.
    """

    def __init__(self, eco: Any, monitor: Any = None, every: int = EVERY) -> None:
        self.eco = eco
        self.monitor = monitor
        self.every = int(every)
        self.streaks: Dict[str, RobotStreak] = {r.robot_id: RobotStreak(r.robot_id) for r in eco.fleet.all()}
        self.history: List[Reading] = []
        self._last_at = -1
        self._previous_kinds: Set[str] = set()
        self._non_stable_streak = 0
        self._kind_streaks: Dict[str, int] = {}
        self.first_tick: Dict[str, Optional[int]] = {s: None for s in STATES}
        self.counts: Dict[str, int] = {s: 0 for s in STATES}
        #: The current spell of non-STABLE readings: when it began, None when STABLE.
        self.spell_since: Optional[int] = None
        self.persistent_since: Optional[int] = None

    # ------------------------------------------------------------ the clock
    def _blocked_by(self, robot: Any) -> Optional[str]:
        route = getattr(robot, "_route", None) or []
        if len(route) > 1:
            try:
                return self.eco.env.occupied_by_robot(route[1], excluding=robot.robot_id)
            except Exception:
                return None
        return None

    def tick(self, now: Optional[int] = None) -> Optional[Reading]:
        """Once per simulated tick, after the ecosystem stepped: the streaks, and an assessment when due."""
        now = int(self.eco.world.tick if now is None else now)
        for robot in self.eco.fleet.all():
            s = self.streaks.setdefault(robot.robot_id, RobotStreak(robot.robot_id))
            if getattr(robot.status, "value", robot.status) == "BLOCKED":
                if s.ticks == 0:
                    s.since = now
                s.ticks += 1
                s.blocked_by = self._blocked_by(robot)
            else:
                s.reset()
        # Head to head: each blocked by the other, counted per tick on both sides.
        for a, s in self.streaks.items():
            b = s.blocked_by
            if b and self.streaks.get(b) is not None and self.streaks[b].blocked_by == a:
                s.pair_ticks += 1
            else:
                s.pair_ticks = 0
        # Unintentional blockage: the way ahead (whatever the status says) held
        # by a robot in a block; remembered for BLOCK_TICKS so the churn of the
        # queued robot's own status does not hide it.
        for robot in self.eco.fleet.all():
            s = self.streaks[robot.robot_id]
            ahead = self._blocked_by(robot)
            held = ahead if (ahead and self.streaks.get(ahead) is not None
                             and self.streaks[ahead].ticks >= BLOCK_TICKS and s.ticks < BLOCK_TICKS) else None
            if held:
                if s.behind_at is None or now - s.behind_at >= BLOCK_TICKS:
                    s.behind_since = now
                s.behind_at, s.behind = now, held
            elif s.behind_at is not None and now - s.behind_at >= BLOCK_TICKS:
                s.behind_at = s.behind = s.behind_since = None
        if self._last_at >= 0 and now - self._last_at < self.every:
            return None
        self._last_at = now
        return self.assess(now)

    # ------------------------------------------------------- the assessment
    def _dkrmm(self) -> Tuple[Optional[str], Optional[float]]:
        current = getattr(self.monitor, "current", None) if self.monitor is not None else None
        if current is None:
            return None, None
        try:
            state = getattr(getattr(current, "state", None), "value", None)
            rho = getattr(getattr(current, "indicators", None), "propagation_across_agents", None)
            return state, (float(rho) if rho is not None else None)
        except Exception:
            return None, None

    def _work(self, now: int) -> Tuple[int, int, Dict[str, int], int, int]:
        """The parcels: overdue (count, URGENT among them, by zone, oldest miss) and the intake count."""
        overdue = urgent = oldest = intake = 0
        by_zone: Dict[str, int] = {}
        for parcel in self.eco.env.parcels.values():
            carried = getattr(parcel, "position", None) is None
            zone = getattr(parcel, "current_zone", None)
            zone = str(getattr(zone, "value", zone) or "")
            if not carried and zone == "INTAKE":
                intake += 1
            due = getattr(parcel, "due_by", None)
            if due is None or now <= int(due):
                continue
            if getattr(parcel, "bagged_in", "") or getattr(parcel, "loaded_on", ""):
                continue
            overdue += 1
            oldest = max(oldest, now - int(due))
            key = "carried" if carried else zone.lower()
            by_zone[key] = by_zone.get(key, 0) + 1
            prio = getattr(parcel, "priority", None)
            if str(getattr(prio, "value", prio) or "").upper() == "URGENT":
                urgent += 1
        return overdue, urgent, by_zone, oldest, intake

    def assess(self, now: int) -> Reading:
        robots: List[Dict[str, Any]] = []
        kinds: Set[str] = set()
        in_block: List[str] = []
        pairs: List[List[str]] = []
        queued: List[str] = []
        for robot in self.eco.fleet.all():
            s = self.streaks[robot.robot_id]
            errand = robot.current_task or None
            if s.ticks >= BLOCK_TICKS:
                in_block.append(robot.robot_id)
                kinds.add("blocked" if errand else "orphaned")
            unintentional = (s.ticks < BLOCK_TICKS and s.behind_at is not None and now - s.behind_at < BLOCK_TICKS)
            if unintentional:
                queued.append(robot.robot_id)
            robots.append({"robot": robot.robot_id, "blocked_for": int(s.ticks), "since": s.since,
                           "errand": errand, "blocked_by": s.blocked_by,
                           "in_block": s.ticks >= BLOCK_TICKS, "trapped": s.ticks >= TRAP_TICKS,
                           "unintentional": unintentional,
                           "behind": s.behind if unintentional else None,
                           "behind_since": s.behind_since if unintentional else None})
            b = s.blocked_by
            if (s.pair_ticks >= BLOCK_TICKS and b and self.streaks.get(b) is not None
                    and self.streaks[b].pair_ticks >= BLOCK_TICKS and robot.robot_id < b):
                pairs.append([robot.robot_id, b])
        if pairs:
            kinds.add("deadlock")
        if queued:
            kinds.add("unintentional")
        total = len(robots)
        # A robot in unintentional blockage is counted as having no errand:
        # unavailable, like an orphaned one.
        lost = len(in_block) + len(queued)
        available = total - lost
        if lost >= FLEET_LOST:
            kinds.add("fleet")
        overdue, overdue_urgent, overdue_by_zone, overdue_oldest, intake = self._work(now)
        if overdue:
            kinds.add("overdue")
        # Streaks of presence per kind, including this assessment.
        self._kind_streaks = {k: (self._kind_streaks.get(k, 0) + 1) for k in kinds}
        state = classify(kinds, self._previous_kinds, self._non_stable_streak, self._kind_streaks)
        dk_state, dk_rho = self._dkrmm()
        reading = Reading(tick=now, state=state, kinds=sorted(kinds), robots=robots, pairs=pairs,
                          fleet_total=total, fleet_available=available,
                          rho_fleet=(lost / total) if total else 0.0,
                          dkrmm_state=dk_state, dkrmm_rho=dk_rho,
                          non_stable_streak=self._non_stable_streak, kind_streaks=dict(self._kind_streaks),
                          overdue=overdue, overdue_urgent=overdue_urgent, overdue_by_zone=overdue_by_zone,
                          overdue_oldest=overdue_oldest, intake=intake)
        # Bookkeeping for the next assessment and for the digest.
        self._previous_kinds = set(kinds)
        self._non_stable_streak = 0 if state == "STABLE" else self._non_stable_streak + 1
        self.counts[state] += 1
        if self.first_tick[state] is None:
            self.first_tick[state] = now
        if state == "STABLE":
            self.spell_since = None
            self.persistent_since = None
        else:
            if self.spell_since is None:
                self.spell_since = now
            if state == "PERSISTENT" and self.persistent_since is None:
                self.persistent_since = now
            if state != "PERSISTENT":
                self.persistent_since = None
        self.history.append(reading)
        if len(self.history) > HISTORY:
            del self.history[: len(self.history) - HISTORY]
        return reading

    # -------------------------------------------------------------- reports
    def state(self) -> Dict[str, Any]:
        """The digest the page reads: the current reading, the sequence, the counts, the first ticks."""
        current = self.history[-1] if self.history else None
        return {
            "attached": True,
            "every": self.every,
            "block_ticks": BLOCK_TICKS,
            "fleet_lost": FLEET_LOST,
            "persistent_assessments": PERSISTENT_ASSESSMENTS,
            "trap_ticks": TRAP_TICKS,
            "kinds_known": list(KINDS),
            "states": list(STATES),
            "assessments": len(self.history),
            "state": current.state if current else None,
            "tick": current.tick if current else None,
            "current": current.as_dict() if current else None,
            "sequence": [[r.tick, r.state] for r in self.history],
            "counts": dict(self.counts),
            "first_tick": dict(self.first_tick),
            "spell_since": self.spell_since,
            "persistent_since": self.persistent_since,
            "note": "facts about the fleet and the work on DK-RMM's clock, with the monitor's state words applied to facts; "
                    "DK-RMM itself is unchanged and its own state and propagation are quoted beside them",
        }


__all__ = ["BLOCK_TICKS", "FLEET_LOST", "HISTORY", "KINDS", "OperationWatch", "PERSISTENT_ASSESSMENTS",
           "Reading", "RobotStreak", "STATES", "TRAP_TICKS", "UNSTABLE_PERSISTING", "UNSTABLE_STREAK", "classify"]
