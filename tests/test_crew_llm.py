"""`build_llm` routes to CrewAI's ollama provider; `OllamaAudit` sees every call (spec 10)."""
import dataclasses
import types

import httpx
import pytest
from crewai.llms.hooks.transport import HTTPTransport

from post_office.crew import llm as llm_module
from post_office.crew.audit import NO_RESPONSE, OllamaAudit, calling
from post_office.crew.llm import UnexpectedProviderError, build_llm


def test_build_llm_routes_to_crewai_ollama_provider(fake_ollama):
    llm = build_llm(fake_ollama.settings)
    print(type(llm).__name__, llm.provider, llm.base_url)
    assert type(llm).__name__ == "OpenAICompatibleCompletion"
    assert llm.provider == "ollama" and llm.model == "qwen3:8b"
    assert llm.base_url == fake_ollama.base_url + "/v1"
    assert llm.max_retries == 0


def test_no_cloud_key_is_read(monkeypatch, fake_ollama):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-matter")
    assert build_llm(fake_ollama.settings).api_key != "sk-should-not-matter"


def test_audit_refuses_a_foreign_host(fake_ollama):
    audit = OllamaAudit(fake_ollama.settings, on_call=lambda r: None)
    with pytest.raises(UnexpectedProviderError):
        audit.on_outbound(httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))


def test_audit_records_served_model_and_latency(fake_ollama):
    seen = []
    llm = build_llm(fake_ollama.settings, OllamaAudit(fake_ollama.settings, seen.append))
    fake_ollama.script(lambda req: "R1")
    with calling("SCHEDULING", "owner"):
        out = llm.call("Answer R1 or R2")
    assert out.strip() == "R1" and seen[0].served_model == "qwen3:8b" and seen[0].agent_id == "SCHEDULING"


def test_audit_record_carries_url_usage_status_and_phase(fake_ollama):
    audit = OllamaAudit(fake_ollama.settings, on_call=lambda r: None)
    llm = build_llm(fake_ollama.settings, audit)
    with calling("ROUTING", "peer"):
        llm.call("Allowed answers:\n- R2\n- R3")
    (rec,) = audit.records
    assert rec.url == fake_ollama.base_url + "/v1/chat/completions"
    assert (rec.agent_id, rec.phase, rec.requested_model, rec.status, rec.error) == \
        ("ROUTING", "peer", "qwen3:8b", 200, "")
    assert rec.prompt_tokens and rec.completion_tokens and rec.latency_ms >= 0
    assert len(rec.call_id) == 12


def test_audit_outside_calling_is_unattributed(fake_ollama):
    audit = OllamaAudit(fake_ollama.settings, on_call=lambda r: None)
    build_llm(fake_ollama.settings, audit).call("hello")
    assert (audit.records[0].agent_id, audit.records[0].phase) == ("", "")


def _audited_client(audit):
    # CrewAI's own interceptor transport, without the LLM layer (which would retry a 500
    # and print a console panel for it)
    return httpx.Client(transport=HTTPTransport(interceptor=audit), trust_env=False, timeout=5)


def test_audit_records_a_server_error_without_raising(fake_ollama):
    audit = OllamaAudit(fake_ollama.settings, on_call=lambda r: None)
    fake_ollama.fail_with(500)
    with _audited_client(audit) as client:
        r = client.post(fake_ollama.base_url + "/v1/chat/completions",
                        json={"model": "qwen3:8b", "messages": []})
    assert r.status_code == 500 and r.json()["error"]["message"] == "fake failure 500"
    (rec,) = audit.records
    assert rec.status == 500 and rec.error == "HTTP 500" and rec.served_model == ""


def test_audit_records_an_unreadable_reply_and_passes_it_on(fake_ollama):
    seen = []
    audit = OllamaAudit(fake_ollama.settings, on_call=seen.append)
    response = httpx.Response(200, content=b"not json", request=httpx.Request("GET", "http://x"))
    assert audit.on_inbound(response) is response and response.content == b"not json"
    assert seen[-1].error.startswith("unreadable reply") and seen[-1].status == 200


def test_a_failing_callback_never_breaks_the_call(fake_ollama):
    def boom(record):
        raise RuntimeError("logger down")

    audit = OllamaAudit(fake_ollama.settings, on_call=boom)
    assert build_llm(fake_ollama.settings, audit).call("hello").strip() == "OK"
    assert len(audit.records) == 1 and isinstance(audit.callback_errors[0], RuntimeError)


def test_audit_reports_the_model_actually_served(fake_ollama):
    seen = []
    fake_ollama.serve_models(["qwen3:4b"])
    build_llm(fake_ollama.settings, OllamaAudit(fake_ollama.settings, seen.append)).call("hello")
    assert (seen[0].requested_model, seen[0].served_model) == ("qwen3:8b", "qwen3:4b")


def test_thinking_off_asks_ollama_for_no_reasoning(fake_ollama):
    build_llm(fake_ollama.settings).call("hello")
    body = fake_ollama.requests[-1]
    assert body["reasoning_effort"] == "none"
    assert body["model"] == "qwen3:8b" and body["seed"] == 42 and body["temperature"] == 0


def test_thinking_prompt_leaves_the_request_alone(fake_ollama):
    settings = dataclasses.replace(fake_ollama.settings, thinking="prompt")
    build_llm(settings).call("hello")
    assert "reasoning_effort" not in fake_ollama.requests[-1]


def test_build_llm_refuses_a_different_provider(monkeypatch, fake_ollama):
    impostor = types.SimpleNamespace(provider="openai", model="qwen3:8b",
                                     base_url=fake_ollama.base_url + "/v1")
    monkeypatch.setattr(llm_module, "LLM", lambda **kwargs: impostor)
    with pytest.raises(UnexpectedProviderError, match="provider"):
        build_llm(fake_ollama.settings)


def test_transport_failure_is_recorded(fake_ollama, quiet_crewai_console):
    settings = dataclasses.replace(fake_ollama.settings, timeout=1)
    audit = OllamaAudit(settings, on_call=lambda r: None)
    llm = build_llm(settings, audit)
    assert llm.max_retries == 0
    fake_ollama.delay(2.5)
    with calling("ROUTING", "peer"):
        with pytest.raises(Exception):
            llm.call("hello")
    (rec,) = audit.records
    assert rec.status is None and rec.error == NO_RESPONSE and rec.served_model == ""
    assert (rec.agent_id, rec.phase) == ("ROUTING", "peer") and rec.latency_ms >= 900
    assert len(fake_ollama.requests) == 1  # one call, one attempt


def test_an_unanswered_attempt_is_recorded_by_the_next_one(fake_ollama):
    audit = OllamaAudit(fake_ollama.settings, on_call=lambda r: None)
    url = fake_ollama.base_url + "/v1/chat/completions"
    audit.on_outbound(httpx.Request("POST", url, json={"model": "qwen3:8b"}))  # never answered
    assert audit.records == []
    with _audited_client(audit) as client:
        client.post(url, json={"model": "qwen3:8b", "messages": []})
    first, second = audit.records
    assert (first.status, first.error) == (None, NO_RESPONSE)
    assert (second.status, second.error) == (200, "")
    assert audit.flush_pending() is None  # nothing left in flight
