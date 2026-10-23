"""
The overdue backlog (2026-10-21), DK-RMM's 21st indicator.

Definition: the number of accepted parcels, across all priority classes and
processing stages, whose expected departure time has passed but that have not
yet been dispatched. A parcel is accepted when the intake gate gives it a
promised departure (`due_by`); a dispatched parcel leaves `env.parcels`.

What is checked: its place in the registry (base, direction up) and in the
backlog evidence kind; the snapshot's count at every stage (on the floor in any
zone, on a robot) and its exclusions (no promise, promise not yet passed, at the
promise tick itself); the indicator read off the snapshot, not evaluable without
one; and the monitor scoring it against its own baseline like every other
indicator, the rise feeding the backlog kind.
"""

from __future__ import annotations

import pytest

from post_office.dkrmm import monitor as mon
from post_office.dkrmm.indicators import (BASE_INDICATORS, INDICATOR_META, INDICATOR_NAMES,
                                          compute_indicators)
from post_office.dkrmm.monitor import DKRMM
from post_office.dkrmm.operations import snapshot_state
from tests.test_dkrmm_operational import StateEco, parcel


def promised(zone: str, due_by: int, carried: bool = False):
    """An accepted parcel: one the intake gate gave a promised departure."""
    p = parcel(zone, carried=carried)
    p.due_by = due_by
    return p


def test_it_is_the_twenty_first_indicator_and_feeds_the_backlog_kind():
    assert len(INDICATOR_NAMES) == 21 and INDICATOR_NAMES[-1] == "overdue_backlog"
    meta = INDICATOR_META["overdue_backlog"]
    assert meta["kind"] == "base" and meta["direction"] == "up" and meta["about"]
    assert "overdue_backlog" in BASE_INDICATORS
    assert mon.EVIDENCE["backlog"] == ("backlog_growth", "overdue_backlog")
    assert "backlog" in mon.OPERATIONAL_KINDS
    assert sum(name == "overdue_backlog" for names in mon.EVIDENCE.values() for name in names) == 1


def test_the_snapshot_counts_accepted_parcels_past_their_promise_at_every_stage():
    eco = StateEco(parcels={
        "P1": promised("INTAKE", 100),                   # past its promise
        "P2": promised("SORTING", 150),                  # past
        "P3": promised("DISPATCH", 120),                 # at the door, not yet on a van that left: past
        "P4": promised("SORTING", 90, carried=True),     # on a robot: past
        "P5": promised("INTAKE", 200),                   # promise still ahead
        "P6": promised("TEMPORARY_STORAGE", 160),        # at its promise tick: not yet late
        "P7": parcel("INTAKE"),                          # never accepted: no promise
    })
    eco.world.tick = 160
    assert snapshot_state(eco)["overdue_backlog"] == 4
    eco.world.tick = 161
    assert snapshot_state(eco)["overdue_backlog"] == 5    # P6 is now late
    eco.world.tick = 99
    assert snapshot_state(eco)["overdue_backlog"] == 1    # only P4
    del eco.env.parcels["P4"]                              # dispatched: it has left the building
    assert snapshot_state(eco)["overdue_backlog"] == 0


def test_the_indicator_is_read_off_the_snapshot_and_not_evaluable_without_one():
    w = compute_indicators([], ticks=20, roster=4, snapshot={"overdue_backlog": 3})
    assert w.overdue_backlog == 3.0 and w.evaluable["overdue_backlog"] is True
    assert w.detail["overdue"] == {"parcels": 3}
    assert w.values()["overdue_backlog"] == 3.0
    none = compute_indicators([], ticks=20, roster=4, snapshot={})
    assert none.overdue_backlog == 0.0 and none.evaluable["overdue_backlog"] is False


def test_the_monitor_scores_it_against_its_own_baseline_and_a_rise_is_backlog_evidence():
    # Three accepted parcels, all with their promise far ahead: nothing overdue,
    # and the number of parcels inside never changes, so backlog growth stays 0.
    eco = StateEco(parcels={f"P{i}": promised("SORTING", 10_000) for i in range(1, 4)})
    m = DKRMM(eco).attach()
    for i in range(6):                                     # six readings: a flat baseline at 0
        eco.world.tick = 1 + 20 * i
        a = m.assess(eco.world.tick)
        assert a.indicators.overdue_backlog == 0.0 and a.evaluable["overdue_backlog"] is True
    eco.env.parcels["P2"].due_by = 50                      # two promises missed
    eco.env.parcels["P3"].due_by = 60
    eco.world.tick = 121
    a = m.assess(121)
    assert a.indicators.overdue_backlog == 2.0
    assert a.baseline["overdue_backlog"] == pytest.approx(0.0)
    assert a.z["overdue_backlog"] == 3.0                   # a flat baseline that moved (signals.zscore)
    assert a.z["backlog_growth"] == 0.0                    # the stock did not change
    assert a.deviation["overdue_backlog"] == "up"
    assert "backlog" in a.kinds and a.in_evidence["overdue_backlog"] == "backlog"
