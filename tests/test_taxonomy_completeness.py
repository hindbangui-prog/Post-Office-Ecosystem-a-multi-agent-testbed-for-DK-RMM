"""
Every event a seeded NORMAL run produces is classified without the fallback (spec 3, 8).

Two runs: 300 ticks on the experts' rules (seed 1, `PYTHONHASHSEED=0`), and 120
ticks with the seven CrewBrains on the fake Ollama, every consultation answered
by the `deciding_script`. Each logged event goes through `classify` again, with
the content's `interaction_type` as `content_type` the way `EventLogger.emit`
passes it; the result must not fall back and must equal the event's own stamp
(`interaction_type`, `channel`), and the set of observed (category, topic,
message_type) triples must be a subset of EXPECTED. A new source event therefore
fails here under its own name, and the person who added it decides which rule it
belongs to.

Neither seeded run produces a `delegation` (every CONSULT_REQUEST's content says
`question`); that type is covered by
`tests/test_taxonomy.py::test_4_a_consult_request_follows_its_content_type` and
`tests/test_event_stamping.py::test_a_consult_request_whose_content_says_delegation_is_a_delegation`.
"""

from __future__ import annotations

from typing import Iterable, List, Set, Tuple

import pytest

from post_office.communication.taxonomy import classify
from post_office.config.settings import normal_config
from post_office.simulation.ecosystem import build
from tests.consult_helpers import ecosystem_on
from tests.fake_ollama import deciding_script

Triple = Tuple[str, str, str]

#: Every (category, topic, message_type) the seeded runs are known to produce.
EXPECTED: Set[Triple] = set()
for _topic in ("agent_created", "consult_closed", "consult_opened", "consult_question",
               "consult_response", "decision", "llm_call"):
    EXPECTED.add(("agent", _topic, ""))
EXPECTED.add(("battery", "battery_band", ""))
for _type in ("CONSULT_CLOSE", "CONSULT_REQUEST", "CONSULT_RESPONSE", "OBJECTIVE",
              "PLAN_APPROVAL", "PLAN_PROPOSAL", "POLICY", "RESOURCE_GRANT", "RESOURCE_REQUEST",
              "ROBOT_COMMAND", "ROBOT_REPORT", "ROUTE_REQUEST", "ROUTE_RESPONSE",
              "STATUS_REPORT", "SUBTASK_REQUEST", "TASK_ACCEPTED", "TASK_ASSIGNMENT",
              "TASK_COMPLETED", "TASK_FAILED"):
    EXPECTED.add(("communication", "message", _type))
EXPECTED.add(("communication", "subagent_message", "SUBTASK_RESULT"))
for _topic in ("bag_handed_over", "parcel_arrived", "parcel_classified", "parcel_departed",
               "parcel_dropped", "parcel_lifted", "parcel_packed", "parcel_passed_through",
               "parcel_received", "parcel_refused", "parcel_returned", "promise_revised",
               "van_departed"):
    EXPECTED.add(("parcel", _topic, ""))
for _topic in ("storage_claimed", "storage_policy", "storage_released"):
    EXPECTED.add(("resource", _topic, ""))
for _topic in ("arrived_at_dropoff", "arrived_at_pickup", "block_resolved", "blocked",
               "command_abort", "command_set_route", "command_step_aside", "command_transport",
               "command_yield",
               "delivered", "moved", "passed_via", "picked", "stalled", "yield_failed",
               "yielded"):
    EXPECTED.add(("robot", _topic, ""))
for _topic in ("interception", "llm", "simulation_started", "simulation_stopped"):
    EXPECTED.add(("simulation", _topic, ""))
for _topic in ("plan_approved", "policy_applied", "policy_changed", "system_started",
               "system_stopped"):
    EXPECTED.add(("supervisor", _topic, ""))
for _topic in ("errand_handed_over", "task_assigned", "task_completed", "task_created",
               "task_failed", "task_released", "task_started"):
    EXPECTED.add(("task", _topic, ""))


def _triple(event) -> Triple:
    return (event.category, event.topic, str(event.detail.get("message_type", "") or ""))


def _all_events(eco) -> List:
    events = eco.logger.recent(limit=10 ** 7)
    assert len(events) == eco.logger.total, "the logger dropped events; raise keep_events"
    return events


def _content_type(event) -> str:
    """The content's `interaction_type`, as `EventLogger.emit` reads it."""
    content = event.detail.get("content")
    return str(content.get("interaction_type", "") or "") if isinstance(content, dict) else ""


def _check(events: Iterable) -> Set[Triple]:
    observed: Set[Triple] = set()
    fell_back = []
    mismatched = []
    for event in events:
        got = classify(event.category, event.topic, event.actor, event.target,
                       event.detail.get("message_type", ""),
                       content_type=_content_type(event))
        if got.fallback:
            fell_back.append((event.seq, _triple(event), event.actor, event.target))
        if (event.interaction_type, event.channel) != (got.interaction_type, got.channel):
            mismatched.append((event.seq, _triple(event),
                               (event.interaction_type, event.channel),
                               (got.interaction_type, got.channel)))
        observed.add(_triple(event))
    assert fell_back == [], f"events classified by the fallback: {fell_back[:20]}"
    assert mismatched == [], f"stamp differs from classify: {mismatched[:20]}"
    unexpected = sorted(observed - EXPECTED)
    assert unexpected == [], f"new source events, add them to EXPECTED: {unexpected}"
    return observed


def test_a_300_tick_rules_only_run_is_fully_classified():
    eco = build(seed=1, config=normal_config(), run_id="taxonomy-rules", scenario="normal")
    eco.start()
    try:
        for _ in range(300):
            eco.step()
        events = _all_events(eco)
    finally:
        eco.close()
    assert len(events) > 1000
    observed = _check(events)
    # The run exercises every channel: governance, deterministic, robot, environment.
    assert ("communication", "message", "OBJECTIVE") in observed
    assert ("communication", "message", "ROUTE_REQUEST") in observed
    assert ("communication", "message", "ROBOT_COMMAND") in observed
    assert ("parcel", "parcel_arrived", "") in observed
    assert ("agent", "decision", "") in observed


@pytest.mark.usefixtures("quiet_crewai_console")
def test_a_120_tick_fake_model_run_is_fully_classified(fake_ollama):
    fake_ollama.script(deciding_script("Take the first: its way is clear."))
    eco = ecosystem_on(fake_ollama)
    try:
        for _ in range(120):
            eco.step()
        events = _all_events(eco)
    finally:
        eco.close()
    assert fake_ollama.requests, "the fake served no model call"
    observed = _check(events)
    # Channel B is reached: model calls and at least one consultation.
    assert ("agent", "llm_call", "") in observed
    assert ("agent", "consult_opened", "") in observed
    assert ("communication", "message", "CONSULT_REQUEST") in observed
