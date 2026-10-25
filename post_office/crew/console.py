"""
CrewAI's console, kept quiet; and a console that can print what the tools say.

CrewAI's global event listener prints rich panels (tool execution started and
completed, "LLM Error", ...) for every agent, whatever the agent's own
`verbose`, and some of them from an event-bus thread. `quiet()` switches that
listener's formatter off for the duration of a block and restores it after.
The test fixture `quiet_crewai_console` and the command-line tools (`main.py`,
`tools/run_normal.py`, `tools/verify_ollama.py`) all use it, so the panels are
silenced one way everywhere. Nothing is hidden from the record: every model
call is still an `llm_call` event and an audit record.

`quiet()` also switches CrewAI's and OpenTelemetry's anonymous telemetry off
(`CREWAI_DISABLE_TELEMETRY=true`, `OTEL_SDK_DISABLED=true`, set with
`os.environ.setdefault`, so a value already in the environment is kept). The
command-line tools set the same two variables before CrewAI is imported;
setting them here covers every other way in (the API server, a test), because
CrewAI checks the variable before each telemetry operation as well as when it
starts.

CrewAI is imported inside `quiet()`, so importing this module does not load it.
"""

from __future__ import annotations

import contextlib
import os
import sys
from typing import Iterator

#: The environment that switches CrewAI's and OpenTelemetry's telemetry off.
NO_TELEMETRY = {"CREWAI_DISABLE_TELEMETRY": "true", "OTEL_SDK_DISABLED": "true"}


def no_telemetry() -> None:
    """Telemetry off, unless the environment already says otherwise."""
    for name, value in NO_TELEMETRY.items():
        os.environ.setdefault(name, value)


@contextlib.contextmanager
def quiet() -> Iterator[None]:
    """CrewAI's console panels off inside the block, as they were after it; telemetry off."""
    no_telemetry()
    from crewai.events.event_listener import event_listener

    formatter = event_listener.formatter
    before = formatter.verbose
    formatter.verbose = False
    try:
        yield
    finally:
        formatter.verbose = before


def utf8_stdout() -> None:
    """
    Print UTF-8 whatever the console's code page, so a report with an arrow in
    it does not fail when it is redirected to a file on Windows.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # not a text stream that can be reconfigured
            pass
