"""
Where the model lives and how it is asked: the Ollama settings (spec 10).

Every value comes from the environment, over an optional `.env` in the project
root, over the defaults below. The `.env` file is read with python-dotenv's
`dotenv_values` and never exported, so loading settings does not change
`os.environ` for anything else in the process.

A model name containing "/" is refused: CrewAI reads the text before a slash as
the provider, so "openai/gpt-4o" would quietly route the experts to a cloud
service. The provider is always "ollama"; only the model name is configurable.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional
from urllib.parse import urlsplit

#: The project root, where an optional `.env` is looked for.
ROOT = Path(__file__).resolve().parents[2]

#: Accepted values of OLLAMA_THINKING. "off" asks Ollama to switch reasoning off
#: (`reasoning_effort="none"`); "prompt" leaves the request alone and lets the
#: role prompt carry `/no_think`.
THINKING_MODES = ("off", "prompt")

DEFAULTS: Dict[str, str] = {
    "OLLAMA_BASE_URL": "http://localhost:11434",
    "OLLAMA_MODEL": "qwen3:8b",
    "OLLAMA_TIMEOUT": "120",
    "OLLAMA_SEED": "42",
    "OLLAMA_TEMPERATURE": "0",
    "OLLAMA_MAX_TOKENS": "512",
    "OLLAMA_THINKING": "off",
    "CONSULT_DEADLINE_S": "300",
}


class InvalidModelName(ValueError):
    """The configured model would select a CrewAI provider other than Ollama."""


@dataclass(frozen=True)
class OllamaSettings:
    base_url: str
    model: str
    timeout: int
    seed: Optional[int]
    temperature: float
    max_tokens: int
    thinking: str
    consult_deadline_s: float

    def __post_init__(self) -> None:
        if not self.model or "/" in self.model:
            raise InvalidModelName(
                f"OLLAMA_MODEL={self.model!r} is not an Ollama model name; give the bare "
                f"name (e.g. 'qwen3:8b'), the provider is always ollama")
        if self.thinking not in THINKING_MODES:
            raise ValueError(f"OLLAMA_THINKING={self.thinking!r}; expected one of "
                             f"{', '.join(THINKING_MODES)}")
        parts = urlsplit(self.base_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"OLLAMA_BASE_URL={self.base_url!r} is not an http(s) URL")

    @property
    def model_string(self) -> str:
        """The model as CrewAI's `LLM` takes it."""
        return f"ollama/{self.model}"

    @property
    def host(self) -> str:
        """Scheme and network location of the Ollama server, e.g. 'http://localhost:11434'."""
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _number(name: str, raw: str, cast: Callable[[str], Any]) -> Any:
    try:
        return cast(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a valid {cast.__name__}") from None


def _seed(raw: str) -> Optional[int]:
    if raw.strip().lower() in ("none", "null", "off"):
        return None
    return _number("OLLAMA_SEED", raw, int)


def load_settings(env: Mapping[str, str] | None = None, dotenv: bool = True,
                  root: Path | None = None) -> OllamaSettings:
    """
    The settings from `env` (default: `os.environ`) over `<root>/.env` (when
    `dotenv` is true and the file exists) over `DEFAULTS`. Empty values count as
    unset.
    """
    values: Dict[str, str] = dict(DEFAULTS)
    if dotenv:
        path = (root if root is not None else ROOT) / ".env"
        if path.is_file():
            from dotenv import dotenv_values

            values.update({k: v for k, v in dotenv_values(path).items()
                           if k in DEFAULTS and v not in (None, "")})
    source = os.environ if env is None else env
    values.update({k: source[k] for k in DEFAULTS if source.get(k) not in (None, "")})

    return OllamaSettings(
        base_url=values["OLLAMA_BASE_URL"].strip().rstrip("/"),
        model=values["OLLAMA_MODEL"].strip(),
        timeout=_number("OLLAMA_TIMEOUT", values["OLLAMA_TIMEOUT"], int),
        seed=_seed(values["OLLAMA_SEED"]),
        temperature=_number("OLLAMA_TEMPERATURE", values["OLLAMA_TEMPERATURE"], float),
        max_tokens=_number("OLLAMA_MAX_TOKENS", values["OLLAMA_MAX_TOKENS"], int),
        thinking=values["OLLAMA_THINKING"].strip().lower(),
        consult_deadline_s=_number("CONSULT_DEADLINE_S", values["CONSULT_DEADLINE_S"], float),
    )
