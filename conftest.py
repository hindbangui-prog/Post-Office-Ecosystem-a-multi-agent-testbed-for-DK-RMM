"""Pytest root configuration: keep CrewAI telemetry off, load the shared fake Ollama plugin."""
import os

# Set before anything imports CrewAI, so no test run reports telemetry.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

pytest_plugins = ["tests.fake_ollama"]
