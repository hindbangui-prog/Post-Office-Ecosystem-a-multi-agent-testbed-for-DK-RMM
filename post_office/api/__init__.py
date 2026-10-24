"""
HTTP and WebSocket over a running ecosystem.

`runner.py` has no web dependencies and can be used on its own to drive a
simulation from a thread. The FastAPI server that serves it is added with the
API and is only loaded when somebody asks for the API, so `python main.py`
never imports FastAPI or uvicorn.
"""

from .runner import SimulationRunner

__all__ = ["SimulationRunner"]
