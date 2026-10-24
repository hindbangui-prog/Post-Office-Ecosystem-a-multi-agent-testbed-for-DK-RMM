"""
The agent hierarchy.

    SupervisorAgent      plain Python: objective, policy, approval, on/off
      PlannerAgent       decomposes the objective into tasks
        SortingAgent     what is this parcel and where does it go?
        SchedulingAgent  which job next, which robot, in what order?
        RoutingAgent     how does that robot get there?
        ResourceAgent    can the facility afford it? -- the only agent that
                         may say no
          ten sub-agents, three or two each; see agents/subagents/
        RobotAgent       one per robot; the only caller of a robot's methods

Every agent answers `step()` once per tick: read the inbox, then do whatever it
does unprompted. Every judgement goes through `decide()`, which is the seam a
`CrewBrain` slots into without another line changing anywhere.
"""

from .brain import Answer, Brain, ConstantBrain, DeterministicBrain, Question
from .base import BaseAgent, SubAgent
from .supervisor import DEFAULT_OBJECTIVE, SupervisorAgent
from .planner_agent import PlannerAgent
from .sorting_agent import SortingAgent
from .routing_agent import RoutingAgent
from .scheduling_agent import SchedulingAgent
from .resource_agent import ResourceAgent
from .robot_agent import RobotAgent

__all__ = [
    "Brain", "DeterministicBrain", "ConstantBrain", "Question", "Answer",
    "BaseAgent", "SubAgent",
    "SupervisorAgent", "PlannerAgent",
    "SortingAgent", "RoutingAgent", "SchedulingAgent", "ResourceAgent",
    "RobotAgent", "DEFAULT_OBJECTIVE",
]
