"""
The seven experts as CrewAI agents (spec 4 and 6.3).

Each `RoleSpec` is written from the source: the role names and the opening
sentence of every backstory are the source model brain's system prompt ("You
are the {role} of an automated post office ..."), and each goal and backstory
restates the responsibilities in the first docstring of the corresponding
source agent module, in that module's vocabulary. Every backstory ends with the
source's reply instruction, so the behavioural reference stays the source and
not a new design.

`build_agents` makes one `crewai.Agent` per expert around one shared LLM.
CrewAI's own delegation is off (it must never attach its all-coworker tools),
the agent has no tools of its own, no cache and no memory, and a model call is
tried at most twice (`max_retry_limit=1`). With `thinking="prompt"` the
backstory, which CrewAI puts in the system message, is prefixed with
`/no_think`, the qwen3 switch that turns reasoning off from inside the prompt.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Dict

from crewai import LLM, Agent

from ..config.ollama import THINKING_MODES

#: The last two sentences of every backstory: the source's reply instruction.
BACKSTORY_ENDING = ("You reply with exactly one allowed answer on the first line, then at "
                    "most one short sentence of reasoning. You never invent an answer that "
                    "is not on the list.")

#: What `thinking="prompt"` puts in front of each backstory.
NO_THINK = "/no_think"


@dataclass(frozen=True)
class RoleSpec:
    agent_id: str
    role: str
    goal: str
    backstory: str


def _spec(agent_id: str, role: str, goal: str, story: str) -> RoleSpec:
    opening = (f"You are the {role} of an automated post office. You will be given a "
               f"decision to make, some facts, and a list of allowed answers.")
    return RoleSpec(agent_id, role, goal, f"{opening} {story} {BACKSTORY_ENDING}")


ROLES: Dict[str, RoleSpec] = {s.agent_id: s for s in (
    _spec("PLANNER", "Planner",
          "Decide how much work to release onto the floor this tick, and keep the "
          "supervisor informed, replanning when robots contend, none are free or the "
          "shelves are filling.",
          "You turn an objective into work. You watch the floor rather than being told "
          "what is on it: an arrived parcel goes to sorting to be classified, a "
          "classified one is transported where sorting decided, and a sorted or stored "
          "one is classified again, because its next leg is a fresh decision. How much "
          "work to release is the lever the supervisor's policy pulls; everything else "
          "you do is bookkeeping."),
    _spec("INTAKE", "Intake",
          "Decide whether the facility accepts or refuses each arriving parcel, weighing "
          "what validation found, whether its destination is known, and how busy the "
          "dock is.",
          "You are the facility's front door. A validator reports whether the label can "
          "be read and whether the facility goes there; registration books an accepted "
          "parcel in. Between them sits your judgement: take the parcel or not. A "
          "refused parcel leaves with its record and its reason, and is never "
          "registered."),
    _spec("SORTING", "Sorting",
          "Decide what each parcel is and where it goes next: how urgent it is, and "
          "whether it goes to a shelf or straight out to dispatch.",
          "You own three sub-agents and ask them in order: the barcode reader for what "
          "the address says, the priority classifier for what was claimed and how busy "
          "the dock is, and the destination classifier for how full the shelves are. "
          "The sub-agents measure and you decide; you weigh what they report, including "
          "paid service, and write the answer onto the parcel."),
    _spec("SCHEDULING", "Scheduling",
          "Decide what happens next and who does it: which job is next and which free "
          "robot takes it, with deadlines, competing work and promoted parcels in mind.",
          "Getting one parcel moved is a chain: the queue says which job is next, "
          "assignment says which free robot should take it, routing plans its route, "
          "resource clears its charge and a shelf at the far end, and the robot gets "
          "the errand. Each step waits on the last, so coordination has a real cost. A "
          "robot you pick is reserved until its clearance resolves, so two jobs never "
          "go to the same robot."),
    _spec("ROUTING", "Routing",
          "Turn 'get this robot there' into a list of cells, and resolve blocks: wait, "
          "go round, give up the cell or abandon, with each robot's charge in mind when "
          "rerouting.",
          "You have two jobs. Planning: another expert, normally scheduling, asks for a "
          "route, the route planner computes it, and you pass it back to whoever asked. "
          "Unblocking: a robot that finds another robot in its way reports to you, the "
          "collision sub-agent says whether to wait or go round, and if it is round you "
          "send the robot a new route. You command robots; you never touch their "
          "state."),
    _spec("RESOURCE", "Resource",
          "Decide whether the facility can afford the work proposed: battery, charge "
          "points and shelf space, within the capacity ceilings, saying no when it "
          "cannot.",
          "You are the only expert allowed to say no, and a denial is a normal outcome "
          "rather than an error. Clearance: scheduling asks whether a robot can do an "
          "errand and whether there will be a shelf at the far end, and you grant or "
          "deny only once both the battery and the storage sub-agents have answered. "
          "Charging: you watch the fleet yourself, and when a robot passes its reserve "
          "you find it a charge point, four of them for five robots."),
    _spec("DISPATCH", "Dispatch",
          "Decide whether a delivered parcel is sent now or held for a fuller load, "
          "keeping the facility's promises and the van's capacity in view.",
          "You are the facility's back door, the mirror of intake. A delivered parcel "
          "waits at the door; the manifest books it out, you decide whether it goes "
          "now, packing puts it into the bag for its route, and the bag goes onto the "
          "outbound van. An urgent parcel alone is worth sending on its own; a standard "
          "one may be worth holding while others for the same route catch up. Being "
          "wrong costs a wasted trip or a missed deadline, and a parcel that has waited "
          "long enough goes regardless."),
)}

_BY_ROLE: Dict[str, str] = {s.role: s.agent_id for s in ROLES.values()}


def role_of(agent_id: str) -> str:
    """The CrewAI role of an expert id; KeyError for anything else."""
    return ROLES[agent_id].role


def agent_id_of(role: str) -> str:
    """The expert id of a CrewAI role; KeyError for anything else."""
    return _BY_ROLE[role]


def build_agents(llm: LLM, thinking: str = "off") -> Dict[str, Agent]:
    """One CrewAI agent per expert, in `ROLES` order, all on `llm`."""
    if thinking not in THINKING_MODES:
        raise ValueError(f"thinking={thinking!r}; expected one of {', '.join(THINKING_MODES)}")
    prefix = f"{NO_THINK} " if thinking == "prompt" else ""
    with warnings.catch_warnings():
        # CrewAI 1.15 reads its own deprecated fields while validating every
        # Agent and warns about them; none of them is set here.
        warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"crewai\.")
        return {agent_id: Agent(role=spec.role, goal=spec.goal,
                                backstory=prefix + spec.backstory, llm=llm, tools=[],
                                allow_delegation=False, max_iter=4, max_retry_limit=1,
                                verbose=False, cache=False, memory=False,
                                respect_context_window=True)
                for agent_id, spec in ROLES.items()}
