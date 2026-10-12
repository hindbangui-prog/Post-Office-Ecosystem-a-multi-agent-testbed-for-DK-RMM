"""
The live page in a headless browser (spec 16), served by uvicorn on a free port.

The runner's experts are on the fake Ollama. After a scripted consultation
(SCHEDULING asks ROUTING about two robots the walk cannot separate, and decides
R2) the Consultations pane shows the peer's words and `DECISION: R2`; the
Ollama pane shows the served model; the DK-RMM pane shows a state; and no text
on the page names a removed scenario family.

The Trajectory and RCT log tabs (trajectory/RCT design, sections 8 and 10)
open lazily, the Trajectory tails the run and stops asking while hidden, a
reset rebuilds it and leaves the RCT log alone, the RCT log lists an RCT forced
on a runner that records to `tmp_path`, and the DK-RMM pane's gate posts a
person's verdict and shows it, the server's 409 included, and explains the
current reading with `/dkrmm/explain`'s own summary.

The Runtime communication pane (taxonomy design, sections 6 and 8) is checked
against `post_office/ui/feed.py`, whose rules the page's JavaScript mirrors:
a row for every channel, `(none)` and no edge for a decision, the channel
chips, chain follow by click and by a typed parcel id, every request and
response cell equal to `feed.feed_row` of the same event, the model only on
channel B rows and model-backed decisions, the floor's class legend and
ENVIRONMENT node, and the floor's list equal to the feed's tail (a reply row's
own text, every other row's request text).

Needs the `ui-test` extra (`pip install -e ".[ui-test]"`) and a Chromium for
Playwright; without Playwright the module is skipped.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request

import pytest

pytest.importorskip("playwright", reason="the live UI test needs the ui-test extra")
from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from post_office.api import server  # noqa: E402
from post_office.api.runner import SimulationRunner  # noqa: E402
from post_office.communication import taxonomy  # noqa: E402
from post_office.config.settings import scenarios  # noqa: E402
from post_office.crew.console import quiet  # noqa: E402
from post_office.dkrmm import OperationalState  # noqa: E402
from post_office.dkrmm.indicators import INDICATOR_NAMES  # noqa: E402
from post_office.ui import feed  # noqa: E402
from tests.consult_helpers import ask, equally_placed  # noqa: E402
from tests.fake_ollama import FakeOllama, consultation_script  # noqa: E402

FORBIDDEN = ("attack", "perturb", "stress", "inject", "experiment", "autodk", "openrt")
PEER = "R2: corridor clear, the shorter walk from the sorting belt."
STATES = [s.value for s in OperationalState]
WAIT_MS = 20000
#: The feed's columns, in the order the table draws them (spec 6.1).
COLUMNS = ["tick", "sender", "receiver", "type", "class", "request", "response",
           "decision", "latency", "model", "edge"]
CHANNELS = ("A", "B", "C", "D", "E", "decision", "system")
#: Where the review package keeps the screenshots (git-ignored).
PACKAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       ".superpowers", "sdd", "2026-10-02-runtime-taxonomy")
#: The trajectory/RCT review package (git-ignored).
PACKAGE_RCT = os.path.join(os.path.dirname(PACKAGE), "2026-10-02-trajectory-rct")


def _pick_r2(_peer_text: str) -> str:
    return "R2"


@pytest.fixture(scope="module")
def live():
    """(base url, runner, fake): uvicorn in a thread over a model-mode runner."""
    import uvicorn

    fake = FakeOllama()
    fake.script(consultation_script(PEER, decide=_pick_r2))
    with quiet():
        runner = SimulationRunner(settings=fake.settings, tick_seconds=0)
        previous = server.use(runner)
        uv = None
        thread = None
        try:
            runner.eco.start()
            runner.step(21)  # past DK-RMM's first assessment (every 20 ticks)
            uv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=0,
                                               log_level="warning", lifespan="off"))
            thread = threading.Thread(target=uv.run, name="uvicorn-live-ui", daemon=True)
            thread.start()
            deadline = time.monotonic() + 20
            while not (uv.started and uv.servers):
                assert time.monotonic() < deadline, "uvicorn did not start"
                time.sleep(0.02)
            port = uv.servers[0].sockets[0].getsockname()[1]
            yield f"http://127.0.0.1:{port}", runner, fake
        finally:
            if uv is not None:
                uv.should_exit = True
            if thread is not None:
                thread.join(timeout=10)
            server.use(previous)
            runner.close()
            fake.stop()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        try:
            made = playwright.chromium.launch()
        except PlaywrightError as exc:  # no Chromium installed for Playwright
            pytest.skip(f"no headless Chromium: {exc}")
        try:
            yield made
        finally:
            made.close()


@pytest.fixture
def page(live, browser):
    base, _, _ = live
    made = browser.new_page(viewport={"width": 1500, "height": 950})
    made.goto(base + "/", wait_until="domcontentloaded")
    made.wait_for_selector("#tab-consultations", state="attached")
    try:
        yield made
    finally:
        made.close()


def _consult(runner) -> None:
    """One SCHEDULING consultation with ROUTING, run as a tick would run it."""
    with runner._lock:
        sched = runner.eco.agents["SCHEDULING"]
        sched.triggers.register("choose_robot", equally_placed)
        ask(sched)
        runner._publish()


def _text(page, selector: str) -> str:
    return page.inner_text(selector)


def _wait_text(page, selector: str, needle: str) -> None:
    page.wait_for_function(
        "([sel, needle]) => { const el = document.querySelector(sel);"
        " return !!el && el.innerText.includes(needle); }",
        arg=[selector, needle], timeout=WAIT_MS)


def _no_forbidden(text: str) -> None:
    low = text.lower()
    found = [word for word in FORBIDDEN if word in low]
    assert not found, f"the page says {found}"


def test_the_page_loads_with_one_scenario_and_the_model_badge(page):
    assert page.title() == "Automated post office"
    options = page.eval_on_selector_all("#scenario option", "els => els.map(e => e.textContent)")
    # Normal first, with its label unchanged; then the C2-NEAR conditions.
    assert options[0] == "NORMAL · CrewAI · Ollama/qwen3:8b · DK-RMM"
    assert options == [label for _, label in scenarios("qwen3:8b")] and len(options) == 8
    assert page.eval_on_selector("#scenario", "el => el.value") == "default"
    assert page.is_hidden("#c2near")
    _wait_text(page, "#model-badge", "Ollama · qwen3:8b · 7/7 experts")
    page.wait_for_selector("#pane-robots", state="attached")
    _no_forbidden(page.evaluate("document.body.innerText"))


def test_a_consultation_appears_in_the_consultations_pane(live, page):
    _, runner, _ = live
    _consult(runner)
    page.click("#tab-consultations")
    _wait_text(page, "#pane-consultations", "DECISION: R2")
    text = _text(page, "#pane-consultations")
    assert PEER in text
    assert "SCHEDULING → ROUTING" in text
    assert "choose_robot · equally_placed" in text
    assert "decided" in text and "qwen3:8b" in text
    _no_forbidden(page.evaluate("document.body.innerText"))


def test_the_ollama_pane_shows_the_served_model(page):
    page.click("#tab-llm")
    _wait_text(page, "#pane-llm", "qwen3:8b")
    text = _text(page, "#pane-llm")
    assert "SCHEDULING" in text and "owner" in text
    assert re.search(r"\d+ ms", text), "latency is shown"
    _no_forbidden(page.evaluate("document.body.innerText"))


def test_the_dkrmm_pane_shows_a_state_and_the_indicators(page):
    page.click("#tab-dkrmm")
    page.wait_for_function(
        "(states) => { const el = document.querySelector('#dk-pane-state');"
        " return !!el && states.includes(el.innerText.trim()); }",
        arg=STATES, timeout=WAIT_MS)
    # The registry's twenty (twelve behavioural, eight operational) since
    # 2026-10-12, one row each.
    assert page.locator("#pane-dkrmm .indicator").count() == len(INDICATOR_NAMES)
    assert page.locator("#pane-dkrmm .strip span").count() >= 1
    _no_forbidden(page.evaluate("document.body.innerText"))


def test_the_roster_card_rings_the_expert_inside_a_model_call(live, page):
    _, runner, fake = live
    fake.delay(1.0)
    worker = threading.Thread(target=_consult, args=(runner,), daemon=True)
    try:
        worker.start()
        page.wait_for_selector('#roster .card.busy[data-agent="SCHEDULING"]',
                               state="attached", timeout=WAIT_MS)
    finally:
        fake.delay(0)
        worker.join(timeout=60)
    page.wait_for_selector("#roster .card.busy", state="detached", timeout=WAIT_MS)


def test_no_tab_and_no_source_names_a_removed_family(live, page):
    base, _, _ = live
    for tab in ("#tab-robots", "#tab-consultations", "#tab-llm", "#tab-dkrmm", "#tab-feed",
                "#tab-trajectory", "#tab-rcts"):
        page.click(tab)
        _no_forbidden(page.evaluate("document.body.innerText"))
    import urllib.request

    # The raw sources, comments included, of the shell and of the two pages it frames.
    for path in ("/", "/ui/rcts", "/ui/trajectory"):
        with urllib.request.urlopen(base + path) as response:
            _no_forbidden(response.read().decode("utf-8"))


# ------------------------------------------------- the Runtime communication pane
def _server_rows(runner, first_seq: int):
    """The runner's events from `first_seq` on, the rows the page's buffer holds."""
    return runner.events(after=max(0, int(first_seq) - 1), limit=2000)


def _open_feed(page, runner) -> None:
    """Open the pane and wait until it has drawn the run's newest event."""
    page.click("#tab-feed")
    last = runner.event_counts()["total"]
    page.wait_for_function(
        "(last) => { const t = document.querySelector('#feed-table');"
        " return !!t && Number(t.dataset.lastSeq || 0) >= last; }",
        arg=last, timeout=WAIT_MS)


def _rows_js(page):
    """Every row of the table as the page shows it: its data attributes and cell texts."""
    return page.evaluate(
        "() => [...document.querySelectorAll('#feed-table tbody tr[data-seq]')]"
        "  .filter((tr) => !tr.hidden && tr.offsetParent !== null)"
        "  .map((tr) => ({ seq: Number(tr.dataset.seq), channel: tr.dataset.channel,"
        "    type: tr.dataset.type, topic: tr.dataset.topic, corr: tr.dataset.corr,"
        "    consultation: tr.dataset.consultation, parcel: tr.dataset.parcel,"
        "    chain: tr.classList.contains('chain'), selected: tr.classList.contains('selected'),"
        "    cells: [...tr.children].map((td) => [...td.childNodes]"
        "      .filter((n) => n.nodeName !== 'SMALL').map((n) => n.textContent).join('')),"
        "    small: (tr.querySelector('td.what small') || {}).textContent || '',"
        "    titles: [...tr.children].map((td) => td.getAttribute('title') || '') }))")


def _cell(row, name: str) -> str:
    return row["cells"][COLUMNS.index(name)]


def _ensure_traffic(runner) -> None:
    """Enough ticks for every channel: robot commands begin once tasks are released."""
    if runner.event_counts()["total"] < 1200:
        runner.step(40)


def test_the_runtime_communication_pane_shows_a_row_for_every_channel(live, page):
    _, runner, _ = live
    _consult(runner)
    _ensure_traffic(runner)
    _open_feed(page, runner)
    assert page.locator("#feed-table thead th").all_text_contents() == COLUMNS
    for channel in CHANNELS:
        assert page.locator(f'#feed-table tr[data-channel="{channel}"]').count() >= 1, channel
    rows = _rows_js(page)
    assert len(rows) >= 7
    assert page.inner_text("#tab-feed-em").strip() == str(len(rows))
    assert "no event yet" not in page.inner_text("#pane-feed")
    legend = page.inner_text("#feed-legend")
    for label in ("governance", "llm_expert", "deterministic", "robot", "environment",
                  "decision (node pulse, no edge)", "(none) = no receiver, no edge"):
        assert label in legend, label
    _no_forbidden(page.evaluate("document.body.innerText"))


def test_a_decision_row_reads_none_for_its_receiver_and_has_no_edge(live, page):
    _, runner, _ = live
    _open_feed(page, runner)
    rows = [r for r in _rows_js(page) if r["channel"] == "decision"]
    assert rows, "no decision row"
    for row in rows:
        assert _cell(row, "receiver") == "(none)"
        assert _cell(row, "edge") == ""
    with_edge = [r for r in _rows_js(page) if _cell(r, "edge")]
    assert with_edge, "no row with an edge"
    for row in with_edge:
        assert _cell(row, "edge") == f'{_cell(row, "sender")} -> {_cell(row, "receiver")}'
        assert _cell(row, "receiver") != "(none)"


def test_the_channel_chip_leaves_only_that_channels_rows(live, page):
    _, runner, _ = live
    _open_feed(page, runner)
    everything = len(_rows_js(page))
    page.click('#feed-filters [data-channel="D"]')
    page.wait_for_function(
        "() => [...document.querySelectorAll('#feed-table tbody tr[data-seq]')]"
        "  .every((tr) => tr.dataset.channel === 'D')", timeout=WAIT_MS)
    rows = _rows_js(page)
    assert rows and all(r["channel"] == "D" for r in rows)
    assert 0 < len(rows) < everything
    assert page.inner_text("#tab-feed-em").strip() == str(len(rows))
    page.click('#feed-filters [data-channel="D"]')          # a chip toggles
    page.wait_for_function(
        "(n) => document.querySelectorAll('#feed-table tbody tr[data-seq]').length >= n",
        arg=everything, timeout=WAIT_MS)


def test_clicking_a_consult_question_row_highlights_its_consultation(live, page):
    _, runner, _ = live
    _consult(runner)
    _open_feed(page, runner)
    question = page.locator(
        '#feed-table tr[data-topic="consult_question"]:not([data-consultation=""])').last
    cid = question.get_attribute("data-consultation")
    assert cid
    question.click()
    page.wait_for_selector(f'#feed-table tr.selected[data-consultation="{cid}"]',
                           state="attached", timeout=WAIT_MS)
    for topic in ("consult_response", "consult_closed", "decision"):
        selector = f'#feed-table tr.chain[data-topic="{topic}"][data-consultation="{cid}"]'
        assert page.locator(selector).count() >= 1, topic
    summary = page.inner_text("#chain-summary")
    assert re.fullmatch(rf"chain: {re.escape(cid)} · \d+ rows · \d+ edges", summary.strip()), summary
    assert not page.is_checked("#follow-newest")
    # The same row again clears the selection.
    question.click()
    page.wait_for_selector("#feed-table tr.chain", state="detached", timeout=WAIT_MS)
    assert page.locator("#feed-table tr.selected").count() == 0


def test_clicking_a_decision_row_highlights_the_consultation_it_names(live, page):
    _, runner, _ = live
    _consult(runner)
    _open_feed(page, runner)
    decision = page.locator(
        '#feed-table tr[data-topic="decision"]:not([data-consultation=""])').last
    cid = decision.get_attribute("data-consultation")
    assert cid
    decision.click()
    page.wait_for_selector(f'#feed-table tr.selected[data-topic="decision"][data-consultation="{cid}"]',
                           state="attached", timeout=WAIT_MS)
    for topic in ("consult_opened", "consult_question", "consult_response", "consult_closed"):
        selector = f'#feed-table tr.chain[data-topic="{topic}"][data-consultation="{cid}"]'
        assert page.locator(selector).count() >= 1, topic
    # The consultation's bus twins share its correlation id and are lit too.
    assert page.locator(f'#feed-table tr.chain[data-topic="message"][data-corr="{cid}"]').count() >= 1
    # And exactly feed.chain_select of the same seed over the same rows.
    shown = _rows_js(page)
    rows = _server_rows(runner, min(r["seq"] for r in shown))
    seed = next(r for r in rows if r["seq"] == int(decision.get_attribute("data-seq")))
    lit = {r["seq"] for r in shown if r["chain"] or r["selected"]}
    assert lit == feed.chain_select(rows, seed)


def test_a_fresh_page_on_a_long_run_holds_the_last_2000_events_without_a_hole(live, browser):
    base, runner, _ = live
    while runner.event_counts()["total"] <= 2200:
        runner.step(10)
    total = runner.event_counts()["total"]
    fresh = browser.new_page(viewport={"width": 1500, "height": 950})
    try:
        fresh.goto(base + "/", wait_until="domcontentloaded")
        fresh.click("#tab-feed")
        fresh.wait_for_function(
            "(last) => Number(document.querySelector('#feed-table').dataset.lastSeq || 0) >= last",
            arg=total, timeout=WAIT_MS)
        fresh.wait_for_function(
            "() => document.querySelectorAll('#feed-table tbody tr[data-seq]').length >= 2000",
            timeout=WAIT_MS)
        seqs = fresh.evaluate(
            "() => [...document.querySelectorAll('#feed-table tbody tr[data-seq]')].map((tr) => Number(tr.dataset.seq))")
    finally:
        fresh.close()
    assert runner.event_counts()["total"] == total, "the run moved during the test"
    assert len(seqs) == 2000
    assert seqs == list(range(total - 1999, total + 1)), (seqs[0], seqs[-1], total)


def test_a_parcel_id_in_the_box_highlights_only_its_rows(live, page):
    _, runner, _ = live
    _open_feed(page, runner)
    shown = _rows_js(page)
    rows = _server_rows(runner, min(r["seq"] for r in shown))
    # A parcel whose chain is its own rows only: no selected decision of its
    # chain names a consultation, so the closure adds nothing.
    parcel_id, expected = None, set()
    for candidate in sorted({r["corr"] for r in shown if r["corr"].startswith("P-")}):
        selected = feed.chain_select_by_id(rows, candidate)
        by_seq = {int(r["seq"]): r for r in rows}
        if selected and all(
                by_seq[s].get("correlation_id") == candidate
                or (by_seq[s].get("detail") or {}).get("parcel_id") == candidate
                for s in selected):
            parcel_id, expected = candidate, selected
            break
    assert parcel_id, "no parcel id with a self-contained chain"
    page.fill("#chain-id", parcel_id)
    page.press("#chain-id", "Enter")
    _wait_text(page, "#chain-summary", f"chain: {parcel_id}")
    chain = [r for r in _rows_js(page) if r["chain"]]
    assert {r["seq"] for r in chain} == expected
    for row in chain:
        assert row["corr"] == parcel_id or row["parcel"] == parcel_id, row
    page.click("#chain-clear")
    page.wait_for_selector("#feed-table tr.chain", state="detached", timeout=WAIT_MS)
    assert page.input_value("#chain-id") == ""


def test_every_request_and_response_cell_is_the_feed_rows_value(live, page):
    _, runner, _ = live
    _consult(runner)
    _open_feed(page, runner)
    shown = _rows_js(page)
    rows = _server_rows(runner, min(r["seq"] for r in shown))
    by_seq = {int(r["seq"]): r for r in rows}
    pairs = feed.pair(rows)
    requests_by_response = {int(v): int(k) for k, v in pairs.items()}
    by_consultation = feed.models_by_consultation(rows)
    model = runner.settings.model
    sample = []
    for channel in CHANNELS:
        sample.extend([r for r in shown if r["channel"] == channel][-10:])
    assert len(sample) >= 50, len(sample)
    paired = 0
    for row in sample:
        event = by_seq[row["seq"]]
        response = by_seq.get(int(pairs.get(str(event["seq"]), -1)))
        request = by_seq.get(requests_by_response.get(event["seq"], -1))
        want = feed.feed_row(event, response, by_consultation, model, paired_request=request)
        assert _cell(row, "request") == want["request"], row["seq"]
        assert _cell(row, "response") == want["response"], row["seq"]
        assert _cell(row, "decision") == want["decision"], row["seq"]
        assert _cell(row, "sender") == want["sender"] and _cell(row, "receiver") == want["receiver"]
        assert _cell(row, "type") == want["interaction_type"]
        # The event's own topic under the type, and the bus message's type as
        # the cell's title: the twin rows of one exchange are told apart.
        assert row["small"] == event["topic"]
        assert row["titles"][COLUMNS.index("type")] == ((event.get("detail") or {}).get("message_type") or "")
        assert _cell(row, "class") == want["channel"]
        assert _cell(row, "model") == (want["model"] or "")
        if want["latency_ms"] is not None:
            # Math.round, as the page's other panes round a latency.
            assert _cell(row, "latency") == f'{math.floor(want["latency_ms"] + 0.5)} ms'
        elif want["latency_ticks"] is not None:
            assert _cell(row, "latency") == f'{want["latency_ticks"]} ticks'
        else:
            assert _cell(row, "latency") == ""
        if want["paired_seq"] is not None:
            paired += 1
            assert str(want["paired_seq"]) in row["titles"][COLUMNS.index("response")]
    assert paired > 0


def test_the_model_cell_is_filled_only_on_channel_b_rows_and_llm_decisions(live, page):
    _, runner, _ = live
    _consult(runner)
    _open_feed(page, runner)
    shown = _rows_js(page)
    by_seq = {int(r["seq"]): r for r in _server_rows(runner, min(r["seq"] for r in shown))}
    named = 0
    for row in shown:
        model = _cell(row, "model")
        if not model:
            continue
        named += 1
        event = by_seq[row["seq"]]
        if row["channel"] == "decision":
            assert (event.get("detail") or {}).get("mode") == "llm", row["seq"]
        else:
            assert row["channel"] == "B", row["seq"]
    assert named > 0
    assert any(_cell(r, "model") for r in shown if r["channel"] == "decision")
    assert all(not _cell(r, "model") for r in shown if r["channel"] in ("A", "C", "D", "E", "system"))


def test_the_floor_shows_the_class_legend_and_the_environment_node(live, page):
    """
    The graph as it is drawn now: the class key is the last line of the
    legend under the canvas (not a header key), the floor's own events have
    no node (no `NODES.ENVIRONMENT`; they are in the Runtime communication
    pane), the robots are the lowest tier, and the canvas with the robots'
    rings fits the pane without scrolling at both viewports.
    """
    _, runner, _ = live
    page.click("#tab-robots")
    floor = page.frame_locator("#pane-robots")
    floor.locator("#graph-classes i").first.wait_for(state="attached", timeout=WAIT_MS)
    legend = floor.locator("#graph-classes").inner_text()
    for row in taxonomy.table()["channels"][:5]:
        assert f'{row["id"]} {row["label"]}' in legend, row["id"]
    assert "decision = node pulse" in legend
    assert "(none)" not in legend, "the no-edge note belongs to the feed, not the floor"
    assert floor.locator("#latest h3").text_content().startswith("Runtime communication")
    # The class key is inside the graph section's legend, below the canvas,
    # and is the legend's last line.
    assert floor.locator("#graph-section .legend #graph-classes").count() == 1
    canvas = floor.locator("#graph").bounding_box()
    legend_box = floor.locator("#graph-section .legend").bounding_box()
    box = floor.locator("#graph-classes").bounding_box()
    assert canvas and legend_box and box
    assert legend_box["y"] >= canvas["y"] + canvas["height"] - 1
    assert box["y"] >= legend_box["y"] - 1
    assert box["y"] + box["height"] <= legend_box["y"] + legend_box["height"] + 1
    last_child = floor.locator("#graph-section .legend > :last-child")
    assert last_child.get_attribute("id") == "graph-classes"
    frame = page.query_selector("#pane-robots").content_frame()
    for viewport in ({"width": 1500, "height": 950}, {"width": 1280, "height": 800}):
        page.set_viewport_size(viewport)
        page.wait_for_timeout(300)
        # A robot's radius (9.5, grown with GS) plus its widest ring, the chain
        # ring at r + 12 GS, with half of that ring's 2.5 GS stroke.
        nodes = frame.evaluate(
            "() => { drawGraph(); const g = document.getElementById('graph');"
            " const grow = 1 + (GS - 1) * 0.5, r = 9.5 * grow, ring = r + 12 * GS + 1.25 * GS;"
            " const rect = g.getBoundingClientRect(), scale = rect.width / g.width;"
            " const sec = document.getElementById('graph-section').getBoundingClientRect();"
            " const lg = document.querySelector('#graph-section .legend').getBoundingClientRect();"
            " const robots = ROBOTS.map((id) => NODES[id]);"
            " const lowest = Math.max(...robots.map((n) => n.y));"
            " const others = Object.keys(NODES).filter((id) => !ROBOTS.includes(id)).map((id) => NODES[id].y);"
            " return { env: NODES.ENVIRONMENT || null,"
            "   lowest, others, h: g.height, w: g.width,"
            "   ringBottom: lowest + ring,"
            "   ringTop: Math.min(...robots.map((n) => n.y)) - ring,"
            "   left: Math.min(...robots.map((n) => n.x)) - ring,"
            "   right: Math.max(...robots.map((n) => n.x)) + ring,"
            "   screenLeft: rect.left + (Math.min(...robots.map((n) => n.x)) - ring) * scale,"
            "   screenRight: rect.left + (Math.max(...robots.map((n) => n.x)) + ring) * scale,"
            "   canvasH: rect.height, legendBottom: lg.bottom - sec.top, sectionH: sec.height,"
            "   viewH: window.innerHeight, viewW: window.innerWidth, scrollY: window.scrollY }; }")
        # No node for the floor's own events: the robots are the lowest tier.
        assert nodes["env"] is None
        assert nodes["others"] and all(nodes["lowest"] > y for y in nodes["others"])
        # Robots, pulse ring and chain ring all inside the canvas, and the
        # canvas inside the iframe's width ...
        assert 0 <= nodes["ringTop"] and nodes["ringBottom"] <= nodes["h"], (viewport, nodes)
        assert 0 <= nodes["left"] and nodes["right"] <= nodes["w"], (viewport, nodes)
        assert 0 <= nodes["screenLeft"] and nodes["screenRight"] <= nodes["viewW"], (viewport, nodes)
        # ... and the graph section, canvas and key together, is sized to the
        # floor beside it (one window less a margin): no taller than the
        # iframe's viewport, with its key inside it, so the whole canvas is on
        # screen at once (`fitGraph`), not cut off below the pane.
        assert nodes["scrollY"] == 0
        assert nodes["sectionH"] <= nodes["viewH"], (viewport, nodes)
        assert nodes["legendBottom"] <= nodes["sectionH"] + 1, (viewport, nodes)
        assert nodes["canvasH"] < nodes["sectionH"], (viewport, nodes)
        box = page.locator("#pane-robots").bounding_box()
        assert box and box["y"] >= 0 and box["y"] + box["height"] <= viewport["height"] + 1
    page.set_viewport_size({"width": 1500, "height": 950})
    # The list under the floor is the shell's rows, newest first, coloured by class.
    _consult(runner)
    floor.locator("#latest-list li[data-channel]").first.wait_for(state="attached", timeout=WAIT_MS)
    items = floor.locator("#latest-list li[data-channel]")
    ticks = [int(t) for t in items.locator(".tk").all_inner_texts()]
    assert ticks == sorted(ticks, reverse=True)
    assert len(ticks) <= 40
    # And it equals the feed's tail, one text per row, the row's own: the
    # response column on a reply row (a paired reply, or a response-kind
    # row), the request column on every other row.
    total = runner.event_counts()["total"]
    page.wait_for_function(
        "(last) => Number(document.querySelector('#feed-table').dataset.lastSeq || 0) >= last",
        arg=total, timeout=WAIT_MS)
    page.wait_for_timeout(300)
    got = floor.locator("#latest-list li[data-channel]").evaluate_all(
        "(els) => els.map((li) => ({ tick: li.querySelector('.tk').textContent,"
        "  pair: li.querySelector('.pair').textContent, type: li.querySelector('.ty').textContent,"
        "  text: (li.querySelector('.txt') || {}).textContent || null }))")
    rows = _server_rows(runner, max(1, total - 1999))      # the shell's buffer, the last 2000
    by_seq = {int(r["seq"]): r for r in rows}
    pairs = feed.pair(rows)
    requests_by_response = {int(v): int(k) for k, v in pairs.items()}
    by_consultation = feed.models_by_consultation(rows)
    want = []
    for event in sorted(rows, key=lambda r: int(r["seq"]))[-len(got):][::-1]:
        response = by_seq.get(int(pairs.get(str(event["seq"]), -1)))
        request = by_seq.get(requests_by_response.get(event["seq"], -1))
        row = feed.feed_row(event, response, by_consultation, runner.settings.model,
                            paired_request=request)
        reply = request is not None or row["interaction_type"] in feed.RESPONSE_TYPES
        text = row["response"] if reply else row["request"]
        want.append({"tick": str(row["tick"]), "pair": f'{row["sender"]} -> {row["receiver"]}',
                     "type": row["interaction_type"] if text == row["interaction_type"]
                     else f'{row["interaction_type"]}:',
                     "text": None if text == row["interaction_type"] else text})
    assert len(got) == min(40, len(rows))
    assert got == want
    assert any(e["interaction_type"] in feed.RESPONSE_TYPES for e in rows[-len(got):]), \
        "no reply row in the tail"


def test_screenshots_for_the_review_package(live, page):
    _, runner, _ = live
    if not os.path.isdir(PACKAGE):
        pytest.skip("no review package directory")
    _open_feed(page, runner)
    page.screenshot(path=os.path.join(PACKAGE, "task4-feed.png"))
    page.click("#tab-robots")
    page.wait_for_timeout(800)
    page.screenshot(path=os.path.join(PACKAGE, "task4-floor.png"))


# ------------------------------------------------ the Trajectory and RCT log tabs
@pytest.fixture
def recorded(live, tmp_path):
    """
    (base url, runner, folder): a rules-only runner that records to `tmp_path`,
    served by the same server for one test, before any reading; the
    model-mode runner is served again afterwards.
    """
    base, _, _ = live
    with quiet():
        runner = SimulationRunner(rules_only=True, tick_seconds=0, record_dir=tmp_path)
        previous = server.use(runner)
        try:
            runner.eco.start()
            yield base, runner, tmp_path
        finally:
            server.use(previous)
            runner.close()


@pytest.fixture
def rpage(recorded, browser):
    base, _, _ = recorded
    made = browser.new_page(viewport={"width": 1500, "height": 950})
    made.goto(base + "/", wait_until="domcontentloaded")
    made.wait_for_selector("#tab-consultations", state="attached")
    try:
        yield made
    finally:
        made.close()


def _errors(page):
    """Every console error and uncaught exception of the page and its frames from now on."""
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors


def _open_tab(page, tab: str, frame_id: str):
    """Click an iframe tab and wait for the shell's loading box to go: the frame has loaded."""
    page.click(tab)
    page.wait_for_selector("#loading", state="hidden", timeout=WAIT_MS)
    return page.query_selector(frame_id).content_frame()


def _force_rct(runner):
    """As tests/test_recording.py: the last reading is marked RCT and the recorder updated."""
    reading = runner.monitor.history[-1]
    reading.state = OperationalState.RCT
    runner.recorder.update(runner.monitor, runner.eco)
    return reading


def _shot(page, name: str) -> None:
    if os.path.isdir(PACKAGE_RCT):
        page.screenshot(path=os.path.join(PACKAGE_RCT, name))


def test_the_trajectory_and_rct_log_tabs_follow_the_existing_ones_and_load_lazily(page):
    tabs = page.eval_on_selector_all(".tabs [role=tab]", "els => els.map((e) => e.id)")
    assert tabs[-2:] == ["tab-trajectory", "tab-rcts"]
    assert page.inner_text("#tab-trajectory").split() == ["Trajectory", "this", "run,", "live"]
    assert page.inner_text("#tab-rcts").split() == ["RCT", "log", "detected", "RCTs"]
    # Not loaded until opened.
    assert page.get_attribute("#pane-trajectory", "src") is None
    assert page.get_attribute("#pane-rcts", "src") is None
    assert page.is_hidden("#pane-trajectory") and page.is_hidden("#pane-rcts")


def test_the_trajectory_tab_shows_the_run_and_stops_asking_while_hidden(live, page):
    _, runner, _ = live
    _consult(runner)
    errors = _errors(page)
    tails = []
    page.on("request", lambda r: tails.append(r.url) if "/ui/trajectory/tail" in r.url else None)
    held = []
    page.route("**/ui/trajectory", lambda route: held.append(route))
    page.click("#tab-trajectory")
    assert page.get_attribute("#pane-trajectory", "src") == "/ui/trajectory"
    assert page.text_content("#loading") == "building trajectory from the run so far…"
    # While the page is being built the box is what a reader sees, not an empty pane.
    deadline = time.monotonic() + WAIT_MS / 1000
    while not held:
        assert time.monotonic() < deadline, "the trajectory was never asked for"
        page.wait_for_timeout(50)
    on_top = page.evaluate(
        "() => { const r = document.querySelector('.panes').getBoundingClientRect();"
        " return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2).id; }")
    assert on_top == "loading"
    for route in held:
        route.continue_()
    page.unroute("**/ui/trajectory")
    page.wait_for_selector("#loading", state="hidden", timeout=WAIT_MS)
    frame = page.query_selector("#pane-trajectory").content_frame()
    frame.wait_for_selector("#stream .row", timeout=WAIT_MS)
    assert frame.locator("#lanes canvas").count() == 4
    assert frame.inner_text("#whose .badge").lower() == "live"
    # It tails: rows the runner logs after the page was built arrive.
    before = frame.evaluate("EVENTS.length")
    runner.step(3)
    frame.wait_for_function("(n) => EVENTS.length > n", arg=before, timeout=WAIT_MS)
    assert frame.locator("#stream .row").count() >= 1
    _no_forbidden(frame.evaluate("document.body.innerText"))
    _shot(page, "task4-trajectory.png")
    # Behind another tab it is told to stop (`poSuspend(true)`): no tail requests.
    page.click("#tab-robots")
    page.wait_for_timeout(1500)                       # a request already in flight lands
    stopped = len(tails)
    page.wait_for_timeout(3000)
    assert len(tails) == stopped, "the hidden trajectory kept polling"
    # Shown again, it resumes; its src was not set again.
    page.click("#tab-trajectory")
    page.wait_for_timeout(1500)
    assert len(tails) > stopped
    assert page.get_attribute("#pane-trajectory", "src") == "/ui/trajectory"
    # The consultation view draws a bar per consultation.
    frame.click("#m-discuss")
    frame.wait_for_selector(".dbar", timeout=WAIT_MS)
    assert frame.locator(".dbar").count() >= 1
    assert errors == []


def test_a_trajectory_that_arrives_after_its_tab_was_left_stays_still(live, page):
    # Left before its page arrived: the page is told it is hidden once it has
    # loaded, so it asks for no tail until it is shown.
    tails = []
    page.on("request", lambda r: tails.append(r.url) if "/ui/trajectory/tail" in r.url else None)
    held = []
    page.route("**/ui/trajectory", lambda route: held.append(route))
    page.click("#tab-trajectory")
    deadline = time.monotonic() + WAIT_MS / 1000
    while not held:
        assert time.monotonic() < deadline, "the trajectory was never asked for"
        page.wait_for_timeout(50)
    page.click("#tab-robots")                         # away before the page has arrived
    for route in held:
        route.continue_()
    page.unroute("**/ui/trajectory")
    frame = page.query_selector("#pane-trajectory").content_frame()
    frame.wait_for_function("() => typeof poSuspend === 'function'", timeout=WAIT_MS)
    page.wait_for_timeout(1500)                       # its first ask, at start-up, lands
    stopped = len(tails)
    page.wait_for_timeout(3000)
    assert page.is_hidden("#pane-trajectory")
    assert len(tails) == stopped, "the hidden trajectory kept polling"
    assert frame.evaluate("suspended") is True
    # Shown, it follows the run again.
    page.click("#tab-trajectory")
    page.wait_for_timeout(1500)
    assert len(tails) > stopped


def test_the_rct_log_tab_says_it_is_not_saving_without_a_recorder(page):
    errors = _errors(page)
    frame = _open_tab(page, "#tab-rcts", "#pane-rcts")
    assert page.get_attribute("#pane-rcts", "src") == "/ui/rcts"
    frame.wait_for_function(
        "() => document.getElementById('note').innerText.includes('not saving RCTs')",
        timeout=WAIT_MS)
    _no_forbidden(frame.evaluate("document.body.innerText"))
    assert errors == []


def test_the_rct_log_tab_lists_a_forced_rct_with_its_cause(recorded, rpage):
    base, runner, folder = recorded
    runner.step(21)
    reading = _force_rct(runner)
    saved = json.loads((folder / "rct" / runner.recorder.name / f"{reading.tick}.json")
                       .read_text(encoding="utf-8"))
    errors = _errors(rpage)
    frame = _open_tab(rpage, "#tab-rcts", "#pane-rcts")
    frame.wait_for_selector("#list tr.rct", timeout=WAIT_MS)
    row = frame.locator("#list tr.rct").first
    assert str(reading.tick) in row.inner_text() and runner.recorder.name in row.inner_text()
    row.click()
    frame.wait_for_selector("#detail .ex-sum", timeout=WAIT_MS)
    assert frame.inner_text("#detail .ex-sum") == saved["explanation"]["summary"]
    assert "cause, as saved at detection" in frame.inner_text("#detail").lower()
    _no_forbidden(frame.evaluate("document.body.innerText"))
    _wait_text(rpage, "#runline", f"tick {runner.last_frame['tick']} ")
    _shot(rpage, "task4-rcts.png")
    # The DK-RMM pane lists this run's RCT under the history strip.
    rpage.click("#tab-dkrmm")
    listed = f'#dk-rcts tr[data-tick="{reading.tick}"]'
    rpage.wait_for_selector(listed, state="attached", timeout=WAIT_MS)
    text = rpage.inner_text(listed)
    with urllib.request.urlopen(base + "/dkrmm/rcts") as response:
        want = json.loads(response.read().decode("utf-8"))["rcts"][0]
    assert str(want["tick"]) in text and want["detected_at"] in text
    assert ", ".join(want["kinds"]) in text and want["status"] in text
    order = rpage.evaluate(
        "() => { const strip = document.getElementById('dk-pane-strip');"
        " const list = document.getElementById('dk-rcts');"
        " return !!(strip.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING); }")
    assert order, "the RCT list is under the history strip"
    assert errors == []


def test_a_reset_rebuilds_the_trajectory_and_leaves_the_rct_log(recorded, rpage):
    _, runner, _ = recorded
    errors = _errors(rpage)
    runner.step(2)
    rcts = _open_tab(rpage, "#tab-rcts", "#pane-rcts")
    rcts.wait_for_selector("#note", timeout=WAIT_MS)
    rcts.evaluate("() => { window.kept = 1; }")
    trajectory = _open_tab(rpage, "#tab-trajectory", "#pane-trajectory")
    trajectory.wait_for_selector("#stream .row", timeout=WAIT_MS)
    trajectory.evaluate("() => { window.kept = 1; }")
    rpage.evaluate("() => { window.kept = 1; }")
    old_run = runner.eco.run_id
    # Reset with the Trajectory showing: it is built again for the new run.
    rpage.click("#reset")
    rpage.wait_for_function(
        "() => (document.getElementById('pane-trajectory').getAttribute('src') || '')"
        ".startsWith('/ui/trajectory?t=')", timeout=WAIT_MS)
    rpage.wait_for_selector("#loading", state="hidden", timeout=WAIT_MS)
    trajectory = rpage.query_selector("#pane-trajectory").content_frame()
    trajectory.wait_for_function("() => typeof DATA === 'object' && !!DATA", timeout=WAIT_MS)
    assert trajectory.evaluate("() => window.kept") is None
    assert trajectory.evaluate("() => DATA.run_id") == runner.eco.run_id != old_run
    # The RCT log spans runs: not reloaded. Nor is the shell.
    assert rpage.get_attribute("#pane-rcts", "src") == "/ui/rcts"
    assert rpage.query_selector("#pane-rcts").content_frame().evaluate("() => window.kept") == 1
    assert rpage.evaluate("() => window.kept") == 1
    # Reset with the Trajectory hidden: dropped, and built when next opened.
    rpage.click("#tab-rcts")
    second = runner.eco.run_id
    rpage.click("#reset")
    rpage.wait_for_function(
        "() => !document.getElementById('pane-trajectory').hasAttribute('src')", timeout=WAIT_MS)
    assert runner.eco.run_id != second
    assert rpage.get_attribute("#pane-rcts", "src") == "/ui/rcts"
    assert rpage.query_selector("#pane-rcts").content_frame().evaluate("() => window.kept") == 1
    trajectory = _open_tab(rpage, "#tab-trajectory", "#pane-trajectory")
    assert rpage.get_attribute("#pane-trajectory", "src") == "/ui/trajectory"
    trajectory.wait_for_function("() => typeof DATA === 'object' && !!DATA", timeout=WAIT_MS)
    assert trajectory.evaluate("() => DATA.run_id") == runner.eco.run_id
    assert errors == []


def test_the_trajectory_says_finished_once_its_run_has_ended(recorded, browser):
    base, runner, _ = recorded
    runner.step(2)
    made = browser.new_page(viewport={"width": 1400, "height": 900})
    try:
        made.goto(base + "/ui/trajectory", wait_until="domcontentloaded")
        made.wait_for_selector(".row", timeout=WAIT_MS)
        assert made.get_attribute("#whose .badge", "class") == "badge now"
        assert made.inner_text("#whose .badge").lower() == "live"
        runner.reset()
        runner.step(2)
        made.wait_for_function(
            "() => document.getElementById('follow').textContent.includes('run ended')",
            timeout=WAIT_MS)
        assert made.get_attribute("#whose .badge", "class") == "badge past"
        assert made.inner_text("#whose .badge").lower() == "finished"
    finally:
        made.close()


# ---------------------------------------------------------- the DK-RMM gate
def _dkrmm_read(page) -> None:
    page.click("#tab-dkrmm")
    page.wait_for_function(
        "(states) => { const el = document.querySelector('#dk-pane-state');"
        " return !!el && states.includes(el.innerText.trim()); }",
        arg=STATES, timeout=WAIT_MS)


def _post(base: str, path: str, body):
    request = urllib.request.Request(base + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_the_gate_records_a_verdict_and_the_pane_shows_it(live, page):
    _, runner, _ = live
    errors = _errors(page)
    _dkrmm_read(page)
    page.wait_for_selector("#dk-validate:not([disabled])", state="attached", timeout=WAIT_MS)
    assert page.input_value("#dk-by") == "operator"
    page.fill("#dk-by", "hind")
    page.fill("#dk-note", "the morning rush")
    page.click("#dk-validate")
    _wait_text(page, "#dk-gate-status", "VALIDATED")
    current = runner.monitor.current.as_dict()
    assert current["status"] == "VALIDATED" and current["decided_by"] == "hind"
    assert current["note"] == "the morning rush"
    result = page.inner_text("#dk-gate-result")
    for value in ("VALIDATED", "hind", "the morning rush", current["decided_at"],
                  f"tick {current['tick']}"):
        assert value in result, value
    meta = page.inner_text("#dk-gate-meta")
    assert "hind" in meta and current["decided_at"] in meta and "the morning rush" in meta
    page.wait_for_selector("#dk-activate:not([disabled])", state="attached", timeout=WAIT_MS)
    assert page.is_disabled("#dk-validate") and page.is_disabled("#dk-dismiss")
    page.click("#dk-activate")
    _wait_text(page, "#dk-gate-status", "ACTIVE")
    assert runner.monitor.current.status.value == "ACTIVE"
    # The next reading is DISCOVERED again; dismiss it.
    runner.step(20)
    page.wait_for_selector("#dk-dismiss:not([disabled])", state="attached", timeout=WAIT_MS)
    page.fill("#dk-note", "a false alarm")
    in_flight = page.evaluate(
        "() => { document.getElementById('dk-dismiss').click();"
        " return ['dk-validate', 'dk-activate', 'dk-dismiss']"
        "   .map((id) => document.getElementById(id).disabled); }")
    assert in_flight == [True, True, True], "the buttons are disabled while the POST is in flight"
    _wait_text(page, "#dk-gate-status", "DISMISSED")
    assert "a false alarm" in page.inner_text("#dk-gate-result")
    assert runner.monitor.current.status.value == "DISMISSED"
    assert runner.monitor.current.note == "a false alarm"
    _no_forbidden(page.evaluate("document.body.innerText"))
    assert errors == []


def test_a_verdict_before_the_first_reading_shows_the_servers_409(recorded, rpage):
    base, runner, _ = recorded
    assert runner.monitor.current is None
    rpage.click("#tab-dkrmm")
    rpage.wait_for_selector("#dk-validate:not([disabled])", state="attached", timeout=WAIT_MS)
    assert rpage.is_disabled("#dk-activate")
    for verdict in ("validate", "dismiss"):
        status, body = _post(base, f"/dkrmm/{verdict}", {"by": "operator", "note": ""})
        assert status == 409
        rpage.click(f"#dk-{verdict}")
        rpage.wait_for_function(
            "(want) => document.getElementById('dk-gate-result').innerText.trim() === want",
            arg=body["detail"], timeout=WAIT_MS)
    assert runner.monitor.current is None
    # The fields are bounded as the server bounds them; a value set past the
    # bound (by script, which maxlength does not stop) is refused with 422, and
    # the page shows the server's message for it.
    assert rpage.get_attribute("#dk-by", "maxlength") == "80"
    assert rpage.get_attribute("#dk-note", "maxlength") == "500"
    status, body = _post(base, "/dkrmm/validate", {"by": "x" * 81, "note": ""})
    assert status == 422
    want = "; ".join(d["msg"] for d in body["detail"])
    rpage.evaluate("() => { document.getElementById('dk-by').value = 'x'.repeat(81); }")
    rpage.click("#dk-validate")
    rpage.wait_for_function(
        "(want) => document.getElementById('dk-gate-result').innerText.trim() === want",
        arg=want, timeout=WAIT_MS)


def test_explain_shows_the_readings_own_summary(live, page):
    base, runner, _ = live
    _consult(runner)
    runner.step(20)              # a reading whose window holds that consultation
    errors = _errors(page)
    _dkrmm_read(page)
    page.wait_for_selector("#dk-explain:not([disabled])", state="attached", timeout=WAIT_MS)
    page.click("#dk-explain")
    page.wait_for_selector("#dk-explain-box .ex-sum", timeout=WAIT_MS)
    tick = int(page.get_attribute("#dk-explain-box", "data-tick"))
    assert tick in [row.tick for row in runner.monitor.history]
    with urllib.request.urlopen(f"{base}/dkrmm/explain?tick={tick}") as response:
        want = json.loads(response.read().decode("utf-8"))
    assert page.inner_text("#dk-explain-box .ex-sum") == want["summary"]
    assert want["kinds"] and want["discussions"], "the window holds trouble and a consultation"
    box = page.inner_text("#dk-explain-box")
    # The RCT log's sentences, from the same fields, in the same words.
    linked = want["linked"]
    for sentence in (
            f"{want['messages']} messages in the window, {want['discussion_messages']}"
            " of them between experts consulting.",
            f"Trouble events linked: {linked.get('strong', 0)} strongly (same task or parcel), "
            f"{linked.get('weak', 0)} only through a shared robot, {linked.get('none', 0)}"
            " to no consultation. A link is evidence, not proof of cause: compare with the same"
            " run with consultations off."):
        assert sentence in box, sentence
    assert "against its baseline" in box.lower()
    assert f"ticks {want['window'][0]}–{want['window'][1]}" in box.lower()
    for kind in want["kinds"]:
        assert f"{kind['kind']} · {kind['count']}" in box
    assert page.locator("#dk-explain-box table.ex-disc tbody tr").count() == len(want["discussions"])
    for d in want["discussions"]:
        assert d["id"] in box
    _shot(page, "task4-dkrmm.png")
    _no_forbidden(page.evaluate("document.body.innerText"))
    assert errors == []


# ------------------------------------------- the shell's own panes across a reset
@pytest.fixture
def modelled(live):
    """
    (base url, runner): a model-mode runner on its own fake Ollama, past its
    first reading and with one consultation (so it has consultations, model
    calls and a reading to explain), served by the same server for one test.
    """
    base, _, _ = live
    fake = FakeOllama()
    fake.script(consultation_script(PEER, decide=_pick_r2))
    with quiet():
        runner = SimulationRunner(settings=fake.settings, tick_seconds=0)
        previous = server.use(runner)
        try:
            runner.eco.start()
            runner.step(21)
            _consult(runner)
            yield base, runner
        finally:
            server.use(previous)
            runner.close()
            fake.stop()


@pytest.fixture
def mpage(modelled, browser):
    base, _ = modelled
    made = browser.new_page(viewport={"width": 1500, "height": 950})
    made.goto(base + "/", wait_until="domcontentloaded")
    made.wait_for_selector("#tab-consultations", state="attached")
    try:
        yield made
    finally:
        made.close()


def _shell(page):
    """What the shell holds of a run: its feed buffer, tables, selection and DK-RMM pane."""
    return page.evaluate(
        "() => ({ run: runId, generation: typeof generation === 'undefined' ? null : generation,"
        "  runs: [...new Set(EVENTS.map((e) => e.run_id))], seqs: EVENTS.map((e) => Number(e.seq)),"
        "  consult: [...document.querySelectorAll('#consult-rows tr')].map((tr) => tr.dataset.id),"
        "  calls: [...document.querySelectorAll('#llm-rows tr')].map((tr) => tr.dataset.id),"
        "  selected: selectedSeq, chained: document.querySelectorAll('#feed-table tr.chain, #feed-table tr.selected').length,"
        "  explain: Object.keys(EXPLAIN), box: document.getElementById('dk-explain-box').innerHTML,"
        "  gate: document.getElementById('dk-gate-result').textContent,"
        "  state: document.getElementById('dk-pane-state').textContent,"
        "  rcts: document.getElementById('dk-rcts').innerText })")


def _the_old_run_everywhere(page, runner) -> None:
    """Every shell pane showing the old run: rows, a selected chain, an explanation, a verdict."""
    page.click("#tab-consultations")
    page.wait_for_selector("#consult-rows tr", state="attached", timeout=WAIT_MS)
    page.wait_for_selector("#llm-rows tr", state="attached", timeout=WAIT_MS)
    _open_feed(page, runner)
    page.locator('#feed-table tr[data-topic="consult_question"]').last.click()
    page.wait_for_selector("#feed-table tr.selected", state="attached", timeout=WAIT_MS)
    page.click("#tab-dkrmm")
    page.wait_for_selector("#dk-explain:not([disabled])", state="attached", timeout=WAIT_MS)
    page.click("#dk-explain")
    page.wait_for_selector("#dk-explain-box .ex-sum", timeout=WAIT_MS)
    page.click("#dk-validate")
    _wait_text(page, "#dk-gate-result", "last decision")


def _only_the_new_run(page, runner) -> None:
    """After a reset: every pane holds the new run and nothing of the old one."""
    total = runner.event_counts()["total"]
    page.wait_for_function("(n) => EVENTS.length >= n", arg=total, timeout=WAIT_MS)
    page.wait_for_timeout(2000)                    # two refresh beats
    state = _shell(page)
    assert state["run"] == runner.eco.run_id
    assert state["runs"] == [runner.eco.run_id]
    # The new run's own low seqs are all there, none dropped as a duplicate.
    assert state["seqs"] == list(range(1, total + 1))
    assert set(state["consult"]) <= {row["id"] for row in runner.consultations(40)}
    assert set(state["calls"]) <= {row["call_id"] for row in runner.llm_calls(40)}
    assert state["selected"] is None and state["chained"] == 0
    assert state["explain"] == [] and state["box"] == "" and state["gate"] == ""
    assert state["state"] == "warming up"
    assert "No RCT detected in this run so far." in state["rcts"]


def _post_reset(base: str, seed: int) -> None:
    request = urllib.request.Request(f"{base}/simulation/reset?seed={seed}", data=b"",
                                     method="POST")
    with urllib.request.urlopen(request) as response:
        assert response.status == 200


def test_a_reset_from_elsewhere_starts_the_shells_own_panes_again(modelled, mpage):
    base, runner = modelled
    page = mpage
    errors = _errors(page)
    refused = []
    page.on("response", lambda r: refused.append((r.status, r.url)) if r.status >= 400 else None)
    _the_old_run_everywhere(page, runner)
    old, old_ids = runner.eco.run_id, {row["id"] for row in runner.consultations(40)}
    _post_reset(base, 7)                         # another tab, or the API
    page.wait_for_function("(old) => runId !== old", arg=old, timeout=WAIT_MS)
    _only_the_new_run(page, runner)
    # A second word of the same run (the heartbeat after the socket) changes nothing.
    generation = _shell(page)["generation"]
    page.evaluate("(id) => restack(id)", runner.eco.run_id)
    assert _shell(page)["generation"] == generation
    # The floor's header follows the new run's seed.
    page.click("#tab-robots")
    floor = page.query_selector("#pane-robots").content_frame()
    floor.wait_for_function(
        "() => document.querySelector('header .sub').textContent.startsWith('seed 7 · ')",
        timeout=WAIT_MS)
    # The new run's own rows arrive, and only they.
    runner.step(21)
    _consult(runner)
    want = {row["id"] for row in runner.consultations(40)}
    assert want
    page.click("#tab-consultations")
    page.wait_for_function(
        "(n) => document.querySelectorAll('#consult-rows tr').length >= n",
        arg=len(want), timeout=WAIT_MS)
    page.wait_for_timeout(1600)
    shown = set(_shell(page)["consult"])
    assert shown == want, (shown, want, old_ids)
    # While the reset swaps the monitor, a DK-RMM read can find none and is
    # answered 503 ("no runtime monitor"), which the browser logs; nothing
    # else may fail.
    assert all(status == 503 and "/dkrmm/" in url for status, url in refused), refused
    assert [e for e in errors if "status of 503" not in e] == []


def test_answers_held_across_a_reset_never_reach_the_new_run(modelled, mpage):
    base, runner = modelled
    page = mpage
    _the_old_run_everywhere(page, runner)
    page.click("#dk-explain")                    # closed, and asked again below
    page.wait_for_function("() => document.getElementById('dk-explain-box').innerHTML === ''",
                           timeout=WAIT_MS)
    page.evaluate("() => { for (const key of Object.keys(EXPLAIN)) delete EXPLAIN[key]; }")
    # Answers computed for the old run and delivered only after the reset:
    # the feed's pages, the consultation table and an explanation.
    held, holding = [], {"on": True}
    asked = re.compile(r"/(consultations|events|dkrmm/explain)\?")

    def hold(route):
        if holding["on"]:
            held.append((route.request.url, route, route.fetch()))
        else:
            route.continue_()

    page.route(asked, hold)
    old_total = runner.event_counts()["total"]
    page.click("#dk-explain")
    page.evaluate("(n) => { backfill(n, 0); }", old_total)   # the old run's seqs from 1
    deadline = time.monotonic() + WAIT_MS / 1000
    while not all(any(k in url for url, _, _ in held)
                  for k in ("/consultations?", "/events?", "/dkrmm/explain?")):
        assert time.monotonic() < deadline, [url for url, _, _ in held]
        page.wait_for_timeout(100)
    old = runner.eco.run_id
    # The DK-RMM pane's reads are held too: until the new run's first answer is
    # painted, the pane shows no reading and its gate decides nothing (the
    # old reading, validated above, would otherwise leave Activate armed).
    dk_reads = re.compile(r"/dkrmm/(state|series|indicators|rcts)(\?|$)")
    page.route(dk_reads, hold)
    with quiet():
        runner.reset(seed=3)
    page.wait_for_function("(old) => runId !== old", arg=old, timeout=WAIT_MS)
    page.wait_for_timeout(500)                     # a held DK-RMM poll of the new run
    pane = page.evaluate(
        "() => ({ current: CURRENT, state: document.getElementById('dk-pane-state').textContent,"
        "  strip: document.getElementById('dk-pane-strip').children.length,"
        "  indicators: document.querySelectorAll('#dk-pane-indicators tr').length,"
        "  disabled: ['dk-validate', 'dk-activate', 'dk-dismiss', 'dk-explain']"
        "    .map((id) => document.getElementById(id).disabled) })")
    assert pane == {"current": None, "state": "warming up", "strip": 0, "indicators": 0,
                    "disabled": [True, True, True, True]}, pane
    holding["on"] = False
    for _, route, response in held:
        route.fulfill(response=response)
    page.unroute(dk_reads)
    # The new run's first answer re-arms the gate (no reading yet: the server's
    # 409 says why there is nothing to decide).
    page.wait_for_selector("#dk-validate:not([disabled])", state="attached", timeout=WAIT_MS)
    _only_the_new_run(page, runner)
    # The new run's own reading is explained from the new run, not the old cache.
    runner.step(21)
    page.wait_for_function(
        "(states) => states.includes(document.getElementById('dk-pane-state').innerText.trim())",
        arg=STATES, timeout=WAIT_MS)
    page.click("#dk-explain")
    page.wait_for_selector("#dk-explain-box .ex-sum", timeout=WAIT_MS)
    tick = int(page.get_attribute("#dk-explain-box", "data-tick"))
    with urllib.request.urlopen(f"{base}/dkrmm/explain?tick={tick}") as response:
        want = json.loads(response.read().decode("utf-8"))
    assert page.inner_text("#dk-explain-box .ex-sum") == want["summary"]
    assert _shell(page)["explain"] == [f"{runner.eco.run_id}|{tick}"]
    page.unroute(asked)
