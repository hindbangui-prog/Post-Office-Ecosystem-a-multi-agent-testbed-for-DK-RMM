"""
P7-ONOFF-MODEL: the Phase 7 ON-OFF agent misbehaviour on experts that decide
by their rules first and consult the model when a rule says it is
insufficient.

The configuration is `onoff_attack`'s, imported and not copied: the same four
ON phases (1200-1500, 1800-2200, 2500-3000, 3300-3800), the same displacement
(ROUTING answers WAIT to every blocked robot, SCHEDULING gives every errand the
lowest-battery able robot and starts the non-urgent task with the most slack),
the same hospital consignment of 20 urgent parcels between 1400 and 3400, the
same horizon 4400, the same seeds. Nothing in it is re-derived here, so a
rules-only run of `p7-onoff` and a run of this preset on the same seed differ
in one thing only: which path the targeted decisions take.

That path is the project's own, untouched (`agents/base.py`): the Python rule
answers first; when it is insufficient (ROUTING's `still_blocked` after six
ticks of blockage, `low_on_charge`, `expensive_detour`; SCHEDULING's peer
conditions) the expert consults the model through CrewAI and the
consultation service, the gate validates the answer, and the recorded
decision is what the ON phase displaces or the OFF phase acts on. The frozen
Phase 7 confirmation ran on rules alone, so there are no frozen artifacts for
this preset: every run shows its own outcome, nothing is replayed and nothing
is claimed to be reproduced. The preset needs the experts on the model and
refuses to run on a rules-only app, as the C2 condition of C2-NEAR does.

What this module adds is observation for the live page (`OnOffModelFaults`,
a subclass of `OnOffFaults` that changes nothing about the run):

- the model's part per phase (before the window, ON 1, OFF 1, ..., after the
  window): the targeted decisions ROUTING and SCHEDULING took, how many the
  rule answered, how many went to the model and how those ended at the gate
  (accepted, rejected, nothing usable), how many were displaced, the raw
  model calls, the triggers that sent a decision to the model;
- every blocked streak that ROUTING was asked about, with the answers it
  gave during the streak by path (rule, model, displaced) and the last answer
  before the block cleared, so the page can say what a block ended on
  without inferring more than the record holds (the other robot may simply
  have moved);
- the rules-only reference of the same seed, for the side-by-side column:
  `p7_rules_reference.json`, computed by `tools/p7_rules_reference.py` from
  the existing `p7-onoff` preset for the seed picker's six seeds. A seed
  outside the file has no reference and the page says so.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import onoff_attack as base
from .onoff_attack import (AGENTS, ATTACK_END, ATTACK_START, DEMO_SEED, OnOffFaults, PHASES,
                           POLICY_KINDS, RUN_TICKS, SEED_OPTIONS, TRAPPED_SEEDS, phase_at)

# ------------------------------------------------------------------ identity
STUDY = "P7-ONOFF-MODEL"
PRESET = "p7-onoff-model"
SCENARIO_ID = "P7-ONOFF-MODEL"
#: The selector's label (2026-10-23; until then "Phase 7 · ON–OFF Agent
#: Misbehaviour · rules first, model when insufficient · CrewAI ·
#: Ollama/{model}"). It no longer names the model; `label()` still takes one
#: so its callers are unchanged, and the page names the model on its own badge.
LABEL_TEMPLATE = "ON-OFF, model"
MECHANISM = base.MECHANISM
#: The decision kinds the misbehaviour can displace, per targeted agent.
TARGETED: Dict[str, List[str]] = {agent: list(POLICY_KINDS[agent]) for agent in AGENTS}
#: Where the rules-only reference figures live.
REFERENCE_PATH = Path(__file__).with_name("p7_rules_reference.json")
#: How many ended blocked streaks the status carries (the newest).
RESOLUTIONS_KEPT = 60


def label(model: Optional[str] = None) -> str:
    """The scenario's label naming `model` (the configured one when None)."""
    from ..config.settings import _model_name

    return LABEL_TEMPLATE.format(model=_model_name(model))


def phase_key(tick: int) -> str:
    """`before`, `ON1`, `OFF1`, ..., `after`: the phase a tick falls in, as the per-phase tallies key it."""
    ph = phase_at(int(tick))
    if ph.get("before_window"):
        return "before"
    if ph.get("after_window"):
        return "after"
    return f"{ph['phase']}{int(ph['k']) + 1}"


def phase_keys() -> List[str]:
    """Every phase key in clock order."""
    keys = ["before"]
    for ph in PHASES:
        keys.append(f"ON{ph['k'] + 1}")
        if ph["off_to"] < ATTACK_END:
            keys.append(f"OFF{ph['k'] + 1}")
    keys.append("after")
    return keys


PHASE_KEYS: List[str] = phase_keys()


def _tally() -> Dict[str, Any]:
    return {"decisions": 0, "rule": 0, "model_asked": 0, "model_accepted": 0, "model_rejected": 0,
            "model_failed": 0, "displaced": 0, "llm_calls": 0, "by_agent": {}, "by_trigger": {}}


# ------------------------------------------------------------- the reference
@lru_cache(maxsize=1)
def _reference_file() -> Dict[str, Any]:
    try:
        return json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def reference(seed: int) -> Dict[str, Any]:
    """
    The rules-only figures of `p7-onoff` on `seed` from `p7_rules_reference.json`
    (`available: True` and the figures), or `available: False` with the seeds
    the file holds, when the seed is not among them or the file is missing.
    """
    data = _reference_file()
    runs = data.get("runs") or {}
    row = runs.get(str(int(seed)))
    if row is None:
        return {"available": False, "seed": int(seed), "seeds": sorted(int(s) for s in runs),
                "preset": base.PRESET, "source": data.get("source", "")}
    return {"available": True, "seed": int(seed), "preset": base.PRESET,
            "source": data.get("source", ""), "computed": data.get("computed", ""), **row}


# ------------------------------------------------------------- the observer
class OnOffModelFaults(OnOffFaults):
    """
    `OnOffFaults` with the model's part observed. The arrivals and the
    displacement are installed by the base class at construction, from the
    frozen specification; this class only listens to the event log and reads
    the robots, and changes nothing about the run.
    """

    def __init__(self, eco: Any, seed: int, ticks: int = RUN_TICKS, model: Optional[str] = None) -> None:
        #: Per phase key: how the targeted decisions were taken.
        self.model_by_phase: Dict[str, Dict[str, Any]] = {key: _tally() for key in PHASE_KEYS}
        #: Per robot, during its current blocked streak: ROUTING's answers by path and the last one.
        self._streak_model: Dict[str, Dict[str, Any]] = {}
        #: Ended blocked streaks ROUTING was asked about, newest last.
        self.resolutions: List[Dict[str, Any]] = []
        self.resolution_counts: Dict[str, int] = {"rule": 0, "model": 0, "displaced": 0, "none": 0}
        self._last_decision_by_agent: Dict[str, Dict[str, Any]] = {}
        self.model_name = model
        super().__init__(eco, seed, ticks)

    # ------------------------------------------------------------- listening
    def _streak_row(self, robot: str) -> Dict[str, Any]:
        row = self._streak_model.get(robot)
        if row is None:
            row = self._streak_model[robot] = {"rule": 0, "model": 0, "displaced": 0, "asked": 0, "last": None}
        return row

    @staticmethod
    def _path_word(detail: Dict[str, Any]) -> str:
        """`rule` or `model` for a recorded decision: the gate's `fallback` is the rule's answer after the model."""
        mode = str(detail.get("mode", ""))
        path = str(detail.get("path", ""))
        if mode == "llm" and path.startswith("llm/"):
            return "model"
        return "rule"

    def _on_event(self, event: Any) -> None:
        super()._on_event(event)
        try:
            topic = event.topic
            actor = str(event.actor or "")
            if actor not in TARGETED:
                return
            detail = event.detail or {}
            # The phase a decision belongs to is the one it was taken in: on
            # the live clock the model answers ticks later, and its decision
            # event (and any displacement) carry the tick it was asked
            # (`request_tick`, `initiated_tick`). A model call's tick is
            # already its consultation's.
            taken = detail.get("request_tick", detail.get("initiated_tick", event.tick))
            tally = self.model_by_phase[phase_key(int(taken if taken is not None else event.tick))]
            if topic == "llm_call":
                tally["llm_calls"] += 1
                agent_row = tally["by_agent"].setdefault(actor, {"decisions": 0, "rule": 0, "model_asked": 0,
                                                                  "model_accepted": 0, "displaced": 0, "llm_calls": 0})
                agent_row["llm_calls"] += 1
                return
            kind = str(detail.get("decision", ""))
            if kind not in TARGETED[actor]:
                return
            agent_row = tally["by_agent"].setdefault(actor, {"decisions": 0, "rule": 0, "model_asked": 0,
                                                              "model_accepted": 0, "displaced": 0, "llm_calls": 0})
            if topic == "decision":
                tally["decisions"] += 1
                agent_row["decisions"] += 1
                mode = str(detail.get("mode", ""))
                status = str(detail.get("status", ""))
                word = self._path_word(detail)
                if mode == "llm":
                    tally["model_asked"] += 1
                    agent_row["model_asked"] += 1
                    trigger = str(detail.get("trigger") or "unknown")
                    tally["by_trigger"][trigger] = tally["by_trigger"].get(trigger, 0) + 1
                    if status == "llm_accepted":
                        tally["model_accepted"] += 1
                        agent_row["model_accepted"] += 1
                    elif status == "llm_rejected":
                        tally["model_rejected"] += 1
                    else:
                        tally["model_failed"] += 1
                else:
                    tally["rule"] += 1
                    agent_row["rule"] += 1
                last = {"tick": int(event.tick), "kind": kind, "choice": str(detail.get("choice")),
                        "by": word, "trigger": str(detail.get("trigger") or ""), "displaced_to": None}
                self._last_decision_by_agent[actor] = last
                if actor == "ROUTING" and kind == "resolve_block":
                    robot = str((detail.get("facts") or {}).get("robot"))
                    w = self.watch.get(robot)
                    if w is not None and w.streak > 0:
                        row = self._streak_row(robot)
                        row["asked"] += 1
                        row[word] += 1
                        row["last"] = dict(last, robot=robot)
            elif topic == "attack_displaced":
                tally["displaced"] += 1
                agent_row["displaced"] += 1
                last = self._last_decision_by_agent.get(actor)
                if last is not None and last.get("kind") == kind:
                    last["displaced_to"] = str(detail.get("displaced"))
                    if actor == "ROUTING":
                        # The displaced answer follows the honest decision event
                        # of the same call, which named the robot (base class).
                        row = self._streak_model.get(str(self._last_routing_robot or ""))
                        if (row is not None and row.get("last") is not None
                                and row["last"].get("tick") == int(event.tick)):
                            row["last"]["displaced_to"] = str(detail.get("displaced"))
                            row["displaced"] += 1
                            row[row["last"]["by"]] -= 1   # the answer acted on was the displaced one
        except Exception:
            pass   # an observer never stops a tick

    # ------------------------------------------------------------- the clock
    def observe(self, tick: int) -> None:
        """Before the base class resets an ended streak, keep what ROUTING answered during it."""
        tick = int(tick)
        if tick <= self._observed_tick or tick < 0:
            return
        for robot in self.eco.fleet.all():
            w = self.watch[robot.robot_id]
            if robot.status.value != "BLOCKED" and w.streak > 0:
                row = self._streak_model.pop(robot.robot_id, None)
                if row is not None and row["asked"]:
                    last = row["last"] or {}
                    ended_on = ("displaced" if last.get("displaced_to") else last.get("by") or "none")
                    self.resolution_counts[ended_on] = self.resolution_counts.get(ended_on, 0) + 1
                    self.resolutions.append({
                        "robot": robot.robot_id, "start": w.streak_start, "end": tick,
                        "ticks": int(w.streak), "phase": phase_key(int(w.streak_start or tick)),
                        "answers": {"rule": int(row["rule"]), "model": int(row["model"]),
                                    "displaced": int(row["displaced"])},
                        "last": last, "ended_on": ended_on,
                        "ticks_after_last": (tick - int(last["tick"])) if last.get("tick") is not None else None,
                        "trapped": w.trapped_since is not None,
                    })
                    del self.resolutions[:-RESOLUTIONS_KEPT]
                elif row is not None:
                    self.resolution_counts["none"] += 1
        super().observe(tick)

    # -------------------------------------------------------------- reports
    def model_report(self) -> Dict[str, Any]:
        """The model's part of the run so far, per phase and in all."""
        total = _tally()
        for tally in self.model_by_phase.values():
            for key in ("decisions", "rule", "model_asked", "model_accepted", "model_rejected",
                        "model_failed", "displaced", "llm_calls"):
                total[key] += int(tally[key])
            for trigger, n in tally["by_trigger"].items():
                total["by_trigger"][trigger] = total["by_trigger"].get(trigger, 0) + int(n)
            for agent, row in tally["by_agent"].items():
                acc = total["by_agent"].setdefault(agent, {k: 0 for k in row})
                for k, v in row.items():
                    acc[k] = acc.get(k, 0) + int(v)
        now = int(self.eco.world.tick)
        ongoing = []
        for robot, row in self._streak_model.items():
            w = self.watch.get(robot)
            if w is not None and w.streak > 0 and row["asked"]:
                ongoing.append({"robot": robot, "start": w.streak_start, "ticks": int(w.streak),
                                "answers": {"rule": int(row["rule"]), "model": int(row["model"]),
                                            "displaced": int(row["displaced"])},
                                "last": row["last"], "trapped": w.trapped_since is not None})
        return {
            "agents": list(AGENTS), "kinds": {a: list(k) for a, k in TARGETED.items()},
            "phase_keys": list(PHASE_KEYS), "phase_now": phase_key(now),
            "by_phase": {key: dict(tally) for key, tally in self.model_by_phase.items()},
            "total": total,
            "resolutions": list(self.resolutions),
            "resolution_counts": dict(self.resolution_counts),
            "ongoing": ongoing,
            "model": self.model_name,
            "note": "the targeted decisions of ROUTING and SCHEDULING by the path they took; a block's last "
                    "answer is what ROUTING said before it cleared, not proof that it cleared it",
        }

    def summary(self) -> Dict[str, Any]:
        out = super().summary()
        out["model"] = self.model_report()
        out["note"] = ("observed events of this run on the rules-first, model-when-insufficient path; no frozen "
                       "artifacts exist for it, DK-RMM's alerts are reported separately and this run is not "
                       "labelled a confirmed Dragon-King")
        return out

    def status(self) -> Dict[str, Any]:
        out = super().status()
        out.update({"scenario": SCENARIO_ID, "preset": PRESET, "label": label(self.model_name),
                    "variant": "model", "rules_preset": base.PRESET,
                    "model": self.model_report(), "reference": reference(self.seed)})
        return out


__all__ = ["AGENTS", "ATTACK_END", "ATTACK_START", "DEMO_SEED", "LABEL_TEMPLATE", "MECHANISM",
           "OnOffModelFaults", "PHASE_KEYS", "PRESET", "REFERENCE_PATH", "RUN_TICKS", "SCENARIO_ID",
           "SEED_OPTIONS", "STUDY", "TARGETED", "TRAPPED_SEEDS", "label", "phase_key", "phase_keys",
           "reference"]
