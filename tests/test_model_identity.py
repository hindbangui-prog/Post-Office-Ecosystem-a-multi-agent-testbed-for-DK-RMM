"""`verify_model` / `require_model` (spec 10): the configured model is the one installed."""
import dataclasses
import socket

import pytest

from post_office.crew.identity import ModelUnavailable, require_model, verify_model


def test_installed_model_is_identified(fake_ollama):
    ident = verify_model(fake_ollama.settings)
    assert ident.ok is True and ident.problems == []
    assert (ident.model, ident.base_url, ident.digest) == ("qwen3:8b", fake_ollama.base_url,
                                                          "fake-qwen3:8b")
    assert (ident.family, ident.parameter_size, ident.quantization) == ("qwen3", "8.2B", "Q4_K_M")
    assert ident.installed == ["qwen3:8b"]
    assert ident.as_dict()["digest"] == "fake-qwen3:8b"
    assert ("GET", "/api/tags") in fake_ollama.calls and ("POST", "/api/show") in fake_ollama.calls
    assert require_model(fake_ollama.settings) == ident


def test_missing_model_refuses_and_names_installed(fake_ollama):
    fake_ollama.serve_models(["qwen3:4b"])
    ident = verify_model(fake_ollama.settings)
    assert ident.ok is False and ident.installed == ["qwen3:4b"]
    assert ident.problems == ["model qwen3:8b is not installed; installed: qwen3:4b"]
    with pytest.raises(ModelUnavailable, match="qwen3:4b") as caught:
        require_model(fake_ollama.settings)
    assert caught.value.identity.ok is False


def test_unreachable_server_is_reported_not_raised(fake_ollama):
    with socket.socket() as s:  # a port nobody listens on
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    settings = dataclasses.replace(fake_ollama.settings, base_url=f"http://127.0.0.1:{port}")
    ident = verify_model(settings, timeout=2.0)
    assert ident.ok is False
    assert ident.problems[0].startswith("cannot reach")
    assert f"http://127.0.0.1:{port}" in ident.problems[0]
    with pytest.raises(ModelUnavailable, match="cannot reach"):
        require_model(settings)


def test_untagged_name_matches_latest(fake_ollama):
    fake_ollama.serve_models(["qwen3:latest"])
    settings = dataclasses.replace(fake_ollama.settings, model="qwen3")
    ident = verify_model(settings)
    assert ident.ok is True and ident.digest == "fake-qwen3:latest" and ident.family == "qwen3"


def test_listed_but_unshowable_model_is_a_problem(fake_ollama, monkeypatch):
    monkeypatch.setattr(fake_ollama, "_show", lambda body: (500, {"error": "broken"}))
    ident = verify_model(fake_ollama.settings)
    assert ident.ok is False and ident.digest == "fake-qwen3:8b"
    assert ident.problems == ["cannot show model qwen3:8b: HTTP 500"]
