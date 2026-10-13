"""
`backlog_level_deviation` (2026-10-13; docs/dkrmm-mathematics.md, section 22).

How much of the headroom between a zone's normal parcel level and its
capacity is in use now, e_z = (L_z - B_z) / (C_z - B_z), the largest over the
zones with a capacity. One test per case of the brief, on the small fake
ecosystem of tests/test_dkrmm_operational.py: no simulation runs, every input
is written out and every expected number is worked out by hand.
"""

from __future__ import annotations

import json
from statistics import median
from types import SimpleNamespace

import pytest

from post_office.api.digest import indicator_rows, monitor_digest
from post_office.dkrmm import monitor as mon
from post_office.dkrmm.indicators import (DERIVED_INDICATORS, INDICATOR_META,
                                          INDICATOR_NAMES, compute_indicators)
from post_office.dkrmm.monitor import DKRMM
from post_office.dkrmm.states import OperationalState
from tests.test_dkrmm_operational import StateEco, ev, parcel

NAME = "backlog_level_deviation"


# ------------------------------------------------------------------ helpers
def fill(eco, **zones):
    """Put exactly these parcels in the building: zone name -> count."""
    eco.env.parcels.clear()
    n = 0
    for zone, count in zones.items():
        for _ in range(count):
            n += 1
            eco.env.parcels[f"P{n}"] = (parcel("INTAKE", carried=True)
                                        if zone == "carried" else parcel(zone))


def assess(m, eco, tick, events=(), **zones):
    """One assessment at `tick` with the building holding `zones`."""
    fill(eco, **zones)
    for event in events:
        m.observe(event)
    return m.assess(tick)


def talk(tick, dropped=False):
    """Five messages sent in the 20 ticks before `tick`, all dropped if asked."""
    sent = [ev(tick - k, "message", "A0", "A1") for k in range(5)]
    lost = [ev(tick - k, "message_dropped", "A0", "A1") for k in range(5)] if dropped else []
    return sent + lost


def normal(m, eco, intake=(4, 5, 4, 3, 4, 5, 4, 3), storage=(1, 0, 1, 2, 1, 0, 1, 1),
           sorting=2, dispatch=3):
    """A run of ordinary assessments every 20 ticks, ending at tick 20 * len."""
    out = []
    for i, (n_in, n_st) in enumerate(zip(intake, storage)):
        tick = 20 * (i + 1)
        out.append(assess(m, eco, tick, talk(tick), INTAKE=n_in, TEMPORARY_STORAGE=n_st,
                          SORTING=sorting, DISPATCH=dispatch))
    return out


def dropped(m, eco, tick, extra=(), **zones):
    """An assessment in which every message was dropped, as under M-S-DROP."""
    return assess(m, eco, tick, talk(tick, dropped=True) + list(extra), **zones)


def fault(m, eco, intake, start=180, extra=lambda tick: ()):
    """
    M-S-DROP in miniature, after `normal`: every message dropped from
    `start`, the intake at each listed level in turn (first at its normal 4,
    then filling), the other zones where they were.
    """
    return [dropped(m, eco, start + 20 * k, extra(start + 20 * k), INTAKE=level,
                    TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
            for k, level in enumerate(intake)]


@pytest.fixture
def eco():
    # Dock cap 26 (max_on_dock), 20 shelves (storage capacity).
    return StateEco(max_on_dock=26, storage=(0, 20))


@pytest.fixture
def m(eco):
    # A baseline of eight readings, so the eight ordinary ones of `normal`
    # form it; everything else as in the monitor (EVERY, WINDOW, thresholds).
    return DKRMM(eco, baseline=8).attach()


# ------------------------------------------------------------ the registry
def test_registered_as_a_derived_up_indicator_in_the_backlog_kind():
    assert NAME in INDICATOR_NAMES and INDICATOR_NAMES[-1] == NAME
    assert len(INDICATOR_NAMES) == 21
    assert NAME in DERIVED_INDICATORS
    assert INDICATOR_META[NAME]["direction"] == "up"
    assert INDICATOR_META[NAME]["about"] == (
        "current unfinished-parcel backlog by zone relative to its normal "
        "baseline and available capacity; sustained elevation remains a "
        "signal even when backlog growth returns to zero")
    assert mon.EVIDENCE["backlog"] == ("backlog_growth", NAME)
    assert "backlog" in mon.OPERATIONAL_KINDS
    # It adds no kind: the kinds the rules count are the twelve they were.
    assert len(mon.EVIDENCE) == 12


def test_compute_indicators_leaves_it_to_the_monitor():
    w = compute_indicators([], ticks=20, roster=4, snapshot={"by_zone": {"INTAKE": 26}})
    assert w.evaluable[NAME] is False and w.backlog_level_deviation == 0.0


# --------------------------------------------- 1. a low backlog near normal
def test_a_backlog_at_its_normal_level_reads_near_zero(m, eco):
    normal(m, eco)
    a = assess(m, eco, 180, INTAKE=4, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    zones = a.indicators.detail["backlog_level"]["zones"]
    # INTAKE: the median of 4,5,4,3,4,5,4,3 is 4; (4 - 4) / (26 - 4) = 0.
    assert zones["INTAKE"]["baseline"] == 4.0
    assert zones["INTAKE"]["headroom_used"] == 0.0
    # TEMPORARY_STORAGE: the median of 1,0,1,2,1,0,1,1 is 1; (1 - 1) / 19 = 0.
    assert zones["TEMPORARY_STORAGE"]["headroom_used"] == 0.0
    assert a.evaluable[NAME] and a.indicators.backlog_level_deviation == 0.0
    assert a.deviation[NAME] == "none" and a.in_evidence[NAME] is None


# ------------------------------------------------------ 2. a growing backlog
def test_a_growing_intake_rises_and_counts_as_backlog_evidence(m, eco):
    normal(m, eco)
    values = []
    for k, n_in in enumerate((10, 16, 22)):
        a = assess(m, eco, 180 + 20 * k, INTAKE=n_in, TEMPORARY_STORAGE=1,
                   SORTING=2, DISPATCH=3)
        values.append(a.indicators.backlog_level_deviation)
    # (10-4)/22, (16-4)/22, (22-4)/22: the baseline does not learn from a
    # window called UNSTABLE or RCT on operational evidence, and these are
    # at most DEVIATING here, so check the first two by hand only.
    assert values[0] == pytest.approx(6 / 22)
    assert values[0] < values[1] < values[2]
    assert a.deviation[NAME] == "up" and a.in_evidence[NAME] == "backlog"
    assert a.indicators.backlog_growth > 0


# ---------------------------- 3. a persistently elevated backlog, no growth
def test_an_elevated_backlog_that_stops_growing_stays_a_signal(m, eco):
    """
    The messages are lost, the intake fills from 4 to 20 and stays there.
    Growth is 0 once it stops rising; the level is not. Those windows are
    UNSTABLE or RCT on operational evidence, so by the existing learning rule
    (H') nothing elevated enters a baseline and the reading holds.
    """
    normal(m, eco)
    rows = fault(m, eco, [4, 4, 4, 8, 12, 16, 20, 20, 20, 20, 20, 20])
    rising, plateau = rows[3:7], rows[7:]
    assert [r.indicators.backlog_level_deviation for r in rising] == pytest.approx(
        [4 / 22, 8 / 22, 12 / 22, 16 / 22])
    assert all(r.indicators.backlog_growth > 0 for r in rising)
    assert all(r.indicators.backlog_growth == 0.0 for r in plateau)
    assert all(r.deviation["backlog_growth"] == "none" for r in plateau)
    assert all(r.indicators.backlog_level_deviation == pytest.approx(16 / 22)
               for r in plateau)
    assert all(r.deviation[NAME] == "up" and r.in_evidence[NAME] == "backlog"
               for r in rising + plateau)
    assert all("backlog" in r.kinds for r in plateau)
    assert all(r.state in (OperationalState.UNSTABLE, OperationalState.RCT)
               for r in plateau)
    # The z holds too: the baseline it is read against stopped learning.
    assert len({round(r.z[NAME], 6) for r in plateau}) == 1
    assert list(m._levels["INTAKE"])[-3:] == [4.0, 4.0, 4.0]


def test_on_a_plateau_with_no_other_evidence_the_existing_baseline_rule_absorbs_it(m, eco):
    """
    The same jump to 20 with every message delivered: backlog is the only
    kind, so the windows are DEVIATING, and DEVIATING windows teach the
    baselines (BASELINE_LEARNS_FROM, unchanged). Once more than half of the
    zone's past levels are the plateau its median is the plateau, and the
    level reads as normal again. Recorded as the behaviour of the unchanged
    learning rule, not of this indicator: with the monitor's own baseline of
    24 readings the median is the plateau after 13 of them, 260 ticks.
    """
    normal(m, eco)
    rows = [assess(m, eco, 180 + 20 * k, talk(180 + 20 * k), INTAKE=20,
                   TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3) for k in range(8)]
    assert rows[0].deviation[NAME] == "up" and rows[0].state is OperationalState.DEVIATING
    assert rows[0].indicators.backlog_level_deviation == pytest.approx(16 / 22)
    assert all("delivery" not in r.kinds for r in rows)
    assert list(m._levels["INTAKE"]) == [20.0] * 8
    assert rows[-1].indicators.detail["backlog_level"]["zones"]["INTAKE"]["baseline"] == 20.0
    assert rows[-1].indicators.backlog_level_deviation == 0.0
    assert rows[-1].deviation[NAME] == "none"


# --------------------------- 4. a full dock refusing arrivals, held at cap
def test_a_full_dock_refusing_arrivals_reads_one_with_growth_at_zero(m, eco):
    normal(m, eco)
    full = [4, 4, 4, 10, 16, 22, 26, 26, 26, 26, 26, 26]
    refusals = lambda tick: ([ev(tick - 5, "arrival_refused", "GENERATOR")]
                             if tick >= 180 + 20 * 6 else [])
    rows = fault(m, eco, full, extra=refusals)
    held = rows[7:]
    for a in rows[6:]:
        intake = a.indicators.detail["backlog_level"]["zones"]["INTAKE"]
        assert intake["level"] == 26.0 and intake["capacity"] == 26.0
        assert intake["at_capacity"] is True
        assert intake["baseline"] == 4.0
        assert intake["headroom_used"] == pytest.approx(1.0)      # (26-4)/(26-4)
        assert a.indicators.backlog_level_deviation == pytest.approx(1.0)
        assert a.deviation[NAME] == "up" and "backlog" in a.kinds
    for a in held:
        assert a.indicators.backlog_growth == 0.0
        assert a.deviation["backlog_growth"] == "none"
        assert a.indicators.counts["arrivals_refused"] >= 1
    # The dock fills the saturation category too, as before; untouched here.
    assert held[-1].indicators.detail["resources"]["dock"]["value"] == 1.0


# ------------------------------------------- 5. different levels by zone
def test_each_zone_is_measured_apart_and_the_value_is_the_fullest(m, eco):
    normal(m, eco)
    a = assess(m, eco, 180, INTAKE=10, TEMPORARY_STORAGE=11, SORTING=6,
               DISPATCH=3, carried=2)
    detail = a.indicators.detail["backlog_level"]
    zones = detail["zones"]
    assert zones["INTAKE"]["headroom_used"] == pytest.approx((10 - 4) / 22)
    assert zones["TEMPORARY_STORAGE"]["headroom_used"] == pytest.approx((11 - 1) / 19)
    assert detail["zone"] == "TEMPORARY_STORAGE"
    assert a.indicators.backlog_level_deviation == pytest.approx(10 / 19)
    # Sorting and dispatch have no declared capacity: evidence, not value.
    assert zones["SORTING"]["capacity"] is None
    assert zones["SORTING"]["headroom_used"] is None
    assert zones["SORTING"]["ratio_to_baseline"] == pytest.approx(6 / 2)
    assert zones["SORTING"]["note"] == "no capacity declared; evidence only"
    assert zones["DISPATCH"]["ratio_to_baseline"] == pytest.approx(1.0)
    # The total counts every parcel once, the two on robots included.
    assert zones["TOTAL"]["level"] == 10 + 11 + 6 + 3 + 2
    assert zones["TOTAL"]["level"] == a.snapshot["backlog"]
    assert sum(a.snapshot["by_zone"].values()) == a.snapshot["backlog"]
    assert zones["TOTAL"]["headroom_used"] is None


def test_a_parcel_that_has_left_is_not_in_any_count(m, eco):
    normal(m, eco)
    a = assess(m, eco, 180, INTAKE=4, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    before = a.indicators.detail["backlog_level"]["zones"]["TOTAL"]["level"]
    # One parcel loaded and gone: it is no longer in env.parcels.
    b = assess(m, eco, 200, INTAKE=4, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=2)
    assert b.indicators.detail["backlog_level"]["zones"]["TOTAL"]["level"] == before - 1
    assert b.indicators.detail["backlog_level"]["zones"]["DISPATCH"]["level"] == 2


# ------------- 6. empty queues, zero baselines, capacity and data unavailable
def test_empty_queues_are_a_reading_of_zero_not_a_missing_one(m, eco):
    for k in range(4):
        assess(m, eco, 20 * (k + 1))                      # nothing inside at all
    a = assess(m, eco, 100)
    zones = a.indicators.detail["backlog_level"]["zones"]
    assert all(zones[z]["level"] == 0.0 for z in mon.LEVEL_ZONES)
    assert zones["INTAKE"]["baseline"] == 0.0
    assert zones["INTAKE"]["headroom_used"] == 0.0          # (0-0)/(26-0)
    assert zones["SORTING"]["ratio_to_baseline"] is None    # 0 / 0 is not a ratio
    assert a.evaluable[NAME] and a.indicators.backlog_level_deviation == 0.0


def test_a_zone_normally_empty_still_has_a_value_against_its_capacity(m, eco):
    normal(m, eco, intake=(0, 0, 0, 0, 0, 0, 0, 0))
    a = assess(m, eco, 180, INTAKE=13, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    intake = a.indicators.detail["backlog_level"]["zones"]["INTAKE"]
    assert intake["baseline"] == 0.0 and intake["ratio_to_baseline"] is None
    assert intake["headroom_used"] == pytest.approx(13 / 26)


def test_unread_capacity_or_no_headroom_gives_no_value(eco):
    eco.generator.max_on_dock = None            # the dock cap could not be read
    eco.env.storage.capacity = 0                # no shelves at all
    m = DKRMM(eco).attach()
    normal(m, eco)
    a = assess(m, eco, 180, INTAKE=26, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    zones = a.indicators.detail["backlog_level"]["zones"]
    assert zones["INTAKE"]["note"] == "capacity not read"
    assert zones["TEMPORARY_STORAGE"]["note"] == "capacity not read"
    assert a.evaluable[NAME] is False
    assert a.indicators.backlog_level_deviation == 0.0 and a.z[NAME] == 0.0
    assert a.deviation[NAME] == "none"
    row = next(r for r in indicator_rows(m) if r["name"] == NAME)
    assert row["value"] is None and row["status"] == "n/a"


def test_a_capacity_at_or_below_the_normal_level_has_no_headroom(eco):
    eco.generator.max_on_dock = 4
    m = DKRMM(eco).attach()
    normal(m, eco)
    a = assess(m, eco, 180, INTAKE=4, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    intake = a.indicators.detail["backlog_level"]["zones"]["INTAKE"]
    assert intake["note"] == "no headroom above the normal level"
    assert intake["headroom_used"] is None
    assert a.indicators.detail["backlog_level"]["zone"] == "TEMPORARY_STORAGE"


def test_unreadable_parcels_leave_it_unread_and_teach_nothing(eco):
    m = DKRMM(eco).attach()
    normal(m, eco)
    learned = {z: len(m._levels[z]) for z in m._levels}
    del eco.env.parcels                           # the building cannot be read
    a = m.assess(180)
    assert a.snapshot["by_zone"] is None and a.snapshot["backlog"] is None
    assert a.evaluable[NAME] is False
    zones = a.indicators.detail["backlog_level"]["zones"]
    assert all(row["level"] is None and row["note"] == "level not read"
               for row in zones.values())
    assert {z: len(m._levels[z]) for z in m._levels} == learned


def test_a_short_baseline_is_not_read(m, eco):
    rows = normal(m, eco, intake=(4, 5, 4), storage=(1, 0, 1))
    assert all(r.evaluable[NAME] is False for r in rows)
    assert (rows[-1].indicators.detail["backlog_level"]["zones"]["INTAKE"]["note"]
            == "baseline too short")
    # The fourth reading is measured against three past levels: still short.
    fourth = assess(m, eco, 80, INTAKE=4, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    assert fourth.evaluable[NAME] is False
    fifth = assess(m, eco, 100, INTAKE=4, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    assert fifth.evaluable[NAME] is True


# ---------------------------------- 7. the history and the baseline compared
def test_each_zone_baseline_is_the_median_of_its_learned_levels(m, eco):
    normal(m, eco)
    assert list(m._levels["INTAKE"]) == [4, 5, 4, 3, 4, 5, 4, 3]
    assert list(m._levels["TOTAL"]) == [10, 10, 10, 10, 10, 10, 10, 9]
    a = assess(m, eco, 180, INTAKE=9, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    assert (a.indicators.detail["backlog_level"]["zones"]["INTAKE"]["baseline"]
            == median([4, 5, 4, 3, 4, 5, 4, 3]))
    # The indicator itself has a series like every other: z is read against
    # the values before this window, and `baseline` is their mean.
    past = [r for r in m.history[:-1] if r.evaluable[NAME]]
    series = [r.indicators.backlog_level_deviation for r in past]
    assert a.baseline[NAME] == pytest.approx(sum(series) / len(series))
    assert a.z[NAME] == pytest.approx(DKRMM._signed_z(a.indicators.backlog_level_deviation,
                                                      series))


def test_a_formed_baseline_does_not_learn_a_full_dock_called_unstable(m, eco):
    normal(m, eco)
    assert len(m._levels["INTAKE"]) == 8               # formed at 8
    rows = fault(m, eco, [4, 4, 4, 10, 16, 22, 26, 26, 26, 26])
    for r in rows[3:]:
        assert r.state in (OperationalState.UNSTABLE, OperationalState.RCT)
        assert set(r.kinds) & set(mon.OPERATIONAL_KINDS)
    # Only the levels of the three windows still at 4 were learned (they
    # were DEVIATING); every elevated one was refused, so the full dock is
    # measured against the normal it left and does not become the normal.
    assert list(m._levels["INTAKE"]) == [3, 4, 5, 4, 3, 4, 4, 4]
    assert rows[-1].indicators.backlog_level_deviation == pytest.approx(1.0)
    assert rows[-1].deviation[NAME] == "up"


# ------------------------- 8. through the existing rules, thresholds intact
def test_the_state_rules_and_thresholds_are_unchanged():
    assert (mon.EVERY, mon.WINDOW, mon.BASELINE) == (20, 60, 24)
    assert mon.DEVIATION_Z == 2.0
    assert (mon.UNSTABLE_KINDS, mon.RCT_KINDS) == (2, 3)
    assert mon.RCT_PROPAGATION == 0.5 and mon.PERSISTENT == 3
    assert mon.MIN_ACTIVITY == 24
    assert mon.BASELINE_LEARNS_FROM == (OperationalState.STABLE,
                                        OperationalState.DEVIATING,
                                        OperationalState.RECOVERY)
    assert mon.LEVEL_MIN_BASELINE == mon.TAIL_MIN_BASELINE == 4


def test_on_its_own_it_is_one_kind_and_one_kind_is_a_deviation(m, eco):
    normal(m, eco)
    a = assess(m, eco, 180, INTAKE=26, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    assert a.deviation[NAME] == "up"
    assert a.kinds == ["backlog"]
    assert a.state is OperationalState.DEVIATING     # not UNSTABLE, not RCT
    # And straight through the classifier, z alone at its largest: one kind.
    m._last_kinds = ["backlog"]
    m._persistence = 0
    z = {name: 0.0 for name in INDICATOR_NAMES}
    z[NAME] = 50.0
    state, kinds, _ = m._classify(a.indicators, z)
    assert kinds == ["backlog"] and state is OperationalState.DEVIATING


def test_it_counts_in_the_severity_like_every_up_indicator(m, eco):
    normal(m, eco)
    a = assess(m, eco, 180, INTAKE=26, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    expected = sum(mon.directional(n, a.z[n]) for n in INDICATOR_NAMES
                   if a.evaluable[n]) / len(INDICATOR_NAMES)
    assert a.severity == pytest.approx(expected)
    assert mon.directional(NAME, -3.0) == 0.0 and mon.directional(NAME, 3.0) == 3.0


def test_watching_writes_nothing_to_the_building(m, eco):
    normal(m, eco)
    fill(eco, INTAKE=26, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    before = (dict(eco.env.parcels), eco.env.storage.used, eco.env.storage.capacity,
              eco.generator.max_on_dock, eco.generator.refused, eco.emitted)
    m.assess(180)
    assert (dict(eco.env.parcels), eco.env.storage.used, eco.env.storage.capacity,
            eco.generator.max_on_dock, eco.generator.refused, eco.emitted) == before


# ---------------------------------- 9. persisted and shown like the others
def test_it_is_saved_and_shown_with_its_zone_evidence(m, eco):
    normal(m, eco)
    a = assess(m, eco, 180, INTAKE=26, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    saved = json.loads(json.dumps(a.as_dict()))
    assert saved["indicators"][NAME] == pytest.approx(1.0)
    assert saved["evaluable"][NAME] is True
    assert saved["deviation"][NAME] == "up"
    assert saved["in_evidence"][NAME] == "backlog"
    detail = saved["indicators"]["detail"]["backlog_level"]
    assert detail["tick"] == 180 and detail["every"] == 20
    assert detail["zone"] == "INTAKE"
    assert detail["zones"]["INTAKE"]["level"] == 26
    assert set(detail["zones"]) == set(mon.LEVEL_ZONES) | {mon.LEVEL_TOTAL}
    series = m.series()
    assert series["indicators"][NAME][-1] == pytest.approx(1.0)

    row = next(r for r in indicator_rows(m) if r["name"] == NAME)
    assert row["kind"] == "derived" and row["direction"] == "up"
    assert row["value"] == pytest.approx(1.0) and row["tick"] == 180
    assert row["in_evidence"] == "backlog" and row["status"] == "deviating up"
    assert row["detail"]["zones"]["INTAKE"]["capacity"] == 26
    ops = monitor_digest(m)["operations"]["backlog"]
    assert ops["level_deviation"] == pytest.approx(1.0)
    assert ops["level_zone"] == "INTAKE"


def test_the_pane_paints_its_row_and_the_headroom_line(m, eco):
    from post_office.ui.live import _read, dkrmm_html

    normal(m, eco)
    assess(m, eco, 180, INTAKE=26, TEMPORARY_STORAGE=1, SORTING=2, DISPATCH=3)
    html = dkrmm_html(SimpleNamespace(monitor=m, preset="normal"))
    assert html.count('<tr class="indicator') == len(INDICATOR_NAMES)
    assert f'title="' in html and f'>{NAME}</td>' in html
    assert "headroom used" in html and "100% (INTAKE)" in html
    # The live page's own painter (live.html) draws the same line.
    assert '["headroom used"' in _read("live.html")
