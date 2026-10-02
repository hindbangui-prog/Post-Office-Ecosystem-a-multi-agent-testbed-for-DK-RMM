"""What drove a DK-RMM reading: the events of its window, the consultations near it,
and how the window compares with the windows it was measured against."""
from types import SimpleNamespace

import pytest

from post_office.observability.rct_explain import explain
from tests.consult_helpers import ask, ecosystem_on, equally_placed, events as logged
from tests.fake_ollama import deciding_script


def ev(tick, topic, actor="", target="", corr="", **detail):
    return SimpleNamespace(tick=tick, topic=topic, actor=actor, target=target,
                           correlation_id=corr, detail=detail)


def discussion(did, opened, closed, options, choice, outcome="decided",
               owner="SCHEDULING", peer="ROUTING", decision="choose_robot"):
    """One consultation as `crew/events.py` writes it: opened, its request, closed."""
    return [
        ev(opened, "consult_opened", owner, peer, did, consultation_id=did,
           peer=peer, decision=decision, options=[str(o) for o in options]),
        ev(opened, "message", owner, peer, did, message_type="CONSULT_REQUEST",
           content={"consultation_id": did, "decision": decision, "text": "Which one?"}),
        ev(closed, "consult_closed", owner, peer, did, consultation_id=did,
           decision=decision, outcome=outcome, choice=choice),
    ]


def base_run():
    events = [ev(1, "task_created", "SCHEDULING", corr="P-1", task_id="T-1", parcel_id="P-1")]
    # A quiet stretch: one blocked robot every 20 ticks up to tick 480.
    for t in range(10, 480, 20):
        events.append(ev(t, "blocked", "R9", corr=""))
    return events


def test_the_window_is_split_by_the_evidence_kind_each_event_feeds():
    events = base_run() + [
        ev(500, "blocked", "R2"), ev(505, "blocked", "R2"), ev(506, "blocked", "R4"),
        ev(510, "task_released", "SCHEDULING", corr="P-1", task_id="T-1"),
        ev(512, "command_yield", "ROUTING", "R2"),
    ]
    out = explain(events, tick=520)
    assert out["window"] == [461, 520]
    kinds = {k["kind"]: k for k in out["kinds"]}
    assert kinds["spread"]["count"] >= 3            # blocked robots
    blocked = next(t for t in kinds["spread"]["topics"] if t["topic"] == "blocked")
    assert blocked["agents"][0] == ["R2", 2]
    assert kinds["retry"]["count"] == 1              # task_released
    assert kinds["congestion"]["count"] == 2         # task_released + command_yield


def test_a_discussion_on_the_same_task_is_a_strong_link_and_a_shared_robot_a_weak_one():
    events = base_run() + discussion("DSC-1", 490, 500, ["T-1", "T-2"], "T-1",
                                     decision="choose_next_task", peer="DISPATCH")
    events += discussion("DSC-2", 492, 498, ["R2", "R3"], "R2")
    events += [
        ev(505, "task_released", "SCHEDULING", corr="P-1", task_id="T-1"),
        ev(506, "blocked", "R2"),
        ev(507, "blocked", "R5"),
    ]
    out = explain(events, tick=520)
    by_id = {d["id"]: d for d in out["discussions"]}
    assert by_id["DSC-1"]["strong"] >= 1 and by_id["DSC-1"]["weak"] == 0
    assert by_id["DSC-2"]["weak"] >= 1 and by_id["DSC-2"]["strong"] == 0
    assert out["linked"]["none"] >= 1                 # R5 touches no discussion
    assert out["discussion_messages"] == 2            # the two CONSULT_REQUEST messages
    assert "strongly linked to a consultation" in out["summary"]



def test_an_open_consultation_keeps_the_options_it_was_opened_with():
    # Opened with two tasks, asked by a CONSULT_REQUEST that names no options,
    # and not closed: its options are its only link.
    events = base_run() + discussion("DSC-4", 495, 0, ["T-1", "T-2"], None)[:2]
    events += [ev(505, "task_released", "SCHEDULING", corr="P-1", task_id="T-1")]
    out = explain(events, tick=520)
    row = {d["id"]: d for d in out["discussions"]}["DSC-4"]
    assert row["outcome"] == "open" and row["closed"] is None
    assert row["strong"] >= 1


def test_a_consultation_with_no_peer_names_its_owner_alone():
    events = base_run() + discussion("DSC-5", 495, 500, ["T-1"], "T-1", owner="INTAKE",
                                     peer="", decision="accept_parcel")
    events += [ev(505, "task_released", "SCHEDULING", corr="P-1", task_id="T-1")]
    out = explain(events, tick=520)
    assert "(most: DSC-5 INTAKE, decided)" in out["summary"]
    assert "\u2194" not in out["summary"]

def test_an_event_before_the_discussion_opened_is_not_linked_to_it():
    events = base_run() + [ev(470, "blocked", "R2")]
    events += discussion("DSC-3", 500, 510, ["R2"], "R2")
    out = explain(events, tick=520)
    assert {d["id"]: d for d in out["discussions"]}["DSC-3"]["weak"] == 0


def test_the_baseline_says_when_the_window_follows_a_quiet_stretch():
    events = base_run() + [ev(t, "blocked", "R2") for t in range(490, 520)]
    out = explain(events, tick=520)
    base = out["baseline"]
    assert base["windows"] > 0 and base["this"] > base["mean"] * 3
    assert "quiet" in out["summary"]


def test_nothing_recorded_is_said_plainly():
    out = explain([], tick=100)
    assert out["trouble"] == 0 and out["discussions"] == []
    assert out["summary"]


def test_each_reading_gets_the_clock_time_its_tick_was_reached():
    from post_office.observability.rct_explain import wall_clock_at

    events = [SimpleNamespace(tick=t, wall_clock=f"2026-09-26T10:00:{t:02d}+00:00")
              for t in (1, 2, 5)]
    got = wall_clock_at(events, [2, 4, 0])
    assert got[2].endswith(":02+00:00") and got[4].endswith(":02+00:00") and got[0] == ""


def test_a_log_rewritten_by_a_new_run_is_read_afresh(tmp_path):
    import json

    from post_office.observability.rct_explain import events_from_log

    log = tmp_path / "run.jsonl"
    log.write_text("\n".join(json.dumps({"tick": t, "topic": "x", "run_id": "a"})
                             for t in range(5)) + "\n")
    assert len(events_from_log(str(log), run_id="a")) == 5
    log.write_text("\n".join(json.dumps({"tick": t, "topic": "y", "run_id": "b"})
                             for t in range(8)) + "\n")
    fresh = events_from_log(str(log), run_id="b")
    assert len(fresh) == 8 and {e.topic for e in fresh} == {"y"}


@pytest.mark.usefixtures("quiet_crewai_console")
def test_a_consultation_of_a_fake_model_run_is_explained_with_its_links(fake_ollama):
    fake_ollama.script(deciding_script("Take the first: its way is clear."))
    eco = ecosystem_on(fake_ollama)
    try:
        for _ in range(60):
            eco.step()
        if not logged(eco, "consult_opened"):
            # None arose on its own: one SCHEDULING consultation with ROUTING,
            # as the live UI tests force it.
            sched = eco.agents["SCHEDULING"]
            sched.triggers.register("choose_robot", equally_placed)
            ask(sched)
        everything = logged(eco)
    finally:
        eco.close()
    opened = [e for e in everything if e.topic == "consult_opened"][-1]
    cid = opened.detail["consultation_id"]
    closed = next(e for e in everything
                  if e.topic == "consult_closed" and e.detail["consultation_id"] == cid)
    out = explain(everything, tick=closed.tick)
    row = next(d for d in out["discussions"] if d["id"] == cid)
    assert row["owner"] == opened.actor and row["peer"] == opened.detail["peer"]
    assert row["decision"] == opened.detail["decision"]
    assert row["outcome"] == closed.detail["outcome"] and row["outcome"] != "open"
    assert row["opened"] == opened.tick and row["closed"] == closed.tick
    assert isinstance(row["strong"], int) and isinstance(row["weak"], int)
    lo, hi = out["window"]
    consult_rows = [e for e in everything if lo <= e.tick <= hi
                    and e.topic in ("message", "subagent_message")
                    and str(e.detail.get("message_type", "")).startswith("CONSULT_")]
    assert consult_rows and out["discussion_messages"] == len(consult_rows)
