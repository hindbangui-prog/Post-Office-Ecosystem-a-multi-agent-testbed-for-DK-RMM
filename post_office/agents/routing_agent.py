"""
The routing agent: turns "get this robot there" into a list of cells.

Two quite different jobs, one per sub-agent.

*Planning.* Another expert -- normally scheduling, sometimes resource -- asks
for a route. Routing forwards the geometry to SUB-ROUTE and passes the answer
back to whoever asked. It remembers who asked in `_waiting`, keyed by the id of
the message it sent, which is how a request/response pair survives an
asynchronous bus.

*Unblocking.* A robot that finds another robot in its way reports to routing,
not to the scheduler: the scheduler's plan is still fine, it is the path that
is not. Routing asks SUB-COLLISION whether to wait or go round, and if the
answer is to go round it sends the robot a new route itself.

Note which direction the commands flow. Routing sends `ROBOT_COMMAND` to a
robot; it never touches the robot's fields. The robot agent applies the command
to its own body.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..communication.directory import AgentKind
from ..communication.events import EventCategory
from ..communication.message import Message, MessageType
from ..environment.grid import Position
from ..robots.robot import RobotState
from .base import BaseAgent
from .brain import Answer
from .deferral import Deferral, is_pending
from .reasoning import REASONS, Trigger


class RoutingAgent(BaseAgent):
    """Plans robot routes, and decides what to do when one is obstructed."""

    kind = AgentKind.EXPERT

    #: How long to leave a robot alone after asking it to move.
    PUSH_COOLDOWN = 8

    PLANNER_SUB = "SUB-ROUTE"
    COLLISION_SUB = "SUB-COLLISION"

    def __init__(self, agent_id: str = "ROUTING", parent_id: str = "PLANNER",
                 **kw) -> None:
        super().__init__(agent_id, "routing", parent_id=parent_id, **kw)
        self._waiting: Dict[str, Dict[str, Any]] = {}
        self.routes_planned = 0
        self.blocks_resolved = 0
        self.reroutes = 0
        self.yields = 0
        self.abandons = 0
        self.pushes = 0
        self._pushed_at: Dict[str, int] = {}

    # ----------------------------------------------------------------- rules
    def install_triggers(self) -> None:
        """
        When waiting one more tick stops being the right answer.

        Most blocks clear themselves. Two robots meet in a doorway, one goes
        through, the other follows a tick later; deliberating over that would
        cost more than the block. So a first block is routine and the rule
        says wait.

        A block that is still there on the second look is different in kind:
        whatever is in the way is not passing, and the choice between waiting
        longer, going round, and giving up the cell is a trade between this
        robot's errand and everything else moving on that floor. A robot low
        on charge makes it sharper again, because waiting costs it the margin
        it needs to reach a plug.
        """

        #: How long a block has to persist before it stops being ordinary
        #: traffic. Two robots meeting in a doorway are clear within a tick or
        #: two even on a quiet floor -- measured at 55% of blocks in a quiet
        #: run, which made "blocked twice" a description of normal operation
        #: rather than a reason to think. The clerk re-asks on an escalating
        #: schedule -- 1, 3, 6, 9 ticks -- so this is the third look, by which
        #: point whatever is in the way is plainly not moving on its own.
        PERSISTENT = 6

        def still_blocked(facts):
            blocked = float(facts.get("ticks_blocked", 1) or 1)
            if blocked >= PERSISTENT:
                return Trigger(REASONS.FAILED,
                               f"still blocked after {blocked:.0f} ticks")
            return None

        def expensive_detour(facts):
            extra = facts.get("detour_extra")
            direct = facts.get("direct_distance")
            try:
                if extra is not None and direct and float(extra) > float(direct):
                    return Trigger(REASONS.CONFLICT,
                                   f"the way round costs {float(extra):.0f} "
                                   f"extra on a {float(direct):.0f} journey")
            except (TypeError, ValueError):
                return None
            return None

        def low_on_charge(facts):
            if float(facts.get("battery", 100) or 100) < 30:
                return Trigger(REASONS.ENVIRONMENT,
                               f"{float(facts.get('battery', 0)):.0f}% left "
                               f"while blocked")
            return None

        self.triggers.register("resolve_block", still_blocked)
        self.triggers.register("resolve_block", low_on_charge)
        self.triggers.register("resolve_block", expensive_detour)

    def install_rules(self) -> None:
        """
        What a blocked robot should do, and the fallback under any model.

        SUB-COLLISION measures the floor -- is there a way round, how much
        longer is it, is there anywhere to step aside to -- and this agent
        chooses between the moves that measurement found. The rule used to live
        on the sub-agent, which meant the only judgement in this subsystem was
        made one level below the agent responsible for the floor.
        """
        rules = self.rules()
        if rules is None:
            return

        def choose(question) -> Answer:
            facts = question.facts
            options = set(question.options)
            blocked_for = int(facts.get("ticks_blocked", 1) or 1)
            detour_extra = facts.get("detour_extra")
            # Judged against the journey it lengthens and against what the
            # robot has left, rather than as a bare number of cells: four extra
            # cells on a six-cell trip and on a sixty-cell trip are not the
            # same decision, and neither is a detour at 20% charge.
            direct = float(facts.get("direct_distance", 0) or 0)
            battery = float(facts.get("battery", 100) or 100)

            if "PUSH" in options:
                return Answer("PUSH",
                              f"{facts.get('blocked_by')} has stopped in the "
                              f"way and will not move on its own")
            if "ABANDON" in options:
                return Answer("ABANDON",
                              f"{facts.get('blocked_by')} is standing on the "
                              f"destination; this errand cannot be finished")
            if blocked_for >= 2 and "YIELD" in options:
                return Answer("YIELD",
                              f"stuck {blocked_for} ticks against "
                              f"{facts.get('blocked_by')}; giving up the cell")
            if (detour_extra is not None and direct
                    and float(detour_extra) > max(4.0, direct * 0.5)):
                return Answer("WAIT", f"going round costs {detour_extra} cells "
                                      f"on a {direct:.0f}-cell journey; waiting "
                                      "is cheaper")
            if detour_extra is not None and battery < 30.0:
                return Answer("WAIT", f"at {battery:.0f}% there is no charge to "
                                      "spare on going round")
            if detour_extra is not None and blocked_for >= 2:
                return Answer("REROUTE",
                              f"blocked {blocked_for} ticks; {detour_extra} "
                              f"extra cells is cheaper than waiting longer")
            return Answer("WAIT",
                          f"blocked {blocked_for} tick(s); the doorway usually "
                          f"clears")

        rules.register("resolve_block", choose)

    # --------------------------------------------------------------- inbound
    def handle(self, message: Message) -> None:
        if message.message_type is MessageType.ROUTE_REQUEST:
            self._plan(message)
        elif message.message_type is MessageType.ROBOT_REPORT:
            self._robot_report(message)
        elif message.message_type is MessageType.SUBTASK_RESULT:
            self._sub_result(message)

    def _plan(self, message: Message) -> None:
        """Forward a route request to the sub-agent that does the geometry."""
        content = dict(message.content)
        operation = content.get("operation", "plan_transport")
        sent = self.send(self.PLANNER_SUB, MessageType.SUBTASK_REQUEST, content,
                         correlation_id=message.correlation_id)
        if sent is not None:
            self._waiting[sent.message_id] = {
                "reply_to": message.sender,
                "request_id": message.message_id,
                "correlation_id": message.correlation_id,
                "operation": operation,
                "task_id": content.get("task_id"),
                "robot_id": content.get("robot_id"),
            }

    def _robot_report(self, message: Message) -> None:
        """A robot is stuck. Ask the specialist, do not guess."""
        content = message.content
        report = content.get("report")

        if report in ("yielded", "stalled", "yield_failed"):
            # It has stepped aside, or it has been waiting too long. Either way
            # what it needs is a route from where it actually is now.
            self._replan(message)
            return

        if report not in ("blocked", "route_invalid"):
            return
        self._ask_collision(content.get("robot_id", message.sender),
                            content.get("blocked_by"),
                            content.get("ticks_blocked", 1),
                            content.get("goal"), message.correlation_id)

    def _ask_collision(self, robot_id: str, blocked_by: Any, ticks_blocked: Any,
                       goal: Any, correlation_id: str) -> None:
        """Ask the collision clerk what the ways out of a block are."""
        sent = self.send(self.COLLISION_SUB, MessageType.SUBTASK_REQUEST,
                         {"operation": "resolve_block",
                          "robot_id": robot_id,
                          "blocked_by": blocked_by,
                          "ticks_blocked": ticks_blocked,
                          "goal": goal,
                          "correlation_id": correlation_id},
                         correlation_id=correlation_id)
        if sent is not None:
            self._waiting[sent.message_id] = {
                "reply_to": "",           # nothing to answer; we act ourselves
                "correlation_id": correlation_id,
                "operation": "resolve_block",
                "robot_id": robot_id,
            }

    def _replan(self, message: Message) -> None:
        """Give a robot a route from wherever it has ended up to wherever it was going."""
        content = message.content
        robot_id = content.get("robot_id", message.sender)
        robot = self.world.fleet.get(robot_id)
        goal = content.get("goal") or (robot.destination.as_dict()
                                       if robot is not None and robot.destination
                                       else None)
        if robot is None or goal is None:
            return
        sent = self.send(self.PLANNER_SUB, MessageType.SUBTASK_REQUEST,
                         {"operation": "plan_route", "robot_id": robot_id,
                          "start": robot.current_position.as_dict(),
                          "goal": goal, "purpose": "replan"},
                         correlation_id=message.correlation_id)
        if sent is not None:
            self._waiting[sent.message_id] = {
                "reply_to": "",                 # the route comes back to us
                "correlation_id": message.correlation_id,
                "operation": "replan",
                "robot_id": robot_id,
            }

    # --------------------------------------------------------- sub-agent work
    def _sub_result(self, message: Message) -> None:
        context = self._waiting.pop(message.in_reply_to or "", None)
        if context is None:
            return
        content = message.content
        operation = content.get("operation", "")

        if operation in ("plan_transport", "plan_route"):
            self.routes_planned += 1
            reply_to = context.get("reply_to")
            if reply_to:
                self.send(reply_to, MessageType.ROUTE_RESPONSE, content,
                          correlation_id=context.get("correlation_id", ""),
                          in_reply_to=context.get("request_id"),
                          text=content.get("_text", ""))
            elif context.get("operation") == "replan" and content.get("ok"):
                # Nobody asked for this one; it was our own idea, so we send it
                # to the robot ourselves.
                self.send(context["robot_id"], MessageType.ROBOT_COMMAND,
                          {"operation": "set_route", "route": content["route"]},
                          correlation_id=context.get("correlation_id", ""),
                          text=f"{context['robot_id']}: carry on from here.")
            return

        if operation == "resolve_block":
            self.blocks_resolved += 1
            robot_id = content.get("robot_id", context.get("robot_id", ""))
            options = [str(o) for o in content.get("options", ["WAIT"])] or ["WAIT"]
            # The clerk found the ways out; choosing between them is this
            # agent's call.
            deferral = self._block_deferral(robot_id, context, content, options)
            answer = self.decide(
                "resolve_block",
                f"Robot {robot_id} is blocked by "
                f"{content.get('blocked_by', 'something')}. Should it wait, go "
                "the long way round, or give up its cell?",
                options=tuple(options),
                correlation_id=context.get("correlation_id", robot_id),
                robot=robot_id,
                blocked_by=content.get("blocked_by", "?"),
                ticks_blocked=content.get("ticks_blocked", 1),
                direct_distance=content.get("direct_distance"),
                detour_extra=content.get("detour_extra"),
                battery=content.get("battery", 100),
                deferral=deferral,
            )
            if is_pending(answer):
                # The model has it. Until it answers the robot does what a
                # WAIT would have it do -- nothing new -- and keeps reporting
                # the block, which is what brings the question back if the
                # answer arrives too late to use.
                return
            self._carry_out_block(robot_id, context, content, options, answer)

    def _block_deferral(self, robot_id: str, context: Dict[str, Any],
                        content: Dict[str, Any], options: List[str]) -> Deferral:
        """
        What a pending `resolve_block` needs to finish later, or to give way.

        The answer is about a robot standing in one cell with one other robot
        in its way. If by the time it arrives the robot has moved, stopped
        being blocked, or changed errand -- or the robot in the way has moved
        -- it is an answer to a situation that no longer exists.
        """
        robot = self.world.fleet.get(robot_id)
        blocker = self.world.fleet.get(str(content.get("blocked_by") or ""))
        seen = (robot.current_position if robot is not None else None,
                robot.current_task if robot is not None else None,
                blocker.current_position if blocker is not None else None)

        def still_valid(answer: Answer) -> str:
            now = self.world.fleet.get(robot_id)
            if now is None:
                return f"{robot_id} is gone"
            if now.status is not RobotState.BLOCKED:
                return f"{robot_id} is no longer blocked ({now.status.value})"
            if now.current_position != seen[0]:
                return f"{robot_id} has moved since the question was asked"
            if now.current_task != seen[1]:
                return f"{robot_id} is on a different errand now"
            if blocker is not None and blocker.current_position != seen[2]:
                return f"{blocker.robot_id} has moved out of the picture"
            return ""

        def reevaluate(why: str) -> None:
            # Still stuck: ask the clerk again from where things stand now,
            # and let the rules have the first word. Not stuck: nothing to do.
            now = self.world.fleet.get(robot_id)
            if now is None or now.status is not RobotState.BLOCKED:
                return
            self._ask_collision(robot_id, content.get("blocked_by"),
                                max(1, int(getattr(now, "_blocked_for", 1) or 1)),
                                content.get("goal"),
                                context.get("correlation_id", ""))

        return Deferral(key=robot_id,
                        apply=lambda answer: self._carry_out_block(
                            robot_id, context, content, options, answer),
                        still_valid=still_valid, reevaluate=reevaluate)

    def _carry_out_block(self, robot_id: str, context: Dict[str, Any],
                         content: Dict[str, Any], options: List[str],
                         answer: Answer) -> None:
        """Turn the answer to a block into the command it stands for."""
        action = answer.choice if answer.choice in options else "WAIT"
        content = {**content, "action": action, "reason": answer.reason,
                   "source": answer.source}
        if action == "REROUTE" and content.get("route"):
            self.reroutes += 1
            self.send(robot_id, MessageType.ROBOT_COMMAND,
                      {"operation": "set_route", "route": content["route"]},
                      correlation_id=context.get("correlation_id", robot_id),
                      text=f"New route for {robot_id}: {content.get('reason','')}")
        elif action == "PUSH" and content.get("push_to"):
            pushed = content["push_robot"]
            if self.tick - self._pushed_at.get(pushed, -99) < self.PUSH_COOLDOWN:
                # It was asked a moment ago and is presumably still moving.
                # Asking again every other tick walks it across the building
                # one cell at a time, at half a percent of battery a step.
                return
            self._pushed_at[pushed] = self.tick
            self.pushes += 1
            self.send(content["push_robot"], MessageType.ROBOT_COMMAND,
                      {"operation": "step_aside", "cell": content["push_to"]},
                      correlation_id=context.get("correlation_id", robot_id),
                      text=(f"{content['push_robot']}: you are in "
                            f"{robot_id}'s way; please move."))
        elif action == "ABANDON":
            # Routing cannot fix this one. Tell the scheduler, whose errand
            # it is, rather than leaving the robot to stare at the problem.
            self.abandons += 1
            self.send("SCHEDULING", MessageType.TASK_FAILED,
                      {"task_id": content.get("task_id"),
                       "robot_id": robot_id,
                       "reason": content.get("reason", "destination occupied"),
                       "blocked_by": content.get("occupant_of_goal")},
                      correlation_id=context.get("correlation_id", robot_id),
                      text=(f"{robot_id} cannot reach its destination: "
                            f"{content.get('occupant_of_goal')} is on it."))
        elif action == "YIELD" and content.get("yield_to"):
            self.yields += 1
            self.send(robot_id, MessageType.ROBOT_COMMAND,
                      {"operation": "yield", "cell": content["yield_to"],
                       "route": content.get("resume_route", []),
                       "hold": content.get("hold", 0),
                       "goal": content.get("goal")},
                      correlation_id=context.get("correlation_id", robot_id),
                      text=f"{robot_id}: step aside, {content.get('reason','')}")
        self.world.logger.emit(
            EventCategory.ROBOT, "block_resolved", tick=self.tick,
            actor=self.agent_id, target=robot_id,
            correlation_id=context.get("correlation_id", ""),
            action=content.get("action"), reason=content.get("reason", ""),
            source=content.get("source", ""),
        )

    # ----------------------------------------------------------------- state
    def state(self) -> Dict[str, Any]:
        return {
            "routes_planned": self.routes_planned,
            "blocks_resolved": self.blocks_resolved,
            "reroutes_issued": self.reroutes,
            "yields_ordered": self.yields,
            "errands_abandoned": self.abandons,
            "robots_moved_aside": self.pushes,
            "awaiting_subagents": len(self._waiting),
            "subagents": [self.PLANNER_SUB, self.COLLISION_SUB],
        }
