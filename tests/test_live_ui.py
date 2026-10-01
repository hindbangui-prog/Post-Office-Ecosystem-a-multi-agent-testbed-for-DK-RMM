"""
The live page in a headless browser (spec 16), served by uvicorn on a free port.

The runner's experts are on the fake Ollama. After a scripted consultation
(SCHEDULING asks ROUTING about two robots the walk cannot separate, and decides
R2) the Consultations pane shows the peer's words and `DECISION: R2`; the
Ollama pane shows the served model; the DK-RMM pane shows a state; and no text
on the page names a removed scenario family.

Needs the `ui-test` extra (`pip install -e ".[ui-test]"`) and a Chromium for
Playwright; without Playwright the module is skipped.
"""

from __future__ import annotations

import re
import threading
import time

import pytest

pytest.importorskip("playwright", reason="the live UI test needs the ui-test extra")
from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from post_office.api import server  # noqa: E402
from post_office.api.runner import SimulationRunner  # noqa: E402
from post_office.crew.console import quiet  # noqa: E402
from post_office.dkrmm import OperationalState  # noqa: E402
from tests.consult_helpers import ask, equally_placed  # noqa: E402
from tests.fake_ollama import FakeOllama, consultation_script  # noqa: E402

FORBIDDEN = ("attack", "perturb", "stress", "inject", "experiment", "autodk", "openrt")
PEER = "R2: corridor clear, the shorter walk from the sorting belt."
STATES = [s.value for s in OperationalState]
WAIT_MS = 20000


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
    assert options == ["NORMAL · CrewAI · Ollama/qwen3:8b · DK-RMM"]
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


def test_the_dkrmm_pane_shows_a_state_and_the_twelve_indicators(page):
    page.click("#tab-dkrmm")
    page.wait_for_function(
        "(states) => { const el = document.querySelector('#dk-pane-state');"
        " return !!el && states.includes(el.innerText.trim()); }",
        arg=STATES, timeout=WAIT_MS)
    assert page.locator("#pane-dkrmm .indicator").count() == 12
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
    for tab in ("#tab-robots", "#tab-consultations", "#tab-llm", "#tab-dkrmm"):
        page.click(tab)
        _no_forbidden(page.evaluate("document.body.innerText"))
    import urllib.request

    with urllib.request.urlopen(base + "/") as response:
        _no_forbidden(response.read().decode("utf-8"))
