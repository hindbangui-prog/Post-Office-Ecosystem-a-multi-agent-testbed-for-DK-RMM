"""
Which robot takes this job.

The project's own `agents/brain.py` names this as a canonical example of a
decision a language model might make better than a rule, and until now it was
the one judgement in the system with no sub-agent and no brain behind it: a
tuple comparison inside the scheduler, `(distance, -battery, robot_id)`, taking
the nearest free robot and breaking ties on charge.

That ordering is defensible and frequently right, which is exactly why it was
easy to leave alone. It is also flatly wrong in the cases that matter. A robot
four cells away with twelve percent charge will reach the parcel and then have
to abandon the errand to go and charge, leaving the parcel where it started and
the job to be issued again; a robot twelve cells away with ninety-five percent
will simply do it. Distance, remaining charge, the length of the whole errand
and how close the parcel is to missing its van do not reduce to a sort key, and
a rule that pretends they do is the kind of baseline that makes a model look
good for the wrong reason.

So the scheduler asks. The sub-agent is handed every free robot with what is
known about it and returns one of them; the deterministic rule below scores
them, and a model put behind this agent is choosing from the same list on the
same facts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...communication.message import Message
from ..base import SubAgent
from ..brain import Answer, Question

#: What a robot is assumed to spend per cell, the same figure the battery
#: sub-agent estimates with. Duplicated as a constant rather than imported so
#: that this agent's rule is readable on its own; both trace back to
#: `robots/robot.py`'s MOVE_COST.
COST_PER_CELL = 0.55

#: How much charge a robot should have left after finishing, before this agent
#: will send it. Below this it is choosing a robot that will strand itself.
MARGIN = 12.0


class AssignmentSubAgent(SubAgent):
    """Chooses which free robot is sent on an errand."""

    def __init__(self, parent_id: str, agent_id: str = "SUB-ASSIGNMENT", **kw):
        super().__init__(agent_id, "robot assignment", parent_id, **kw)
        #: How many times the scheduler has consulted it. Worth counting: this
        #: agent exists because a decision that was never asked was being made
        #: anyway, and a run in which it is never asked is that state returning.
        self.asked = 0

    def perform(self, message: Message) -> Optional[Dict[str, Any]]:
        content = message.content
        candidates: List[Dict[str, Any]] = list(content.get("robots") or ())
        if not candidates:
            return {"operation": "choose_robot", "ok": False,
                    "reason": "no robot free",
                    "_text": "Nothing free to send."}

        self.asked += 1
        errand = float(content.get("errand_cells", 0) or 0)
        about: Dict[str, Any] = {}
        for c in candidates:
            distance = float(c.get("distance", 0) or 0)
            battery = float(c.get("battery", 0) or 0)
            # What the errand would cost this robot, worked out here because
            # measuring is the tool's job. Whether to send it anyway is not.
            spend = (distance + errand) * COST_PER_CELL
            about[c["robot_id"]] = {
                "distance": c.get("distance"),
                "battery": c.get("battery"),
                "carrying": c.get("carrying"),
                "cost": round(spend, 1),
                "left_after": round(battery - spend, 1),
                "can_finish": bool(battery - spend >= MARGIN),
            }
        able = sorted(r for r, d in about.items() if d["can_finish"])
        return {
            "operation": "choose_robot",
            "ok": True,
            "candidates": sorted(about),
            "robots": about,
            # The ones that could finish the errand with the margin intact.
            # Arithmetic, and the same answer every time; which of them
            # actually goes is the scheduler's call.
            "able": able,
            "errand_cells": content.get("errand_cells", 0),
            "priority": content.get("priority", "NORMAL"),
            "slack": content.get("slack"),
            "_text": (f"{len(about)} free, {len(able)} could finish "
                      f"{content.get('parcel_id') or 'the job'}."),
        }
