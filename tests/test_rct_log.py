"""The RCT log: every RCT saved by earlier and current app runs, each with its cause."""
import json

import pytest

from post_office.config.settings import scenario_label
from post_office.observability.rct_log import list_rcts, load_rct


def saved(root, run, tick, detected_at, status="DISCOVERED", summary="Mostly blocked.",
          scenario="normal"):
    path = root / "rct" / run / f"{tick}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = {"scenario": scenario} if scenario else {}
    path.write_text(json.dumps({
        **extra,
        "run_id": run.split("-")[0], "tick": tick, "detected_at": detected_at,
        "reading": {"tick": tick, "state": "RCT", "severity": 3.5, "kinds": ["spread"],
                    "evidence": ["blocked robots"], "status": status},
        "explanation": {"summary": summary, "window": [tick - 59, tick]},
    }), encoding="utf-8")


def test_every_saved_rct_is_listed_newest_first_across_runs(tmp_path):
    saved(tmp_path, "api-1", 2701, "2026-09-25T10:00:00+00:00")
    saved(tmp_path, "api-1", 2721, "2026-09-25T10:00:20+00:00", status="DISMISSED")
    saved(tmp_path, "api-2", 400, "2026-09-26T09:00:00+00:00")
    rows = list_rcts(tmp_path)
    assert [(r["run"], r["tick"]) for r in rows] == [("api-2", 400), ("api-1", 2721),
                                                     ("api-1", 2701)]
    first = rows[1]
    assert first["status"] == "DISMISSED" and first["kinds"] == ["spread"]
    assert first["summary"] == "Mostly blocked." and first["severity"] == 3.5
    assert "explanation" not in first                  # the list stays small


def test_each_listed_rct_names_its_scenario(tmp_path):
    saved(tmp_path, "api-1", 2701, "2026-09-25T10:00:00+00:00")
    saved(tmp_path, "api-3", 500, "2026-09-26T11:00:00+00:00", scenario="stress_actorattack")
    rows = {r["run"]: r for r in list_rcts(tmp_path)}
    assert rows["api-1"]["scenario"] == "normal"
    assert rows["api-1"]["scenario_label"] == scenario_label()
    assert rows["api-3"]["scenario_label"] == "stress_actorattack"


def test_an_rct_saved_without_a_scenario_takes_its_runs_record(tmp_path):
    saved(tmp_path, "api-1", 2701, "2026-09-25T10:00:00+00:00", scenario="")
    saved(tmp_path, "api-2", 100, "2026-09-25T11:00:00+00:00", scenario="")
    record = tmp_path / "dkrmm" / "api-1.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"scenario": "default"}), encoding="utf-8")
    rows = {r["run"]: r for r in list_rcts(tmp_path)}
    assert rows["api-1"]["scenario"] == "normal"
    assert rows["api-2"]["scenario"] == "" and rows["api-2"]["scenario_label"] == "unknown"


def test_a_selected_rct_comes_back_with_its_cause(tmp_path):
    saved(tmp_path, "api-1", 2701, "2026-09-25T10:00:00+00:00")
    one = load_rct(tmp_path, "api-1", 2701)
    assert one["explanation"]["summary"] == "Mostly blocked."
    assert one["reading"]["evidence"] == ["blocked robots"]
    assert load_rct(tmp_path, "api-1", 9999) is None


def test_names_that_leave_the_log_folder_are_refused(tmp_path):
    saved(tmp_path, "api-1", 2701, "2026-09-25T10:00:00+00:00")
    for bad in ("..", "../rct", "api-1/..", "a\\b", ""):
        with pytest.raises(ValueError):
            load_rct(tmp_path, bad, 2701)


def test_a_damaged_file_does_not_hide_the_others(tmp_path):
    saved(tmp_path, "api-1", 2701, "2026-09-25T10:00:00+00:00")
    (tmp_path / "rct" / "api-1" / "2721.json").write_text("{half", encoding="utf-8")
    (tmp_path / "rct" / "api-1" / "2741.json.tmp").write_text("{}", encoding="utf-8")
    assert [r["tick"] for r in list_rcts(tmp_path)] == [2701]
    assert list_rcts(tmp_path / "missing") == []

