"""
The ecosystem: everything assembled, and the tick loop that drives it.

One tick, in order:

    1. advance the clock everywhere
    2. deliver the messages sent during the previous tick
    3. let new parcels arrive
    4. every agent steps, in a fixed declared order
    5. write a snapshot

Step 2 is what makes step 4's order almost irrelevant. Because delivery happens
once, before anybody acts, a message costs exactly one tick whoever sends it and
whoever receives it -- so reordering two agents cannot change who hears what
first. The order still matters for the physical world (a robot that moves early
in a tick is somewhere else when a later robot checks whether its next cell is
free), which is why the order is declared explicitly here rather than left to a
dictionary: supervisor, planner, experts, sub-agents, robots.

Determinism is a property this class is responsible for. Same seed, same
config, same event stream, byte for byte -- and `tests/test_ecosystem.py`
checks it rather than taking it on trust.
"""

from __future__ import annotations

import contextlib

import os
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..agents.base import BaseAgent
from ..agents.brain import Brain
from ..agents.dispatch_agent import DispatchAgent
from ..agents.intake_agent import IntakeAgent
from ..agents.planner_agent import PlannerAgent
from ..agents.resource_agent import ResourceAgent
from ..agents.robot_agent import RobotAgent
from ..agents.routing_agent import RoutingAgent
from ..agents.scheduling_agent import SchedulingAgent
from ..agents.sorting_agent import SortingAgent
from ..agents.subagents import (AssignmentSubAgent, BarcodeSubAgent,
                                BatteryManagementSubAgent,
                                ChargingStationSubAgent,
                                CollisionAvoidanceSubAgent,
                                DeadlineMonitorSubAgent,
                                DestinationClassificationSubAgent,
                                ManifestSubAgent, PackingSubAgent,
                                PriorityClassificationSubAgent,
                                QueueManagementSubAgent,
                                RegistrationSubAgent, RoutePlanningSubAgent,
                                StorageMonitoringSubAgent,
                                ValidationSubAgent)
from ..agents.supervisor import DEFAULT_OBJECTIVE, SupervisorAgent
from ..communication.bus import MessageBus
from ..communication.directory import Directory
from ..communication.events import EventCategory, EventLogger
from ..core.ids import IdFactory
from ..core.rng import SeededRNG
from ..core.world import Policy, World
from ..environment.layout import (CHARGE_RATE, DEFAULT_ROBOT_HOME,
                                  build_environment)
from ..environment.parcels import ParcelStatus
from ..policy import PolicyGate
from ..robots.fleet import build_fleet
from ..tasks.registry import TaskRegistry
from .generator import ParcelGenerator
from .recovery import RecoveryService


class PostOfficeEcosystem:
    """The whole prototype: facility, fleet, hierarchy, clock."""

    def __init__(self, seed: int = 1, config: Optional[Dict[str, Any]] = None,
                 log_path: Optional[str] = None, run_id: str = "run",
                 brains: Optional[Dict[str, Brain]] = None,
                 scenario: str = "normal") -> None:
        self.seed = int(seed)
        self.config: Dict[str, Any] = dict(config or {})
        #: Which scenario this run is, in the operator's terms (`normal` is
        #: the only one in this prototype). The configuration dictionary says
        #: what the facility *does*; this says what the run *is*, and a run
        #: record needs both.
        from ..config.settings import scenario_name
        self.scenario = scenario_name(scenario)
        self.run_id = run_id
        self.log_path = log_path
        self._brains = dict(brains or {})
        self.agents: Dict[str, BaseAgent] = {}
        self.order: List[str] = []
        self.snapshots: List[Dict[str, Any]] = []
        self._build()

    # ------------------------------------------------------------- assembly
    def _build(self) -> None:
        cfg = self.config
        # Before the logger opens a file, so a refused configuration leaves
        # no handle behind.
        self._refuse_perturbations(cfg)
        self.logger = EventLogger(run_id=self.run_id, path=self.log_path,
                                  keep=int(cfg.get("keep_events", 8000)))
        self.rng = SeededRNG(self.seed)
        self.ids = IdFactory()

        self.env = build_environment(
            storage_capacity=int(cfg.get("storage_capacity", 20)),
            charge_rate=float(cfg.get("charge_rate", CHARGE_RATE)),
        )
        self.env.set_event_sink(self.logger.routed_sink(
            {"storage_": EventCategory.RESOURCE,
             "charging_": EventCategory.RESOURCE},
            default=EventCategory.PARCEL, actor="ENVIRONMENT"))

        policy = Policy(
            max_concurrent_transports=int(cfg.get("max_concurrent_transports", 8)),
            reserve_battery=float(cfg.get("reserve_battery", 35.0)),
            resume_battery=float(cfg.get("resume_battery", 90.0)),
            store_normal_parcels=bool(cfg.get("store_normal_parcels", True)),
            status_report_every=int(cfg.get("status_report_every", 20)),
            max_storage_load=float(cfg.get("max_storage_load", 0.9)),
        )

        self.fleet = build_fleet(
            self.env,
            homes=cfg.get("robot_homes") or DEFAULT_ROBOT_HOME,
            speed=int(cfg.get("robot_speed", 1)),
            load_capacity=int(cfg.get("robot_load_capacity", 3)),
            low_battery=policy.reserve_battery,
        )
        for robot in self.fleet.all():
            robot.resume_battery = policy.resume_battery

        self.tasks = TaskRegistry(self.ids,
                                  event_sink=self.logger.sink_for(EventCategory.TASK))

        self.world = World(env=self.env, tasks=self.tasks, fleet=self.fleet,
                           rng=self.rng, logger=self.logger, ids=self.ids,
                           policy=policy)
        # Built after the world because it reads it, and installed on it
        # because every agent has to reach the same one: a per-agent gate
        # would let an agent's own refusals go uncounted by everybody else.
        self.gate = PolicyGate(self.world)
        self.world.gate = self.gate
        # The other half of the same split: the gate says what an agent may
        # decide, and this carries out the physical interventions agents are
        # only allowed to ask for.
        self.recovery = RecoveryService(self.world)

        self.directory = Directory()
        self.bus = MessageBus(self.directory, self.logger,
                              ids=IdFactory(width=6),
                              keep=int(cfg.get("keep_messages", 6000)))

        self.generator = ParcelGenerator(
            self.env, self.rng, self.ids, self.logger,
            mean_interval=float(cfg.get("arrival_interval", 40.0)),
            initial=int(cfg.get("initial_parcels", 8)),
            max_on_dock=int(cfg.get("max_on_dock", 20)),
        )

        self._populate(cfg)

        # The backlog is on the dock before anybody presses Start. It used to
        # be put there by `start()`, which meant a freshly built run showed an
        # empty building: the operator opened the app, saw a bare floor and a
        # supervisor with nothing to supervise, and only on the first tick did
        # the morning's post appear out of nowhere. Parcels waiting at six for
        # a shift that begins at seven is the truthful order, and it is also
        # the one that reads correctly when the run is paused at tick zero.
        self.generator.seed_dock(self.world.tick, self.seed)

    def _populate(self, cfg: Dict[str, Any]) -> None:
        """
        Create and attach every agent, parents before children.

        Registration order is also the tick order, and both are declared here
        in one place rather than discovered from a dictionary -- so that when a
        run behaves differently after a refactor, the order is not one of the
        things you have to rule out.
        """
        supervisor = SupervisorAgent(
            objective=cfg.get("objective", DEFAULT_OBJECTIVE),
            brain=self._brains.get("SUPERVISOR"))
        planner = PlannerAgent(brain=self._brains.get("PLANNER"))
        intake = IntakeAgent(brain=self._brains.get("INTAKE"))
        sorting = SortingAgent(brain=self._brains.get("SORTING"))
        routing = RoutingAgent(brain=self._brains.get("ROUTING"))
        scheduling = SchedulingAgent(brain=self._brains.get("SCHEDULING"))
        resource = ResourceAgent(brain=self._brains.get("RESOURCE"))
        dispatch = DispatchAgent(brain=self._brains.get("DISPATCH"))

        subagents = [
            ValidationSubAgent("INTAKE",
                               brain=self._brains.get("SUB-VALIDATION")),
            RegistrationSubAgent("INTAKE",
                                 brain=self._brains.get("SUB-REGISTRATION")),
            BarcodeSubAgent("SORTING", brain=self._brains.get("SUB-BARCODE")),
            PriorityClassificationSubAgent("SORTING",
                                           brain=self._brains.get("SUB-PRIORITY")),
            DestinationClassificationSubAgent("SORTING",
                                              brain=self._brains.get("SUB-DESTINATION")),
            RoutePlanningSubAgent("ROUTING", brain=self._brains.get("SUB-ROUTE")),
            CollisionAvoidanceSubAgent("ROUTING",
                                       brain=self._brains.get("SUB-COLLISION")),
            QueueManagementSubAgent("SCHEDULING",
                                    brain=self._brains.get("SUB-QUEUE")),
            DeadlineMonitorSubAgent("SCHEDULING",
                                    brain=self._brains.get("SUB-DEADLINE")),
            AssignmentSubAgent("SCHEDULING",
                               brain=self._brains.get("SUB-ASSIGNMENT")),
            BatteryManagementSubAgent("RESOURCE",
                                      brain=self._brains.get("SUB-BATTERY")),
            ChargingStationSubAgent("RESOURCE",
                                    brain=self._brains.get("SUB-CHARGING")),
            StorageMonitoringSubAgent("RESOURCE",
                                      brain=self._brains.get("SUB-STORAGE")),
            ManifestSubAgent("DISPATCH",
                             brain=self._brains.get("SUB-MANIFEST")),
            PackingSubAgent("DISPATCH",
                            brain=self._brains.get("SUB-PACKING")),
        ]
        robots = [RobotAgent(robot, brain=self._brains.get(robot.robot_id))
                  for robot in self.fleet.all()]

        # Order is tick order, and a parent must be attached before its
        # children: the directory builds the tree from `parent_id`. The two
        # gates sit where they do in the parcel's life -- intake first, dispatch
        # last -- so a tick reads front door to back door.
        for agent in ([supervisor, planner, intake, sorting, routing,
                       scheduling, resource, dispatch] + subagents + robots):
            self._attach(agent)

        self.supervisor = supervisor
        # Conditional automation: how far a rule's answer has to fall short
        # before an expert asks its model. One setting for every expert, from
        # the configuration, and written into the run's summary.
        from ..agents.reasoning import DEFAULT_POLICY, POLICIES
        policy = str(cfg.get("consult_policy", DEFAULT_POLICY) or DEFAULT_POLICY)
        if policy not in POLICIES:
            raise ValueError(f"consult_policy is one of {POLICIES}, not {policy!r}")
        self.consult_policy = policy
        for expert in (planner, intake, sorting, routing, scheduling, resource, dispatch):
            expert.consult_policy = policy
        self.planner = planner
        self.experts = {a.agent_id: a for a in (intake, sorting, routing,
                                                scheduling, resource,
                                                dispatch)}
        self.subagents = {a.agent_id: a for a in subagents}
        self.robot_agents = {a.agent_id: a for a in robots}
        self._install_rule_coverage(cfg)
        self._install_async_decisions(cfg)
        self._install_urgent_route(cfg)
        self._install_interception()
        self._install_crew()

    def _install_async_decisions(self, cfg: Dict[str, Any]) -> None:
        """
        Whether a model decision may finish on a later tick (`BaseAgent.decide`).

        Off unless the configuration says `async_decisions`; the live runner
        switches it with `set_async_decisions` while its clock runs
        (`api/runner.py`): there a model that takes seconds
        must hold up the one parcel, robot or task it is deciding about, not
        the tick and every robot on the floor. Every headless run and every
        experiment keeps the tick waiting for the model, as before.
        `llm_deadline_ticks` is how long such a decision may stay with the
        model before the rule's answer is used (0: the service's own
        deadline, `CONSULT_DEADLINE_S`).
        """
        self.set_async_decisions(bool(cfg.get("async_decisions", False)),
                                 int(cfg.get("llm_deadline_ticks", 0) or 0))

    def set_async_decisions(self, on: bool, deadline_ticks: int = 0) -> None:
        """
        Switch non-blocking model decisions on or off for every expert.

        The live runner turns it on while its clock runs and off for a step
        taken by hand (`api/runner.py`). Decisions already with the model are
        finished either way, on the ticks that follow.
        """
        self.async_decisions = bool(on)
        for agent in [self.planner] + list(self.experts.values()):
            agent.async_decisions = bool(on)
            agent.llm_deadline_ticks = max(0, int(deadline_ticks or 0))

    def _install_urgent_route(self, cfg: Dict[str, Any]) -> None:
        """
        Whether urgent parcels go intake -> sorting hall -> door in one trip.

        Off unless the configuration says `urgent_via_sorting`, which the app
        sets for its runs. With it, an urgent parcel leaving intake is carried
        through the sorting hall and on to the dispatch door by the same robot,
        instead of being put down in the hall and collected again: its answer
        at the sorting stop is fixed by rule (URGENT -> DISPATCH), so there is
        nothing to wait there for.
        """
        wanted = bool(cfg.get("urgent_via_sorting", False))
        self.urgent_via_sorting = wanted
        destination_clerk = self.subagents.get("SUB-DESTINATION")
        if destination_clerk is not None:
            destination_clerk.urgent_via_sorting = wanted

    def _install_rule_coverage(self, cfg: Dict[str, Any]) -> None:
        """
        Whether a condition that says its rule covers the case is believed.

        `legacy` unless the configuration says `rule_coverage: authoritative`,
        which `normal_config()` sets for NORMAL runs.
        """
        wanted = str(cfg.get("rule_coverage", "legacy") or "legacy")
        if wanted not in ("legacy", "authoritative"):
            raise ValueError("rule_coverage is 'legacy' or 'authoritative', "
                             f"not {wanted!r}")
        self.rule_coverage = wanted
        for agent in [self.planner] + list(self.experts.values()):
            agent.rule_coverage = wanted

    @staticmethod
    def _refuse_perturbations(cfg: Dict[str, Any]) -> None:
        """
        Refuse a configuration that asks for any perturbation.

        Perturbations are not part of this phase: a non-empty `interceptors`
        list or any truthy `perturbations` key is an error rather than a run
        that would build silently mislabelled as NORMAL.
        """
        interceptors = cfg.get("interceptors", [])
        if (interceptors != [] and interceptors != ()) or cfg.get("perturbations"):
            raise ValueError("perturbations are not part of this phase")

    def _install_interception(self) -> None:
        """
        The interception layer, inert in this phase.

        The configuration has already been checked by `_refuse_perturbations`.
        The (empty) set in force is written to the log so a run record says
        so rather than leaving it to be inferred.
        """
        self._refuse_perturbations(self.config)
        # The C2-NEAR-SYSTEM-OVERRIDE campaign is the one thing the seam can
        # carry; it is listed here when its key is present and nowhere else.
        active = ["c2near_system_override"] if self.config.get("c2near_system_override") else []
        self.logger.emit(EventCategory.SIMULATION, "interception",
                         tick=self.world.tick, actor="SIMULATION", active=active,
                         perturbations="none")

    def _install_crew(self) -> None:
        """
        The CrewAI consultation service, for the experts that have a `CrewBrain`.

        CrewAI replaces the implementation of model-backed peer consultation at
        the Brain seam while preserving the existing peer map and consultation
        semantics. One `OllamaAudit` per ecosystem: the experts' shared LLM is
        rebuilt here (`build_llm`, with the same checks) around this
        ecosystem's audit and given to every CrewAI agent, because CrewAI
        builds its HTTP clients when the LLM is made and an interceptor set
        afterwards would never be used. A reset therefore gets a fresh audit
        too. The service's interception is `from_config(self.config)`, inert
        in this phase (`_refuse_perturbations` has already turned away any
        configuration that asks for more, before the logger opened). Without any
        `CrewBrain` nothing is installed and CrewAI is never imported.
        """
        self.crew = None
        self.activity = None
        # A CrewBrain is recognised by its CrewAI agent, so that a rules-only
        # run does not import CrewAI to find out it has none.
        crew_brains = {agent_id: agent.brain for agent_id, agent in self.agents.items()
                       if getattr(agent.brain, "crew_agent", None) is not None
                       and hasattr(agent.brain, "bind")}
        if not crew_brains:
            return
        from ..crew.audit import OllamaAudit
        from ..crew.consultation import ConsultationService
        from ..crew.events import ConsultEvents
        from ..crew import interception
        from ..crew.llm import build_llm
        from ..discussion.briefings import briefing_for

        settings = next(iter(crew_brains.values())).settings
        assert all(b.settings == settings for b in crew_brains.values()), "one settings for all"
        audit = OllamaAudit(settings, on_call=lambda record: None)
        llm = build_llm(settings, interceptor=audit)
        for brain in crew_brains.values():
            brain.crew_agent.llm = llm
        events = ConsultEvents(self.logger, self.bus, settings.model)
        inter = interception.from_config(self.config)
        # Hooks that want the ecosystem (the C2-NEAR-SYSTEM-OVERRIDE campaign
        # reads its clock, its logger and its service) are bound here; the
        # plain `AgentHooks` of a Normal run has no `bind` and is untouched.
        bind = getattr(inter.agent, "bind", None)
        if callable(bind):
            bind(self)
        service = ConsultationService(
            agents={agent_id: brain.crew_agent for agent_id, brain in crew_brains.items()},
            world=self.world, bus=self.bus, logger=self.logger,
            interception=inter, settings=settings,
            audit=audit,
            briefing_source=lambda agent_id: briefing_for(self.agents[agent_id]),
            events=events)
        for brain in crew_brains.values():
            brain.bind(service)
        self.crew = service
        self.logger.emit(EventCategory.SIMULATION, "llm", tick=self.world.tick,
                         actor="SIMULATION", backend="ollama", model=settings.model,
                         base_url=settings.base_url, agents=sorted(crew_brains))
        self._install_activity()

    def _install_activity(self) -> None:
        """
        The idle gate for the experts' model calls (`simulation.activity`).

        Installed with the consultation service, so only in a run with an
        expert on the model: a rules-only run has no model call to skip, and
        builds, runs and logs exactly as it did without it.
        """
        from .activity import ActivityGate

        gate = ActivityGate(self.fleet, self.env, self.logger)
        self.activity = gate
        self.world.activity = gate
        gate.announce(self.world.tick)

    def _attach(self, agent: BaseAgent) -> None:
        agent.attach(self.bus, self.world)
        self.agents[agent.agent_id] = agent
        self.order.append(agent.agent_id)

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self.world.running:
            return
        self.logger.emit(EventCategory.SIMULATION, "simulation_started",
                         tick=self.world.tick, actor="SIMULATION",
                         seed=self.seed, run_id=self.run_id,
                         scenario=self.scenario,
                         agents=len(self.agents), robots=len(self.fleet),
                         config=dict(self.config))
        self.supervisor.start()
        self.env.departures.open(self.world.tick)

    def stop(self, reason: str = "stopped") -> None:
        if self.supervisor.world is not None and self.world.running:
            self.supervisor.stop(reason)
        self.logger.emit(EventCategory.SIMULATION, "simulation_stopped",
                         tick=self.world.tick, actor="SIMULATION", reason=reason)

    def close(self) -> None:
        crew = getattr(self, "crew", None)
        if crew is not None:
            # A consultation abandoned at its deadline may still be running on
            # a CrewAI agent the next ecosystem (a reset) will reuse; two loops
            # on one agent would share its executor, so wait for it first. So
            # may one a live run started and was still waiting on: it is
            # closed as abandoned first, so it writes nothing more.
            crew.abandon_pending()
            crew.drain(crew.settings.consult_deadline_s)
        for agent in self.agents.values():
            agent.brain.close()
        self.logger.close()

    def _depart_vans(self, tick: int) -> None:
        """Let go the vans whose time has come, and take their parcels away."""
        for van in self.env.departures.advance(tick):
            for parcel_id in van.loaded:
                parcel = self.env.parcels.get(parcel_id)
                if parcel is None:
                    continue
                parcel.set_status(ParcelStatus.DISPATCHED, tick, "DISPATCH",
                                  vehicle=van.vehicle_id, route=van.route)
                self.env.remove_parcel(parcel_id)
            self.logger.emit(EventCategory.PARCEL, "van_departed", tick=tick,
                             actor="DISPATCH", vehicle=van.vehicle_id,
                             route=van.route, parcels=len(van.loaded),
                             units=van.units, capacity=van.capacity)

    # ------------------------------------------------------------- the clock
    def step(self) -> Dict[str, Any]:
        """One tick. Returns the snapshot it produced."""
        # A consultation started on an earlier tick may still be running; what
        # its worker writes to the run waits for the end of this tick
        # (`ConsultationService.tick_lock`). No lock without a model.
        crew = getattr(self, "crew", None)
        with (crew.tick_lock if crew is not None else contextlib.nullcontext()):
            return self._step()

    def _step(self) -> Dict[str, Any]:
        tick = self.world.tick + 1
        self.world.advance(tick)
        self.bus.advance(tick)

        self.bus.deliver()

        # Idle or active for this whole tick, read before any agent steps
        # (a run with an expert on the model only; see `simulation.activity`).
        if self.activity is not None:
            self.activity.observe(tick)

        if self.world.running:
            self.generator.step(tick, self.seed)

        for agent_id in self.order:
            agent = self.agents.get(agent_id)
            if agent is not None:
                agent.step()

        # After the agents, because a request made this tick is a request the
        # facility has not acted on yet. The engine decides what becomes of
        # it; the agent that asked has no say from here.
        self.recovery.step(tick)

        # After the agents, so a van that leaves this tick takes everything the
        # gate managed to load onto it this tick. A departure is the facility's
        # doing and not an agent's -- it happens whether or not anybody was
        # ready, which is what makes it a cut-off.
        self._depart_vans(tick)

        snapshot = self.snapshot()
        self.snapshots.append(snapshot)
        if len(self.snapshots) > 2000:
            del self.snapshots[:1000]
        return snapshot

    def reasoning_summary(self) -> Dict[str, Dict[str, Any]]:
        """
        How much of this run was thought about, and why.

        One row per expert: decisions taken, how many of those went to the
        brain rather than the rule, what triggered them, and how often the
        gate refused the result. This is the measurement the conditional
        arrangement exists to produce -- a quiet facility should be almost
        entirely rules, and the interesting question is what the ratio does
        as the floor is put under pressure.
        """
        summary: Dict[str, Dict[str, Any]] = {}
        reasoners = dict(self.experts)
        reasoners[self.planner.agent_id] = self.planner
        for agent_id, agent in sorted(reasoners.items()):
            summary[agent_id] = {
                "decisions": agent._decisions_made,
                "llm": agent.reasoned,
                "refused": agent.gate_refusals,
                "triggers": dict(sorted(agent.trigger_counts.items())),
                # Pressure noticed while the rule still answered -- the
                # decisions the earlier arrangement would have sent to the
                # model and this one keeps on the rule.
                "noted": dict(sorted(agent.noted_counts.items())),
                # Where the answers came from: deterministic, llm/<trigger>,
                # fallback. The telemetry that shows a normal run is mostly
                # rules and only sometimes the model.
                "paths": dict(sorted(agent.path_counts.items())),
                # Triggers that would have called the model while the
                # facility was idle; the rule answered (`simulation.activity`).
                "idle_skipped": agent.idle_skips,
                # In a live run: model calls not made because the expert's
                # model was still on an earlier question; the rule answered.
                "busy_skipped": getattr(agent, "busy_skips", 0),
                # How each decision was handled: rule_sufficient,
                # llm_insufficient, idle_rule, idle_no_rule, rule_no_model.
                "handling": dict(sorted(agent.handling_counts.items())),
            }
        return summary

    def decision_paths(self) -> Dict[str, int]:
        """The whole run's decisions by where the answer came from."""
        total: Dict[str, int] = {}
        for row in self.reasoning_summary().values():
            for path, n in row["paths"].items():
                total[path] = total.get(path, 0) + n
        return dict(sorted(total.items()))

    def run(self, ticks: int, on_tick=None) -> None:
        for _ in range(int(ticks)):
            snapshot = self.step()
            if on_tick is not None:
                on_tick(snapshot)

    def reset(self, run_id: Optional[str] = None,
              brains: Optional[Dict[str, Brain]] = None,
              seed: Optional[int] = None,
              config: Optional[Dict[str, Any]] = None,
              scenario: Optional[str] = None) -> "PostOfficeEcosystem":
        """
        A fresh ecosystem with the same seed and config.

        Rebuilding rather than unwinding: a reset that tries to put a running
        system back to zero in place is how stale state survives into the next
        run and quietly ruins it.

        `run_id` names the new run. Reusing the old name keeps the two runs in
        one stream, which is what the JSONL file has always done and what the
        tests expect; a caller that stores runs separately -- the trace database
        does -- passes a fresh one so a row can be attributed to exactly one of
        them.

        `brains` is the one thing a reset can change, because a brain is handed
        to an agent when the agent is built and never after. Passing a new
        mapping is therefore how a model gets behind an agent that did not have
        one; passing nothing keeps whatever this ecosystem was built with. An
        empty mapping is a choice and is honoured: it means every agent back on
        its own Python rules.
        """
        self.close()
        # `seed` and `config` are the other two things a rebuild can change,
        # and for the same reason as `brains`: both are read at construction
        # and never after, so a different day or a different scenario means a
        # different facility. Neither moves on an ordinary reset -- "put that
        # back how it was" should hand you the run you were already watching.
        return PostOfficeEcosystem(seed=self.seed if seed is None else int(seed),
                                   config=(self.config if config is None
                                           else dict(config)),
                                   log_path=self.log_path,
                                   run_id=run_id or self.run_id,
                                   brains=(self._brains if brains is None
                                           else brains),
                                   # Carried with the config, because the two
                                   # are one choice.
                                   scenario=(self.scenario if scenario is None
                                             else scenario))

    # --------------------------------------------------------------- reports
    def snapshot(self) -> Dict[str, Any]:
        # Deliberately cheap: this is built once per tick, so it counts what is
        # still inside and reads the facility's running totals for the rest
        # rather than walking every parcel the run has ever seen.
        env = self.env
        inside = env.parcels
        return {
            "tick": self.world.tick,
            "running": self.world.running,
            "parcels_total": len(inside) + len(env.departed),
            "parcels_on_floor": sum(1 for p in inside.values()
                                    if p.position is not None),
            "parcels_dispatched": env.dispatched_count,
            # Apart from the dispatched total on purpose: a parcel the intake
            # gate turned away was never handled, and folding the two together
            # would flatter the throughput figure by the refusal rate.
            "parcels_refused": env.refused_count,
            "parcels_returned": env.returned_count,
            "mean_dwell": env.mean_dwell,
            "tasks": self.tasks.counts(),
            "robots": self.fleet.status_counts(),
            "battery": self.fleet.battery_summary(),
            "storage": {"used": env.storage.used,
                        "capacity": env.storage.capacity,
                        "refusals": env.storage.refusals},
            "messages": self.bus.log.sent,
            "messages_refused": self.bus.log.refused,
            "events": self.logger.total,
        }

    def summary(self) -> Dict[str, Any]:
        """What a demonstration prints at the end."""
        parcels = list(self.env.all_parcels().values())
        dispatched = [p for p in parcels if p.status is ParcelStatus.DISPATCHED]
        dwells = sorted(p.dwell for p in dispatched if p.dwell is not None)
        by_status: Dict[str, int] = {}
        for parcel in parcels:
            by_status[parcel.status.value] = by_status.get(parcel.status.value, 0) + 1
        return {
            "run_id": self.run_id,
            "seed": self.seed,
            "scenario": self.scenario,
            "consult_policy": getattr(self, "consult_policy", "insufficient"),
            "decision_paths": self.decision_paths(),
            # The idle gate's record (`simulation.activity`): None in a
            # rules-only run, which has no model call to skip.
            "activity": (self.activity.summary()
                         if getattr(self, "activity", None) is not None else None),
            "ticks": self.world.tick,
            "agents": len(self.agents),
            "experts": len(self.experts),
            "subagents": len(self.subagents),
            "robots": len(self.fleet),
            "parcels_created": self.generator.created,
            "parcels_dispatched": len(dispatched),
            # The intake gate's refusals, counted apart from the dispatched
            # total: a parcel the facility declined was never handled, and
            # folding the two together would flatter the throughput figure.
            "parcels_refused": self.env.refused_count,
            "parcels_returned": self.env.returned_count,
            # The first thing in this model that can go wrong for a parcel: it
            # missed the departure it was promised. Counted both ways -- those
            # that left late, and those still here whose van has gone.
            "parcels_late": sum(1 for p in parcels
                                if p.late_at(self.world.tick)),
            "vans_departed": self.env.departures.departures,
            "parcels_by_status": dict(sorted(by_status.items())),
            "arrival_refusals": self.generator.refused,
            "median_dwell": dwells[len(dwells) // 2] if dwells else None,
            "tasks": self.tasks.counts(),
            "messages": self.bus.log.sent,
            "messages_refused": self.bus.log.refused,
            "events": self.logger.total,
            "storage_refusals": self.env.storage.refusals,
            "charge_refusals": self.experts["RESOURCE"].charge_refusals,
            "reroutes": self.experts["ROUTING"].reroutes,
            "supervisor_interventions": len(self.supervisor.interventions),
            "robots_recovered": self.experts["RESOURCE"].recoveries,
            "llm": self.llm_summary(),
        }

    def llm_summary(self) -> Dict[str, Any]:
        """The consultation service's figures for this run; empty without CrewBrains."""
        crew = getattr(self, "crew", None)
        return crew.summary() if crew is not None else {}


def build(seed: int = 1, config: Optional[Dict[str, Any]] = None,
          log_path: Optional[str] = None, run_id: str = "run",
          brains: Optional[Dict[str, Brain]] = None,
          scenario: str = "normal") -> PostOfficeEcosystem:
    """Convenience constructor, so callers need not import the class."""
    return PostOfficeEcosystem(seed=seed, config=config, log_path=log_path,
                               run_id=run_id, brains=brains,
                               scenario=scenario)
