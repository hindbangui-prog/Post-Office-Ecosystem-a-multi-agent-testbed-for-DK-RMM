"""The fake Ollama server the CrewAI tests talk to: tags, show, plain replies, tool calls."""
import json

import httpx

from tests.fake_ollama import consultation_script


def _client():
    return httpx.Client(trust_env=False, timeout=5)


def _chat(fake, messages, **extra):
    with _client() as c:
        r = c.post(fake.base_url + "/v1/chat/completions",
                   json={"model": "qwen3:8b", "messages": messages, **extra})
    return r


def test_tags_and_show(fake_ollama):
    with _client() as c:
        tags = c.get(fake_ollama.base_url + "/api/tags").json()
        shown = c.post(fake_ollama.base_url + "/api/show", json={"model": "qwen3:8b"})
        missing = c.post(fake_ollama.base_url + "/api/show", json={"model": "llama3:8b"})
    assert [m["name"] for m in tags["models"]] == ["qwen3:8b"]
    assert tags["models"][0]["digest"] == "fake-qwen3:8b"
    assert shown.json()["details"]["family"] == "qwen3"
    assert missing.status_code == 404


def test_default_reply_is_the_first_allowed_answer_else_ok(fake_ollama):
    r = _chat(fake_ollama, [{"role": "user", "content": "Pick.\n\nAllowed answers:\n- R2\n- R3\n"}])
    body = r.json()
    assert body["model"] == "qwen3:8b" and body["usage"]["total_tokens"] > 0
    assert body["choices"][0]["message"]["content"] == "R2"
    r = _chat(fake_ollama, [{"role": "user", "content": "hello"}])
    assert r.json()["choices"][0]["message"]["content"] == "OK"
    assert len(fake_ollama.requests) == 2


def test_scripted_dict_becomes_native_tool_calls(fake_ollama):
    fake_ollama.script(lambda req: {"tool": "ask_question_to_coworker",
                                    "args": {"coworker": "ROUTING", "question": "q", "context": "c"}})
    choice = _chat(fake_ollama, [{"role": "user", "content": "hi"}]).json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls" and choice["message"]["content"] is None
    (call,) = choice["message"]["tool_calls"]
    assert call["id"] == "call_1" and call["function"]["name"] == "ask_question_to_coworker"
    assert json.loads(call["function"]["arguments"])["coworker"] == "ROUTING"


def test_fail_with_and_served_models(fake_ollama):
    fake_ollama.fail_with(503)
    assert _chat(fake_ollama, [{"role": "user", "content": "hi"}]).status_code == 503
    fake_ollama.fail_with(None)
    fake_ollama.serve_models(["gemma4:26b"])
    assert _chat(fake_ollama, [{"role": "user", "content": "hi"}]).json()["model"] == "gemma4:26b"


def test_consultation_script_walks_owner_peer_owner():
    tools = [{"type": "function", "function": {
        "name": "ask_question_to_coworker",
        "description": "Ask a specific question to one of the following coworkers: ROUTING\nThe input...",
        "parameters": {"type": "object", "required": ["question", "context", "coworker"],
                       "properties": {"question": {}, "context": {}, "coworker": {}}}}}]
    respond = consultation_script("Take R2, it is free.", lambda peer: "R2" if "R2" in peer else "R1")
    first = respond({"messages": [{"role": "system", "content": "You are SCHEDULING"},
                                  {"role": "user", "content": "Decide"}], "tools": tools})
    assert first["tool"] == "ask_question_to_coworker" and first["args"]["coworker"] == "ROUTING"
    peer = respond({"messages": [{"role": "system", "content": "You are ROUTING"},
                                 {"role": "user", "content": "You are consulted by SCHEDULING; ..."}]})
    assert peer == "Take R2, it is free."
    final = respond({"messages": [{"role": "user", "content": "Decide"},
                                  {"role": "tool", "tool_call_id": "call_1",
                                   "content": "Take R2, it is free."}], "tools": tools})
    assert final == "DECISION: R2"
