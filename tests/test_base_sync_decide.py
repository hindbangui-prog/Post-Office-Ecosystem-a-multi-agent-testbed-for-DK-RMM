"""`BaseAgent.decide` on the synchronous path (spec 6.2), and `step()` dropping CONSULT_* messages."""
import pytest

from post_office.agents.base import BaseAgent
from post_office.agents.brain import Answer, Brain, DeterministicBrain, Question
from post_office.communication.message import Message, MessageType
from post_office.simulation import build

CONSULT_KEYS = ("consultation_id", "peer", "turns")


class ConsultingBrain(Brain):
    """A brain that consults: it records the trigger it was handed and names its consultation."""

    name = "fake-crew"

    def __init__(self, fallback):
        self.fallback = fallback
        self.triggers = []
        self.last_consultation = None

    def answer(self, question: Question) -> Answer:
        raise AssertionError("the consulting path must be used when a trigger fired")

    def answer_consulting(self, question: Question, trigger) -> Answer:
        self.triggers.append(trigger)
        self.last_consultation = {"consultation_id": "CSL-0001", "peer": "ROUTING", "turns": 1}
        return Answer(question.options[0], "asked a peer", source="crewai:test")


@pytest.fixture
def eco():
    made = build(seed=11, run_id="sync-decide")
    made.start()
    yield made
    made.close()


def decisions_of(eco, actor):
    rows = []
    eco.logger.subscribe(lambda e: rows.append(e) if e.topic == "decision" and e.actor == actor else None)
    return rows


def release_work(planner):
    return planner.decide("release_work", "how many?", options=(0, 1, 2),
                          waiting=1, headroom=8, free_robots=4,
                          open_transports=0, ceiling=8, storage_load=0.1)


def test_a_fired_trigger_goes_to_answer_consulting_and_the_record_names_the_consultation(eco):
    planner = eco.planner
    planner.consult_policy = "always"
    brain = ConsultingBrain(planner.rules())
    planner.brain = brain
    rows = decisions_of(eco, planner.agent_id)

    answer = release_work(planner)

    assert len(brain.triggers) == 1 and brain.triggers[0].reason
    assert answer.source == "crewai:test"
    detail = rows[-1].detail
    assert detail["mode"] == "llm"
    assert detail["trigger"] == brain.triggers[0].reason
    assert (detail["consultation_id"], detail["peer"], detail["turns"]) == ("CSL-0001", "ROUTING", 1)
    record = planner.decisions[-1]
    assert (record["consultation_id"], record["peer"], record["turns"]) == ("CSL-0001", "ROUTING", 1)


def test_a_deterministic_brain_writes_no_consultation_fields(eco):
    planner = eco.planner
    assert isinstance(planner.brain, DeterministicBrain)
    rows = decisions_of(eco, planner.agent_id)

    release_work(planner)

    detail = rows[-1].detail
    assert detail["path"] == "deterministic"
    assert not any(key in detail for key in CONSULT_KEYS)
    assert not any(key in planner.decisions[-1] for key in CONSULT_KEYS)


class _Inbox:
    """Just enough of a bus for `step()`: an inbox that hands over its messages once."""

    def __init__(self, messages):
        self._messages = list(messages)

    def inbox(self, agent_id):
        out, self._messages = self._messages, []
        return out


class _Listener(BaseAgent):
    def __init__(self):
        super().__init__("LISTENER", "test listener")
        self.handled = []

    def handle(self, message):
        self.handled.append(message.message_type)


def _message(message_type, n):
    return Message(message_id=f"M-{n}", tick=1, sender="SCHEDULING", receiver="LISTENER",
                   message_type=message_type)


def test_step_drops_consult_messages_and_handles_the_rest():
    agent = _Listener()
    agent.bus = _Inbox([_message(MessageType.CONSULT_REQUEST, 1),
                        _message(MessageType.CONSULT_RESPONSE, 2),
                        _message(MessageType.CONSULT_CLOSE, 3),
                        _message(MessageType.ALERT, 4)])
    agent.step()
    assert agent.handled == [MessageType.ALERT]
    assert agent.received == 4
