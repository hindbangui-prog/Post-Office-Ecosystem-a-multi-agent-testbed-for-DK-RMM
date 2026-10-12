"""
M-S-DROP decision-pathway analysis: rules-only, model-enabled, and the matched
no-drop control, read from the runs' own event logs.

Usage (from the repository root):

    python tools/analyze_ms_drop_model.py \
        --model results/collapse_scenarios/MS-DROP \
        --model-summary results/collapse_scenarios/summary.json \
        --rules <rules-only MS-DROP dir> --rules-summary <its summary.json> \
        --control results/c2_near_system_override/N \
        --out results/m_s_drop_crewai/analysis

Each of `--model`, `--rules` and `--control` is a directory holding one
`s<seed>/` folder per seed, as `tools/run_collapse_scenarios.py` and
`tools/run_c2near_system_override.py` write them. Any of the three may be left
out. Nothing is read from configuration to decide what the model did: every
count below comes from an event in `events.jsonl` (or, for the collapse
verdict and the DK-RMM sequence, from the files the driver wrote beside it).

What is counted, split at the fault tick (`--fault-tick`, 400) into `pre`
(ticks before it) and `post` (the fault tick and after):

decisions        `decision` events, per acting agent: all; answered by the rule
                 (`status` "deterministic"); eligible for the model (the rule
                 recorded a trigger, `detail.trigger` non-empty); answered by
                 the model and accepted (`llm_accepted`); model answer refused
                 and the rule's used (`llm_rejected`); refused by the gate
                 (`validation` "policy" or "state"), split by who proposed it;
                 malformed (`validation` "schema").
consultations    `consult_opened` per owner, `consult_closed` by outcome, peer
                 questions, delegations and responses, refusals; and the tick
                 gap between a question and its response (0 means the exchange
                 finished inside the tick, which a bus message cannot do: the
                 bus delivers at the next tick at the earliest).
model calls      `llm_call` per agent: count, HTTP 200 without error, failed,
                 by phase (owner, peer, late), latency, served model; owner
                 calls beyond the expected one (plus one after a peer exchange)
                 per consultation, which is what a retry would look like.
messages         `message` + `subagent_message` sent, by type; dropped
                 (`message_dropped`, matched by message id and counted in the
                 phase the message was sent in); delivered = sent - dropped -
                 still pending when the run ended (sent on the last tick).
robot commands   ROBOT_COMMAND messages sent, dropped, and applied: a robot
                 writes `command_<operation>` only inside `RobotAgent.handle`,
                 after a delivered command has been carried out.
chains           for every decision the model answered and the gate accepted:
                 the messages its agent sent in the same tick after it (until
                 the agent's next decision), whether they were dropped, and
                 whether any robot later applied a command carrying the
                 decision's correlation id. The message attribution is by
                 position in the log, not by an explicit link (the log has
                 none); it is stated as such in the output.
operations       arrivals, refusals, first refusal tick (the dock at its
                 limit), parcels departed and the last departure tick, tasks
                 started and completed, backlog at the end (series.csv).
collapse         the classification row of `--*-summary` for the seed.
dkrmm            `dkrmm.json`: which monitor wrote it (the extended monitor of
                 2026-10-12 records `communication_failure_rate`), state
                 counts, first DEVIATING / UNSTABLE / RCT at or after the
                 fault, RCT count, final state.

Outputs (never over an existing file): `<out>/analysis.json` and
`<out>/analysis.md`. Refuses an `--out` inside `results/normal`.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

FAULT_TICK = 400
PHASES = ("pre", "post")
GATE_REFUSALS = ("policy", "state")
MESSAGE_TOPICS = ("message", "subagent_message")


# --------------------------------------------------------------- helpers
def _phase(tick: int, fault_tick: int) -> str:
    return "post" if int(tick) >= fault_tick else "pre"


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _events(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _latency(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"n": 0, "mean_ms": None, "median_ms": None, "max_ms": None}
    return {"n": len(values), "mean_ms": round(statistics.mean(values), 1),
            "median_ms": round(statistics.median(values), 1),
            "max_ms": round(max(values), 1)}


def _new_decisions() -> Dict[str, int]:
    return {"all": 0, "rule": 0, "eligible": 0, "model_accepted": 0,
            "model_rejected": 0, "gate_refused_rule": 0, "gate_refused_model": 0,
            "malformed": 0, "other_status": 0}


# ------------------------------------------------------------ one run
def analyze_run(run_dir: Path, fault_tick: int = FAULT_TICK) -> Dict[str, Any]:
    """Every count of the module docstring for one run directory."""
    events_path = run_dir / "events.jsonl"
    decisions: Dict[str, Dict[str, Dict[str, int]]] = {
        p: defaultdict(_new_decisions) for p in PHASES}
    statuses: Dict[str, Counter] = {p: Counter() for p in PHASES}
    consult: Dict[str, Dict[str, Any]] = {
        p: {"opened": Counter(), "outcomes": Counter(), "questions": 0,
            "delegations": 0, "responses": 0, "refused": 0,
            "response_tick_gap": Counter(), "with_peer": 0} for p in PHASES}
    calls: Dict[str, Dict[str, Any]] = {
        p: {"by_agent": Counter(), "ok": 0, "failed": 0, "by_phase": Counter(),
            "served": Counter(), "latency": [], "errors": Counter()} for p in PHASES}
    owner_calls: Counter = Counter()
    exchanged: set = set()
    consult_phase: Dict[str, str] = {}
    question_tick: Dict[str, int] = {}

    sent: Dict[str, Dict[str, Any]] = {}          # message_id -> {tick, type, ...}
    dropped_ids: set = set()
    applied: Dict[str, Counter] = {p: Counter() for p in PHASES}
    applied_by_corr: Dict[str, List[int]] = defaultdict(list)
    task_assigned: Counter = Counter()
    ops: Dict[str, Any] = {"arrived": Counter(), "arrival_refused": Counter(),
                           "departed": Counter(), "tasks_started": Counter(),
                           "tasks_completed": Counter(), "first_refusal_tick": None,
                           "first_refusal_after_fault": None,
                           "last_departure_tick": None,
                           "last_departure_after_fault": None,
                           "last_command_applied_tick": None, "van_parcels": Counter()}
    # decisions answered by the model and accepted, with the messages that
    # followed them (attributed by position, see the docstring)
    chains: List[Dict[str, Any]] = []
    open_chain: Dict[str, Dict[str, Any]] = {}     # actor -> chain collecting messages
    last_tick = 0

    for event in _events(events_path):
        topic = event.get("topic", "")
        tick = int(event.get("tick", 0))
        last_tick = max(last_tick, tick)
        phase = _phase(tick, fault_tick)
        actor = str(event.get("actor") or "")
        detail = event.get("detail") or {}

        # a chain stops collecting at the end of its tick
        for key in [k for k, c in open_chain.items() if c["tick"] != tick]:
            open_chain.pop(key, None)

        if topic == "decision":
            row = decisions[phase][actor]
            row["all"] += 1
            status = str(detail.get("status") or "")
            statuses[phase][status] += 1
            validation = str(detail.get("validation") or "")
            model = status.startswith("llm")
            if status == "deterministic":
                row["rule"] += 1
            elif status == "llm_accepted":
                row["model_accepted"] += 1
            elif status == "llm_rejected":
                row["model_rejected"] += 1
            else:
                row["other_status"] += 1
            if detail.get("trigger"):
                row["eligible"] += 1
            if validation in GATE_REFUSALS:
                row["gate_refused_model" if model else "gate_refused_rule"] += 1
            if validation == "schema":
                row["malformed"] += 1
            open_chain.pop(actor, None)
            if status == "llm_accepted":
                chain = {"tick": tick, "phase": phase, "actor": actor,
                         "decision": detail.get("decision"),
                         "choice": detail.get("choice"),
                         "correlation_id": event.get("correlation_id") or "",
                         "messages": []}
                chains.append(chain)
                open_chain[actor] = chain

        elif topic == "consult_opened":
            cid = str(detail.get("consultation_id") or event.get("correlation_id") or "")
            consult_phase[cid] = phase
            consult[phase]["opened"][actor] += 1
            if detail.get("peer"):
                consult[phase]["with_peer"] += 1
        elif topic == "consult_closed":
            consult[phase]["outcomes"][str(detail.get("outcome") or "")] += 1
        elif topic in ("consult_question", "consult_delegation"):
            cid = str(detail.get("consultation_id") or "")
            consult[phase]["questions" if topic == "consult_question" else "delegations"] += 1
            question_tick[cid] = tick
            exchanged.add(cid)
        elif topic == "consult_response":
            cid = str(detail.get("consultation_id") or "")
            consult[phase]["responses"] += 1
            if cid in question_tick:
                consult[phase]["response_tick_gap"][tick - question_tick[cid]] += 1
        elif topic == "consult_refused":
            consult[phase]["refused"] += 1

        elif topic == "llm_call":
            c = calls[phase]
            c["by_agent"][actor] += 1
            ok = detail.get("status") == 200 and not detail.get("error")
            c["ok" if ok else "failed"] += 1
            if not ok:
                c["errors"][str(detail.get("error") or detail.get("status"))] += 1
            c["by_phase"][str(detail.get("phase") or "")] += 1
            c["served"][str(detail.get("served_model") or "")] += 1
            if detail.get("latency_ms") is not None:
                c["latency"].append(float(detail["latency_ms"]))
            if detail.get("phase") == "owner":
                owner_calls[str(detail.get("consultation_id") or "")] += 1

        elif topic in MESSAGE_TOPICS:
            mid = str(detail.get("message_id") or "")
            content = detail.get("content") or {}
            sent[mid] = {"tick": tick, "type": str(detail.get("message_type") or ""),
                         "operation": content.get("operation") if isinstance(content, dict) else None,
                         "sender": actor, "receiver": str(event.get("target") or "")}
            chain = open_chain.get(actor)
            if chain is not None:
                chain["messages"].append(mid)
        elif topic == "message_dropped":
            dropped_ids.add(str(detail.get("message_id") or ""))

        elif topic.startswith("command_"):
            applied[phase][topic[len("command_"):]] += 1
            applied_by_corr[str(event.get("correlation_id") or "")].append(tick)
            ops["last_command_applied_tick"] = tick
        elif topic == "task_assigned":
            task_assigned[phase] += 1
        elif topic == "parcel_arrived":
            ops["arrived"][phase] += 1
        elif topic == "arrival_refused":
            ops["arrival_refused"][phase] += 1
            if ops["first_refusal_tick"] is None:
                ops["first_refusal_tick"] = tick
            if phase == "post" and ops["first_refusal_after_fault"] is None:
                ops["first_refusal_after_fault"] = tick
        elif topic == "parcel_departed":
            ops["departed"][phase] += 1
            ops["last_departure_tick"] = tick
            if phase == "post":
                ops["last_departure_after_fault"] = tick
        elif topic == "van_departed":
            ops["van_parcels"][phase] += int(detail.get("parcels") or 0)
        elif topic == "task_started":
            ops["tasks_started"][phase] += 1
        elif topic == "task_completed":
            ops["tasks_completed"][phase] += 1

    # ---------------------------------------------------------- messages
    messages = {p: {"sent": 0, "dropped": 0, "delivered": 0, "pending_at_end": 0,
                    "by_type": defaultdict(lambda: {"sent": 0, "dropped": 0, "delivered": 0}),
                    "robot_commands": {"sent": 0, "dropped": 0, "delivered": 0,
                                       "by_operation": Counter()}}
                for p in PHASES}
    for mid, m in sent.items():
        p = _phase(m["tick"], fault_tick)
        row = messages[p]
        row["sent"] += 1
        fate = ("dropped" if mid in dropped_ids
                else "pending" if m["tick"] >= last_tick else "delivered")
        bucket = row["by_type"][m["type"]]
        bucket["sent"] += 1
        if fate == "dropped":
            row["dropped"] += 1
            bucket["dropped"] += 1
        elif fate == "pending":
            row["pending_at_end"] += 1
        else:
            row["delivered"] += 1
            bucket["delivered"] += 1
        if m["type"] == "ROBOT_COMMAND":
            rc = row["robot_commands"]
            rc["sent"] += 1
            rc["by_operation"][str(m["operation"])] += 1
            if fate == "dropped":
                rc["dropped"] += 1
            elif fate == "delivered":
                rc["delivered"] += 1

    # ------------------------------------------------------------ chains
    chain_summary = {p: {"model_decisions_accepted": 0, "with_messages": 0,
                         "messages": 0, "messages_dropped": 0, "messages_delivered": 0,
                         "with_robot_command_applied": 0, "by_decision": Counter()}
                     for p in PHASES}
    for chain in chains:
        s = chain_summary[chain["phase"]]
        s["model_decisions_accepted"] += 1
        s["by_decision"][f"{chain['actor']}:{chain['decision']}"] += 1
        if chain["messages"]:
            s["with_messages"] += 1
        s["messages"] += len(chain["messages"])
        s["messages_dropped"] += sum(1 for m in chain["messages"] if m in dropped_ids)
        s["messages_delivered"] += sum(1 for m in chain["messages"]
                                       if m not in dropped_ids and sent[m]["tick"] < last_tick)
        corr = chain["correlation_id"]
        if corr and any(t >= chain["tick"] for t in applied_by_corr.get(corr, [])):
            s["with_robot_command_applied"] += 1

    # ------------------------------------------------- retries (owner calls)
    beyond = 0
    for cid, n in owner_calls.items():
        expected = 2 if cid in exchanged else 1
        if n > expected:
            beyond += n - expected

    # -------------------------------------------------------- side files
    done = _read_json(run_dir / "done.json") or {}
    verify = _read_json(run_dir / "verify.json") or {}
    backlog_end = None
    try:
        with (run_dir / "series.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if rows:
            backlog_end = int(float(rows[-1]["backlog"]))
    except (OSError, KeyError, ValueError):
        backlog_end = None
    dk = _dkrmm(run_dir / "dkrmm.json", fault_tick)

    def phased(counter: Counter) -> Dict[str, int]:
        return {p: int(counter.get(p, 0)) for p in PHASES}

    out: Dict[str, Any] = {
        "run_dir": str(run_dir),
        "mode": done.get("mode") or verify.get("mode"),
        "seed": done.get("seed"),
        "ticks": done.get("ticks"),
        "last_tick": last_tick,
        "model": ((verify.get("settings") or {}).get("model")
                  if verify.get("mode") == "model" else None),
        "model_digest": ((verify.get("identity") or {}).get("digest")
                         if verify.get("mode") == "model" else None),
        "served_models": verify.get("served_models"),
        "decisions": {p: {a: dict(r) for a, r in sorted(decisions[p].items())} for p in PHASES},
        "decision_status": {p: dict(statuses[p]) for p in PHASES},
        "consultations": {p: {**{k: (dict(v) if isinstance(v, Counter) else v)
                                 for k, v in consult[p].items()}} for p in PHASES},
        "llm_calls": {p: {"total": sum(calls[p]["by_agent"].values()),
                          "ok": calls[p]["ok"], "failed": calls[p]["failed"],
                          "errors": dict(calls[p]["errors"]),
                          "by_agent": dict(calls[p]["by_agent"]),
                          "by_phase": dict(calls[p]["by_phase"]),
                          "served": dict(calls[p]["served"]),
                          "latency": _latency(calls[p]["latency"])} for p in PHASES},
        "owner_calls_beyond_expected": beyond,
        "messages": {p: {"sent": messages[p]["sent"], "dropped": messages[p]["dropped"],
                         "delivered": messages[p]["delivered"],
                         "pending_at_end": messages[p]["pending_at_end"],
                         "by_type": {k: dict(v) for k, v in sorted(messages[p]["by_type"].items())},
                         "robot_commands": {**{k: v for k, v in messages[p]["robot_commands"].items()
                                               if k != "by_operation"},
                                            "by_operation": dict(messages[p]["robot_commands"]["by_operation"]),
                                            "applied": dict(applied[p]),
                                            "applied_total": sum(applied[p].values())}}
                     for p in PHASES},
        "task_assigned_in_registry": phased(task_assigned),
        "chains": {p: {**{k: v for k, v in chain_summary[p].items() if k != "by_decision"},
                       "by_decision": dict(chain_summary[p]["by_decision"])} for p in PHASES},
        "chain_attribution": ("messages sent by the deciding agent in the same tick after "
                              "the decision and before its next decision; position in the log, "
                              "not an explicit link"),
        "operations": {"arrived": phased(ops["arrived"]),
                       "arrival_refused": phased(ops["arrival_refused"]),
                       "first_refusal_tick": ops["first_refusal_tick"],
                       "first_refusal_after_fault": ops["first_refusal_after_fault"],
                       "departed": phased(ops["departed"]),
                       "van_parcels": phased(ops["van_parcels"]),
                       "last_departure_tick": ops["last_departure_tick"],
                       "last_departure_after_fault": ops["last_departure_after_fault"],
                       "tasks_started": phased(ops["tasks_started"]),
                       "tasks_completed": phased(ops["tasks_completed"]),
                       "last_command_applied_tick": ops["last_command_applied_tick"],
                       "backlog_end": backlog_end},
        "dkrmm": dk,
    }
    for p in PHASES:
        totals = _new_decisions()
        for row in out["decisions"][p].values():
            for k in totals:
                totals[k] += row[k]
        out.setdefault("decision_totals", {})[p] = totals
        eligible = totals["eligible"]
        opened = sum(out["consultations"][p]["opened"].values())
        out.setdefault("eligible_consulted", {})[p] = {
            "eligible": eligible, "consulted": opened,
            "share": (round(opened / eligible, 4) if eligible else None)}
    return out


def _dkrmm(path: Path, fault_tick: int) -> Dict[str, Any]:
    data = _read_json(path)
    if not data:
        return {"available": False}
    state = data.get("state") or {}
    record = data.get("record") or {}
    # `state_series` is one row per assessment ({"tick", "state", ...});
    # `ticks` is the same spine as plain integers.
    rows = record.get("state_series") or []
    ticks = record.get("ticks") or []
    indicators = record.get("indicator_series") or {}
    states = [(int(r.get("tick", t)), str(r.get("state")))
              if isinstance(r, dict) else (int(t), str(r))
              for t, r in zip(ticks, rows)]
    first: Dict[str, Optional[int]] = {}
    for name in ("DEVIATING", "UNSTABLE", "RCT"):
        first[name] = next((t for t, s in states if t >= fault_tick and s == name), None)
    after = Counter(s for t, s in states if t >= fault_tick)
    cfr = indicators.get("communication_failure_rate")
    first_cfr_full = None
    if cfr:
        first_cfr_full = next((int(t) for t, v in zip(ticks, cfr)
                               if int(t) >= fault_tick and v is not None and float(v) >= 0.99), None)
    return {"available": True,
            "monitor": "extended (2026-10-12)" if cfr is not None else "pre-extension",
            "counts": state.get("counts"),
            "final": ((state.get("current") or {}).get("state")),
            "first_after_fault": first,
            "counts_after_fault": dict(after),
            "rct_count": int((state.get("counts") or {}).get("RCT", 0)),
            "first_failure_rate_full": first_cfr_full}


# ------------------------------------------------------------- campaign
def _summary_rows(path: Optional[Path]) -> Dict[int, Dict[str, Any]]:
    if path is None:
        return {}
    data = _read_json(path) or {}
    return {int(r["seed"]): r for r in data.get("runs", [])
            if r.get("scenario") == "MS-DROP"}


def _seed_dirs(root: Optional[Path]) -> Dict[int, Path]:
    if root is None or not root.is_dir():
        return {}
    out = {}
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name.startswith("s") and child.name[1:].isdigit():
            if (child / "events.jsonl").exists():
                out[int(child.name[1:])] = child
    return out


COLLAPSE_KEYS = ("outcome", "collapse_tick", "collapse_criterion", "first_degraded_tick",
                 "critical_stop_tick", "dispatched", "backlog_end", "arrival_refused",
                 "dropped", "dkrmm", "rcts")


def analyze(model: Optional[Path], rules: Optional[Path], control: Optional[Path],
            model_summary: Optional[Path], rules_summary: Optional[Path],
            fault_tick: int = FAULT_TICK) -> Dict[str, Any]:
    groups = {"model": _seed_dirs(model), "rules": _seed_dirs(rules),
              "control": _seed_dirs(control)}
    summaries = {"model": _summary_rows(model_summary), "rules": _summary_rows(rules_summary)}
    seeds = sorted(set().union(*[set(g) for g in groups.values()]))
    result: Dict[str, Any] = {"fault_tick": fault_tick, "seeds": seeds,
                              "sources": {"model": str(model) if model else None,
                                          "rules": str(rules) if rules else None,
                                          "control": str(control) if control else None,
                                          "model_summary": str(model_summary) if model_summary else None,
                                          "rules_summary": str(rules_summary) if rules_summary else None},
                              "runs": {}}
    for label, dirs in groups.items():
        for seed, path in dirs.items():
            run = analyze_run(path, fault_tick)
            row = summaries.get(label, {}).get(seed)
            run["collapse"] = ({k: row.get(k) for k in COLLAPSE_KEYS} if row else None)
            result["runs"].setdefault(label, {})[str(seed)] = run
    return result


# -------------------------------------------------------------- markdown
def _get(run: Optional[Dict[str, Any]], *path: str) -> Any:
    cur: Any = run
    for key in path:
        if cur is None:
            return None
        cur = cur.get(key) if isinstance(cur, dict) else None
    return cur


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple)):
        return "+".join(str(v) for v in value)
    return str(value)


def markdown(result: Dict[str, Any]) -> str:
    runs = result["runs"]
    lines = [f"# M-S-DROP decision pathway, fault at tick {result['fault_tick']}", "",
             "Generated by `tools/analyze_ms_drop_model.py` from the runs' event logs. "
             "`pre` is ticks before the fault, `post` the fault tick and after. "
             "n/a means the value is not in that run's files.", ""]
    rows = [
        ("LLM calls, pre / post", lambda r: f"{_get(r,'llm_calls','pre','total')} / {_get(r,'llm_calls','post','total')}"),
        ("LLM calls failed (all)", lambda r: _fmt((_get(r,'llm_calls','pre','failed') or 0) + (_get(r,'llm_calls','post','failed') or 0))),
        ("decisions, pre / post", lambda r: f"{_get(r,'decision_totals','pre','all')} / {_get(r,'decision_totals','post','all')}"),
        ("eligible for the model, pre / post", lambda r: f"{_get(r,'eligible_consulted','pre','eligible')} / {_get(r,'eligible_consulted','post','eligible')}"),
        ("consultations, pre / post", lambda r: f"{_get(r,'eligible_consulted','pre','consulted')} / {_get(r,'eligible_consulted','post','consulted')}"),
        ("model answers accepted, pre / post", lambda r: f"{_get(r,'decision_totals','pre','model_accepted')} / {_get(r,'decision_totals','post','model_accepted')}"),
        ("gate refusals (rule + model), all", lambda r: _fmt(sum((_get(r,'decision_totals',p,'gate_refused_rule') or 0) + (_get(r,'decision_totals',p,'gate_refused_model') or 0) for p in PHASES))),
        ("messages sent, pre / post", lambda r: f"{_get(r,'messages','pre','sent')} / {_get(r,'messages','post','sent')}"),
        ("messages dropped, post", lambda r: _fmt(_get(r,'messages','post','dropped'))),
        ("robot commands applied, pre / post", lambda r: f"{_get(r,'messages','pre','robot_commands','applied_total')} / {_get(r,'messages','post','robot_commands','applied_total')}"),
        ("parcels departed, pre / post", lambda r: f"{_get(r,'operations','departed','pre')} / {_get(r,'operations','departed','post')}"),
        ("last parcel departure", lambda r: _fmt(_get(r,'operations','last_departure_tick'))),
        ("first arrival refused after fault", lambda r: _fmt(_get(r,'operations','first_refusal_after_fault'))),
        ("backlog at end", lambda r: _fmt(_get(r,'operations','backlog_end'))),
        ("collapse outcome / tick", lambda r: (f"{_get(r,'collapse','outcome')} / {_get(r,'collapse','collapse_tick')}" if _get(r,'collapse') else "n/a")),
        ("critical stop tick", lambda r: _fmt(_get(r,'collapse','critical_stop_tick'))),
        ("DK-RMM monitor / final", lambda r: (f"{_get(r,'dkrmm','monitor')} / {_get(r,'dkrmm','final')}" if _get(r,'dkrmm','available') else "n/a")),
        ("DK-RMM first UNSTABLE / RCT after fault", lambda r: (f"{_get(r,'dkrmm','first_after_fault','UNSTABLE')} / {_get(r,'dkrmm','first_after_fault','RCT')}" if _get(r,'dkrmm','available') else "n/a")),
    ]
    for seed in result["seeds"]:
        lines += [f"## Seed {seed}", "", "| Measurement | Rules-only | Model-enabled | Matched no-drop control (model) |",
                  "|---|---:|---:|---:|"]
        rr, mm, cc = (runs.get(k, {}).get(str(seed)) for k in ("rules", "model", "control"))
        for label, fn in rows:
            cells = []
            for run in (rr, mm, cc):
                cells.append("not run" if run is None else fn(run))
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ main
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--rules", type=Path, default=None)
    parser.add_argument("--control", type=Path, default=None)
    parser.add_argument("--model-summary", type=Path, default=None)
    parser.add_argument("--rules-summary", type=Path, default=None)
    parser.add_argument("--fault-tick", type=int, default=FAULT_TICK)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    out = args.out.resolve()
    if "results" in out.parts and "normal" in out.parts[out.parts.index("results"):]:
        parser.error("refusing to write inside results/normal")
    targets = [out / "analysis.json", out / "analysis.md"]
    existing = [str(t) for t in targets if t.exists()]
    if existing:
        parser.error("refusing to overwrite: " + ", ".join(existing))
    result = analyze(args.model, args.rules, args.control, args.model_summary,
                     args.rules_summary, args.fault_tick)
    if not result["seeds"]:
        parser.error("no s<seed>/events.jsonl found under the given directories")
    out.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    targets[1].write_text(markdown(result), encoding="utf-8")
    print(f"wrote {targets[0]} and {targets[1]} ({len(result['seeds'])} seeds)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
