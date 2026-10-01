"""
The line at the top of the window: what the monitor makes of the run.

The digest is small, but it is what a reader glances at, so the properties that
keep it honest are worth holding: a state is never implied by absence, and a
monitor that throws never takes the page or the run with it.

Carried from the source with the functions about the removed disturbance digest
deleted (see docs/provenance_trimmed_tests.md).
"""

from pathlib import Path

from post_office.api.digest import monitor_digest
from post_office.config.settings import config
from post_office.simulation import build

LIVE = Path(__file__).resolve().parent.parent / "post_office" / "ui" / "live.html"


# --------------------------------------------------------------- the monitor

def test_no_monitor_says_so_rather_than_going_quiet():
    # A strip that simply vanished would read as STABLE at a glance, and not
    # being watched is a different thing from being watched and found ordinary.
    digest = monitor_digest(None)
    assert digest["attached"] is False
    assert "state" not in digest


def test_a_monitor_that_throws_does_not_take_the_run_with_it():
    class Broken:
        def state(self):
            raise RuntimeError("no")

    assert monitor_digest(Broken())["attached"] is False


def test_the_digest_carries_what_a_state_rests_on():
    from post_office.dkrmm import DKRMM

    eco = build(seed=5, config=config("default"), run_id="digest-monitor")
    monitor = DKRMM(eco).attach()
    eco.start()
    for _ in range(80):
        eco.step()
        monitor.tick()

    digest = monitor_digest(monitor)
    assert digest["attached"] is True
    # The cadence, so a reader can tell "no reading yet" from "read and quiet".
    assert digest["every"] and digest["window"] and digest["baseline"]
    assert digest["assessments"] >= 1
    assert digest["tick"] is not None
    assert digest["next_at"] == digest["tick"] + digest["every"]
    # Whether the window held enough to read at all is part of the reading.
    assert "enough_activity" in digest


# ------------------------------------------------------------------- the app

def test_the_shell_paints_the_verdict_from_the_summary():
    page = LIVE.read_text(encoding="utf-8")
    assert "paintVerdict(s.dkrmm)" in page


def test_the_shell_distinguishes_unwatched_from_stable():
    page = LIVE.read_text(encoding="utf-8")
    assert "not attached" in page
    assert "no monitor on this run" in page


def test_the_shell_has_a_colour_for_every_state():
    from post_office.dkrmm.states import OperationalState

    page = LIVE.read_text(encoding="utf-8")
    for state in OperationalState:
        assert f".st.s-{state.value}" in page, state.value


def test_the_summary_endpoint_offers_the_monitor_digest():
    server = (Path(__file__).resolve().parent.parent / "post_office" / "api"
              / "server.py").read_text(encoding="utf-8")
    assert '"dkrmm": monitor_digest(' in server
