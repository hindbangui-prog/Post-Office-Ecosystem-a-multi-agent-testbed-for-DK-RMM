"""
The live model deadline is real time, whatever the speed.

At a fixed number of ticks the deadline shrank with the speed: 120 ticks were
2 minutes at the page's 1x (a second a tick) but under a second at 128x
(7.8 ms a tick), and every model answer came too late. Now `LIVE_LLM_DEADLINE_S` of wall clock is converted to ticks at the
current speed, and again when the speed changes.
"""

from post_office.api.runner import LIVE_LLM_DEADLINE_S, SimulationRunner, live_deadline_ticks


def test_the_same_seconds_at_every_speed():
    for speed in (1, 4, 16, 32, 128, 512):             # the page's speeds: 1x is 1 s a tick
        tick_s = 1.0 / speed
        ticks = live_deadline_ticks(tick_s)
        assert abs(ticks * tick_s - LIVE_LLM_DEADLINE_S) < tick_s + 1e-9
    assert live_deadline_ticks(1.0 / 128) == 7680                # 60 s at 7.8 ms a tick (128x)
    assert live_deadline_ticks(0) == live_deadline_ticks(1.0 / 512)       # unpaced: the fastest speed


def test_a_change_of_speed_reconverts_the_deadline():
    r = SimulationRunner(tick_seconds=0.25)            # rules only: the switch still applies
    try:
        r._live_decisions(True)
        agent = r.eco.experts["SCHEDULING"]
        assert agent.async_decisions and agent.llm_deadline_ticks == live_deadline_ticks(0.25)
        r.tick_seconds = 1.0 / 128                     # 128x, what POST /simulation/speed does
        r._refresh_live_deadline()
        assert agent.llm_deadline_ticks == live_deadline_ticks(1.0 / 128)
        assert agent.llm_deadline_ticks * r.tick_seconds >= LIVE_LLM_DEADLINE_S - 1e-9
        r._live_decisions(False)                       # a step by hand: the tick waits, as before
        r.tick_seconds = 0.25
        r._refresh_live_deadline()
        assert not agent.async_decisions
    finally:
        r.close()
