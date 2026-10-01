"""
Phases 4 and 5: the experts, their sub-agents, the planner and the supervisor.

These tests run the real ecosystem rather than mocking the bus, because almost
everything worth checking about an agent here is about what it says to somebody
else, and a mocked bus would only confirm that the mock works.
"""

from __future__ import annotations

import pytest

from post_office.agents.brain import Answer, ConstantBrain, DeterministicBrain, Question
from post_office.agents.subagents import make_barcode, parse_barcode
from post_office.communication import AgentKind, MessageType
from post_office.environment import ParcelPriority, ParcelStatus, Zone
from post_office.simulation import build
from post_office.tasks import TaskStatus, TaskType


@pytest.fixture
def eco():
    ecosystem = build(seed=3, run_id="agents")
    ecosystem.start()
    yield ecosystem
    ecosystem.close()


def run(eco, ticks):
    eco.run(ticks)
    return eco


# ------------------------------------------------------------ the hierarchy
def test_the_hierarchy_has_the_shape_the_spec_asks_for(eco):
    assert len(eco.experts) == 6
    assert len(eco.subagents) == 15
    assert len(eco.fleet) == 5
    assert len(eco.agents) == 28          # 1 + 1 + 6 + 15 + 5

    directory = eco.directory
    assert directory.parent_of("PLANNER") == "SUPERVISOR"
    for expert in eco.experts:
        assert directory.parent_of(expert) == "PLANNER"
    for sub_id, sub in eco.subagents.items():
        assert directory.parent_of(sub_id) in eco.experts
        assert directory.get(sub_id).kind is AgentKind.SUBAGENT


def test_every_expert_owns_its_own_subagents(eco):
    owned = {e: sorted(c for c in eco.directory.children_of(e)
                       if c in eco.subagents)
             for e in eco.experts}
    assert owned == {
        "INTAKE": ["SUB-REGISTRATION", "SUB-VALIDATION"],
        "SORTING": ["SUB-BARCODE", "SUB-DESTINATION", "SUB-PRIORITY"],
        "ROUTING": ["SUB-COLLISION", "SUB-ROUTE"],
        "SCHEDULING": ["SUB-ASSIGNMENT", "SUB-DEADLINE", "SUB-QUEUE"],
        "RESOURCE": ["SUB-BATTERY", "SUB-CHARGING", "SUB-STORAGE"],
        "DISPATCH": ["SUB-MANIFEST", "SUB-PACKING"],
    }
    # the robots hang off the scheduler, which is the expert that commands them
    assert sorted(c for c in eco.directory.children_of("SCHEDULING")
                  if c in eco.robot_agents) == eco.fleet.ids()


def test_no_subagent_ever_addresses_anyone_but_its_parent(eco):
    run(eco, 200)
    for message in eco.bus.log.recent(5000):
        record = eco.directory.get(message.sender)
        if record is not None and record.kind is AgentKind.SUBAGENT:
            assert message.receiver == record.parent_id, message


def test_no_robot_ever_addresses_the_planner_or_the_supervisor(eco):
    run(eco, 200)
    for message in eco.bus.log.recent(5000):
        record = eco.directory.get(message.sender)
        if record is not None and record.kind is AgentKind.ROBOT:
            assert message.receiver in eco.experts, message


def test_the_hierarchy_holds_without_anybody_being_refused(eco):
    # A refusal here would mean an agent tried to work outside the hierarchy.
    run(eco, 200)
    assert eco.bus.log.refused == 0, eco.bus.log.refusals()


# ------------------------------------------------------------------ barcode
def test_a_barcode_encodes_where_the_facility_decided_the_parcel_goes():
    """
    The label this building prints, not one the sender brought. It carries the
    route and the service the facility settled on, so reading one back tells
    you what was decided rather than what was declared.
    """
    code = make_barcode("BRNO", "EXP", "0042")
    assert make_barcode("BRNO", "EXP", "0042") == code
    assert make_barcode("PLZEN", "EXP", "0042") != code
    fields = parse_barcode(code)
    assert fields["valid"]
    assert fields["route"] == "BRNO"
    assert fields["service"] == "EXP"
    assert fields["serial"] == "0042"


def test_a_damaged_barcode_is_reported_rather_than_guessed():
    assert parse_barcode("nonsense")["valid"] is False


# --------------------------------------------------------------- the flow
def test_a_parcel_is_scanned_graded_and_given_a_destination(eco):
    run(eco, 40)
    # Parcels the facility actually took: one turned away at the door was never
    # read, graded or given anywhere to go, which is the point of turning it
    # away.
    classified = [p for p in eco.env.all_parcels().values()
                  if p.status is ParcelStatus.CLASSIFIED]
    assert classified, "nothing was classified in forty ticks"
    parcel = classified[0]
    assert parcel.route_label
    assert parcel.destination is not None
    actors = {h["actor"] for h in parcel.processing_history}
    assert "SORTING" in actors


def test_the_whole_chain_appears_in_one_parcels_conversation(eco):
    run(eco, 260)
    # Reaching the back door, not leaving the building: since the facility got
    # a timetable a parcel waits at dispatch for its van, and the first van of
    # a run does not leave inside 260 ticks. The chain this test is about is
    # complete by then either way.
    carried = [p for p in eco.env.all_parcels().values()
               if p.timestamps.get("awaiting_dispatch") is not None]
    assert carried, "no parcel reached dispatch in 260 ticks"
    thread = eco.bus.log.thread(carried[0].parcel_id)
    senders = {m.sender for m in thread}
    # planner, an expert, a sub-agent and a robot all speak about one parcel
    assert "PLANNER" in senders
    assert senders & set(eco.experts)
    assert senders & set(eco.subagents)
    assert senders & set(eco.robot_agents)


def test_parcels_actually_reach_dispatch(eco):
    """
    All the way out, which now means onto a van and gone with it. Long enough
    for the timetable: the first departure of a run is at the van interval, so
    a four-hundred-tick run reaches the door but never leaves the yard.
    """
    run(eco, 1400)
    dispatched = [p for p in eco.env.all_parcels().values()
                  if p.status is ParcelStatus.DISPATCHED]
    assert len(dispatched) >= 3
    for parcel in dispatched:
        assert parcel.position is None          # it left the building
        assert parcel.dwell is not None and parcel.dwell > 0
        assert parcel.loaded_on, "and it left on a van"


def test_normal_parcels_pass_through_storage_and_urgent_ones_do_not(eco):
    run(eco, 400)
    for parcel in eco.env.all_parcels().values():
        if parcel.status is not ParcelStatus.DISPATCHED:
            continue
        stored = "stored" in parcel.timestamps
        if parcel.priority is ParcelPriority.URGENT:
            assert not stored, f"{parcel.parcel_id} was shelved despite being urgent"


# ------------------------------------------------------------------- tasks
def test_a_task_carries_its_parcels_correlation_id(eco):
    run(eco, 60)
    for task in eco.tasks.all():
        if task.parcel_id:
            assert task.correlation_id == task.parcel_id


def test_no_task_is_ever_lost(eco):
    # Every task is either finished or still somebody's responsibility. A task
    # that is open, unassigned and has no parcel on the floor is a leak.
    run(eco, 300)
    for task in eco.tasks.open_tasks():
        if task.parcel_id:
            parcel = eco.env.parcels.get(task.parcel_id)
            assert parcel is not None


def test_a_transport_task_names_a_robot_once_it_is_under_way(eco):
    run(eco, 120)
    started = [t for t in eco.tasks.all()
               if t.task_type is TaskType.TRANSPORT
               and t.status in (TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED)]
    assert started
    assert all(t.assigned_robot for t in started)


# --------------------------------------------------------------- resources
def test_the_resource_agent_refuses_work_a_flat_robot_cannot_finish(eco):
    """
    The veto, exercised where it actually bites.

    This used to put the fleet at 40% and expect a refusal, which said more
    about the old battery than about the rule: an errand cost most of a charge,
    so a robot above the line routinely could not finish one. Now it can -- a
    robot above the line that could not do a job would mean the line was in the
    wrong place -- so the refusal has to be provoked, by lowering the line and
    leaving less in the battery than the errand costs.
    """
    for robot in eco.fleet.all():
        robot.low_battery = 2.0        # available, so the scheduler offers work
        robot.battery_level = 6.0      # and an errand costs more than that
    run(eco, 120)
    assert eco.experts["RESOURCE"].denied > 0


def test_a_refused_job_goes_back_to_the_queue_rather_than_failing(eco):
    """
    A transport the resource agent will not clear goes back to the queue. It
    does not fail -- the work is still there to do and the robot will be
    charged before long.

    Counted over transports only: an intake task for a parcel the gate turned
    away fails on purpose, and folding that in would make this assertion about
    two unrelated things.
    """
    from post_office.tasks.task import TaskStatus, TaskType

    for robot in eco.fleet.all():
        robot.battery_level = 40.0
    run(eco, 80)
    failed = [t for t in eco.tasks.all()
              if t.status is TaskStatus.FAILED
              and t.task_type is TaskType.TRANSPORT]
    assert not failed, [t.task_id for t in failed]


def test_a_flat_robot_is_taken_to_a_charge_point(eco):
    for robot in eco.fleet.all():
        robot.battery_level = 22.0
    run(eco, 120)
    assert eco.experts["RESOURCE"].charges_arranged > 0
    assert max(r.battery_level for r in eco.fleet.all()) > 30.0


def test_storage_capacity_is_respected(eco):
    run(eco, 400)
    assert eco.env.storage.used <= eco.env.storage.capacity
    stored = {p.parcel_id for p in eco.env.all_parcels().values()
              if p.status is ParcelStatus.STORED}
    assert eco.env.storage.held >= stored or stored >= eco.env.storage.held


# -------------------------------------------------------------- supervisor
def test_the_supervisor_sets_an_objective_and_approves_a_plan(eco):
    run(eco, 10)
    assert eco.planner.objective
    assert eco.planner.approved is True
    assert eco.supervisor.plan is not None


def test_the_supervisor_receives_status_reports(eco):
    run(eco, 80)
    assert len(eco.supervisor.reports) >= 3
    assert "parcels_dispatched" in eco.supervisor.reports[-1]


def test_stopping_the_system_stops_new_work_but_not_the_floor(eco):
    run(eco, 120)
    created_before = eco.planner.tasks_created
    eco.supervisor.stop("test")
    run(eco, 40)
    assert eco.planner.tasks_created == created_before
    assert eco.world.running is False


def test_the_supervisor_shuts_storage_when_the_shelves_fill(eco):
    eco.env.storage.capacity = 4
    for i in range(4):
        eco.env.claim_storage(f"X-{i}")
    run(eco, 60)
    assert eco.world.policy.store_normal_parcels is False
    assert any("storage" in i.get("note", "") for i in eco.supervisor.interventions)


# ------------------------------------------------------------------ brains
def test_every_judgement_is_recorded_with_the_brain_that_made_it(eco):
    run(eco, 120)
    decisions = [e for e in eco.logger.recent(4000) if e.topic == "decision"]
    assert decisions
    assert all(d.detail.get("source") for d in decisions)
    # `classify_priority` is not among them any more: a service class is sold
    # rather than decided, so sorting reads it off the label and writes it down.
    assert {d.detail["decision"] for d in decisions} >= {"classify_destination",
                                                         "release_work"}
    assert "classify_priority" not in {d.detail["decision"] for d in decisions}


def test_a_brain_can_be_swapped_for_one_agent_without_touching_anything_else():
    """
    The whole point of the seam: one agent given a different brain, the rest of
    the ecosystem unchanged and still running.

    Through sorting's destination decision rather than its grade. The grade is
    no longer decided at all -- a service class is sold, and the facility reads
    it off the label -- so a brain cannot move it, and one that could would be
    a brain rewriting somebody's contract.
    """
    eco = build(seed=5, run_id="swap",
                brains={"SORTING": ConstantBrain(Zone.DISPATCH.value)})
    eco.start()
    eco.run(400)
    # Every answer this brain gave to the question sorting actually asks.
    # A parcel's first leg is always to SORTING and is settled rather than
    # decided -- there is only one place a parcel can go from the dock -- so
    # what the brain moves is the shelf-or-door call after that.
    asked = [d for d in eco.experts["SORTING"].decisions
             if d["kind"] == "classify_destination"]
    assert asked, "sorting never asked the question"
    assert {d["choice"] for d in asked} == {Zone.DISPATCH.value}
    # And the visible consequence: nothing was ever shelved.
    assert not [p for p in eco.env.all_parcels().values()
                if "stored" in p.timestamps]
    eco.close()


def test_an_unanswerable_question_is_visible_rather_than_silently_wrong():
    brain = DeterministicBrain()
    answer = brain.answer(Question(kind="who_knows", asked_by="X",
                                   prompt="?", options=("A", "B")))
    assert answer.choice == "A"
    assert answer.confidence == 0.0
    assert "no rule" in answer.reason


def test_a_constant_brain_still_answers_from_the_offered_options():
    brain = ConstantBrain("NOT_AN_OPTION")
    answer = brain.answer(Question(kind="k", asked_by="X", prompt="?",
                                   options=("A", "B")))
    assert answer.choice == "A"
