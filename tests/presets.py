"""
Configurations the carried tests used by preset name, now that settings has only `default`.

The source's `config("busy")` was `{**DEFAULT_CONFIG, "arrival_interval": 20.0,
"initial_parcels": 16}` and its `config("normal")` was `config("default")`. The
carried tests that ran the facility under that heavier load keep doing so
through `busy_config`, which reproduces the source preset value for value.
"""

from __future__ import annotations

from typing import Any, Dict

from post_office.config.settings import DEFAULT_CONFIG

#: The source's BUSY_CONFIG overrides, verbatim.
BUSY_OVERRIDES: Dict[str, Any] = {"arrival_interval": 20.0, "initial_parcels": 16}


def busy_config(**overrides) -> Dict[str, Any]:
    """The source's `config("busy", **overrides)`."""
    return {**DEFAULT_CONFIG, **BUSY_OVERRIDES, **overrides}
