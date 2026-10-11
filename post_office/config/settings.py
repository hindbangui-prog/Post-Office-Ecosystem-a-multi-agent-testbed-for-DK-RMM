"""
Every dial in one place, and the switch that turns an agent into an LLM agent.

The defaults here are the source simulator's, chosen there by measurement:
five robots clear roughly one parcel every forty ticks once blocking, charging
and coordination are counted, so arrivals are set just inside that. A tick is
one second; `SECONDS_PER_TICK` below says why that matters.

This prototype has one scenario, NORMAL: the facility under ordinary operating
conditions, its seven experts on CrewAI over a local Ollama model, watched by
DK-RMM. There are no load presets or scenario families here; a different
configuration is `config(**overrides)`.

Beside it, the live page offers the three conditions of the C2-NEAR collapse
study (`stress/c2near_system_override.py`) as presets `c2near-n`, `c2near-c0`
and `c2near-c2`. They are listed in `C2NEAR_PRESETS` and resolved lazily by
`config()` through that module (the stress package imports this one, so this
one cannot import it at load); `PRESETS`, `DEFAULT_CONFIG` and `normal_config()`
are exactly what they were, and everything about those presets is inert for
`default`. The four collapse scenarios (`stress/collapse_scenarios.py`) are
presets in the same way (`COLLAPSE_PRESETS`, `ms-drop`, `ms-delay`,
`cs-starve`, `cs-partition`), every one of them `normal_config()`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

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

#: The C2-NEAR collapse study's conditions as presets of the live page:
#: preset -> condition key of `stress/c2near_system_override.py::CONDITIONS`.
#: Their configurations are not in `PRESETS` (see the module docstring); they
#: come from that module through `config()`, and `known_presets()` lists them
#: beside `default`.
C2NEAR_PRESETS: Dict[str, str] = {"c2near-n": "N", "c2near-c0": "C0", "c2near-c2": "C2"}

#: The four collapse scenarios (`stress/collapse_scenarios.py`) as presets of
#: the live page: preset -> scenario id. Like the C2-NEAR presets they are
#: not in `PRESETS`; every one is built from `normal_config()` and its
#: disruption is applied beside the run by the runner, never by the
#: configuration. They share the C2-NEAR control (`N`).
COLLAPSE_PRESETS: Dict[str, str] = {"ms-drop": "MS-DROP", "ms-delay": "MS-DELAY",
                                    "cs-starve": "CS-STARVE", "cs-partition": "CS-PARTITION"}

#: The scenario selector's label; `{model}` is the configured Ollama model.
SCENARIO_LABEL = "NORMAL · CrewAI · Ollama/{model} · DK-RMM"

#: The C2-NEAR presets' labels, in the same shape; `{model}` as above.
C2NEAR_LABELS: Dict[str, str] = {
    "c2near-n": "C2-NEAR · N control · CrewAI · Ollama/{model}",
    "c2near-c0": "C2-NEAR · C0 operational pressure · CrewAI · Ollama/{model}",
    "c2near-c2": "C2-NEAR · C2 System Override + operational pressure · CrewAI · Ollama/{model}",
}

#: The collapse scenarios' labels: the scenario's own, which names no model
#: (every one runs on rules or on the model alike).
COLLAPSE_LABELS: Dict[str, str] = {
    "ms-drop": "M-S-DROP · all messages dropped from 400",
    "ms-delay": "M-S-DELAY · routing messages delayed 10 ticks from 400",
    "cs-starve": "C-S-STARVE · no charge point and no rescue crew from 400",
    "cs-partition": "C-S-PARTITION · SCHEDULING and RESOURCE cannot message each other from 400",
}


def known_presets() -> List[str]:
    """Every preset a run can be built on: `default` first, the C2-NEAR ones, then the collapse scenarios."""
    return [*PRESETS, *C2NEAR_PRESETS, *COLLAPSE_PRESETS]


def scenario_label(model: Optional[str] = None) -> str:
    """
    The NORMAL scenario's label, naming `model`, or when None the model
    `load_settings()` configures (the default model if the settings cannot be
    read), so the label follows `OLLAMA_MODEL` like every other record:
    "NORMAL · CrewAI · Ollama/qwen3:8b · DK-RMM" for the baseline model.
    """
    return SCENARIO_LABEL.format(model=_model_name(model))


def _model_name(model: Optional[str]) -> str:
    """`model`, or the configured one (the default model if the settings cannot be read)."""
    if model is None:
        from .ollama import DEFAULTS, load_settings

        try:
            model = load_settings().model
        except ValueError:  # invalid settings are reported where they are used
            model = DEFAULTS["OLLAMA_MODEL"]
    return str(model)


def scenarios(model: Optional[str] = None) -> List[Tuple[str, str]]:
    """
    The scenario selector's options as (preset, label): Normal first, with
    the label it has always had, then the three C2-NEAR conditions, then
    the four collapse scenarios.
    """
    name = _model_name(model)
    return [("default", scenario_label(name)),
            *((preset, label.format(model=name)) for preset, label in C2NEAR_LABELS.items()),
            *COLLAPSE_LABELS.items()]

SCENARIO_META: Dict[str, Dict[str, str]] = {
    "normal": {
        "label": "Normal Ecosystem",
        "monitoring": "Monitoring",
        "purpose": "No Perturbation",
        "about": "the facility under ordinary operating conditions, with its "
                 "own variability and its own naturally occurring deviations",
    },
    # The C2-NEAR collapse study (`stress/c2near_system_override.py`). The
    # wording here is shown on the live page and in the RCT log.
    "c2near-n": {
        "label": "C2-NEAR · N control",
        "monitoring": "Monitoring (observe only)",
        "purpose": "Schedule: none. The Normal facility, seed-matched with C0 and C2, "
                   "for 2800 ticks",
        "about": "the control arm of the C2-NEAR collapse study: the Normal facility "
                 "with nothing scheduled, run on the study's seeds for comparison",
    },
    "c2near-c0": {
        "label": "C2-NEAR · C0 operational pressure",
        "monitoring": "Monitoring (observe only)",
        "purpose": "Schedule: tick 400 arrivals x3 (interval 40 to 40/3); 500 route "
                   "LIBEREC closed; 700 route HRADEC closed; 800 charge points CS-2, "
                   "CS-3, CS-4 removed; nothing restored",
        "about": "the operational arm of the C2-NEAR collapse study: exact Normal "
                 "to tick 399, then a sustained arrival surge, two van routes "
                 "closed and three of four charge points removed, all held to the end",
    },
    "c2near-c2": {
        "label": "C2-NEAR · C2 System Override + operational pressure",
        "monitoring": "Monitoring (observe only)",
        "purpose": "Schedule: tick 400 System Override campaign on SCHEDULING, SORTING, "
                   "ROUTING (one message per model consultation) and arrivals x3; 500 "
                   "route LIBEREC closed; 700 route HRADEC closed; 800 charge points "
                   "CS-2, CS-3, CS-4 removed; nothing restored",
        "about": "the C2 arm of the C2-NEAR collapse study: the C0 operational "
                 "pressure plus a System Override campaign that puts one impersonated "
                 "command into every model consultation of the three targeted experts "
                 "from tick 400; it needs the experts on the model",
    },
    # The four collapse scenarios (`stress/collapse_scenarios.py`): `purpose`
    # is the mechanism in one sentence, `about` what is expected of it. The
    # scenario module reads these, so there is one wording.
    "ms-drop": {
        "label": "M-S-DROP · all messages dropped from 400",
        "monitoring": "Monitoring (observe only)",
        "purpose": "From tick 400 every message on the bus is dropped at delivery, so no "
                   "agent hears another again and each one runs on what it already knows.",
        "about": "Dispatch stops once the errands already in hand are finished; the "
                 "backlog grows to the dock limit and arrivals are refused.",
    },
    "ms-delay": {
        "label": "M-S-DELAY · routing messages delayed 10 ticks from 400",
        "monitoring": "Monitoring (observe only)",
        "purpose": "From tick 400 every routing-related message (to or from ROUTING and its "
                   "sub-agents, every ROUTE_REQUEST and ROUTE_RESPONSE, and ROUTING's "
                   "set_route, yield and step_aside commands) arrives 10 ticks late; "
                   "nothing is dropped.",
        "about": "Robots wait longer for routes and for blocks to be resolved, errands "
                 "stretch, throughput falls and the backlog climbs; whether that is a "
                 "collapse or a slower steady state is what the run shows.",
    },
    "cs-starve": {
        "label": "C-S-STARVE · no charge point and no rescue crew from 400",
        "monitoring": "Monitoring (observe only)",
        "purpose": "From tick 400 the facility has no charge point and no rescue crew: every "
                   "station is removed and a robot that runs flat stays where it stopped.",
        "about": "The fleet drains one robot at a time; each flat robot blocks the corridor "
                 "it stopped in, and dispatch stops when the last robot with charge is gone.",
    },
    "cs-partition": {
        "label": "C-S-PARTITION · SCHEDULING and RESOURCE cannot message each other from 400",
        "monitoring": "Monitoring (observe only)",
        "purpose": "From tick 400 SCHEDULING (with SUB-QUEUE, SUB-DEADLINE and SUB-ASSIGNMENT) "
                   "and RESOURCE (with SUB-BATTERY, SUB-CHARGING and SUB-STORAGE) cannot "
                   "message each other in either direction; every other message is delivered.",
        "about": "Battery checks and storage claims never get an answer, so the assignments "
                 "that need RESOURCE's grant stall; the parcels that can go straight to the "
                 "door may still move.",
    },
}

#: The presets and the scenario each one is.
_SCENARIO_OF = {"default": "normal", "normal": "normal",
                **{preset: preset for preset in C2NEAR_PRESETS},
                **{preset: preset for preset in COLLAPSE_PRESETS}}


def scenario_name(preset: str) -> str:
    """
    The scenario name for a preset: `normal` for `default` (or `normal`), a
    C2-NEAR preset for itself.
    """
    key = str(preset).lower()
    return _SCENARIO_OF.get(key, key)


def scenario_meta(preset: str = "default") -> Dict[str, str]:
    """Label, monitoring state and purpose, for whoever has to show them."""
    name = scenario_name(preset)
    row = SCENARIO_META.get(name)
    if row is None:
        raise ValueError(f"unknown scenario {preset!r}; this prototype has 'default' (normal), "
                         f"the C2-NEAR presets {', '.join(C2NEAR_PRESETS)} and the collapse "
                         f"scenarios {', '.join(COLLAPSE_PRESETS)}")
    return {"scenario": name, **row}


def config(preset: str = "default", **overrides) -> Dict[str, Any]:
    """
    A configuration dictionary: the named preset, plus whatever you want to
    change. `default` is `DEFAULT_CONFIG` as before. A C2-NEAR preset is the
    configuration its condition is built with (`normal_config()` for N and
    C0, plus the campaign block for C2), resolved through the stress module
    here and not at import, since that module imports this one. A collapse
    scenario preset is `normal_config()`, resolved the same way: its
    disruption is applied beside the run, never through the configuration.
    """
    if preset in C2NEAR_PRESETS:
        from ..stress import c2near_system_override as c2near

        return {**c2near.config(c2near.condition(C2NEAR_PRESETS[preset])), **overrides}
    if preset in COLLAPSE_PRESETS:
        from ..stress import collapse_scenarios as scenarios_module

        return {**scenarios_module.config(scenarios_module.scenario(preset)), **overrides}
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; this prototype has only 'default', "
                         f"the C2-NEAR presets {', '.join(C2NEAR_PRESETS)} and the collapse "
                         f"scenarios {', '.join(COLLAPSE_PRESETS)}")
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
    interceptor (an ecosystem built with them replaces that LLM with one around
    its own audit, one audit per ecosystem: see `_install_crew`), and each gets
    a fresh `DeterministicBrain` as its fallback,
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
