#!/usr/bin/env python3
"""
Probe the configured Ollama through the project's own integration, once per expert (spec 10).

    python tools/verify_ollama.py

First the model identity, from the server (`verify_model`: digest, family,
parameter size, quantization, installed models); if the configured model is
not there the problems are printed and the exit code is 1. Then, for each of
the seven experts, the CrewAI agent `build_agents` makes (on the one shared
`build_llm`, with an `OllamaAudit` as its transport interceptor) executes one
two-option task, and one row is printed:

    Planner      → Ollama(http://localhost:11434) → qwen3:8b   served=qwen3:8b  812 ms  ok

`served` is the model name the server put in its reply, as the audit read it;
the latency is the sum over the agent's model calls for the task. The exit
code is 1 if any row's served model differs from `OLLAMA_MODEL` or any call
failed, 0 otherwise (2 for invalid settings).

A last line says whether any raw reply (the message content in the HTTP
response, before anything strips it) contained `<think>`, or carried a separate
`reasoning` field, so `OLLAMA_THINKING` can be settled: with `off` the request
asks for no reasoning, and if the model reasons anyway, `prompt` puts
`/no_think` in the role prompt instead.

The rows report what the tool saw at the configured address; they do not
establish which server answered.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from post_office.config.settings import EXPERTS  # noqa: E402
from post_office.crew.console import utf8_stdout  # noqa: E402

PROBE = ("Decision: probe\nAllowed answers:\n- A\n- B\n"
         "Reply with exactly one allowed answer.")
EXPECTED = "one allowed answer"


def _reply_of(response: httpx.Response) -> Dict[str, Any]:
    """The assistant message of an OpenAI-style chat reply, or {}."""
    try:
        data = json.loads(response.content)
        message = data["choices"][0]["message"]
        return message if isinstance(message, dict) else {}
    except Exception:
        return {}


def _audit_with_replies(settings: Any, records: List[Any]) -> Any:
    """An `OllamaAudit` that also keeps each raw assistant message it passes on."""
    from post_office.crew.audit import OllamaAudit

    class ReplyAudit(OllamaAudit):
        def __init__(self) -> None:
            super().__init__(settings, on_call=records.append)
            self.replies: List[Dict[str, Any]] = []

        def on_inbound(self, message: httpx.Response) -> httpx.Response:
            message = super().on_inbound(message)  # reads the body
            if "text/event-stream" not in message.headers.get("content-type", ""):
                self.replies.append(_reply_of(message))
            return message

    return ReplyAudit()


def main(argv: Optional[Sequence[str]] = None) -> int:
    utf8_stdout()
    from post_office.config.ollama import load_settings
    from post_office.crew.identity import verify_model

    try:
        settings = load_settings()
    except ValueError as exc:  # InvalidBaseUrl, InvalidModelName, a bad number
        print(f"invalid Ollama settings: {exc}", file=sys.stderr)
        return 2

    ident = verify_model(settings)
    print("model identity")
    print(f"  base_url: {ident.base_url}")
    print(f"  model: {ident.model}   digest: {ident.digest or '-'}")
    print(f"  family: {ident.family or '-'}   parameter_size: {ident.parameter_size or '-'}   "
          f"quantization: {ident.quantization or '-'}")
    print(f"  installed: {', '.join(ident.installed) or 'none'}")
    print(f"  thinking: OLLAMA_THINKING={settings.thinking}")
    if not ident.ok:
        print(f"  problems: {'; '.join(ident.problems)}")
        print("not probing: the configured model is not available")
        return 1
    print("")

    from crewai import Task

    from post_office.crew.audit import calling
    from post_office.crew.console import quiet
    from post_office.crew.llm import build_llm
    from post_office.crew.roles import build_agents, role_of

    records: List[Any] = []
    audit = _audit_with_replies(settings, records)
    agents = build_agents(build_llm(settings, interceptor=audit), thinking=settings.thinking)

    failed = False
    with quiet(), warnings.catch_warnings():
        # CrewAI 1.15 warns about its own deprecated fields on every Task/Agent.
        warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"crewai\.")
        for agent_id in EXPERTS:
            agent = agents[agent_id]
            error = ""
            try:
                task = Task(description=PROBE, expected_output=EXPECTED, agent=agent)
                with calling(agent_id, "probe"):
                    try:
                        agent.execute_task(task)
                    finally:
                        # A last attempt that got no response is recorded now,
                        # attributed to this agent, and lands on this row.
                        audit.flush_pending()
            except Exception as exc:  # reported on the row, never raised
                error = f"{type(exc).__name__}: {exc}"
            mine = [r for r in records if r.agent_id == agent_id]
            served = mine[-1].served_model if mine else ""
            latency = sum(r.latency_ms for r in mine)
            bad = [r for r in mine if r.error or r.status != 200]
            if error or bad or not mine:
                status = "FAILED: " + (error or (bad[0].error if bad else "no model call"))
            elif any(r.served_model != settings.model for r in mine):
                status = f"MISMATCH: served {served}, configured {settings.model}"
            else:
                status = "ok"
            failed = failed or status != "ok"
            print(f"{role_of(agent_id):<12} → Ollama({settings.base_url}) → {settings.model}   "
                  f"served={served or '-'}  {latency:.0f} ms  {status}")

    replies = audit.replies
    think = sum(1 for m in replies if "<think>" in str(m.get("content") or ""))
    reasoning = sum(1 for m in replies if m.get("reasoning") or m.get("reasoning_content"))
    print("")
    print(f"thinking: {think} of {len(replies)} replies contained <think>; "
          f"{reasoning} carried a separate reasoning field "
          f"(OLLAMA_THINKING={settings.thinking}"
          + ("; the model reasons despite 'off': consider OLLAMA_THINKING=prompt)"
             if settings.thinking == "off" and (think or reasoning) else ")"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
