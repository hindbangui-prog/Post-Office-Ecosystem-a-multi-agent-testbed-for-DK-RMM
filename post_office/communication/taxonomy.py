"""
The runtime communication taxonomy: what kind of interaction an event is.

A labelling layer over the event log, nothing more. `classify` reads five fields
of an event (category, topic, actor, target and the message type a bus message
carries in its detail) and names the interaction type and the channel it
belongs to; the logger stamps both onto every event it writes. Nothing here
emits, changes or invents an event, and nothing here imports the simulator:
the module is a pure function of its arguments and a table about them, so the
API can serve the table and the page can build its legend from it without
either learning anything about the facility.

The channels:

    A  governance      supervisor and planner: objectives, policies, plans, status,
                       task assignments and the reports that come back up
    B  llm_expert      the model-backed layer: model calls, consultations between
                       experts, their questions, delegations and responses
    C  deterministic   expert to expert and expert to sub-agent requests and
                       responses on the experts' rules
    D  robot           commands to robots and the robots' reports
    E  environment     what agents do to the floor and what the floor reports
    decision           a decision an agent took, whichever way it took it
    system             lifecycle, bus housekeeping and the fallback

The fallback is a classification like any other except for its `fallback`
marker, which the completeness test reads: every event a seeded run produces
must reach a rule, so a new source event fails that test under its own name
rather than being filed quietly under `system`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Dict, Mapping, Optional, Tuple

# ---------------------------------------------------------------- agent kinds

#: The six experts behind the planner. PLANNER is its own kind: its traffic
#: with the supervisor is governance, its traffic with the experts assignment.
EXPERT_IDS: Tuple[str, ...] = ("INTAKE", "SORTING", "SCHEDULING", "ROUTING", "RESOURCE",
                               "DISPATCH")

_ROBOT_ID = re.compile(r"R[0-9]+")

_FIXED_KINDS: Dict[str, str] = {
    "SUPERVISOR": "supervisor",
    "PLANNER": "planner",
    "ENVIRONMENT": "environment",
    "SIMULATION": "simulation",
    "INTAKE_DOCK": "intake_dock",
}


def agent_kind(agent_id: Optional[str]) -> str:
    """
    The kind of agent an id names, read from the id as the floor graph reads it.

    `supervisor`, `planner`, `expert` (the six expert ids), `subagent` (`SUB-*`),
    `robot` (`R<n>`), `environment`, `simulation`, `intake_dock`; `none` for a
    missing id and `other` for anything else.
    """
    agent_id = str(agent_id or "")
    if not agent_id:
        return "none"
    if agent_id in _FIXED_KINDS:
        return _FIXED_KINDS[agent_id]
    if agent_id in EXPERT_IDS:
        return "expert"
    if agent_id.startswith("SUB-"):
        return "subagent"
    if _ROBOT_ID.fullmatch(agent_id):
        return "robot"
    return "other"


#: Actors that are the floor or the run itself rather than an agent: an event
#: they author under `parcel` or `resource` is an update, not an action.
_FLOOR_KINDS = frozenset({"environment", "simulation", "intake_dock", "none"})

#: Actors that are agents of the facility: an event they author under `parcel`
#: or `resource` is an action. An id of kind `other` is neither, and falls
#: through to the fallback so the completeness test names it.
_AGENT_KINDS = frozenset({"supervisor", "planner", "expert", "subagent", "robot"})


# ------------------------------------------------------------------- channels
@dataclass(frozen=True)
class Channel:
    id: str
    label: str
    colour: str
    dash: str
    description: str


CHANNELS: Mapping[str, Channel] = MappingProxyType({c.id: c for c in (
    Channel("A", "governance", "#b06a1e", "solid",
            "Supervisor and planner: objectives, policies, plans, status, task "
            "assignments and the reports that come back up."),
    Channel("B", "llm_expert", "#1b8a7a", "dashed",
            "The model-backed layer: model calls and the consultations between "
            "experts, their questions, delegations and responses."),
    Channel("C", "deterministic", "#7a5cc4", "solid",
            "Expert to expert and expert to sub-agent requests and responses on "
            "the experts' rules."),
    Channel("D", "robot", "#b1452f", "solid",
            "Commands to robots and the robots' reports."),
    Channel("E", "environment", "#5f7f6a", "solid",
            "What agents do to the floor, what the floor reports, and the task "
            "lifecycle."),
    Channel("decision", "decision", "#d89614", "solid",
            "A decision an agent took, on its rules or through a model."),
    Channel("system", "system", "#8a929d", "solid",
            "Run lifecycle, bus housekeeping, and the fallback for anything "
            "no rule names."),
)})


# ---------------------------------------------------------------------- types
@dataclass(frozen=True)
class InteractionType:
    interaction_type: str
    channel: str
    description: str
    #: Whether a row of this type has a target: "always", "sometimes" or "never".
    has_receiver: str
    #: Whether a row of this type may show a latency, and in which unit: "ms"
    #: when the event itself carries `latency_ms`, "ticks" when the row is a
    #: request whose reply (`in_reply_to`) can be paired to it, "none" otherwise.
    #: "may": a STATUS_REPORT is a governance_report nobody answers.
    latency: str
    #: Whether a row of this type may name a model.
    model: bool


TYPES: Mapping[str, InteractionType] = MappingProxyType({t.interaction_type: t for t in (
    InteractionType("decision", "decision",
                    "Topic `decision`: an agent decided, by rule or by model. Carries "
                    "latency_ms and a model only when its mode is llm.",
                    "never", "ms", True),
    InteractionType("llm_call", "B",
                    "Topic `llm_call`: one call to the model server.",
                    "never", "ms", True),
    InteractionType("question", "B",
                    "Topic `consult_question`; message CONSULT_REQUEST whose content's "
                    "interaction_type is not `delegation`: an expert asks its allowed "
                    "peer for a view.",
                    "always", "none", True),
    InteractionType("delegation", "B",
                    "Topic `consult_delegation`; message CONSULT_REQUEST whose content's "
                    "interaction_type is `delegation`: an expert hands its allowed peer "
                    "a task inside a consultation.",
                    "always", "none", True),
    InteractionType("response", "B",
                    "Topic `consult_response`, message CONSULT_RESPONSE: the peer "
                    "answers.",
                    "always", "ms", True),
    InteractionType("consultation", "B",
                    "Topics `consult_opened`, `consult_closed`, `consult_refused`, "
                    "message CONSULT_CLOSE: the consultation itself, opened, refused "
                    "or closed with its outcome.",
                    "sometimes", "ms", True),
    InteractionType("governance_instruction", "A",
                    "Messages OBJECTIVE, POLICY, PLAN_APPROVAL, PLAN_REJECTION, "
                    "STATUS_REQUEST, BROADCAST, and the supervisor's own events.",
                    "sometimes", "none", False),
    InteractionType("governance_report", "A",
                    "Messages PLAN_PROPOSAL (answered by an approval or rejection), "
                    "STATUS_REPORT, and the planner's `policy_applied`.",
                    "sometimes", "ticks", False),
    InteractionType("task_assignment", "A",
                    "Message TASK_ASSIGNMENT from the planner to an expert, answered by "
                    "TASK_ACCEPTED or TASK_REJECTED.",
                    "always", "ticks", False),
    InteractionType("task_report", "A",
                    "A TASK_* message or WORK_NOTICE with the planner at either end.",
                    "always", "none", False),
    InteractionType("expert_request", "C",
                    "Messages ROUTE_REQUEST, RESOURCE_REQUEST, SCHEDULE_REQUEST, "
                    "CHARGE_REQUEST, ALERT between experts.",
                    "always", "ticks", False),
    InteractionType("expert_response", "C",
                    "Messages ROUTE_RESPONSE, RESOURCE_GRANT, RESOURCE_DENIAL, "
                    "SCHEDULE_RESPONSE, and a TASK_* message between two experts.",
                    "always", "none", False),
    InteractionType("subagent_request", "C",
                    "Message SUBTASK_REQUEST from an expert to its sub-agent.",
                    "always", "ticks", False),
    InteractionType("subagent_response", "C",
                    "Message SUBTASK_RESULT from a sub-agent to its expert.",
                    "always", "none", False),
    InteractionType("robot_command", "D",
                    "Message ROBOT_COMMAND, and the `robot` category's `command_*` "
                    "topics.",
                    "always", "none", False),
    InteractionType("robot_report", "D",
                    "Message ROBOT_REPORT, and any `robot` category event a robot "
                    "authors (moved, blocked, picked, delivered, yielded, ...).",
                    "sometimes", "none", False),
    InteractionType("environment_action", "E",
                    "A `parcel`, `resource`, `robot` or `task` event an agent (expert, "
                    "planner, sub-agent or robot) authors that is not a command, report "
                    "or lifecycle step.",
                    "sometimes", "none", False),
    InteractionType("environment_update", "E",
                    "Every `battery` event (RESOURCE's re-logs of a robot's battery "
                    "reports name RESOURCE as target), and a `parcel` or `resource` "
                    "event the floor, the run or the intake dock authors.",
                    "sometimes", "none", False),
    InteractionType("task_lifecycle", "E",
                    "A `task` event about the task itself: created, assigned, started, "
                    "completed, failed, released, cancelled, overdue, timed out.",
                    "never", "none", False),
    InteractionType("system", "system",
                    "The `simulation` category, agent lifecycle, bus housekeeping, and "
                    "the fallback for anything no rule names.",
                    "sometimes", "none", False),
)})


# -------------------------------------------------------------- the rule data
_CONSULT_TOPICS: Dict[str, str] = {
    "consult_question": "question",
    "consult_delegation": "delegation",
    "consult_response": "response",
    "consult_opened": "consultation",
    "consult_closed": "consultation",
    "consult_refused": "consultation",
}

#: A CONSULT_REQUEST is a question or a delegation according to the message
#: content's `interaction_type` (`content_type` below); it is not in this map.
_MESSAGE_TYPES: Dict[str, str] = {
    "CONSULT_RESPONSE": "response",
    "CONSULT_CLOSE": "consultation",
    "OBJECTIVE": "governance_instruction",
    "POLICY": "governance_instruction",
    "PLAN_APPROVAL": "governance_instruction",
    "PLAN_REJECTION": "governance_instruction",
    "STATUS_REQUEST": "governance_instruction",
    "BROADCAST": "governance_instruction",
    "PLAN_PROPOSAL": "governance_report",
    "STATUS_REPORT": "governance_report",
    "TASK_ASSIGNMENT": "task_assignment",
    "ROUTE_REQUEST": "expert_request",
    "RESOURCE_REQUEST": "expert_request",
    "SCHEDULE_REQUEST": "expert_request",
    "CHARGE_REQUEST": "expert_request",
    "ALERT": "expert_request",
    "ROUTE_RESPONSE": "expert_response",
    "RESOURCE_GRANT": "expert_response",
    "RESOURCE_DENIAL": "expert_response",
    "SCHEDULE_RESPONSE": "expert_response",
    "SUBTASK_REQUEST": "subagent_request",
    "SUBTASK_RESULT": "subagent_response",
    "ROBOT_COMMAND": "robot_command",
    "ROBOT_REPORT": "robot_report",
}

#: TASK_* messages and WORK_NOTICE: a report when the planner is at either end,
#: otherwise one expert telling another how a shared job went.
_TASK_MESSAGE_TYPES = frozenset({
    "TASK_ACCEPTED", "TASK_REJECTED", "TASK_COMPLETED", "TASK_FAILED", "TASK_PROGRESS",
    "WORK_NOTICE",
})

_SUPERVISOR_ACTORS: Dict[str, str] = {
    "SUPERVISOR": "governance_instruction",
    "PLANNER": "governance_report",
}

_TASK_LIFECYCLE_TOPICS = frozenset({
    "task_created", "task_assigned", "task_started", "task_completed", "task_failed",
    "task_released", "task_cancelled", "overdue", "queue_question_timed_out",
})

#: The bus writing about itself rather than carrying a message: a refused,
#: dropped or late message is housekeeping even when it names a message type.
_BUS_HOUSEKEEPING_TOPICS = frozenset({
    "message_refused", "message_dropped", "agent_message_received",
})

_LIFECYCLE_TOPICS = frozenset({"agent_created", "agent_removed"}) | _BUS_HOUSEKEEPING_TOPICS


# ------------------------------------------------------------ classification
@dataclass(frozen=True)
class Classification:
    interaction_type: str
    channel: str
    fallback: bool = False


def _named(interaction_type: str, fallback: bool = False) -> Classification:
    return Classification(interaction_type, TYPES[interaction_type].channel, fallback)


def classify(category: Optional[str], topic: Optional[str], actor: Optional[str],
             target: Optional[str], message_type: Optional[str], *,
             content_type: Optional[str] = "") -> Classification:
    """
    Name the interaction type and channel of an event. Pure; never raises.

    `content_type` is the bus message content's `interaction_type`, when the
    caller has it (`detail.content.interaction_type`); it is read only for a
    CONSULT_REQUEST, which is a `delegation` when it says so and a `question`
    otherwise. Keyword-only, so it cannot be confused with the five fields.

    Precedence (spec 3.2): the rules are tried in this order and the first
    match wins. A missing argument is the empty string.

     1. topic `decision`                                   -> decision
     2. topic `llm_call`                                   -> llm_call (B)
     3. topics `consult_*`                                 -> question, delegation,
                                                             response, consultation (B)
     4. `message_type` present, on a carried message (not bus housekeeping):
          CONSULT_REQUEST, by `content_type`               -> delegation or question (B)
          CONSULT_RESPONSE / CONSULT_CLOSE                 -> response, consultation (B)
          governance types                                 -> governance_instruction,
                                                             governance_report (A)
          TASK_ASSIGNMENT                                  -> task_assignment (A)
          TASK_* / WORK_NOTICE with PLANNER at either end  -> task_report (A)
                                   else                    -> expert_response (C)
          expert request / response types                  -> expert_request,
                                                             expert_response (C)
          SUBTASK_*                                        -> subagent_request,
                                                             subagent_response (C)
          ROBOT_COMMAND / ROBOT_REPORT                     -> robot_command,
                                                             robot_report (D)
          an unknown type matches nothing here and falls through
     5. category `supervisor`, by actor: SUPERVISOR        -> governance_instruction (A)
                                         PLANNER           -> governance_report (A)
     6. category `robot`: topic `command_*`                -> robot_command (D)
                          robot actor                      -> robot_report (D)
                          otherwise                        -> environment_action (E)
     7. category `task`: lifecycle topics                  -> task_lifecycle (E)
                         otherwise                         -> environment_action (E)
     8. category `battery`                                 -> environment_update (E)
     9. categories `parcel`, `resource`:
          actor ENVIRONMENT / SIMULATION / INTAKE_DOCK / empty -> environment_update (E)
          an agent actor (expert, planner, sub-agent, robot) -> environment_action (E)
          otherwise (an actor of kind `other`) falls through
    10. category `simulation`; topics agent_created, agent_removed, message_refused,
        message_dropped, agent_message_received            -> system
    11. fallback                                           -> system, fallback=True
    """
    category = str(category or "")
    topic = str(topic or "")
    actor = str(actor or "")
    target = str(target or "")
    message_type = str(message_type or "")
    content_type = str(content_type or "")

    # 1, 2
    if topic == "decision":
        return _named("decision")
    if topic == "llm_call":
        return _named("llm_call")

    # 3
    if topic in _CONSULT_TOPICS:
        return _named(_CONSULT_TOPICS[topic])

    # 4
    if message_type and topic not in _BUS_HOUSEKEEPING_TOPICS:
        if message_type == "CONSULT_REQUEST":
            return _named("delegation" if content_type == "delegation" else "question")
        if message_type in _MESSAGE_TYPES:
            return _named(_MESSAGE_TYPES[message_type])
        if message_type in _TASK_MESSAGE_TYPES:
            if "PLANNER" in (actor, target):
                return _named("task_report")
            return _named("expert_response")

    # 5
    if category == "supervisor" and actor in _SUPERVISOR_ACTORS:
        return _named(_SUPERVISOR_ACTORS[actor])

    # 6
    if category == "robot":
        if topic.startswith("command_"):
            return _named("robot_command")
        if agent_kind(actor) == "robot":
            return _named("robot_report")
        return _named("environment_action")

    # 7
    if category == "task":
        if topic in _TASK_LIFECYCLE_TOPICS:
            return _named("task_lifecycle")
        return _named("environment_action")

    # 8
    if category == "battery":
        return _named("environment_update")

    # 9
    if category in ("parcel", "resource"):
        kind = agent_kind(actor)
        if kind in _FLOOR_KINDS:
            return _named("environment_update")
        if kind in _AGENT_KINDS:
            return _named("environment_action")

    # 10
    if category == "simulation" or topic in _LIFECYCLE_TOPICS:
        return _named("system")

    # 11
    return _named("system", fallback=True)


# ---------------------------------------------------------------------- table
def table() -> dict:
    """
    The taxonomy as JSON: `channels` and `types`, each a list in table order.

    Served by `GET /taxonomy` and compared with the table in `docs/events.md`.
    A fresh structure on every call, so a caller may edit what it receives.
    """
    return {
        "channels": [
            {"id": c.id, "label": c.label, "colour": c.colour, "dash": c.dash,
             "description": c.description}
            for c in CHANNELS.values()
        ],
        "types": [
            {"interaction_type": t.interaction_type, "channel": t.channel,
             "description": t.description, "has_receiver": t.has_receiver,
             "latency": t.latency, "model": t.model}
            for t in TYPES.values()
        ],
    }


__all__ = ["CHANNELS", "TYPES", "EXPERT_IDS", "Channel", "InteractionType", "Classification",
           "agent_kind", "classify", "table"]
