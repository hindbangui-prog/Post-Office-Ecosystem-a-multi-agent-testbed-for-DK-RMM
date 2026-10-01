"""The NORMAL ecosystem refuses any configuration that asks for a perturbation."""
import pytest

from post_office.config.settings import normal_config
from post_office.simulation import build


def test_a_perturbations_key_is_refused(tmp_path):
    log = tmp_path / "logs" / "refused.jsonl"
    with pytest.raises(ValueError, match="perturbations are not part of this phase"):
        build(config={**normal_config(), "perturbations": [{"x": 1}]}, log_path=str(log))
    assert not log.exists(), "the refusal came after the event log was opened"


def test_a_non_empty_interceptor_list_is_refused():
    with pytest.raises(ValueError, match="perturbations are not part of this phase"):
        build(config={**normal_config(), "interceptors": ["delay"]})


def test_a_normal_build_says_once_that_nothing_is_intercepted():
    eco = build(config=normal_config())
    try:
        rows = [e for e in eco.logger.recent(10_000) if e.topic == "interception"]
        assert len(rows) == 1
        assert rows[0].category == "simulation"
        assert rows[0].detail["active"] == []
        assert rows[0].detail["perturbations"] == "none"
    finally:
        eco.close()
