"""
The Consultation trajectory shows the run's consultations, not just the newest.

The trajectory is drawn from the event log, which keeps the newest
`keep_events` events in memory -- a few hundred ticks of a live run -- so a run
past that point showed only its last few consultations (CSL-0013 on, with
SCHEDULING on its eighteenth call). The logger now keeps the consultation
events apart and longer (`EventLogger.consultation_events`), the page's fold
puts those older than the window back in front of it (`views.trajectory_data`),
and the page's own trimming keeps consultation rows (`trimOldest`).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from post_office.communication.events import CONSULTATION_TOPICS, EventLogger
from post_office.ui import live, views


def _run_with(consultations: int, floor_events_between: int, keep: int = 300):
    log = EventLogger(run_id="t", keep=keep)
    log.emit("simulation", "simulation_started", tick=0, actor="SIMULATION")
    for n in range(1, consultations + 1):
        cid = f"CSL-{n:04d}"
        log.emit("agent", "consult_opened", tick=n, actor="SCHEDULING", target="DISPATCH",
                 correlation_id=cid, consultation_id=cid, peer="DISPATCH")
        log.emit("agent", "llm_call", tick=n, actor="SCHEDULING", correlation_id=cid,
                 consultation_id=cid, phase="owner", latency_ms=10.0)
        log.emit("agent", "consult_closed", tick=n, actor="SCHEDULING", correlation_id=cid,
                 consultation_id=cid, outcome="decided", choice="T-1")
        for _ in range(floor_events_between):
            log.emit("robot", "moved", tick=n, actor="R1", cells=1)
    return log


def _runner(log):
    return SimpleNamespace(
        events=lambda after=0, limit=100: [e.as_dict() for e in log.since(after, limit)],
        event_counts=lambda: {"total": log.total, "counts": log.counts()},
        consultation_events=lambda before=None: [e.as_dict()
                                                 for e in log.consultation_events(before)],
        last_frame={"run_id": "t", "seed": 1, "tick": 19}, preset="default", settings=None)


def _consultations_in(rows):
    return sorted({r[9].get("consultation_id") for r in rows
                   if str(r[3]).split("/")[-1] in CONSULTATION_TOPICS})


def test_the_logger_keeps_consultations_the_general_tail_has_dropped():
    log = _run_with(consultations=19, floor_events_between=100, keep=300)
    held = {e.detail.get("consultation_id") for e in log.since(0, 10 ** 6)
            if e.topic in CONSULTATION_TOPICS}
    kept = {e.detail.get("consultation_id") for e in log.consultation_events()}
    assert len(held) < 19 and len(kept) == 19
    newest_held = min(e.seq for e in log.since(0, 10 ** 6))
    assert all(e.seq < newest_held for e in log.consultation_events(before=newest_held))


def test_the_trajectory_fold_has_every_kept_consultation():
    log = _run_with(consultations=19, floor_events_between=100, keep=300)
    data = views.trajectory_data(_runner(log), limit=9000)
    assert _consultations_in(data["events"]) == [f"CSL-{n:04d}" for n in range(1, 20)]
    seqs = [r[0] for r in data["events"]]
    assert seqs == sorted(seqs)                      # still one ordered log


def test_the_page_keeps_consultation_rows_when_it_trims(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    log = _run_with(consultations=3, floor_events_between=5, keep=300)
    data = views.trajectory_data(_runner(log), limit=9000)
    page_html = live._fill("trajectory.html", "/*__TRAJECTORY_DATA__*/null", data)
    path = tmp_path / "trajectory.html"
    path.write_text(page_html, encoding="utf-8")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(path.as_uri())
            page.wait_for_function("typeof ingest === 'function' && EVENTS.length > 0")
            before = page.evaluate("discussionsOf().map(d => d.id).sort()")
            # Far more floor rows than the page holds: it trims its oldest.
            page.evaluate("""() => {
                const last = EVENTS[EVENTS.length - 1];
                const rows = [];
                for (let i = 1; i <= CAP + TRIM; i++)
                    rows.push([last[ID] + i, 99, last[MS] + i, "robot/moved", "R1", "", "",
                               null, "", {}]);
                ingest(rows);
            }""")
            after = page.evaluate("discussionsOf().map(d => d.id).sort()")
            size = page.evaluate("EVENTS.length")
        finally:
            browser.close()
    assert before == ["CSL-0001", "CSL-0002", "CSL-0003"] and after == before
    assert size <= 14000 + 50
