"""
The transport audit: every model call, as the wire saw it (spec 10).

`OllamaAudit` is CrewAI's transport interceptor. `on_outbound` refuses any
request whose host is not the configured Ollama host, before it leaves the
process; `on_inbound` reads the reply and records the model Ollama says it
served, the latency, the token usage and the HTTP status. Each pair becomes one
`LLMCallRecord`, kept in `records` and handed to `on_call`.

The agent and phase a call belongs to are not visible on the wire, so the code
that runs an agent says so with `with calling(agent_id, phase): ...`; the
interceptor reads that context variable on the same thread (or asyncio task).

`on_inbound` never raises: an unreadable reply is recorded with `error` set and
passed on to the client unchanged, so the audit cannot turn a good reply into a
failure or trigger a retry.

A request that gets no response at all (timeout, refused or reset connection)
never reaches `on_inbound`. It stays in flight until the next `on_outbound` on
the same thread/task, or the end of the enclosing `calling` block, or an
explicit `flush_pending()`, and is then recorded with `status=None` and
`error=NO_RESPONSE`, so every attempt leaves exactly one record.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx
from crewai.llms.hooks.base import BaseInterceptor

from ..config.ollama import OllamaSettings
from .llm import UnexpectedProviderError

#: (agent_id, phase) of the model call being made, set by `calling`.
_CALLING: contextvars.ContextVar[Tuple[str, str]] = contextvars.ContextVar(
    "ollama_calling", default=("", ""))

#: The request in flight on this thread/task:
#: (audit, url, requested model, start, (agent_id, phase)).
_IN_FLIGHT: contextvars.ContextVar[Optional[Tuple[Any, str, str, float, Tuple[str, str]]]] = \
    contextvars.ContextVar("ollama_in_flight", default=None)

NO_RESPONSE = "no response (transport error or timeout)"

#: Port of a URL that names none, as CrewAI would fill it for Ollama (http) or https.
_DEFAULT_PORTS = {"http": 11434, "https": 443}


@dataclass
class LLMCallRecord:
    call_id: str
    agent_id: str
    phase: str
    url: str
    requested_model: str
    served_model: str
    latency_ms: float
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    status: Optional[int]
    error: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@contextlib.contextmanager
def calling(agent_id: str, phase: str) -> Iterator[None]:
    """Attribute the model calls made inside this block to `agent_id` in `phase`."""
    token = _CALLING.set((agent_id, phase))
    try:
        yield
    finally:
        pending = _IN_FLIGHT.get()
        if pending is not None:  # the block's last attempt never got a response
            pending[0].flush_pending()
        _CALLING.reset(token)


def current_call() -> Tuple[str, str]:
    """(agent_id, phase) set by the innermost `calling`, or ("", "")."""
    return _CALLING.get()


def _origin(url: str) -> Tuple[str, str, int]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), parts.port or _DEFAULT_PORTS.get(scheme, 0)


def _requested_model(request: httpx.Request) -> str:
    try:
        return str(json.loads(request.content).get("model") or "")
    except Exception:  # a streamed or non-JSON body: the configured model stands
        return ""


def _int_or_none(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class OllamaAudit(BaseInterceptor[httpx.Request, httpx.Response]):
    def __init__(self, settings: OllamaSettings,
                 on_call: Callable[[LLMCallRecord], None]) -> None:
        self.settings = settings
        self.on_call = on_call
        self.records: List[LLMCallRecord] = []
        #: Exceptions raised by `on_call`; kept, not raised into the transport.
        self.callback_errors: List[BaseException] = []
        self._origin = _origin(settings.host)

    # outbound

    def on_outbound(self, message: httpx.Request) -> httpx.Request:
        self.flush_pending()  # the previous attempt on this thread/task got no response
        url = str(message.url)
        requested = _requested_model(message) or self.settings.model
        if _origin(url) != self._origin:
            self._emit(url, requested, "", 0.0, None, None, None,
                       f"refused: host is not the configured Ollama {self.settings.host}")
            raise UnexpectedProviderError(
                f"refusing a model call to {url}: the configured Ollama host is "
                f"{self.settings.host}")
        _IN_FLIGHT.set((self, url, requested, time.perf_counter(), _CALLING.get()))
        return message

    def flush_pending(self, error: str = NO_RESPONSE) -> Optional[LLMCallRecord]:
        """Record this audit's request still in flight here, if any, as unanswered."""
        pending = _IN_FLIGHT.get()
        if pending is None or pending[0] is not self:
            return None
        _IN_FLIGHT.set(None)
        _, url, requested, start, who = pending
        return self._emit(url, requested, "", (time.perf_counter() - start) * 1000.0,
                          None, None, None, error, who=who)

    async def aon_outbound(self, message: httpx.Request) -> httpx.Request:
        return self.on_outbound(message)

    # inbound

    def on_inbound(self, message: httpx.Response) -> httpx.Response:
        try:
            body: Optional[bytes] = None
            if not self._is_stream(message):
                message.read()
                body = message.content
            self._record(message, body)
        except Exception as exc:  # never let the audit break the call
            self._record_failure(message, exc)
        return message

    async def aon_inbound(self, message: httpx.Response) -> httpx.Response:
        try:
            body: Optional[bytes] = None
            if not self._is_stream(message):
                await message.aread()
                body = message.content
            self._record(message, body)
        except Exception as exc:
            self._record_failure(message, exc)
        return message

    # recording

    @staticmethod
    def _is_stream(response: httpx.Response) -> bool:
        return "text/event-stream" in response.headers.get("content-type", "")

    def _take_in_flight(self) -> Tuple[str, str, Optional[float], Optional[Tuple[str, str]]]:
        pending = _IN_FLIGHT.get()
        if pending is None or pending[0] is not self:
            return self.settings.base_url, self.settings.model, None, None
        _IN_FLIGHT.set(None)
        return pending[1], pending[2], pending[3], pending[4]

    def _record(self, response: httpx.Response, body: Optional[bytes]) -> None:
        url, requested, start, who = self._take_in_flight()
        latency = (time.perf_counter() - start) * 1000.0 if start is not None else 0.0
        status = response.status_code
        served, prompt_tokens, completion_tokens, error = "", None, None, ""
        if body is None:
            error = "streamed response: model and usage not read"
        else:
            try:
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError("reply is not a JSON object")
                served = str(data.get("model") or "")
                usage = data.get("usage") or {}
                prompt_tokens = _int_or_none(usage.get("prompt_tokens"))
                completion_tokens = _int_or_none(usage.get("completion_tokens"))
            except Exception as exc:
                error = f"unreadable reply: {type(exc).__name__}: {exc}"
        if status >= 400 and not error:
            error = f"HTTP {status}"
        self._emit(url, requested, served, latency, prompt_tokens, completion_tokens, status, error,
                   who=who)

    def _record_failure(self, response: httpx.Response, exc: BaseException) -> None:
        try:
            url, requested, _, who = self._take_in_flight()
            self._emit(url, requested, "", 0.0, None, None,
                       getattr(response, "status_code", None),
                       f"audit failed: {type(exc).__name__}: {exc}", who=who)
        except Exception as again:  # pragma: no cover - last resort, keep the call alive
            self.callback_errors.append(again)

    def _emit(self, url: str, requested: str, served: str, latency_ms: float,
              prompt_tokens: Optional[int], completion_tokens: Optional[int],
              status: Optional[int], error: str,
              who: Optional[Tuple[str, str]] = None) -> LLMCallRecord:
        agent_id, phase = who if who is not None else _CALLING.get()
        record = LLMCallRecord(call_id=uuid.uuid4().hex[:12], agent_id=agent_id, phase=phase,
                               url=url, requested_model=requested, served_model=served,
                               latency_ms=round(latency_ms, 3), prompt_tokens=prompt_tokens,
                               completion_tokens=completion_tokens, status=status, error=error)
        self.records.append(record)
        try:
            self.on_call(record)
        except Exception as exc:
            self.callback_errors.append(exc)
        return record
