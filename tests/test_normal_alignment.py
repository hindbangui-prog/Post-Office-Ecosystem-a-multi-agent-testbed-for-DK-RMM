"""Rules-only Normal reproduces the source's recorded world and DK-RMM readings.

The baseline was generated from the source package with
`tools/normal_fingerprint.py --from-source`; see docs/alignment-baseline.md.
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import normal_fingerprint as nf  # noqa: E402

BASELINE = ROOT / "tests" / "data" / "normal_baseline_filtered.json"


def test_the_package_under_test_is_this_project():
    """The comparison runs this project's `post_office`, not a copy found elsewhere."""
    import post_office

    package = pathlib.Path(post_office.__file__).resolve()
    assert package.is_relative_to(ROOT.resolve()), package
    assert package.parent == ROOT.resolve() / "post_office", package


def test_the_baseline_records_its_provenance_and_filter():
    before = json.loads(BASELINE.read_text())
    assert len(before["source_tree_sha256"]) == 64
    assert before["ticks"] == 1600
    assert before["strip"] == nf.strip_json()
    assert set(before["runs"]) == {name for name, _, _ in nf.RUNS}


def test_the_filter_leaves_no_trace_of_the_rows_it_drops():
    rows = [{"seq": 1, "tick": 0, "topic": "a"},
            {"seq": 2, "tick": 0, "topic": "interception"},
            {"seq": 3, "tick": 0, "topic": "b", "run_id": "r", "wall_clock": "w"},
            {"seq": 4, "tick": 2, "topic": "llm"},
            {"seq": 5, "tick": 2, "topic": "c"}]
    kept = nf.filter_rows(rows)
    assert [(r["seq"], r["topic"]) for r in kept] == [(1, "a"), (2, "b"), (3, "c")]
    assert "run_id" not in kept[1] and "wall_clock" not in kept[1]
    dropped = nf.stripped_ticks(rows)
    assert dropped == [0, 2]
    snaps = [{"tick": 1, "events": 3}, {"tick": 2, "events": 5}]
    assert [s["events"] for s in nf.net_snapshots(snaps, dropped)] == [2, 3]


@pytest.mark.slow
def test_rules_only_normal_reproduces_the_source_world():
    before = json.loads(BASELINE.read_text())
    after = nf.runs(1600)
    for name, b in before["runs"].items():
        a = after[name]
        for key in ("snapshots_sha256", "dkrmm_readings_sha256", "dkrmm_states", "rct_ticks",
                    "event_stream_filtered_sha256", "summary"):
            assert a[key] == b[key], (name, key)
