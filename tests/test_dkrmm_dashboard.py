"""
The DK-RMM pane and its API after the operational indicators (design of
2026-10-12, section 7): each indicator row carries its kind, direction,
baseline, whether it could be read, which way it deviated and a status word;
the digest says what was observed and carries the operations block; the pane
draws the observed line, the operations block, the tags and the status cells;
and `/dkrmm/indicators` serves the same rows.

The monitor under test is built on a minimal fake ecosystem (the three
things DKRMM reads: logger, roster, clock), so the rows are about the digest
and the page, not about a run.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from post_office.api.digest import indicator_rows, monitor_digest
from post_office.dkrmm.indicators import (BASE_INDICATORS, DERIVED_INDICATORS,
                                          INDICATOR_META, INDICATOR_NAMES)
from post_office.dkrmm.monitor import DKRMM

ROW_KEYS = {"name", "about", "kind", "direction", "value", "baseline", "z",
            "evaluable", "deviation", "in_evidence", "detail", "tick", "status"}
STATUSES = {"ok", "deviating up", "deviating down", "n/a"}


def ev(tick, topic, actor="", target="", **detail):
    return SimpleNamespace(tick=tick, topic=topic, actor=actor, target=target,
                           detail=detail)


class FakeEco:
    """The three things DKRMM reads from an ecosystem: logger, roster, clock."""

    def __init__(self, roster=4):
        self.agents = {f"A{i}": None for i in range(roster)}
        self.world = SimpleNamespace(tick=0)
        self.listeners = []
        self.logger = SimpleNamespace(subscribe=self._subscribe)

    def _subscribe(self, fn):
        self.listeners.append(fn)
        return lambda: self.listeners.remove(fn)


def _window(start: int):
    """A few ticks of messages, a delegation and a started task, from `start`."""
    rows = []
    for t in range(start, start + 8):
        rows.append(ev(t, "message", "A0", "A1"))
        rows.append(ev(t, "message", "A1", "A2"))
        rows.append(ev(t, "message", "A2", "A0"))
        rows.append(ev(t, "message", "A0", "SUB-X"))
        rows.append(ev(t, "subagent_message", "SUB-X", "A0"))
    rows.append(ev(start, "task_created", "A1", task_id=f"T{start}"))
    rows.append(ev(start + 5, "task_started", "A1", task_id=f"T{start}"))
    rows.append(ev(start + 2, "message_dropped", "A2", "A0"))
    return rows


@pytest.fixture(scope="module")
def monitor():
    """A monitor that has made a few assessments over fake windows."""
    eco = FakeEco()
    made = DKRMM(eco, every=10, window=10, baseline=8).attach()
    for n in range(1, 8):
        for event in _window(n * 10 - 9):
            made.observe(event)
        made.assess(n * 10)
    return made


# ------------------------------------------------------------ the rows
def test_the_rows_are_the_registry_in_order_with_the_new_keys(monitor):
    rows = indicator_rows(monitor)
    assert [row["name"] for row in rows] == list(INDICATOR_NAMES)
    assert len(rows) == 20
    for row in rows:
        assert ROW_KEYS <= set(row), row["name"]
        assert row["kind"] == INDICATOR_META[row["name"]]["kind"]
        assert row["direction"] == INDICATOR_META[row["name"]]["direction"]
        assert row["kind"] == ("base" if row["name"] in BASE_INDICATORS else "derived")
        assert row["name"] in BASE_INDICATORS or row["name"] in DERIVED_INDICATORS
        assert row["about"] and row["status"] in STATUSES
        assert row["deviation"] in ("up", "down", "none")
        assert row["tick"] == monitor.current.tick
        assert isinstance(row["detail"], dict)
        assert row["baseline"] is None or isinstance(row["baseline"], float)
    json.dumps(rows)                              # JSON-safe, the API serves them


def test_a_row_that_could_not_be_read_is_none_and_na(monitor):
    rows = {row["name"]: row for row in indicator_rows(monitor)}
    # The fake ecosystem has no building to read: resources are unreadable.
    unread = [row for row in rows.values() if not row["evaluable"]]
    assert unread, "the fake ecosystem gives nothing the state readers can read"
    assert not rows["resource_saturation"]["evaluable"]
    for row in unread:
        assert row["value"] is None
        assert row["z"] == 0.0
        assert row["status"] == "n/a"
        assert row["deviation"] == "none" and row["in_evidence"] is None
    read = [row for row in rows.values() if row["evaluable"]]
    assert read
    for row in read:
        assert isinstance(row["value"], float)
        assert row["status"] != "n/a"


def test_the_detail_is_the_part_of_the_reading_that_belongs_to_the_row(monitor):
    rows = {row["name"]: row for row in indicator_rows(monitor)}
    delivery = rows["communication_failure_rate"]["detail"]
    assert {"attempted", "delivered", "dropped", "late"} <= set(delivery)
    assert delivery["attempted"] > 0 and delivery["dropped"] >= 1
    assert "late_by" not in delivery
    assert {"completed_per_tick", "incoming_per_tick"} <= set(rows["task_completion_rate"]["detail"])
    assert rows["completion_gap"]["detail"] == rows["task_completion_rate"]["detail"]
    assert "backlog_now" in rows["backlog_growth"]["detail"]
    assert "edges_now" in rows["dependency_graph_divergence"]["detail"]
    assert set(rows["tail_deviation"]["detail"]) >= {"task_wait", "message_delay", "zone_backlog"}
    assert "gate_rejections" in rows["guardrail_events"]["detail"]
    assert "p95" in rows["execution_latency"]["detail"]
    assert rows["message_frequency"]["detail"] == {}


def test_the_rows_say_nothing_without_a_monitor_and_nothing_when_it_throws():
    class Broken:
        def state(self):
            raise RuntimeError("no")

    assert indicator_rows(None) == []
    assert indicator_rows(Broken()) == []


def test_before_the_first_reading_every_row_is_not_evaluable():
    rows = indicator_rows(DKRMM(FakeEco()))
    assert [row["name"] for row in rows] == list(INDICATOR_NAMES)
    assert all(row["value"] is None and row["status"] == "n/a" and row["tick"] is None
               for row in rows)


# ---------------------------------------------------------- the digest
def test_the_digest_says_what_was_observed_and_carries_the_operations(monitor):
    digest = monitor_digest(monitor)
    assert digest["attached"] is True
    assert {"observed", "not_evaluated", "operations"} <= set(digest)
    assert isinstance(digest["not_evaluated"], list)
    assert digest["not_evaluated"] == list(monitor.current.not_evaluated)
    assert isinstance(digest["observed"], str) and digest["observed"]
    assert "observed" in digest["observed"] or "no evidence kinds" in digest["observed"]
    ops = digest["operations"]
    assert set(ops) == {"delivery", "backlog", "throughput", "resources"}
    assert set(ops["delivery"]) == {"attempted", "delivered", "dropped", "late", "held_now", "rate"}
    assert set(ops["backlog"]) == {"now", "per_tick", "zones", "unfinished_tasks", "increasing_for"}
    assert set(ops["throughput"]) == {"completed_per_tick", "incoming_per_tick", "gap"}
    # Read off the fake's windows: messages attempted, one dropped per window.
    assert ops["delivery"]["attempted"] > 0 and ops["delivery"]["dropped"] == 1
    assert ops["delivery"]["rate"] is not None
    # Nothing of the building could be read, and the digest says None, not 0.
    assert ops["backlog"]["now"] is None and ops["backlog"]["per_tick"] is None
    assert ops["resources"] is None or all(v is None for v in ops["resources"].values())
    json.dumps(digest)


def test_the_observed_line_names_the_kinds_present_and_the_kinds_not_read():
    from post_office.api.digest import _observed

    assert _observed([], []) == "no evidence kinds"
    assert _observed(["delivery", "structure"], []) == "delivery, structure observed"
    line = _observed(["delivery"], ["refusal", "retry", "congestion", "chatter",
                                    "herding", "spread", "structure", "synchrony"])
    assert line == "delivery observed; behavioural kinds not evaluated"
    assert _observed([], ["retry"]) == "no evidence kinds; retry not evaluated"


def test_the_digest_never_throws():
    class Broken:
        def state(self):
            raise RuntimeError("no")

    class Odd:
        def state(self):
            return {"current": {"tick": 5, "state": "STABLE", "indicators": "not a dict",
                                "kinds": None}, "every": 20}

    assert monitor_digest(None) == {"attached": False}
    assert monitor_digest(Broken())["attached"] is False
    odd = monitor_digest(Odd())
    assert odd["attached"] is True and odd["observed"]
    assert set(odd["operations"]) == {"delivery", "backlog", "throughput", "resources"}


# ------------------------------------------------------------- the pane
def test_the_pane_draws_the_observed_line_the_operations_and_the_rows(monitor):
    from post_office.ui.live import dkrmm_html

    html = dkrmm_html(SimpleNamespace(monitor=monitor, preset="normal"))
    assert 'id="dk-pane-observed"' in html and 'class="dk-observed"' in html
    assert f'id="dk-pane-observed">{monitor_digest(monitor)["observed"]}<' in html
    assert '<dl class="dk-ops" id="dk-pane-ops">' in html
    for label in ("delivery", "backlog", "throughput", "resources"):
        assert f"<dt>{label}</dt>" in html
    assert "failure rate" in html and "unfinished tasks" in html and "n/a" in html
    assert "The indicators <em>base and derived; this window, its baseline, and its distance from it</em>" in html
    assert "The twelve indicators" not in html
    assert html.count('<tr class="indicator') == 20
    assert '<span class="tag">base</span>' in html and '<span class="tag">derived</span>' in html
    assert html.count('<span class="tag">base</span>') == len(BASE_INDICATORS)
    assert html.count('<span class="tag">derived</span>') == len(DERIVED_INDICATORS)
    assert '<td class="status st-na">n/a</td>' in html
    assert '<td class="status st-ok">ok</td>' in html
    assert '<tr class="indicator na">' in html
    assert "↑" in html and "↕" in html and "↓" in html
    assert 'id="dk-pane-stale" hidden' in html
    # The name cell's hover is the detail, "key: value" per line.
    assert 'title="attempted: ' in html
    # No em-dash anywhere in the pane.
    assert chr(0x2014) not in html


def test_the_pane_and_the_page_use_the_same_forbidden_free_words(monitor):
    from post_office.ui.live import dkrmm_html

    html = dkrmm_html(SimpleNamespace(monitor=monitor, preset="normal")).lower()
    for word in ("attack", "perturb", "stress", "inject", "experiment", "autodk", "openrt"):
        assert word not in html, word


# -------------------------------------------------------------- the API
@pytest.fixture(scope="module")
def client():
    """A rules-only runner stepped past the first reading, served by the app."""
    from fastapi.testclient import TestClient

    from post_office.api import server
    from post_office.api.runner import SimulationRunner
    from post_office.crew.console import quiet

    with quiet():
        runner = SimulationRunner(seed=3, run_id="dash", tick_seconds=0,
                                  rules_only=True)
        previous = server.use(runner)
        try:
            runner.eco.start()
            runner.step(45)
            with TestClient(server.app) as made:
                yield made
        finally:
            server.use(previous)
            runner.close()


def test_the_endpoint_serves_the_rows_with_the_new_keys(client):
    body = client.get("/dkrmm/indicators").json()
    assert body["attached"] is True
    assert {"observed", "not_evaluated", "operations"} <= set(body)
    rows = body["indicators"]
    assert [row["name"] for row in rows] == list(INDICATOR_NAMES)
    for row in rows:
        assert ROW_KEYS <= set(row), row["name"]
        assert row["status"] in STATUSES
        assert row["tick"] == body["tick"]
        if row["evaluable"]:
            assert isinstance(row["value"], (int, float))
        else:
            assert row["value"] is None and row["status"] == "n/a"
    # A real building is readable: the resources were read.
    by_name = {row["name"]: row for row in rows}
    assert by_name["resource_saturation"]["evaluable"]
    assert set(body["operations"]["resources"]) >= {"robots", "dock", "storage"}
