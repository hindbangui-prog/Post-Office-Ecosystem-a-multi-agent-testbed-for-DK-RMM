"""
A fake Ollama server for the tests, loaded as a pytest plugin by `conftest.py`.

It is a stdlib `http.server` on 127.0.0.1, port 0, in a daemon thread, and speaks
just enough of Ollama's API for CrewAI and `crew/identity.py`:

- `GET /api/tags` lists the served models (default `["qwen3:8b"]`), digest "fake-<name>";
- `POST /api/show` returns qwen3/8.2B/Q4_K_M details for a served model, 404 otherwise;
- `POST /v1/chat/completions` (OpenAI-compatible) answers with what the responder
  returns: a string is a plain assistant reply, `{"tool": name, "args": {...}}` is a
  native `tool_calls` reply (`{"tool": name, "raw_args": "<text>"}` sends the
  arguments string as given, e.g. malformed JSON). Every reply names the first
  served model and has a `usage` block.

`FakeOllama.requests` holds the parsed bodies of the chat-completion requests, in
order. Without `.script(...)` the reply is the first allowed answer found in the
last user message (the `Allowed answers:` list), else "OK".
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Union

import pytest

from post_office.config.ollama import OllamaSettings

Reply = Union[str, Dict[str, Any]]
Responder = Callable[[Dict[str, Any]], Reply]

_ALLOWED = re.compile(r"Allowed answers:\s*\n\s*[-*]\s*(\S[^\n]*)", re.I)
_COWORKERS = re.compile(r"coworkers:\s*([^\n]+)", re.I)


def text_of(message: Dict[str, Any]) -> str:
    """A chat message's text, whether its content is a string or a list of parts."""
    content = message.get("content")
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def default_responder(body: Dict[str, Any]) -> Reply:
    users = [m for m in body.get("messages", []) if m.get("role") == "user"]
    found = _ALLOWED.search(text_of(users[-1])) if users else None
    return found.group(1).strip() if found else "OK"


def _tool_args(tool: Dict[str, Any], peer: str) -> Dict[str, str]:
    fields = tool.get("function", {}).get("parameters", {}).get("properties") or {
        "question": {}, "context": {}, "coworker": {}}
    args = {}
    for name in fields:
        if name == "coworker":
            args[name] = peer
        elif name == "context":
            args[name] = "I am deciding and want your view from your own facts."
        else:
            args[name] = "Which allowed answer do you recommend, and why?"
    return args


def consultation_script(peer_reply: str, decide: Callable[[str], str]) -> Responder:
    """
    A responder for one owner-peer-owner consultation:

    - a call carrying "consulted by" in a system or user message is the peer's:
      it gets `peer_reply`;
    - an owner call that already holds a `tool` message gets
      `DECISION: <decide(tool text)>`;
    - an owner call offered tools gets a tool call to the first offered tool,
      naming as coworker the first role listed in that tool's description;
    - any other call gets `DECISION: <decide("")>`.
    """

    def respond(body: Dict[str, Any]) -> Reply:
        messages = body.get("messages", [])
        if any("consulted by" in text_of(m) for m in messages
               if m.get("role") in ("system", "user")):
            return peer_reply
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        if tool_messages:
            return f"DECISION: {decide(text_of(tool_messages[-1]))}"
        tools = body.get("tools") or []
        if tools:
            found = _COWORKERS.search(tools[0].get("function", {}).get("description", ""))
            peer = found.group(1).split(",")[0].strip() if found else ""
            return {"tool": tools[0]["function"]["name"], "args": _tool_args(tools[0], peer)}
        return f"DECISION: {decide('')}"

    return respond


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        import sys

        if isinstance(sys.exc_info()[1], ConnectionError):
            return  # the client hung up (a timeout under delay()); nothing to report
        super().handle_error(request, client_address)


def _words(text: str) -> int:
    return max(1, len(text.split()))


class FakeOllama:
    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []
        self.calls: List[tuple] = []  # (method, path) of every request, any endpoint
        self.errors: List[BaseException] = []  # exceptions raised by the responder
        self.served: List[str] = ["qwen3:8b"]
        self._responder: Responder = default_responder
        self._delay = 0.0
        self._fail: Optional[int] = None
        self._raw: Dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._server = _QuietServer(("127.0.0.1", 0), _handler_for(self))
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.02},
                                        name="fake-ollama", daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def settings(self) -> OllamaSettings:
        return OllamaSettings(base_url=self.base_url, model="qwen3:8b", timeout=10, seed=42,
                              temperature=0.0, max_tokens=512, thinking="off",
                              consult_deadline_s=30)

    def script(self, responder: Responder) -> None:
        self._responder = responder

    def serve_models(self, names: List[str]) -> None:
        self.served = list(names)

    def delay(self, seconds: float) -> None:
        self._delay = seconds

    def fail_with(self, status: Optional[int]) -> None:
        """Answer every chat completion with this HTTP status (None: stop failing)."""
        self._fail = status

    def respond_raw(self, path: str, status: int, body: bytes,
                    content_type: str = "text/html") -> None:
        """Answer every request to `path` with these exact bytes (e.g. a non-Ollama server)."""
        self._raw[path] = (status, body, content_type)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    # request handling, called from the server threads

    def _served_model(self) -> str:
        return self.served[0] if self.served else "qwen3:8b"

    def _tags(self) -> Dict[str, Any]:
        return {"models": [{"name": m, "model": m, "digest": "fake-" + m, "size": 1,
                            "modified_at": "2026-10-01T00:00:00Z",
                            "details": {"family": "qwen3", "parameter_size": "8.2B",
                                        "quantization_level": "Q4_K_M"}}
                           for m in self.served]}

    def _show(self, body: Dict[str, Any]) -> tuple:
        name = body.get("model") or body.get("name")
        if name not in self.served:
            return 404, {"error": f"model '{name}' not found"}
        return 200, {"details": {"family": "qwen3", "parameter_size": "8.2B",
                                 "quantization_level": "Q4_K_M"}}

    def _chat(self, body: Dict[str, Any]) -> tuple:
        with self._lock:
            self.requests.append(body)
        if self._delay:
            time.sleep(self._delay)
        if self._fail is not None:
            return self._fail, {"error": {"message": f"fake failure {self._fail}",
                                          "type": "server_error", "code": self._fail}}
        if body.get("stream"):
            return 400, {"error": {"message": "the fake Ollama does not stream",
                                   "type": "invalid_request_error"}}
        try:
            reply = self._responder(body)
        except Exception as exc:  # surfaced to the test through .errors and a 500
            self.errors.append(exc)
            return 500, {"error": {"message": f"responder raised {exc!r}", "type": "server_error"}}
        if isinstance(reply, dict):
            arguments = (reply["raw_args"] if "raw_args" in reply
                         else json.dumps(reply.get("args", {})))
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": reply["tool"], "arguments": arguments}}]}
            finish, out_text = "tool_calls", json.dumps(reply)
        else:
            message = {"role": "assistant", "content": str(reply)}
            finish, out_text = "stop", str(reply)
        prompt = sum(_words(text_of(m)) for m in body.get("messages", []))
        completion = _words(out_text)
        return 200, {"id": "chatcmpl-" + uuid.uuid4().hex[:12], "object": "chat.completion",
                     "created": int(time.time()), "model": self._served_model(),
                     "system_fingerprint": "fake_ollama",
                     "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                     "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                               "total_tokens": prompt + completion}}


def _handler_for(fake: FakeOllama) -> type:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass  # keep test output quiet

        def _send(self, status: int, payload: Any, content_type: str = "application/json") -> None:
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True  # the client gave up waiting

        def do_GET(self) -> None:  # noqa: N802
            fake.calls.append(("GET", self.path))
            if self.path in fake._raw:
                self._send(*fake._raw[self.path])
            elif self.path == "/api/tags":
                self._send(200, fake._tags())
            else:
                self._send(404, {"error": f"no route {self.path}"})

        def do_POST(self) -> None:  # noqa: N802
            fake.calls.append(("POST", self.path))
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._send(400, {"error": "body is not JSON"})
                return
            if self.path in fake._raw:
                self._send(*fake._raw[self.path])
            elif self.path == "/api/show":
                self._send(*fake._show(body))
            elif self.path == "/v1/chat/completions":
                self._send(*fake._chat(body))
            else:
                self._send(404, {"error": f"no route {self.path}"})

    return Handler


@pytest.fixture
def quiet_crewai_console(monkeypatch):
    """
    Silence CrewAI's console panels for a test whose model call is meant to fail.

    CrewAI's global event listener prints an "LLM Error" panel from an event-bus
    thread, which can land outside pytest's capture.
    """
    from crewai.events.event_listener import event_listener

    monkeypatch.setattr(event_listener.formatter, "verbose", False)
    yield


@pytest.fixture
def fake_ollama():
    fake = FakeOllama()
    try:
        yield fake
    finally:
        fake.stop()
