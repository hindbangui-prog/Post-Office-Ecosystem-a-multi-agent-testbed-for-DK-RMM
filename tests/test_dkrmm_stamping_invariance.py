"""
Stamping is metadata: DK-RMM reads the same run with or without it (spec 2.2, 8).

The same seeded ecosystem is run twice with the monitor attached, once with
the classifier replaced by a stub that names nothing and once normally. The
monitor reads `topic`, `actor`, `target` and `detail` of each event and never
the two stamped slots, so every reading it makes, every state it enters and
every count the logger keeps must be identical between the two runs.
"""

from __future__ import annotations

from post_office.communication import events as events_module
from post_office.communication.taxonomy import Classification
from post_office.config.settings import normal_config
from post_office.dkrmm import DKRMM, build_record
from post_office.simulation.ecosystem import build

TICKS = 300
SEED = 1

RECORD_KEYS = ("indicator_series", "z_series", "count_series", "state_series", "transitions",
               "rct_events")


def _watched(run_id: str):
    eco = build(seed=SEED, config=normal_config(), run_id=run_id, scenario="normal")
    monitor = DKRMM(eco).attach()
    eco.start()
    try:
        for _ in range(TICKS):
            eco.step()
            monitor.tick()
        record = build_record(run_id, monitor, seed=SEED, control=True)
        stamps = {(e.interaction_type, e.channel) for e in eco.logger.recent(limit=10 ** 7)}
        out = {
            "state": monitor.state(),
            "record": {key: record[key] for key in RECORD_KEYS},
            "total": eco.logger.total,
            "counts": eco.logger.counts(),
            "stamps": stamps,
        }
    finally:
        monitor.close()
        eco.close()
    return out


def test_dkrmm_reads_the_same_run_with_and_without_stamping(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(events_module.taxonomy, "classify",
                      lambda *args, **kwargs: Classification("", "", False))
        stubbed = _watched("dk-stub")
    normal = _watched("dk-normal")

    # The two runs really differ in their stamps and in nothing else.
    assert stubbed["stamps"] == {("", "")}
    assert ("", "") not in normal["stamps"]
    assert len(normal["stamps"]) > 5

    assert normal["state"]["assessments"] > 0
    assert normal["state"] == stubbed["state"]
    for key in RECORD_KEYS:
        assert normal["record"][key] == stubbed["record"][key], key
    assert normal["record"]["state_series"], "the monitor never assessed anything"
    assert normal["total"] == stubbed["total"]
    assert normal["counts"] == stubbed["counts"]
    assert sum(normal["counts"].values()) == normal["total"]
