"""
The interception seams are installed and do nothing in NORMAL (spec 15).

The identity layers hand back exactly what they are given; `from_config` builds
the inert arrangement from an empty `interceptors` list and refuses anything
else; a NORMAL run says in its log that no perturbation is in force; and a
consultation run through `Interception.inert()` carries the owner's words to
the peer, and the peer's back, byte for byte.
"""

import dataclasses
import json

import pytest

from post_office.agents.brain import Answer
from post_office.config.settings import normal_config
from post_office.crew import interception as interception_module
from post_office.crew.interception import (AgentHooks, CommunicationLayer, ConsultRequest,
                                           ConsultResponse, Interception, from_config)
from post_office.simulation.ecosystem import build
from tests.consult_helpers import ask, events, scheduling_with_equally_placed_robots
from tests.fake_ollama import consultation_script, text_of

PROMPT = "Which robot takes T-1?\nAllowed answers:\n- R1\n- R2\né → tab\there"


def _request():
    return ConsultRequest(consultation_id="CSL-0001", tick=3, sender="SCHEDULING",
                          receiver="ROUTING", interaction_type="question",
                          text="Which robot, R1 or R2?\n", context="T-1 waits at\tdock 2.")


def _response():
    return ConsultResponse(consultation_id="CSL-0001", tick=3, sender="ROUTING",
                           receiver="SCHEDULING", text="R2: its corridor is clear.",
                           latency_ms=12.5, model="qwen3:8b")


def test_the_identity_layers_hand_back_what_they_are_given():
    layer, hooks = CommunicationLayer(), AgentHooks()
    request, response = _request(), _response()
    request_before, response_before = dataclasses.asdict(request), dataclasses.asdict(response)

    assert layer.on_request(request) is request
    assert dataclasses.asdict(request) == request_before
    assert layer.on_response(response) is response
    assert dataclasses.asdict(response) == response_before

    assert hooks.before_prompt("SCHEDULING", PROMPT) is PROMPT
    assert hooks.before_llm_call("SCHEDULING") is None
    answer = Answer("R1", "nearest", source="crewai:qwen3:8b", confidence=1.0)
    assert hooks.after_answer("SCHEDULING", answer) is answer
    assert (answer.choice, answer.reason, answer.source, answer.confidence) == (
        "R1", "nearest", "crewai:qwen3:8b", 1.0)


@pytest.mark.parametrize("cfg", [{}, {"interceptors": []}, {"interceptors": ()},
                                 normal_config()])
def test_an_empty_interceptor_list_is_the_inert_arrangement(cfg):
    built = from_config(cfg)
    assert isinstance(built, Interception)
    assert type(built.communication) is CommunicationLayer
    assert type(built.agent) is AgentHooks
    assert built.active is False


@pytest.mark.parametrize("interceptors", [["delay"], [{"kind": "loss"}], ("isolation",)])
def test_any_interceptor_is_refused(interceptors):
    with pytest.raises(NotImplementedError, match="perturbations are not part of this phase"):
        from_config({"interceptors": interceptors})


def test_a_normal_run_says_no_perturbation_is_in_force():
    eco = build(seed=1, config=normal_config())
    eco.start()
    (started,) = events(eco, "simulation_started")
    (notice,) = events(eco, "interception")
    print(f"\nsimulation_started: {json.dumps(started.detail, sort_keys=True)}")
    print(f"interception: {json.dumps(notice.detail, sort_keys=True)}")

    assert "perturbations" not in started.detail
    assert "perturbations" not in started.detail["config"]
    assert started.detail["config"]["interceptors"] == []
    assert started.detail["scenario"] == "normal"
    assert notice.detail["active"] == [] and notice.detail["perturbations"] == "none"
    assert notice.category == "simulation" and notice.seq < started.seq
    eco.close()


@pytest.mark.usefixtures("quiet_crewai_console")
def test_the_service_gets_its_interception_from_the_configuration(fake_ollama, monkeypatch):
    seen = []
    real = interception_module.from_config

    def spy(cfg):
        seen.append(dict(cfg))
        return real(cfg)

    monkeypatch.setattr(interception_module, "from_config", spy)
    eco, _ = scheduling_with_equally_placed_robots(fake_ollama)
    assert seen == [eco.config]
    assert eco.crew.interception.active is False
    eco.close()


@pytest.mark.usefixtures("quiet_crewai_console")
def test_an_inert_consultation_carries_every_word_unchanged(fake_ollama):
    peer_reply = "R2: its corridor is clear,\tand R1 is éloigné."
    fake_ollama.script(consultation_script(peer_reply, decide=lambda peer: "R2"))
    eco, sched = scheduling_with_equally_placed_robots(fake_ollama)
    eco.crew.interception = Interception.inert()
    answer = ask(sched)
    assert answer.choice == "R2" and answer.source == "crewai:qwen3:8b"

    owner_first, peer_call, owner_last = fake_ollama.requests
    # What the owner sent through the tool, as the model wrote it.
    assistant = next(m for m in owner_last["messages"] if m.get("tool_calls"))
    (tool_call,) = assistant["tool_calls"]
    sent = json.loads(tool_call["function"]["arguments"])

    (question,) = events(eco, "consult_question")
    (request,) = [e for e in events(eco, "message")
                  if e.detail["message_type"] == "CONSULT_REQUEST"]
    assert question.detail["text"] == sent["question"]
    assert question.detail["context"] == sent["context"]
    assert request.detail["content"]["text"] == sent["question"]
    assert request.detail["text"] == sent["question"]

    # What the peer's model was given contains the question and the owner's
    # context exactly as sent.
    peer_text = "\n".join(text_of(m) for m in peer_call["messages"])
    assert sent["question"] in peer_text
    assert peer_text.count(f"What Scheduling told you:\n{sent['context']}") == 1

    # The peer's words reach the event, the bus and the owner's tool result unchanged.
    (response,) = events(eco, "consult_response")
    (bus_response,) = [e for e in events(eco, "message")
                       if e.detail["message_type"] == "CONSULT_RESPONSE"]
    tool_result = [text_of(m) for m in owner_last["messages"] if m.get("role") == "tool"]
    assert response.detail["text"] == peer_reply
    assert bus_response.detail["content"]["text"] == peer_reply
    assert tool_result == [peer_reply]

    # The owner's prompt is the task description, unaltered by the hooks.
    owner_text = "\n".join(text_of(m) for m in owner_first["messages"])
    assert sched.brain.last_prompt and sched.brain.last_prompt in owner_text
    eco.close()
