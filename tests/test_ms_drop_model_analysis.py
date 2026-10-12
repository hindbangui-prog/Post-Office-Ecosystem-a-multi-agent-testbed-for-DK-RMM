"""
`tools/analyze_ms_drop_model.py` on a hand-built run whose every count is known.

The run: fault at tick 10. Before it, a rule decision, a triggered decision the
model answered (with a same-tick peer exchange, a delivered robot command the
robot applied, one owner call beyond the expected two), a model answer the
gate refused, a failed model call. After it, a model decision whose messages
are all dropped and that no robot ever applies, plus one message still pending
on the last tick.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tools import analyze_ms_drop_model as tool


def _ev(tick, topic, actor="", target="", corr="", **detail):
    return {"tick": tick, "topic": topic, "actor": actor, "target": target,
            "correlation_id": corr, "detail": detail}


def _msg(tick, mid, sender, receiver, mtype, corr="", operation=None, sub=False):
    content = {"operation": operation} if operation else {}
    return _ev(tick, "subagent_message" if sub else "message", sender, receiver, corr,
               message_id=mid, message_type=mtype, content=content)


def _run(tmp: Path, name: str = "s7") -> Path:
    run = tmp / name
    run.mkdir(parents=True)
    events = [
        # tick 2: rule decision
        _ev(2, "decision", "INTAKE", corr="P-1", decision="accept_parcel",
            status="deterministic", validation="ok", trigger=""),
        # tick 3: triggered, consulted, model answer accepted, peer exchange in-tick
        _ev(3, "consult_opened", "SCHEDULING", "ROUTING", "CSL-1",
            consultation_id="CSL-1", peer="ROUTING"),
        _ev(3, "consult_question", "SCHEDULING", "ROUTING", "CSL-1", consultation_id="CSL-1"),
        _ev(3, "llm_call", "ROUTING", corr="CSL-1", consultation_id="CSL-1", status=200,
            error="", phase="peer", served_model="m", latency_ms=100.0),
        _ev(3, "consult_response", "ROUTING", "SCHEDULING", "CSL-1", consultation_id="CSL-1"),
        _ev(3, "llm_call", "SCHEDULING", corr="CSL-1", consultation_id="CSL-1", status=200,
            error="", phase="owner", served_model="m", latency_ms=300.0),
        _ev(3, "llm_call", "SCHEDULING", corr="CSL-1", consultation_id="CSL-1", status=200,
            error="", phase="owner", served_model="m", latency_ms=200.0),
        _ev(3, "llm_call", "SCHEDULING", corr="CSL-1", consultation_id="CSL-1", status=200,
            error="", phase="owner", served_model="m", latency_ms=200.0),
        _ev(3, "consult_closed", "SCHEDULING", "ROUTING", "CSL-1", consultation_id="CSL-1",
            outcome="decided"),
        _ev(3, "decision", "SCHEDULING", corr="T-1", decision="choose_robot", choice="R1",
            status="llm_accepted", validation="ok", trigger="contention"),
        _ev(3, "task_assigned", "SCHEDULING", corr="P-2", task_id="T-1", robot_id="R1"),
        _msg(3, "M-1", "SCHEDULING", "R1", "ROBOT_COMMAND", "T-1", "transport"),
        _ev(4, "command_transport", "SCHEDULING", "R1", "T-1"),
        # tick 5: triggered, model answer refused by the gate (state)
        _ev(5, "consult_opened", "ROUTING", corr="CSL-2", consultation_id="CSL-2"),
        _ev(5, "llm_call", "ROUTING", corr="CSL-2", consultation_id="CSL-2", status=500,
            error="boom", phase="owner", served_model="m", latency_ms=50.0),
        _ev(5, "consult_closed", "ROUTING", corr="CSL-2", consultation_id="CSL-2",
            outcome="model_failed"),
        _ev(5, "decision", "ROUTING", corr="T-2", decision="resolve_block",
            status="llm_rejected", validation="state", trigger="failed"),
        _ev(6, "parcel_arrived", "INTAKE"),
        _ev(7, "parcel_departed", "DISPATCH"),
        # tick 9: sent before the fault, dropped at the fault tick
        _msg(9, "M-2", "PLANNER", "INTAKE", "TASK_ASSIGNMENT"),
        _ev(10, "message_dropped", "PLANNER", "INTAKE", message_id="M-2"),
        # tick 12: model decision after the fault, messages dropped, nothing applied
        _ev(12, "consult_opened", "SCHEDULING", corr="CSL-3", consultation_id="CSL-3"),
        _ev(12, "llm_call", "SCHEDULING", corr="CSL-3", consultation_id="CSL-3", status=200,
            error="", phase="owner", served_model="m", latency_ms=400.0),
        _ev(12, "consult_closed", "SCHEDULING", corr="CSL-3", consultation_id="CSL-3",
            outcome="decided"),
        _ev(12, "decision", "SCHEDULING", corr="T-3", decision="choose_robot", choice="R2",
            status="llm_accepted", validation="ok", trigger="conflict"),
        _ev(12, "task_assigned", "SCHEDULING", corr="P-3", task_id="T-3", robot_id="R2"),
        _msg(12, "M-3", "SCHEDULING", "ROUTING", "ROUTE_REQUEST", "P-3", "plan_transport"),
        _msg(12, "M-4", "SCHEDULING", "R2", "ROBOT_COMMAND", "T-3", "transport"),
        _ev(13, "message_dropped", "SCHEDULING", "ROUTING", message_id="M-3"),
        _ev(13, "message_dropped", "SCHEDULING", "R2", message_id="M-4"),
        _ev(14, "arrival_refused", "SIMULATION"),
        _ev(15, "arrival_refused", "SIMULATION"),
        # tick 20, the last tick: a message still pending
        _msg(20, "M-5", "SUB-QUEUE", "SCHEDULING", "SUBTASK_RESULT", sub=True),
    ]
    with (run / "events.jsonl").open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    with (run / "series.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["tick", "backlog"])
        writer.writerow([1, 3])
        writer.writerow([20, 9])
    (run / "done.json").write_text(json.dumps({"mode": "model", "seed": 7, "ticks": 20}))
    (run / "verify.json").write_text(json.dumps(
        {"mode": "model", "settings": {"model": "m"}, "identity": {"digest": "d"},
         "served_models": {"m": 6}}))
    (run / "dkrmm.json").write_text(json.dumps({
        "state": {"counts": {"STABLE": 2, "UNSTABLE": 1, "RCT": 1}, "current": {"state": "RCT"}},
        "record": {"ticks": [1, 9, 11, 13],
                   "state_series": [{"tick": 1, "state": "STABLE"}, {"tick": 9, "state": "STABLE"},
                                    {"tick": 11, "state": "UNSTABLE"}, {"tick": 13, "state": "RCT"}],
                   "indicator_series": {"communication_failure_rate": [0.0, 0.0, 0.5, 1.0]}}}))
    return run


@pytest.fixture()
def run(tmp_path):
    return tool.analyze_run(_run(tmp_path), fault_tick=10)


def test_decisions_are_split_by_who_answered_and_by_phase(run):
    pre, post = run["decision_totals"]["pre"], run["decision_totals"]["post"]
    assert pre["all"] == 3 and pre["rule"] == 1
    assert pre["model_accepted"] == 1 and pre["model_rejected"] == 1
    assert pre["eligible"] == 2
    assert pre["gate_refused_model"] == 1 and pre["gate_refused_rule"] == 0
    assert post["all"] == 1 and post["model_accepted"] == 1 and post["eligible"] == 1


def test_eligible_share_is_consultations_over_triggered_decisions(run):
    assert run["eligible_consulted"]["pre"] == {"eligible": 2, "consulted": 2, "share": 1.0}
    assert run["eligible_consulted"]["post"] == {"eligible": 1, "consulted": 1, "share": 1.0}


def test_model_calls_are_counted_from_llm_call_events_only(run):
    pre = run["llm_calls"]["pre"]
    assert pre["total"] == 5 and pre["ok"] == 4 and pre["failed"] == 1
    assert pre["by_phase"] == {"peer": 1, "owner": 4}
    assert pre["errors"] == {"boom": 1}
    assert run["llm_calls"]["post"]["total"] == 1
    # CSL-1 had a peer exchange: two owner calls expected, three made
    assert run["owner_calls_beyond_expected"] == 1


def test_a_same_tick_peer_exchange_has_gap_zero(run):
    assert run["consultations"]["pre"]["response_tick_gap"] == {0: 1}
    assert run["consultations"]["pre"]["outcomes"] == {"decided": 1, "model_failed": 1}


def test_messages_are_matched_to_drops_by_id_in_the_phase_they_were_sent(run):
    pre, post = run["messages"]["pre"], run["messages"]["post"]
    # M-1 delivered, M-2 sent at 9 and dropped at 10 (counted pre)
    assert (pre["sent"], pre["dropped"], pre["delivered"]) == (2, 1, 1)
    # M-3, M-4 dropped; M-5 sent on the last tick and still pending
    assert (post["sent"], post["dropped"], post["delivered"], post["pending_at_end"]) == (3, 2, 0, 1)


def test_robot_commands_sent_dropped_and_applied_are_separate(run):
    pre = run["messages"]["pre"]["robot_commands"]
    post = run["messages"]["post"]["robot_commands"]
    assert (pre["sent"], pre["delivered"], pre["applied_total"]) == (1, 1, 1)
    assert (post["sent"], post["dropped"], post["applied_total"]) == (1, 1, 0)


def test_a_chain_follows_a_model_decision_to_its_messages_and_their_fate(run):
    pre, post = run["chains"]["pre"], run["chains"]["post"]
    assert pre["model_decisions_accepted"] == 1 and pre["messages"] == 1
    assert pre["messages_delivered"] == 1 and pre["with_robot_command_applied"] == 1
    assert post["model_decisions_accepted"] == 1 and post["messages"] == 2
    assert post["messages_dropped"] == 2 and post["with_robot_command_applied"] == 0
    assert run["task_assigned_in_registry"] == {"pre": 1, "post": 1}


def test_operations_and_dkrmm_are_read_from_the_run(run):
    ops = run["operations"]
    assert ops["arrived"] == {"pre": 1, "post": 0}
    assert ops["departed"] == {"pre": 1, "post": 0} and ops["last_departure_tick"] == 7
    assert ops["first_refusal_after_fault"] == 14 and ops["backlog_end"] == 9
    dk = run["dkrmm"]
    assert dk["monitor"] == "extended (2026-10-12)" and dk["final"] == "RCT"
    assert dk["first_after_fault"] == {"DEVIATING": None, "UNSTABLE": 11, "RCT": 13}
    assert dk["first_failure_rate_full"] == 13


def test_the_cli_refuses_to_overwrite_and_refuses_results_normal(tmp_path):
    root = tmp_path / "model"
    _run(root)
    out = tmp_path / "out"
    assert tool.main(["--model", str(root), "--out", str(out)]) == 0
    assert (out / "analysis.json").exists() and (out / "analysis.md").exists()
    with pytest.raises(SystemExit):
        tool.main(["--model", str(root), "--out", str(out)])
    with pytest.raises(SystemExit):
        tool.main(["--model", str(root), "--out", str(tmp_path / "results" / "normal" / "x")])


def test_missing_groups_are_marked_not_run(tmp_path):
    root = tmp_path / "model"
    _run(root)
    result = tool.analyze(root, None, None, None, None, fault_tick=10)
    text = tool.markdown(result)
    assert "not run" in text and "| collapse outcome / tick | not run | n/a | not run |" in text
