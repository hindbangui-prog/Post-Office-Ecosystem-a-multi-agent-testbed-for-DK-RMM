"""
Which model the experts will actually talk to (spec 10).

`verify_model` asks the Ollama server itself: `GET /api/tags` for the installed
models (and the configured model's digest), then `POST /api/show` for its family,
parameter size and quantization. It never raises for a server problem; it
returns a `ModelIdentity` with `ok` false and the problems spelled out.
`require_model` raises `ModelUnavailable` instead, so a run never starts on a
model that is not there, and nothing is substituted.

Only the standard library is used (no CrewAI import), and system proxy settings
are bypassed: the server is the local Ollama, and a proxy answering in its place
would make the identity meaningless.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..config.ollama import OllamaSettings

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ModelUnavailable(RuntimeError):
    """The configured model cannot be used; `identity` says why."""

    def __init__(self, identity: "ModelIdentity") -> None:
        super().__init__("; ".join(identity.problems) or "model unavailable")
        self.identity = identity


@dataclass
class ModelIdentity:
    model: str
    base_url: str
    digest: str = ""
    family: str = ""
    parameter_size: str = ""
    quantization: str = ""
    installed: List[str] = field(default_factory=list)
    ok: bool = False
    problems: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _request(url: str, timeout: float, payload: Optional[Dict[str, Any]] = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="GET" if data is None else "POST",
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json"})
    with _OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


class _Unexpected(ValueError):
    """A reply that is JSON but not shaped as Ollama's."""


def _reason(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, _Unexpected):
        return str(exc)
    if isinstance(exc, ValueError):
        return f"not JSON ({type(exc).__name__}: {exc})"
    if isinstance(exc, urllib.error.URLError):
        return str(exc.reason)
    return f"{type(exc).__name__}: {exc}"


def _find(models: List[Dict[str, Any]], wanted: str) -> Optional[Dict[str, Any]]:
    """The tags entry for `wanted`; an untagged name means ':latest', as in Ollama."""
    names = {wanted} if ":" in wanted else {wanted, wanted + ":latest"}
    for entry in models:
        if entry.get("name") in names or entry.get("model") in names:
            return entry
    return None


def verify_model(settings: OllamaSettings, timeout: float = 5.0) -> ModelIdentity:
    base = settings.base_url.rstrip("/")
    ident = ModelIdentity(model=settings.model, base_url=base)

    try:
        tags = _request(base + "/api/tags", timeout)
        if not isinstance(tags, dict) or not isinstance(tags.get("models", []), list):
            raise _Unexpected("not an Ollama model list")
        models = [m for m in (tags.get("models") or []) if isinstance(m, dict)]
    except (urllib.error.HTTPError, ValueError) as exc:  # answered, but not as Ollama does
        ident.problems.append(f"unexpected reply from {base}: /api/tags {_reason(exc)}")
        return ident
    except (urllib.error.URLError, OSError) as exc:
        ident.problems.append(f"cannot reach {base}: {_reason(exc)}")
        return ident

    ident.installed = sorted(str(m.get("name") or m.get("model") or "") for m in models)
    entry = _find(models, settings.model)
    if entry is None:
        ident.problems.append(f"model {settings.model} is not installed; installed: "
                              f"{', '.join(ident.installed) or 'none'}")
        return ident
    ident.digest = str(entry.get("digest") or "")

    try:
        shown = _request(base + "/api/show", timeout, {"model": entry.get("name") or settings.model})
        details = shown.get("details") if isinstance(shown, dict) else None
        if not isinstance(details, dict):
            raise _Unexpected("no model details")
    except urllib.error.HTTPError as exc:
        ident.problems.append(f"cannot show model {settings.model}: {_reason(exc)}")
        return ident
    except ValueError as exc:
        ident.problems.append(f"unexpected reply from {base}: /api/show {_reason(exc)}")
        return ident
    except (urllib.error.URLError, OSError) as exc:
        ident.problems.append(f"cannot reach {base}: {_reason(exc)}")
        return ident

    ident.family = str(details.get("family") or "")
    ident.parameter_size = str(details.get("parameter_size") or "")
    ident.quantization = str(details.get("quantization_level") or "")
    ident.ok = not ident.problems
    return ident


def require_model(settings: OllamaSettings, timeout: float = 5.0) -> ModelIdentity:
    """`verify_model`, raising `ModelUnavailable` unless the model is there."""
    ident = verify_model(settings, timeout=timeout)
    if not ident.ok:
        raise ModelUnavailable(ident)
    return ident
