"""Configuration: the NORMAL preset, and the switch that puts a model behind an expert."""

from .settings import (DEFAULT_CONFIG, EXPERTS, LLM_CANDIDATES, PRESETS, config, llm_brains,
                       normal_config, scenario_label, scenarios)

__all__ = ["DEFAULT_CONFIG", "EXPERTS", "LLM_CANDIDATES", "PRESETS", "config", "llm_brains",
           "normal_config", "scenario_label", "scenarios"]
