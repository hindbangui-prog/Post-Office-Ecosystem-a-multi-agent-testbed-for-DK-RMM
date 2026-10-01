"""`OllamaSettings` and `load_settings` (spec 10): defaults, model switch, refusal, `.env`."""
import os

import pytest

from post_office.config.ollama import InvalidModelName, OllamaSettings, load_settings


def test_defaults_are_the_baseline_model_on_local_ollama():
    s = load_settings(env={}, dotenv=False)
    assert s == OllamaSettings(base_url="http://localhost:11434", model="qwen3:8b", timeout=120,
                               seed=42, temperature=0.0, max_tokens=512, thinking="off",
                               consult_deadline_s=300.0)
    assert s.model_string == "ollama/qwen3:8b"
    assert s.host == "http://localhost:11434"


def test_switching_the_model_is_one_variable():
    s = load_settings(env={"OLLAMA_MODEL": "gemma4:26b"}, dotenv=False)
    assert s.model == "gemma4:26b" and s.model_string == "ollama/gemma4:26b"


def test_every_variable_is_read():
    s = load_settings(env={"OLLAMA_BASE_URL": "http://127.0.0.1:9999/", "OLLAMA_TIMEOUT": "30",
                           "OLLAMA_SEED": "7", "OLLAMA_TEMPERATURE": "0.5",
                           "OLLAMA_MAX_TOKENS": "64", "OLLAMA_THINKING": "prompt",
                           "CONSULT_DEADLINE_S": "12.5"}, dotenv=False)
    assert (s.base_url, s.timeout, s.seed, s.temperature, s.max_tokens, s.thinking,
            s.consult_deadline_s) == ("http://127.0.0.1:9999", 30, 7, 0.5, 64, "prompt", 12.5)
    assert s.host == "http://127.0.0.1:9999"


def test_seed_none_disables_the_seed():
    assert load_settings(env={"OLLAMA_SEED": "none"}, dotenv=False).seed is None


@pytest.mark.parametrize("model", ["openai/gpt-4o", "anthropic/claude", "ollama/qwen3:8b"])
def test_a_model_with_a_provider_prefix_is_refused(model):
    with pytest.raises(InvalidModelName):
        load_settings(env={"OLLAMA_MODEL": model}, dotenv=False)


def test_unknown_thinking_mode_is_refused():
    with pytest.raises(ValueError, match="OLLAMA_THINKING"):
        load_settings(env={"OLLAMA_THINKING": "maybe"}, dotenv=False)


def test_bad_number_names_the_variable():
    with pytest.raises(ValueError, match="OLLAMA_TIMEOUT"):
        load_settings(env={"OLLAMA_TIMEOUT": "soon"}, dotenv=False)


def test_dotenv_is_read_only_when_asked(tmp_path):
    (tmp_path / ".env").write_text("OLLAMA_MODEL=gemma4:26b\nOLLAMA_TIMEOUT=60\n")
    before = dict(os.environ)
    assert load_settings(env={}, dotenv=True, root=tmp_path).model == "gemma4:26b"
    assert load_settings(env={}, dotenv=False, root=tmp_path).model == "qwen3:8b"
    assert dict(os.environ) == before  # .env is read, never exported


def test_environment_overrides_dotenv(tmp_path):
    (tmp_path / ".env").write_text("OLLAMA_MODEL=gemma4:26b\nOLLAMA_TIMEOUT=60\n")
    s = load_settings(env={"OLLAMA_MODEL": "qwen3:4b"}, dotenv=True, root=tmp_path)
    assert s.model == "qwen3:4b" and s.timeout == 60


def test_missing_dotenv_is_fine(tmp_path):
    assert load_settings(env={}, dotenv=True, root=tmp_path).model == "qwen3:8b"


def test_as_dict_is_plain_and_complete():
    d = load_settings(env={}, dotenv=False).as_dict()
    assert d == {"base_url": "http://localhost:11434", "model": "qwen3:8b", "timeout": 120,
                 "seed": 42, "temperature": 0.0, "max_tokens": 512, "thinking": "off",
                 "consult_deadline_s": 300.0}


def test_settings_are_frozen():
    s = load_settings(env={}, dotenv=False)
    with pytest.raises(Exception):
        s.model = "other"  # type: ignore[misc]
