"""
The one LLM all seven experts share (spec 10).

`build_llm` asks CrewAI for `ollama/<model>` at the configured base URL and then
checks what it got: CrewAI 1.15 serves the ollama provider through its
OpenAI-compatible completion class at `<base_url>/v1`. Anything else (another
class, provider, model or endpoint) means a CrewAI change has re-routed the
experts, and is refused rather than run.

The API key is passed explicitly as "ollama" (Ollama ignores it), so CrewAI never
falls back to OLLAMA_API_KEY or any cloud key in the environment.

The OpenAI client's own retries are switched off (`max_retries=0`): one model call
is one HTTP attempt, so audit records, latencies and the consultation deadline
stay predictable. CrewAI's agent-level re-run is off as well (`max_retry_limit=0`
in `roles.py`), so a failed call is never repeated.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from crewai import LLM
from crewai.llms.hooks.base import BaseInterceptor

from ..config.ollama import OllamaSettings

EXPECTED_CLASS = "OpenAICompatibleCompletion"
EXPECTED_PROVIDER = "ollama"
#: The key handed to the OpenAI client. Ollama does not check it.
OLLAMA_API_KEY = "ollama"
#: Retries inside the OpenAI client per model call: none.
MAX_RETRIES = 0


class UnexpectedProviderError(RuntimeError):
    """A model call would go, or went, somewhere other than the configured Ollama."""


def build_llm(settings: OllamaSettings,
              interceptor: Optional[BaseInterceptor] = None) -> LLM:
    kwargs: Dict[str, Any] = dict(
        model=settings.model_string, base_url=settings.base_url, api_key=OLLAMA_API_KEY,
        temperature=settings.temperature, seed=settings.seed, timeout=settings.timeout,
        max_tokens=settings.max_tokens, max_retries=MAX_RETRIES, interceptor=interceptor)
    if settings.thinking == "off":
        kwargs["additional_params"] = {"extra_body": {"reasoning_effort": "none"}}
    llm = LLM(**kwargs)

    expected_url = settings.base_url.rstrip("/") + "/v1"
    checks = (("class", type(llm).__name__, EXPECTED_CLASS),
              ("provider", getattr(llm, "provider", None), EXPECTED_PROVIDER),
              ("model", getattr(llm, "model", None), settings.model),
              ("base_url", getattr(llm, "base_url", None), expected_url),
              ("max_retries", getattr(llm, "max_retries", None), MAX_RETRIES))
    wrong = [f"{what} is {got!r}, expected {want!r}" for what, got, want in checks if got != want]
    if wrong:
        raise UnexpectedProviderError(
            f"CrewAI did not build an Ollama LLM for {settings.model_string}: " + "; ".join(wrong))
    return llm
