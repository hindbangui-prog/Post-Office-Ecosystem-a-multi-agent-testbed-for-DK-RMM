"""
Every dial in one place, and the switch that turns an agent into an LLM agent.

The defaults here are the source simulator's, chosen there by measurement:
five robots clear roughly one parcel every forty ticks once blocking, charging
and coordination are counted, so arrivals are set just inside that. A tick is
one second; `SECONDS_PER_TICK` below says why that matters.

This prototype has one scenario, NORMAL: the facility under ordinary operating
conditions, its seven experts on CrewAI over a local Ollama model, watched by
DK-RMM. There are no load presets, stress presets or experiment families here;
a different configuration is `config(**overrides)`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence, Tuple

from ..environment.layout import CHARGE_RATE
from ..robots.robot import COMMIT_BELOW, WORKING_ORDER

if TYPE_CHECKING:
    from ..crew.audit import OllamaAudit
    from ..crew.brain import CrewBrain
    from .ollama import OllamaSettings


#: What a tick is. One second.
#:
#: Stated because a model whose time has no unit cannot be checked against
#: anything: "a median dwell of 400" can never be wrong, and "a median dwell of
#: about seven minutes" can. At one second per tick the figures this simulation
#: produces line up with a real sortation hub in the places that matter -- a
#: robot crosses the floor at about a metre a second, which is an ordinary AMR
#: speed; a twelve-thousand-tick run is three hours and twenty minutes; a median
#: dwell of three to six hundred ticks is five to ten minutes, which is the
#: right order for a parcel passing through a hub.
#:
#: The battery is scaled rather than exaggerated, which it did not used to be.
#: A full charge buys about 830 cells of travel -- roughly eighteen errands, or
#: twenty minutes of work at this scale -- and a committed charge takes about
#: fifty ticks. A real AMR works a shift and fast-charges in under half an hour;
#: the ratio between working and charging is what is preserved here, not the
#: absolute hours, exactly as the van timetable preserves the bite of a cut-off
#: without copying its interval. It used to be 180 cells and a twelve-second
#: recharge, which made a robot's day a shuttle between work and a plug.
SECONDS_PER_TICK = 1.0


def ticks_to_seconds(ticks: float) -> float:
    """Model time in seconds. The one place the scale is applied."""
    return float(ticks) * SECONDS_PER_TICK


def ticks_to_minutes(ticks: float) -> float:
    return ticks_to_seconds(ticks) / 60.0


#: The baseline run. Times are in ticks; a tick is one robot step, one second.
DEFAULT_CONFIG: Dict[str, Any] = {
    # ---------------------------------------------------------------- arrivals
    "arrival_interval": 40.0,      # mean ticks between parcels (geometric)
    # Last night's backlog, already on the dock when the shift starts. A
    # building that opens empty spends its first fifty ticks with five robots
    # looking for something to do, which is the least interesting part of the
    # run and the part anybody watching sees first. Starting loaded puts the
    # queue, the assignment contest and the shelf pressure on screen from tick
    # zero -- and it is what a sorting office actually looks like at six in the
    # morning.
    "initial_parcels": 14,
    # Beyond this, arrivals are refused and logged. Raised with the backlog so
    # that a full-looking dock still has room for the morning's post: a start
    # that instantly turns parcels away would report congestion the facility
    # never caused.
    "max_on_dock": 26,

    # ------------------------------------------------------------------ fleet
    "robot_speed": 1,              # cells per tick
    "robot_load_capacity": 3,      # size units; a LARGE parcel is 3
    # Below this a robot stops taking work and commits to a charge, and this
    # is what a committed charge brings it back to. The robot module owns both
    # numbers and the reasoning behind them.
    "reserve_battery": COMMIT_BELOW,
    "resume_battery": WORKING_ORDER,
    # Percent per tick on a charge point. The layout owns the number and
    # the reasoning behind it; this is the knob an experiment turns.
    "charge_rate": CHARGE_RATE,

    # ------------------------------------------------------------- the facility
    "storage_capacity": 20,        # shelves in temporary storage
    "max_storage_load": 0.9,       # above this, stop routing parcels there

    # --------------------------------------------------------------- the plan
    "max_concurrent_transports": 8,  # the supervisor's ceiling, which it moves
    "store_normal_parcels": True,    # standard post goes via the shelves
    "status_report_every": 20,       # planner -> supervisor cadence

    # ------------------------------------------------------ the agents' brains
    # Conditional automation. Every expert is LLM-based and every decision
    # goes to its Python rule first; the model is invoked only when the rule
    # is insufficient (no rule, no admissible answer, or a condition the agent
    # declared that means its rule cannot be trusted here). "any_trigger" is
    # the earlier arrangement -- every fired condition, including plain
    # contention, went to the model -- under which the recorded battery was
    # run; see `agents/reasoning.py`.
    "consult_policy": "insufficient",

    # -------------------------------------------------------------- the logs
    "keep_events": 8000,           # events held in memory for the API
    "keep_messages": 6000,
}


def normal_config() -> Dict[str, Any]:
    """
    The configuration a NORMAL run is built with.

    `DEFAULT_CONFIG`, with rule coverage authoritative (a condition that says
    its rule covers the case is believed, so the rule answers), urgent parcels
    carried through the sorting hall to the door in one trip, and no
    interceptors. This replaces the source app's `interactive_config`.
    """
    return {**DEFAULT_CONFIG,
            "consult_policy": "insufficient",
            "rule_coverage": "authoritative",
            "urgent_via_sorting": True,
            "interceptors": []}


PRESETS: Dict[str, Dict[str, Any]] = {"default": DEFAULT_CONFIG}

SCENARIOS = [("default", "NORMAL · CrewAI · Ollama/qwen3:8b · DK-RMM")]

SCENARIO_META: Dict[str, Dict[str, str]] = {
    "normal": {
        "label": "Normal Ecosystem",
        "monitoring": "Monitoring",
        "purpose": "No Perturbation",
        "about": "the facility under ordinary operating conditions, with its "
                 "own variability and its own naturally occurring deviations",
    },
}

#: The one preset and the scenario it is.
_SCENARIO_OF = {"default": "normal", "normal": "normal"}


def scenario_name(preset: str) -> str:
    """The scenario name for a preset: `normal` for `default` (or `normal`)."""
    key = str(preset).lower()
    return _SCENARIO_OF.get(key, key)


def scenario_meta(preset: str = "default") -> Dict[str, str]:
    """Label, monitoring state and purpose, for whoever has to show them."""
    name = scenario_name(preset)
    row = SCENARIO_META.get(name)
    if row is None:
        raise ValueError(f"unknown scenario {preset!r}; this prototype has only 'default' (normal)")
    return {"scenario": name, **row}


def config(preset: str = "default", **overrides) -> Dict[str, Any]:
    """A configuration dictionary: the default preset, plus whatever you want to change."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; this prototype has only 'default'")
    return {**PRESETS[preset], **overrides}


# ---------------------------------------------------------------------- LLMs
#: The seven experts, the only agents that may be given a model.
EXPERTS: Tuple[str, ...] = (
    "PLANNER",           # how much work to release, and what to prioritise
    "INTAKE",            # does the facility take this parcel at all?
    "SORTING",           # how urgent, and shelf or straight out?
    "SCHEDULING",        # which job next, and which robot takes it
    "ROUTING",           # wait, go round, give up the cell, or abandon
    "RESOURCE",          # battery, shelves, and four charge points for five
    "DISPATCH",          # send it now, or hold it for a fuller load?
)
LLM_CANDIDATES = EXPERTS


def llm_brains(agent_ids: Sequence[str] = (), settings: Optional["OllamaSettings"] = None,
               verify: bool = True, audit: Optional["OllamaAudit"] = None
               ) -> Dict[str, "CrewBrain"]:
    """
    A `CrewBrain` for each of `agent_ids` (default: all of `EXPERTS`).

    Any id outside `EXPERTS` is a `ValueError`: the seven experts are the only
    agents a model may sit behind. `settings` defaults to `load_settings()`.
    With `verify`, `require_model` must find the configured model on the
    Ollama server first (`ModelUnavailable` otherwise, nothing substituted).
    All the brains share one LLM, built with `audit` as its transport
    interceptor, and each gets a fresh `DeterministicBrain` as its fallback,
    which the agent fills with its rules when the ecosystem builds it.
    CrewAI is imported here and not at module level, so a rules-only run never
    loads it.
    """
    from ..agents.brain import DeterministicBrain
    from ..crew.brain import CrewBrain
    from ..crew.identity import require_model
    from ..crew.llm import build_llm
    from ..crew.roles import build_agents
    from .ollama import load_settings

    ids = tuple(agent_ids) or EXPERTS
    others = [i for i in ids if i not in EXPERTS]
    if others:
        raise ValueError(f"only the experts can be given a model "
                         f"({', '.join(EXPERTS)}); not {', '.join(others)}")
    settings = settings if settings is not None else load_settings()
    if verify:
        require_model(settings)
    agents = build_agents(build_llm(settings, interceptor=audit), thinking=settings.thinking)
    return {i: CrewBrain(i, fallback=DeterministicBrain(), crew_agent=agents[i],
                         settings=settings)
            for i in ids}
