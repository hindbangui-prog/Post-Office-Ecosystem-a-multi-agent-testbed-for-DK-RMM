"""
DK on the live page (2026-10-13): an RCT reading whose dragon-king test held
is shown as DK; an RCT reached by critical slowing down alone stays RCT. A
study run reads STABLE, DEVIATING, UNSTABLE, RCT or DK; Normal keeps its five
monitor states with RCT split the same way. The view is the page's: DK-RMM,
its history and its record are untouched (the monitor still says RCT).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from post_office.dkrmm import OperationalState
from post_office.dkrmm.monitor import Assessment
from post_office.dkrmm.signals import DragonKing
from post_office.stress.states import (DK_STATE, FOUR_STATES, STUDY_STATES, dk_state,
                                       four_state, study_state, study_state_counts)

LIVE_HTML = (__import__("pathlib").Path(__file__).resolve().parent.parent
             / "post_office" / "ui" / "live.html")


def reading(tick, state, dragon=False):
    return Assessment(tick=tick, state=OperationalState(state),
                      dragon=DragonKing(is_dragon=dragon))


# ------------------------------------------------------------------ the words
def test_dk_is_an_rct_whose_dragon_king_test_held_and_nothing_else():
    assert STUDY_STATES == FOUR_STATES + ("DK",) and DK_STATE == "DK"
    assert dk_state("RCT", True) == "DK"
    assert dk_state("RCT", False) == "RCT"
    for word in ("STABLE", "DEVIATING", "UNSTABLE", "RECOVERY"):
        assert dk_state(word, True) == word          # the test alone is not a state
    assert dk_state(OperationalState.RCT, True) == "DK"
    assert dk_state(None, True) is None
    assert study_state("RECOVERY", True) == "STABLE"
    assert study_state("RCT", True) == "DK" and study_state("RCT") == "RCT"
    # The four-state view the measurement and results keep is unchanged.
    assert four_state("RCT") == "RCT" and four_state("RECOVERY") == "STABLE"
    assert study_state_counts(["STABLE", "DK", "RCT", "DK"]) == {
        "STABLE": 1, "DEVIATING": 0, "UNSTABLE": 0, "RCT": 1, "DK": 2}


# ---------------------------------------------------------- the study strip
def test_the_runners_study_block_shows_dk_and_keeps_the_monitors_word():
    from post_office.api.runner import SimulationRunner

    history = [reading(20, "STABLE"), reading(40, "UNSTABLE", dragon=True),
               reading(60, "RCT"), reading(80, "RCT", dragon=True),
               reading(100, "RECOVERY"), reading(120, "RCT", dragon=True)]
    runner = SimulationRunner.__new__(SimulationRunner)
    runner.monitor = SimpleNamespace(history=history)
    block = SimulationRunner._dkrmm_block(runner)
    assert [w for _, w in block["sequence"]] == ["STABLE", "UNSTABLE", "RCT", "DK",
                                                 "STABLE", "DK"]
    assert block["state"] == "DK" and block["raw_state"] == "RCT"
    assert block["counts"] == {"STABLE": 2, "DEVIATING": 0, "UNSTABLE": 1, "RCT": 1, "DK": 2}
    # Every reading the monitor called RCT is still an RCT tick; DK ones also listed apart.
    assert block["rct_ticks"] == [60, 80, 120] and block["first_rct_tick"] == 60
    assert block["dk_ticks"] == [80, 120] and block["first_dk_tick"] == 80
    assert block["states"] == list(STUDY_STATES)
    # The monitor's history is as it was.
    assert [a.state.value for a in history] == ["STABLE", "UNSTABLE", "RCT", "RCT",
                                                "RECOVERY", "RCT"]


# ------------------------------------------- the digest, the API, the pane
@pytest.fixture
def served(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="the API is optional")
    from fastapi.testclient import TestClient

    from post_office.api import server
    from post_office.api.runner import SimulationRunner

    monkeypatch.chdir(tmp_path)
    runner = SimulationRunner(rules_only=True, tick_seconds=0, preset="ms-drop", seed=11)
    previous = server.use(runner)
    client = TestClient(server.app)
    client.__enter__()
    try:
        runner.eco.start()
        runner.step(81)                       # five readings: 1, 21, 41, 61, 81
        yield client, runner
    finally:
        client.__exit__(None, None, None)
        server.use(previous)
        runner.close()


def _make(history, index, state, dragon):
    history[index].state = OperationalState(state)
    history[index].dragon = DragonKing(is_dragon=dragon)


def test_the_api_carries_the_dragon_king_test_of_each_reading(served):
    client, runner = served
    history = runner.monitor.history
    assert len(history) == 5
    _make(history, 2, "RCT", False)           # reached by slowing down
    _make(history, 3, "RCT", True)            # reached by the dragon-king test
    _make(history, 4, "RCT", True)
    runner.monitor.current = history[-1]
    series = client.get("/dkrmm/series").json()
    assert series["states"][-3:] == ["RCT", "RCT", "RCT"]          # the monitor's words
    assert series["dragon"][-3:] == [False, True, True]
    assert len(series["dragon"]) == len(series["ticks"])
    rcts = client.get("/dkrmm/rcts").json()["rcts"]
    assert [(r["tick"], r["dragon"]) for r in rcts] == [(81, True), (61, True), (41, False)]
    summary = client.get("/summary").json()
    digest = summary["dkrmm"]
    assert digest["state"] == "RCT" and digest["dragon"] is True
    assert digest["previous_dragon"] is True and digest["dk_readings"] == 2
    dk = summary["study"]["dkrmm"]
    assert dk["state"] == "DK" and dk["dk_ticks"] == [61, 81]
    assert [w for _, w in dk["sequence"]][-3:] == ["RCT", "DK", "DK"]


def test_the_pane_paints_dk_on_a_study_run_and_on_normal(served):
    from post_office.ui.live import dkrmm_html

    _, runner = served
    history = runner.monitor.history
    _make(history, 3, "RCT", False)
    _make(history, 4, "RCT", True)
    runner.monitor.current = history[-1]
    for preset in ("ms-drop", "default"):
        html = dkrmm_html(SimpleNamespace(monitor=runner.monitor, preset=preset))
        assert 'class="st s-DK" id="dk-pane-state">DK<' in html
        strip = html.split('id="dk-pane-strip">', 1)[1].split("</div>", 1)[0]
        assert strip.count('class="s-DK"') == 1 and strip.count('class="s-RCT"') == 1
    _make(history, 4, "RCT", False)
    html = dkrmm_html(SimpleNamespace(monitor=runner.monitor, preset="ms-drop"))
    assert 'class="st s-RCT" id="dk-pane-state">RCT<' in html and "s-DK" not in html.split(
        'id="dk-pane-strip">', 1)[1].split("</div>", 1)[0]


def test_the_page_maps_dk_in_every_painter():
    page = LIVE_HTML.read_text(encoding="utf-8")
    assert 'const asDk = (state, dragon) => (state === "RCT" && dragon ? "DK" : state);' in page
    assert "dkState(dk.state, dk.dragon)" in page                      # the verdict pill
    assert "dkState(cur.state, (cur.dragon || {}).is_dragon)" in page  # the pane's pill
    assert "(series.dragon || [])[i]" in page                          # the pane's strip
    assert "dk.dk_ticks" in page                                       # the study strip's line
    assert ".st.s-DK" in page and ".c2n .seq .s-DK" in page and ".strip .s-DK" in page
    key = page.split('id="c2n-key"', 1)[1].split("</span>", 1)[0]
    assert [w for w in ("STABLE", "DEVIATING", "UNSTABLE", "RCT", "DK") if f">{w}</i>" in key] \
        == ["STABLE", "DEVIATING", "UNSTABLE", "RCT", "DK"]
