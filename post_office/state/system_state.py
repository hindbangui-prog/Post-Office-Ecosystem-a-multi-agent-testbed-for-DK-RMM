"""
One read-only view of the whole running system, in plain JSON types.

Everything the API serves and everything a future UI draws comes from here, so
that there is exactly one answer to "what is the state of the system" rather
than one per consumer. The five functions the spec asks for are the five
methods below, and they return dictionaries and lists only -- no dataclasses,
no enums, no objects that need a custom encoder.

This module reads and never writes. It is handed the ecosystem and asks it
questions; nothing here can change a parcel, a task or an agent, which is what
makes it safe to expose over HTTP.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..environment.parcels import ParcelStatus
from ..simulation.ecosystem import PostOfficeEcosystem


class SystemState:
    """The read side of the ecosystem."""

    def __init__(self, ecosystem: PostOfficeEcosystem) -> None:
        self.eco = ecosystem

    # ------------------------------------------------------------ everything
    def get_ecosystem_state(self, messages: int = 40,
                            events: int = 40) -> Dict[str, Any]:
        """The whole runtime state: agents, robots, parcels, tasks, resources."""
        eco = self.eco
        return {
            "run": {
                "run_id": eco.run_id,
                "seed": eco.seed,
                "tick": eco.world.tick,
                "running": eco.world.running,
                "objective": eco.world.objective,
                "config": dict(eco.config),
            },
            "policy": eco.world.policy.as_dict(),
            "hierarchy": eco.directory.tree(),
            "agents": self.get_agents(),
            "robots": self.get_robots(),
            "parcels": self.get_parcels(limit=300),
            "tasks": self.get_tasks(limit=300),
            "resources": self.get_resources(),
            "environment": eco.env.as_dict(),
            "communications": eco.bus.as_dict(limit=messages),
            "events": [e.as_dict() for e in eco.logger.recent(events)],
            "counters": eco.snapshot(),
        }

    # ---------------------------------------------------------------- agents
    def get_agents(self) -> List[Dict[str, Any]]:
        return [self.eco.agents[a].as_dict() for a in sorted(self.eco.agents)]

    def get_agent_state(self, agent_id: str) -> Optional[Dict[str, Any]]:
        agent = self.eco.agents.get(agent_id)
        if agent is None:
            return None
        record = self.eco.directory.get(agent_id)
        state = agent.as_dict()
        state["children"] = list(record.children) if record else []
        state["recent_messages"] = [
            m.as_dict() for m in self.eco.bus.log.recent(20, agent_id=agent_id)
        ]
        return state

    # ---------------------------------------------------------------- robots
    def get_robots(self) -> List[Dict[str, Any]]:
        return [r.as_dict() for r in self.eco.fleet.all()]

    def get_robot_state(self, robot_id: str) -> Optional[Dict[str, Any]]:
        robot = self.eco.fleet.get(robot_id)
        if robot is None:
            return None
        state = robot.as_dict()
        state["tasks"] = [t.as_dict() for t in
                          self.eco.tasks.for_robot(robot_id, open_only=False)[-10:]]
        state["recent_messages"] = [
            m.as_dict() for m in self.eco.bus.log.recent(20, agent_id=robot_id)
        ]
        return state

    # --------------------------------------------------------------- parcels
    def get_parcels(self, status: Optional[str] = None,
                    limit: int = 500, inside_only: bool = True
                    ) -> List[Dict[str, Any]]:
        """
        Parcels, newest first, without their biographies.

        Newest first and inside-first matters once a run is long: sorted by id
        and truncated, this endpoint would answer for ever with the first five
        hundred parcels of the run, all of them long gone, and never show
        anything actually on the floor.
        """
        source = (self.eco.env.parcels if inside_only
                  else self.eco.env.all_parcels())
        parcels = [p for p in source.values()
                   if status is None or p.status.value == status]
        parcels.sort(key=lambda p: p.parcel_id, reverse=True)
        return [p.summary() for p in parcels[:limit]]

    def get_parcel_state(self, parcel_id: str) -> Optional[Dict[str, Any]]:
        parcel = self.eco.env.parcel(parcel_id)
        if parcel is None:
            return None
        state = parcel.as_dict()
        state["tasks"] = [t.as_dict() for t in self.eco.tasks.for_parcel(parcel_id)]
        state["conversation"] = [m.as_dict() for m in
                                 self.eco.bus.log.thread(parcel_id)]
        return state

    # ----------------------------------------------------------------- tasks
    def get_tasks(self, status: Optional[str] = None,
                  limit: int = 500) -> List[Dict[str, Any]]:
        tasks = [t for t in self.eco.tasks.all()
                 if status is None or t.status.value == status]
        return [t.summary() for t in tasks[-limit:]]

    def get_task_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.eco.tasks.get(task_id)
        if task is None:
            return None
        state = task.as_dict()
        state["conversation"] = [
            m.as_dict() for m in self.eco.bus.log.thread(task.correlation_id)
        ]
        return state

    # ------------------------------------------------------------- resources
    def get_resources(self) -> Dict[str, Any]:
        env = self.eco.env
        return {
            "storage": env.storage.as_dict(),
            "charging_stations": [s.as_dict() for s in
                                  sorted(env.stations.values(),
                                         key=lambda s: s.station_id)],
            "fleet": {"count": len(self.eco.fleet),
                      "status": self.eco.fleet.status_counts(),
                      "battery": self.eco.fleet.battery_summary()},
            "arrivals": self.eco.generator.as_dict(),
        }

    # -------------------------------------------------------------- messages
    def get_recent_messages(self, limit: int = 50, agent_id: Optional[str] = None,
                            correlation_id: Optional[str] = None,
                            message_type: Optional[str] = None
                            ) -> List[Dict[str, Any]]:
        return [m.as_dict() for m in
                self.eco.bus.log.recent(limit, agent_id=agent_id,
                                        correlation_id=correlation_id,
                                        message_type=message_type)]

    def get_recent_events(self, limit: int = 50, category: Optional[str] = None,
                          actor: Optional[str] = None,
                          correlation_id: Optional[str] = None
                          ) -> List[Dict[str, Any]]:
        return [e.as_dict() for e in
                self.eco.logger.recent(limit, category=category, actor=actor,
                                       correlation_id=correlation_id)]

    def get_refused_messages(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Messages the hierarchy would not carry.

        Worth its own endpoint: an empty list means the hierarchy held, and a
        non-empty one is the most direct evidence there is of an agent trying
        to work outside it.
        """
        return self.eco.bus.log.refusals(limit)
