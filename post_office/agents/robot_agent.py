"""
The agent that owns one robot's body.

The `Robot` class in `robots/` is physics: position, battery, load, a step that
advances it. This class is the participant in the ecosystem: it has an inbox, it
accepts commands, it reports, and it is the *only* thing in the package that
calls a robot's methods. Scheduling and routing send messages; they never reach
into a robot, which is design principle 2 applied to the layer where it is
easiest to break.

Reports are routed by what they are about, not broadcast:

    picked, delivered, pick_failed, arrived     -> SCHEDULING  (the job)
    blocked, route_invalid                      -> ROUTING     (the path)
    battery_low, charging_*                     -> RESOURCE    (the resource)

Movement is logged but not messaged. A robot that told the scheduler about
every cell it crossed would produce a communication log in which the interesting
messages are one part in fifty, and the first thing anyone would do is filter
them out again.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..communication.directory import AgentKind
from ..communication.events import EventCategory
from ..communication.message import Message, MessageType
from ..environment.grid import Position
from ..environment.zones import Zone
from ..robots.robot import Robot
from .base import BaseAgent

#: Which experts hear about what. A report about the job goes to the scheduler,
#: one about the path to routing, one about a resource to the resource agent --
#: and a flat battery is all three agents' problem at once, so it goes to two.
REPORT_ROUTING = {
    "arrived_at_pickup": ("SCHEDULING",),
    "picked": ("SCHEDULING",),
    "delivered": ("SCHEDULING",),
    "pick_failed": ("SCHEDULING",),
    "aborted": ("SCHEDULING",),
    "parked": ("SCHEDULING",),
    "passed_via": ("SCHEDULING",),
    "blocked": ("ROUTING",),
    "route_invalid": ("ROUTING",),
    "yielded": ("ROUTING",),
    "yield_failed": ("ROUTING",),
    "stalled": ("ROUTING",),
    "battery_low": ("RESOURCE",),
    "battery_empty": ("RESOURCE", "SCHEDULING"),
    "charging_started": ("RESOURCE",),
    "charging_finished": ("RESOURCE",),
    "charging_unavailable": ("RESOURCE",),
    "charging_interrupted": ("RESOURCE",),
    "charge_declined": ("RESOURCE",),
}

#: Reports that go in the log but are not worth a message to anybody.
QUIET = {"moved", "charging"}


class RobotAgent(BaseAgent):
    """One robot's representative in the ecosystem."""

    kind = AgentKind.ROBOT

    def __init__(self, robot: Robot, parent_id: str = "SCHEDULING", **kw) -> None:
        super().__init__(robot.robot_id, "transport robot", parent_id=parent_id,
                         **kw)
        self.robot = robot
        self.commands = 0
        self.reports = 0

    # -------------------------------------------------------------- commands
    def handle(self, message: Message) -> None:
        if message.message_type is not MessageType.ROBOT_COMMAND:
            return
        content = message.content
        operation = content.get("operation", "")
        self.commands += 1

        if operation == "transport":
            self.robot.assign_transport(
                self.tick,
                task_id=content.get("task_id", ""),
                parcel_id=content.get("parcel_id", ""),
                pickup=Position.of(content["pickup"]),
                dropoff=Position.of(content["dropoff"]),
                route_to_pickup=[Position.of(p) for p in content.get("to_pickup", ())],
                route_to_dropoff=[Position.of(p) for p in content.get("to_dropoff", ())],
                destination_zone=(Zone(content["destination_zone"])
                                  if content.get("destination_zone") else None),
                via=(Position.of(content["via"]) if content.get("via") else None),
                route_after_via=[Position.of(p) for p in content.get("after_via", ())],
            )
        elif operation == "charge":
            if self.robot.current_task is not None or self.robot.carrying:
                # Refused, not queued. A robot that accepted this would drop
                # whatever it was doing half way across the floor.
                self.send(message.sender, MessageType.ROBOT_REPORT,
                          {"robot_id": self.agent_id, "report": "charge_declined",
                           "reason": "already on an errand",
                           "task_id": self.robot.current_task},
                          correlation_id=message.correlation_id,
                          text=f"{self.agent_id} is busy; charge later.")
                return
            self.robot.assign_charge(
                self.tick, task_id=content.get("task_id", ""),
                station_position=Position.of(content["position"]),
                route=[Position.of(p) for p in content.get("route", ())])
        elif operation == "yield":
            self.robot.yield_to(
                self.tick, Position.of(content["cell"]),
                resume=[Position.of(p) for p in content.get("route", ())],
                hold=int(content.get("hold", 0)))
        elif operation == "park":
            self.robot.go_home(self.tick, Position.of(content["home"]),
                               [Position.of(p) for p in content.get("route", ())])
        elif operation == "step_aside":
            self.robot.step_aside(self.tick, Position.of(content["cell"]))
        elif operation == "set_route":
            self.robot.set_route(self.tick,
                                 [Position.of(p) for p in content.get("route", ())])
        elif operation == "abort":
            task_id = self.robot.current_task
            self.world.env.release_station(self.agent_id)
            carried = self.robot.abort(self.tick, content.get("reason", ""))
            if carried:
                self.world.env.drop_parcel(carried, self.robot.current_position)
            # Whoever ordered the abort has to know what became of the parcel;
            # it is on the floor now, and somebody must be told to fetch it.
            self.send("SCHEDULING", MessageType.ROBOT_REPORT,
                      {"robot_id": self.agent_id, "report": "aborted",
                       "task_id": task_id, "parcel_id": carried,
                       "reason": content.get("reason", ""),
                       "position": self.robot.current_position.as_dict()},
                      correlation_id=carried or self.agent_id,
                      text=(f"{self.agent_id} stood down"
                            + (f"; {carried} is on the floor at "
                               f"{self.robot.current_position}." if carried else ".")))

        self.world.logger.emit(
            EventCategory.ROBOT, f"command_{operation}", tick=self.tick,
            actor=message.sender, target=self.agent_id,
            correlation_id=message.correlation_id,
            task_id=content.get("task_id"), parcel_id=content.get("parcel_id"))

    # ------------------------------------------------------------------ body
    def tick_work(self) -> None:
        """Advance the body, then tell whoever needs to know what happened."""
        before = self.robot.battery_level
        for report in self.robot.step(self.world.env, self.tick):
            self._log(report)
            kind = report.get("report", "")
            if kind in QUIET:
                continue
            for receiver in REPORT_ROUTING.get(kind, ()):
                self.reports += 1
                self.send(receiver, MessageType.ROBOT_REPORT, report,
                          correlation_id=(report.get("parcel_id")
                                          or self.robot.current_task
                                          or self.agent_id),
                          text=self._narrate(report))

        after = self.robot.battery_level
        if int(before // 10) != int(after // 10):
            # Battery is logged when it crosses a ten-percent band rather than
            # every tick: enough for a monitor to see a trend, not enough to
            # drown the log.
            self.world.logger.emit(
                EventCategory.BATTERY, "battery_band", tick=self.tick,
                actor=self.agent_id, level=round(after, 2),
                band=int(after // 10) * 10)

    def _log(self, report: Dict[str, Any]) -> None:
        self.world.logger.emit(
            EventCategory.ROBOT, report.get("report", "report"), tick=self.tick,
            actor=self.agent_id,
            correlation_id=report.get("parcel_id", "") or "",
            **{k: v for k, v in report.items()
               if k not in ("robot_id", "tick", "report")})

    @staticmethod
    def _narrate(report: Dict[str, Any]) -> str:
        """
        The natural-language form of a report.

        Worth having even with deterministic agents: it is what a person reads
        when following one parcel through the communication log, and it is the
        text an LLM agent would be given as context.
        """
        kind = report.get("report", "")
        rid = report.get("robot_id", "?")
        if kind == "arrived_at_pickup":
            return f"{rid} is at the parcel {report.get('parcel_id')}."
        if kind == "picked":
            return f"{rid} has {report.get('parcel_id')} on board."
        if kind == "delivered":
            return (f"{rid} put {report.get('parcel_id')} down in "
                    f"{report.get('zone')}.")
        if kind == "aborted":
            return (f"{rid} stood down from {report.get('task_id')}"
                    + (f"; {report.get('parcel_id')} is on the floor."
                       if report.get("parcel_id") else "."))
        if kind == "battery_empty":
            return f"{rid} is flat at {report.get('position')} and cannot move."
        if kind == "yielded":
            return f"{rid} stepped aside to {report.get('at')}."
        if kind == "stalled":
            return f"{rid} has been waiting {report.get('waited')} ticks."
        if kind == "blocked":
            return (f"{rid} is stuck behind {report.get('blocked_by')} at "
                    f"{report.get('at')}.")
        if kind == "battery_low":
            return f"{rid} is down to {report.get('level')}%."
        if kind == "charging_started":
            return f"{rid} is on {report.get('station_id')}."
        if kind == "charging_finished":
            return f"{rid} is charged and free."
        if kind == "pick_failed":
            return f"{rid} could not pick up: {report.get('reason')}."
        return f"{rid}: {kind}."

    # ----------------------------------------------------------------- state
    def state(self) -> Dict[str, Any]:
        return {"commands_received": self.commands, "reports_sent": self.reports,
                "robot": self.robot.as_dict()}
