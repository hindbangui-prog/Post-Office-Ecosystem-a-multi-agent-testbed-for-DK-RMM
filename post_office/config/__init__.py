"""Configuration: the NORMAL preset, and the switch that puts a model behind an expert."""

from .settings import (DEFAULT_CONFIG, EXPERTS, LLM_CANDIDATES, PRESETS,
                       SCENARIOS, config, llm_brains, normal_config)

__all__ = ["DEFAULT_CONFIG", "EXPERTS", "LLM_CANDIDATES", "PRESETS",
           "SCENARIOS", "config", "llm_brains", "normal_config"]
