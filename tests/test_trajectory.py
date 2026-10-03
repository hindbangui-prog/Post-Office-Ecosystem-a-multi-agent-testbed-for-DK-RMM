"""
The Trajectory page and the RCT log page (trajectory and RCT log design, sections 5 to 7).

The trajectory is a fold over the event logger, nothing else: every row is one
logger event (its `seq` is the row's id), its type is the source sink's
`event_type_for`, its text is `views.describe`, its duration is the event's own
`latency_ms` and its payload carries only the `KEEP` keys. The fold and the
live tail build their rows with the same `trajectory_row`, so a row that
arrives while the page follows the run reads exactly like the same row folded
when the page opened. The logger keeps the newest events in memory; when the
run has logged more, the page says it is showing a window (`truncated`) of
`total`.

The last test opens both pages in headless Chromium (skipped without
Playwright or a browser).
"""

from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from post_office.api import server
from post_office.api.runner import SimulationRunner
from post_office.communication.events import EventLogger
from post_office.config.settings import normal_config
from post_office.crew.console import quiet
from post_office.ui import live, views
from tests.consult_helpers import ask, equally_placed
from tests.fake_ollama import FakeOllama, consultation_script

PEER = "R2: corridor clear, the shorter walk from the sorting belt."


def _held(runner):
    """Every event the runner's logger holds, as dictionaries, oldest first."""
    return runner.events(after=0, limit=10 ** 6)


@pytest.fixture
def rules():
    """A seeded rules-only run, 30 ticks in."""
    runner = SimulationRunner(seed=4, rules_only=True, tick_seconds=0)
    try:
        runner.eco.start()
        runner.step(30)
        yield runner
    finally:
        runner.close()


def _consult(runner) -> None:
    """One SCHEDULING consultation with ROUTING, run as a tick would run it."""
    with runner._lock:
        sched = runner.eco.agents["SCHEDULING"]
        sched.triggers.register("choose_robot", equally_placed)
        ask(sched)
        runner._publish()


@pytest.fixture
def consulted():
    """A run on the fake Ollama with one scripted consultation in its log."""
    fake = FakeOllama()
    fake.script(consultation_script(PEER, decide=lambda _peer: "R2"))
    with quiet():
        runner = SimulationRunner(settings=fake.settings, tick_seconds=0)
        try:
            runner.eco.start()
            runner.step(2)
            _consult(runner)
            yield runner
        finally:
            runner.close()
            fake.stop()


# ------------------------------------------------------------ event types
@pytest.mark.parametrize("category, topic, expected", [
    ("agent", "decision", "agent/decision"),
    ("communication", "message", "agent/message"),
    ("communication", "subagent_message", "agent/message"),
    ("communication", "message_refused", "agent/refused"),
    ("communication", "message_dropped", "communication/message_dropped"),
    ("agent", "consult_opened", "agent/consult_opened"),
    ("agent", "llm_call", "agent/llm_call"),
    ("robot", "moved", "robot/moved"),
    ("battery", "low", "battery/low"),
    ("simulation", "simulation_started", "simulation/simulation_started"),
    ("supervisor", "objective_set", "supervisor/objective_set"),
    ("parcel", "arrived", "parcel/arrived"),
    # A category no rule knows still lands somewhere findable.
    ("monitor", "flag", "agent/monitor.flag"),
])
def test_event_type_for_follows_the_source_sink(category, topic, expected):
    assert views.event_type_for(category, topic) == expected


# ------------------------------------------------------------------- rows
def _logger_with_rows():
    logger = EventLogger(run_id="rows")
    plain = logger.emit("robot", "moved", tick=3, actor="R1", correlation_id="T-1",
                        to=[2, 3], content={"x": 1}, empty="", nothing=None)
    timed = logger.emit("agent", "llm_call", tick=4, actor="ROUTING", correlation_id="CSL-0001",
                        consultation_id="CSL-0001", phase="peer", latency_ms=1234.56789,
                        served_model="qwen3:8b", status="ok", call_id="abc")
    seconds = logger.emit("agent", "decision", tick=5, actor="SORTING", decision="where",
                          choice="STORAGE", reason="shelf free", seconds=2.5)
    request = logger.emit("communication", "message", tick=6, actor="SORTING",
                          target="SUB-BARCODE", correlation_id="P-0001", message_id="M-1",
                          message_type="SUBTASK_REQUEST", content={"parcel_id": "P-0001"},
                          text="", in_reply_to="")
    long_text = logger.emit("agent", "consult_question", tick=7, actor="SCHEDULING",
                            target="ROUTING", correlation_id="CSL-0001",
                            consultation_id="CSL-0001", text="x" * 900,
                            options=[str(n) for n in range(20)])
    return logger, [plain, timed, seconds, request, long_text]


def test_a_row_is_the_source_positional_shape():
    logger, events = _logger_with_rows()
    base = events[0].wall_clock
    for event in events:
        row = views.trajectory_row(event, base)
        assert len(row) == 10
        assert row[0] == event.seq
        assert row[1] == event.tick
        assert isinstance(row[2], float)
        assert row[3] == views.event_type_for(event.category, event.topic)
        assert row[4] == event.actor
        assert row[5] == event.target
        assert row[6] == event.correlation_id
        assert row[8] == views.describe(event, 200)
        assert set(row[9]) <= set(views.KEEP)
        assert all(value not in (None, "", [], {}) for value in row[9].values())
    assert views.trajectory_row(events[0], base)[2] == 0.0
    # The same event as a dictionary reads the same way.
    assert views.trajectory_row(events[1].as_dict(), base) == views.trajectory_row(events[1], base)


def test_a_row_keeps_only_the_keep_keys_trimmed():
    _, (plain, timed, _, request, long_text) = _logger_with_rows()
    base = plain.wall_clock
    assert views.trajectory_row(plain, base)[9] == {
        "interaction_type": plain.interaction_type, "channel": plain.channel}
    load = views.trajectory_row(timed, base)[9]
    assert load["consultation_id"] == "CSL-0001" and load["phase"] == "peer"
    assert load["served_model"] == "qwen3:8b" and load["latency_ms"] == 1234.56789
    assert "call_id" not in load
    # The taxonomy's stamp rides in the payload: the page's lanes read it.
    message = views.trajectory_row(request, base)[9]
    assert message["interaction_type"] == request.interaction_type == "subagent_request"
    assert message["channel"] == request.channel
    assert message["message_id"] == "M-1" and message["message_type"] == "SUBTASK_REQUEST"
    assert "content" not in message and "in_reply_to" not in message   # rendered / empty
    question = views.trajectory_row(long_text, base)[9]
    assert len(question["text"]) == 600 and question["text"].endswith("...")
    assert question["options"] == {"_n": 20}


def test_the_duration_is_the_events_own_latency_and_nothing_else():
    _, (plain, timed, seconds, request, _) = _logger_with_rows()
    base = plain.wall_clock
    assert views.trajectory_row(timed, base)[7] == round(1234.56789, 3)
    for event in (plain, seconds, request):
        assert views.trajectory_row(event, base)[7] is None


# ------------------------------------------------------------- the fold
def test_the_fold_is_every_held_event_once_and_nothing_else(rules):
    held = _held(rules)
    data = views.trajectory_data(rules)
    ids = [row[0] for row in data["events"]]
    assert ids == [event["seq"] for event in held]
    assert len(set(ids)) == len(ids)
    assert data["truncated"] is False
    assert data["total"] == rules.event_counts()["total"] == len(held)
    assert data["run_id"] == rules.eco.run_id and data["archived"] is False
    assert data["started"] == held[0]["wall_clock"]
    assert data["events"][0][2] == 0.0
    assert data["span"] == (data["events"][-1][2] or 1)
    assert data["ticks"] == (max(event["tick"] for event in held) or 1)
    for row, event in zip(data["events"], held):
        assert row[8] == views.describe(event, 200)


def test_the_summary_counts_are_the_logger_events_counted(rules):
    held = _held(rules)
    data = views.trajectory_data(rules)
    summary = data["summary"]
    message_types = [event["detail"].get("message_type") for event in held
                     if event["category"] == "communication"
                     and event["topic"] in ("message", "subagent_message")]
    assert summary["events"] == len(held)
    assert summary["started"] == held[0]["wall_clock"]
    assert summary["last_event"] == held[-1]["wall_clock"]
    assert summary["ticks"] == max(event["tick"] for event in held)
    assert summary["actors"] == len({e["actor"] for e in held if e["actor"]})
    assert summary["correlations"] == len({e["correlation_id"] for e in held
                                           if e["correlation_id"]})
    assert summary["model_requests"] == sum(e["topic"] == "llm_call" for e in held) == 0
    assert summary["tool_calls"] == message_types.count("SUBTASK_REQUEST") > 0
    assert summary["tool_errors"] == 0 and summary["user_actions"] == 0
    assert summary["finished"] is False

    started = [e for e in held if e["topic"] == "simulation_started"]
    assert data["run"] == {"run_id": rules.eco.run_id, "seed": 4, "preset": "normal",
                           "model": "", "started_at": started[0]["wall_clock"],
                           "ticks": rules.last_frame["tick"]}
    log = json.loads(data["log"])
    assert log["run"] == data["run"] and log["summary"] == summary
    assert log["showing"] == f"all {len(held):,} rows"

    rules.stop()
    assert views.trajectory_data(rules)["summary"]["finished"] is True


def test_the_fold_shows_the_newest_rows_when_there_are_more(rules):
    held = _held(rules)
    data = views.trajectory_data(rules, limit=100)
    assert data["truncated"] is True
    assert data["total"] == len(held)
    assert [row[0] for row in data["events"]] == [event["seq"] for event in held[-100:]]
    assert data["started"] == held[-100]["wall_clock"]
    assert json.loads(data["log"])["showing"] == f"the newest 100 of {len(held):,} rows"


def test_a_run_longer_than_the_logger_holds_is_marked_truncated():
    runner = SimulationRunner(seed=4, rules_only=True, tick_seconds=0,
                              config={**normal_config(), "keep_events": 300})
    try:
        runner.eco.start()
        runner.step(10)
        held = _held(runner)
        assert len(held) == 300 < runner.event_counts()["total"]
        data = views.trajectory_data(runner)
        assert data["truncated"] is True
        assert data["total"] == runner.event_counts()["total"]
        assert [row[0] for row in data["events"]] == [event["seq"] for event in held]
    finally:
        runner.close()


def test_truncation_is_read_from_the_rows_not_from_a_later_count(rules, monkeypatch):
    """A tick that logs between the read of the rows and the read of the count
    does not make a complete fold look truncated."""
    held = _held(rules)
    counts = rules.event_counts
    monkeypatch.setattr(rules, "event_counts",
                        lambda: {**counts(), "total": counts()["total"] + 5})
    data = views.trajectory_data(rules)
    assert held[0]["seq"] == 1
    assert data["truncated"] is False
    assert data["total"] == len(held) + 5
    assert json.loads(data["log"])["showing"] == f"all {len(held):,} rows"
    monkeypatch.setattr(rules, "event_counts", lambda: {**counts(), "total": 3})
    assert views.trajectory_data(rules)["total"] == held[-1]["seq"]


# ------------------------------------------------------------- the tail
def test_the_tail_after_a_cut_is_exactly_the_later_events(rules):
    folded = views.trajectory_data(rules)
    cut = folded["events"][10][0]
    tail = views.trajectory_tail(rules, after_id=cut, started=folded["started"], limit=2000)
    assert [row[0] for row in tail["rows"]] == [e["seq"] for e in _held(rules) if e["seq"] > cut]
    assert tail["last_id"] == tail["rows"][-1][0]
    assert tail["total"] == rules.event_counts()["total"]
    by_id = {row[0]: row for row in folded["events"]}
    for row in tail["rows"]:
        assert row == by_id[row[0]], f"row {row[0]} reads two ways"

    last = folded["events"][-1][0]
    rules.step(2)
    fresh = views.trajectory_tail(rules, after_id=last, started=folded["started"])
    assert fresh["rows"] and fresh["rows"][0][0] == last + 1
    assert fresh["rows"][0][2] > 0.0                 # timed from the page's own zero
    assert views.trajectory_tail(rules, after_id=fresh["last_id"])["rows"] == []
    assert views.trajectory_tail(rules, after_id=fresh["last_id"])["last_id"] == fresh["last_id"]
    assert len(views.trajectory_tail(rules, after_id=0, limit=5)["rows"]) == 5


# ------------------------------------------------------- consultations
def test_a_consultation_is_in_the_fold_with_its_calls_timed(consulted):
    data = views.trajectory_data(consulted)
    by_type = {}
    for row in data["events"]:
        by_type.setdefault(row[3], []).append(row)
    opened = by_type["agent/consult_opened"]
    closed = by_type["agent/consult_closed"]
    calls = [row for row in by_type["agent/llm_call"] if row[9].get("consultation_id")]
    ids = {row[9]["consultation_id"] for row in opened}
    assert ids and ids == {row[9]["consultation_id"] for row in closed}
    assert calls and {row[9]["consultation_id"] for row in calls} <= ids
    for row in calls:
        assert row[7] is not None and row[7] == round(row[9]["latency_ms"], 3)
        assert row[9]["phase"] in ("owner", "peer")
    assert {row[9]["phase"] for row in calls} == {"owner", "peer"}
    assert any(row[9].get("text") for row in by_type["agent/consult_question"])
    assert any(PEER in row[9].get("text", "") for row in by_type["agent/consult_response"])
    assert closed[-1][9]["outcome"] == "decided"
    assert data["summary"]["model_requests"] == len(by_type["agent/llm_call"])
    assert data["run"]["model"] == consulted.settings.model


# ---------------------------------------------------------- the pages
def test_the_page_is_the_template_filled_with_the_live_run(rules):
    page = live.trajectory_html(rules, limit=500)
    assert "/*__TRAJECTORY_DATA__*/null" not in page
    assert f'"run_id":"{rules.eco.run_id}"' in page
    assert '"archived":false' in page
    assert "/ui/trajectory/tail" in page, "the page knows where to poll"
    assert 'id="follow"' in page and "poSuspend" in page
    assert "/ui/history" not in page
    assert "Expert consultation" in page and "LLM-Agent Discussion" not in page
    assert "\x00" not in page and "\u2014" not in page and "\r" not in page


@pytest.fixture
def client(rules):
    previous = server.use(rules)
    try:
        yield TestClient(server.app)
    finally:
        server.use(previous)


def test_the_trajectory_route_serves_only_the_live_run(client, rules):
    response = client.get("/ui/trajectory")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert f'"run_id":"{rules.eco.run_id}"' in response.text
    named = client.get(f"/ui/trajectory?run_id={rules.eco.run_id}&limit=200")
    assert named.status_code == 200 and '"archived":false' in named.text
    # Accepted, and refused: the live run is never served as finished.
    assert '"archived":false' in client.get("/ui/trajectory?archived=true").text
    other = client.get("/ui/trajectory?run_id=last-week")
    assert other.status_code == 404
    assert "last-week" in other.json()["detail"]
    assert client.get("/ui/trajectory?limit=5").status_code == 422


def test_the_tail_route_answers_rows_last_id_and_total(client, rules):
    folded = views.trajectory_data(rules)
    cut = folded["events"][-5][0]
    body = client.get("/ui/trajectory/tail",
                      params={"after_id": cut, "started": folded["started"]}).json()
    assert set(body) == {"rows", "last_id", "total"}
    assert [row[0] for row in body["rows"]] == [row[0] for row in folded["events"][-4:]]
    assert body["rows"] == [list(row) for row in folded["events"][-4:]]
    assert client.get("/ui/trajectory/tail?limit=0").status_code == 422


def test_the_tail_refuses_a_page_of_an_earlier_run(client, rules):
    folded = views.trajectory_data(rules)
    old_run, started = folded["run_id"], folded["started"]
    fresh = {"after_id": folded["events"][-1][0], "started": started, "run_id": old_run}
    assert client.get("/ui/trajectory/tail", params=fresh).status_code == 200
    rules.reset()
    rules.step(3)
    assert rules.eco.run_id != old_run
    by_name = client.get("/ui/trajectory/tail", params=fresh)
    assert by_name.status_code == 409
    assert "ended" in by_name.json()["detail"] and old_run in by_name.json()["detail"]
    by_clock = client.get("/ui/trajectory/tail", params={"after_id": 0, "started": started})
    assert by_clock.status_code == 409
    now = views.trajectory_data(rules)
    current = {"after_id": 0, "started": now["started"], "run_id": now["run_id"]}
    assert client.get("/ui/trajectory/tail", params=current).status_code == 200
    assert client.get("/ui/trajectory/tail").status_code == 200


def test_the_rct_log_page_is_served(client):
    response = client.get("/ui/rcts")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    page = response.text
    assert page == live.rcts_html()
    assert "/dkrmm/rct-log" in page and "/dkrmm/rct-log/item" in page and "poSuspend" in page
    assert "<th>Consultation</th>" in page and "experts consulting" in page
    for old in ("<th>Discussion</th>", "discussing", "Expert discussion", "no discussion",
                "discussions off"):
        assert old not in page
    assert "\u2014" not in page and "\r" not in page


# ------------------------------------------------------ in a browser
#: Synthetic rows for checking the page's own rules in the browser only (never
#: served): [id, tick, ms, type, actor, target, correlation, duration, text, payload].
_LANE_ROWS = [
    [1, 0, 0, "agent/message", "SORTING", "SUB-BARCODE", "", None, "",
     {"interaction_type": "subagent_request"}],
    [2, 0, 0, "agent/message", "SUB-BARCODE", "SORTING", "", None, "",
     {"interaction_type": "subagent_response"}],
    [3, 0, 0, "simulation/llm", "SIMULATION", "", "", None, "", {}],
    [4, 0, 0, "robot/moved", "R1", "", "", None, "", {}],
    [5, 0, 0, "agent/decision", "SORTING", "", "", None, "", {}],
    [6, 0, 0, "parcel/parcel_arrived", "ENVIRONMENT", "", "", None, "", {}],
]
_LANES = ["tools", "tools", "operator", "robots", "agents", "world"]
_TONE = {"decided": "ok", "timeout": "warn", "no_valid_decision": "bad",
         "model_failed": "bad", "peer_failed": "", None: "open"}


def _consultation_rows(at):
    """One synthetic consultation per outcome (None: still open), each with an
    owner call and a peer call, after the page's last row at `at` ms."""
    rows, seq = [], 10 ** 9
    for n, outcome in enumerate(_TONE):
        cid = f"CSL-T{n}"
        base = at + 100 + 50 * n
        seq += 1
        rows.append([seq, 1, base, "agent/consult_opened", "SCHEDULING", "ROUTING", cid,
                     None, "", {"consultation_id": cid, "peer": "ROUTING",
                                "decision": "choose_robot"}])
        for phase, actor, end in (("owner", "SCHEDULING", 20), ("peer", "ROUTING", 40)):
            seq += 1
            rows.append([seq, 1, base + end, "agent/llm_call", actor, "", cid, 10.0, "",
                         {"consultation_id": cid, "phase": phase, "latency_ms": 10.0}])
        if outcome is not None:
            seq += 1
            rows.append([seq, 1, base + 45, "agent/consult_closed", "SCHEDULING", "ROUTING",
                         cid, 45.0, "", {"consultation_id": cid, "outcome": outcome}])
    return rows


def _the_page_rules_hold(page):
    """The lanes, the outcome outlines and the phase colours, by the page's own code."""
    assert page.evaluate("rows => rows.map(familyOf)", _LANE_ROWS) == _LANES
    at = page.evaluate("EVENTS[EVENTS.length - 1][MS]")
    page.evaluate("rows => { ingest(rows); rebuild(true); }", _consultation_rows(at))
    for n, (outcome, tone) in enumerate(_TONE.items()):
        bar = page.locator(f'.drow[data-d="CSL-T{n}"] .dbar')
        assert bar.get_attribute("class").split() == ["dbar"] + ([tone] if tone else []), outcome
    colours = page.evaluate("""() => {
        const css = getComputedStyle(document.documentElement);
        const segs = [...document.querySelectorAll('.drow[data-d="CSL-T0"] .dseg')];
        return {agents: css.getPropertyValue('--l-agents').trim(),
                tools: css.getPropertyValue('--l-tools').trim(),
                segs: segs.map(s => [s.classList.contains('peer'),
                                     getComputedStyle(s).backgroundColor])};
    }""")
    assert [peer for peer, _ in colours["segs"]] == [False, True]
    owner, peer = (colour for _, colour in colours["segs"])
    assert owner != peer
    assert owner == _rgb(colours["agents"]) and peer == _rgb(colours["tools"])
    # A consultation with no peer is drawn with its owner alone, no arrow.
    at = page.evaluate("EVENTS[EVENTS.length - 1][MS]")
    solo = [[2 * 10 ** 9, 1, at + 500, "agent/consult_opened", "SCHEDULING", "", "CSL-SOLO",
             None, "", {"consultation_id": "CSL-SOLO", "decision": "choose_robot"}]]
    page.evaluate("rows => { ingest(rows); rebuild(true); }", solo)
    label = page.locator('.drow[data-d="CSL-SOLO"] .dlabel')
    assert label.inner_text().split("\u00b7")[0].split() == ["CSL-SOLO", "SCHEDULING"]
    assert "\u2194" not in label.get_attribute("title")
    page.click('.drow[data-d="CSL-SOLO"]')
    assert page.inner_text("#i-title") == "CSL-SOLO \u00b7 SCHEDULING"


def _rgb(hex_colour):
    value = hex_colour.lstrip("#")
    return "rgb({}, {}, {})".format(*(int(value[i:i + 2], 16) for i in (0, 2, 4)))


def test_both_pages_render_in_a_headless_browser():
    pytest.importorskip("playwright", reason="the browser check needs the ui-test extra")
    import uvicorn
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    fake = FakeOllama()
    fake.script(consultation_script(PEER, decide=lambda _peer: "R2"))
    uv = thread = previous = None
    served = False
    with quiet():
        runner = SimulationRunner(settings=fake.settings, tick_seconds=0)
        try:
            runner.eco.start()
            runner.step(2)
            _consult(runner)
            previous, served = server.use(runner), True
            uv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=0,
                                               log_level="warning", lifespan="off"))
            thread = threading.Thread(target=uv.run, name="uvicorn-trajectory", daemon=True)
            thread.start()
            deadline = time.monotonic() + 20
            while not (uv.started and uv.servers):
                assert time.monotonic() < deadline, "uvicorn did not start"
                time.sleep(0.02)
            base = f"http://127.0.0.1:{uv.servers[0].sockets[0].getsockname()[1]}"
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch()
                except PlaywrightError as exc:
                    pytest.skip(f"no headless Chromium: {exc}")
                try:
                    errors = []
                    page = browser.new_page(viewport={"width": 1400, "height": 900})
                    page.on("console", lambda m: errors.append(m.text)
                            if m.type == "error" else None)
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(base + "/ui/trajectory", wait_until="domcontentloaded")
                    page.wait_for_selector(".row", timeout=20000)
                    assert page.locator(".row").count() > 0
                    assert "live" in page.inner_text("#whose").lower()
                    page.click("#m-discuss")
                    page.wait_for_selector(".dbar", timeout=20000)
                    assert page.locator(".dbar").count() >= 1
                    assert page.locator(".dseg").count() >= 1
                    assert "consultation" in page.inner_text("#count")
                    page.click(".drow")
                    assert "R2" in page.inner_text("#i-body")
                    # A turn names the call's served model, from its own payload.
                    assert fake.settings.model in page.inner_text("#i-body")
                    assert "llm_call" not in page.inner_text("#i-body")
                    _the_page_rules_hold(page)

                    page.goto(base + "/ui/rcts", wait_until="domcontentloaded")
                    page.wait_for_function(
                        "() => document.getElementById('note').innerText"
                        ".includes('not saving RCTs')", timeout=20000)
                    # The RCT log draws a consultation with no peer by its owner alone.
                    cell = page.evaluate(
                        "() => { const box = document.createElement('div');"
                        " box.innerHTML = causeHtml({summary: '', kinds: [], window: [0, 20],"
                        "  events: 0, trouble: 0, messages: 0, discussion_messages: 0,"
                        "  discussions: [{id: 'CSL-SOLO', owner: 'SCHEDULING', peer: '',"
                        "   decision: 'choose_robot', outcome: 'decided', opened: 3, closed: 5,"
                        "   strong: 0, weak: 0}]});"
                        " return box.querySelector('table.ex-disc tbody td').innerText; }")
                    assert cell == "CSL-SOLO SCHEDULING"
                    page.close()
                    assert errors == []

                    # The run is reset under an open page: its tail is refused
                    # and the page says the run has ended.
                    page = browser.new_page()
                    page.goto(base + "/ui/trajectory", wait_until="domcontentloaded")
                    page.wait_for_selector(".row", timeout=20000)
                    runner.reset()
                    runner.step(2)
                    page.wait_for_function(
                        "() => document.getElementById('follow').textContent"
                        ".includes('run ended')", timeout=20000)
                    assert page.is_disabled("#follow")
                    page.close()
                finally:
                    browser.close()
        finally:
            if uv is not None:
                uv.should_exit = True
            if thread is not None:
                thread.join(timeout=10)
            if served:
                server.use(previous)
            runner.close()
            fake.stop()
