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

CrewAI is imported inside `quiet()`, so importing this module does not load it.
"""

from __future__ import annotations

import contextlib
import sys
from typing import Iterator


@contextlib.contextmanager
def quiet() -> Iterator[None]:
    """CrewAI's console panels off inside the block, as they were after it."""
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
