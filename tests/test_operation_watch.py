"""
The operation watch (`observability/operation.py`): the fleet's condition as
facts on DK-RMM's clock, with the monitor's state words applied to those facts,
beside DK-RMM and never part of it.

Checked: the state rule (the paper's equation (3) on facts, PERSISTENT at
fifteen consecutive readings of a kind); Normal reads STABLE throughout on
seeds 1 and 11; the rules-only ON-OFF scenario on seed 11977 reads DEVIATING,
UNSTABLE and then PERSISTENT while the orphaned pair stands, and keeps
reading PERSISTENT when DK-RMM's own state has gone back to STABLE; the watch
changes nothing about the run (the frozen event stream of seed 11977 is
unchanged); the digest reaches /summary. The live page no longer shows the
watch (removed 2026-10-23): no row on the study strip, no chip on the
scenario line, no end-of-run note.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from post_office.api.runner import SimulationRunner
from post_office.crew.console import quiet
from post_office.observability.operation import (BLOCK_TICKS, FLEET_LOST, KINDS, OperationWatch, TRAP_TICKS,
                                                  PERSISTENT_ASSESSMENTS, STATES, classify)

ROOT = Path(__file__).resolve().parents[1]
FROZEN_EVENTS_SHA256_1700 = "d5c2edc19ddb5bd0ff2cb92d2042b73fe803f6dad6d6fe7b03f0a0962b6bc5ac"


def _events_sha(log_path: str, upto: int) -> str:
    rows = []
    for line in open(log_path, encoding="utf-8"):
        event = json.loads(line)
        if not 1 <= int(event.get("tick", 0)) <= upto:
            continue
        for key in ("wall_clock", "run_id", "seq"):
            event.pop(key, None)
        rows.append(json.dumps(event, sort_keys=True, separators=(",", ":")))
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


# ---------------------------------------------------------------- the rule
def test_the_state_rule_is_the_papers_equation_three_on_facts():
    assert KINDS == ("blocked", "orphaned", "deadlock", "fleet", "overdue", "unintentional") and STATES == ("STABLE", "DEVIATING", "UNSTABLE", "PERSISTENT")
    assert BLOCK_TICKS == 20 and FLEET_LOST == 2 and PERSISTENT_ASSESSMENTS == 15
    assert classify(set(), set(), 0, {}) == "STABLE"
    assert classify(set(), {"orphaned"}, 5, {}) == "STABLE"                       # no fact, no state
    assert classify({"orphaned"}, set(), 0, {"orphaned": 1}) == "DEVIATING"       # one kind, first time
    assert classify({"orphaned"}, {"orphaned"}, 1, {"orphaned": 2}) == "DEVIATING"  # one kind persisting is not two
    assert classify({"orphaned", "deadlock"}, {"orphaned", "deadlock"}, 1, {"orphaned": 2, "deadlock": 2}) == "UNSTABLE"
    assert classify({"blocked"}, set(), 3, {"blocked": 1}) == "UNSTABLE"          # one kind, three preceding non-STABLE
    assert classify({"blocked"}, set(), 2, {"blocked": 1}) == "DEVIATING"
    assert classify({"orphaned"}, {"orphaned"}, 14, {"orphaned": 15}) == "PERSISTENT"
    assert classify({"orphaned", "fleet"}, {"orphaned"}, 14, {"orphaned": 15, "fleet": 1}) == "PERSISTENT"


def _run(seed: int, preset: str, ticks: int, log: str = None):
    runner = SimulationRunner(seed=seed, preset=preset, rules_only=True, verify_model=False,
                              tick_seconds=0.0, run_id="opw", log_path=log)
    try:
        assert isinstance(runner.operation, OperationWatch)
        runner.eco.start()
        for _ in range(ticks):
            assert runner._tick()
        if log:
            runner._logger.flush()
        return runner.operation_status(), runner.last_frame
    finally:
        runner.close()


# --------------------------------------------------------------- Normal
@pytest.mark.parametrize("seed", [1, 11])
def test_normal_reads_stable_throughout(seed):
    with quiet():
        status, frame = _run(seed, "default", 1200)
    assert status["attached"] is True and status["every"] == 20
    assert status["assessments"] == 60 and status["counts"] == {"STABLE": 60, "DEVIATING": 0, "UNSTABLE": 0, "PERSISTENT": 0}
    assert status["state"] == "STABLE" and status["spell_since"] is None and status["persistent_since"] is None
    assert all(state == "STABLE" for _, state in status["sequence"])
    cur = status["current"]
    assert cur["kinds"] == [] and cur["fleet_available"] == cur["fleet_total"] == 5 and cur["rho_fleet"] == 0.0
    assert cur["overdue"] == 0 and cur["overdue_by_zone"] == {} and 0 <= cur["intake"] <= 15   # Normal's peak is 15
    assert not any(r["trapped"] or r["unintentional"] for r in cur["robots"])
    assert cur["dkrmm_state"] in ("STABLE", "DEVIATING", "UNSTABLE", "RECOVERY", "RCT")   # quoted, not judged
    assert frame["operation"]["state"] == "STABLE"


# ---------------------------------------------------- the trapped seed
@pytest.fixture(scope="module")
def trapped_run(tmp_path_factory):
    log = str(tmp_path_factory.mktemp("opw") / "events.jsonl")
    with quiet():
        status, frame = _run(11977, "p7-onoff", 4400, log)      # the scenario's horizon
    return status, frame, log


@pytest.mark.slow
def test_the_trapped_seed_reads_persistent_while_dkrmm_reads_stable(trapped_run):
    status, frame, log = trapped_run
    # The watch changes nothing: the first 1,700 ticks are the frozen run's.
    assert _events_sha(log, 1700) == FROZEN_EVENTS_SHA256_1700
    first = status["first_tick"]
    assert first["DEVIATING"] == 1221 and first["UNSTABLE"] == 1261 and first["PERSISTENT"] == 1521
    seq = dict(status["sequence"])
    assert all(seq[t] == "STABLE" for t in range(1, 1201, 20))                    # before the window
    assert all(seq[t] == "PERSISTENT" for t in range(1521, 4400, 20))             # and it never lets go
    assert status["state"] == "PERSISTENT" and status["persistent_since"] == 1521 and status["spell_since"] == 1221
    cur = status["current"]
    assert cur["tick"] == 4381 and set(cur["kinds"]) >= {"orphaned", "deadlock", "fleet"}
    r1 = next(r for r in cur["robots"] if r["robot"] == "R1"); r2 = next(r for r in cur["robots"] if r["robot"] == "R2")
    assert r1["errand"] is None and r2["errand"] is None and r1["blocked_by"] == "R2" and r2["blocked_by"] == "R1"
    assert r1["since"] == 1211 and r1["blocked_for"] == 4381 - 1211 + 1 and ["R1", "R2"] in cur["pairs"]
    assert cur["fleet_available"] <= 3 and cur["rho_fleet"] >= 0.4
    # DK-RMM, quoted beside: STABLE or DEVIATING for most readings after 2601 (its baseline has absorbed
    # the trap), the gap the row exists to show.
    assert cur["dkrmm_state"] in ("STABLE", "DEVIATING")
    assert cur["dkrmm_rho"] is not None and 0.0 <= cur["dkrmm_rho"] <= 1.0
    assert frame["operation"]["state"] == "PERSISTENT"


@pytest.mark.slow
def test_the_trapped_seed_misses_its_promises_and_the_robots_are_called_trapped(trapped_run):
    """The work's fact beside the fleet's: `overdue` is a parcel past the departure the gate promised
    it and not yet bagged (Normal never has one); the robots' streaks are flagged trapped at 300."""
    status, frame, log = trapped_run
    cur = status["current"]
    assert "overdue" in cur["kinds"] and cur["overdue"] >= 20 and cur["overdue_urgent"] >= 1
    assert cur["overdue_by_zone"].get("intake", 0) >= 15 and cur["intake"] >= 20 and cur["overdue_oldest"] > 0
    r1 = next(r for r in cur["robots"] if r["robot"] == "R1")
    assert r1["trapped"] is True and r1["blocked_for"] >= TRAP_TICKS
    # The state timeline is the robots' and does not move: the promise is first missed within one
    # reading of PERSISTENT and the kind is intermittent until the intake fills from ~1900 on.
    assert status["first_tick"] == {"STABLE": 1, "DEVIATING": 1221, "UNSTABLE": 1261, "PERSISTENT": 1521}
    assert status["trap_ticks"] == TRAP_TICKS == 300 == status["persistent_assessments"] * status["every"]
    assert frame["operation"]["current"]["overdue"] == cur["overdue"]


@pytest.mark.slow
def test_a_robot_queued_behind_the_pair_is_in_unintentional_blockage(trapped_run):
    """At the horizon R5 stands in front of R2 with a route through the pair, its status churning
    (BLOCKED, WAITING, IDLE, MOVING) so that no streak of its own reaches 20 ticks; the kind names it,
    by whom, and counts it as having no errand, so the fleet is short of it."""
    status, frame, log = trapped_run
    cur = status["current"]
    assert "unintentional" in cur["kinds"]
    r5 = next(r for r in cur["robots"] if r["robot"] == "R5")
    assert r5["unintentional"] is True and r5["behind"] == "R2" and r5["in_block"] is False
    assert r5["blocked_for"] < BLOCK_TICKS and r5["behind_since"] is not None and r5["behind_since"] < 4381
    assert r5["errand"] is not None                                               # nominally held, not in progress
    lost = sum(1 for r in cur["robots"] if r["in_block"] or r["unintentional"])
    assert lost == 3 and cur["fleet_available"] == 2 and cur["rho_fleet"] == 0.6   # R1, R2 and R5
    assert not any(r["unintentional"] and r["in_block"] for r in cur["robots"])    # one or the other, never both


# ---------------------------------------------------------------- the API
def test_summary_carries_the_operation_digest():
    from fastapi.testclient import TestClient

    from post_office.api import server

    with quiet():
        runner = SimulationRunner(seed=1, rules_only=True, verify_model=False, tick_seconds=0.0, run_id="opapi")
        prev = server.use(runner)
        try:
            runner.eco.start()
            for _ in range(41):
                runner._tick()
            body = TestClient(server.app).get("/summary").json()
        finally:
            server.use(prev)
            runner.close()
    op = body["operation"]
    assert op["attached"] is True and op["assessments"] == 3 and op["state"] == "STABLE"
    assert op["kinds_known"] == list(KINDS) and op["states"] == list(STATES)
    assert body["dkrmm"] is not None                                              # the monitor's digest is still there, untouched


# --------------------------------------------------------------- the page
def test_the_page_shows_no_operation_watch_and_none_of_the_words():
    page = (ROOT / "post_office" / "ui" / "live.html").read_text(encoding="utf-8")
    for word in ("attack", "perturb", "stress", "inject", "experiment", "autodk", "openrt"):
        assert word not in page.lower(), word
    for marker in ('id="c2n-op-seq"', 'id="c2n-op-state"', 'id="c2n-op-line"', 'id="op-verdict"', 'id="op-state"',
                   "function paintStudyOperation", "function paintOpVerdict", "function operationWords", ".s-PERSISTENT",
                   "OPERATION"):
        assert marker not in page, marker
