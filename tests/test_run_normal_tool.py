"""
The command-line entry points, run as the user runs them (spec 19).

Each test starts `main.py`, `tools/run_normal.py` or `tools/verify_ollama.py` in
a subprocess of this interpreter with the fake Ollama's address in
`OLLAMA_BASE_URL`; the fake runs in this process. Nothing here talks to a real
Ollama, and nothing here shows that the tools did: the tools only report the
address and the served model they saw.
"""

import json
import os
import pathlib
import subprocess
import sys

import pytest

from post_office.config.settings import EXPERTS
from post_office.crew.roles import role_of
from tests.fake_ollama import deciding_script

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = ("events.jsonl", "consultations.json", "llm_calls.json", "dkrmm.json",
         "summary.json", "verify.json")
#: Ticks of the model-mode run: about ten seconds against the fake.
TICKS = 60


def _env(fake):
    env = dict(os.environ)
    env.update({"PYTHONHASHSEED": "0", "CREWAI_DISABLE_TELEMETRY": "true",
                "OTEL_SDK_DISABLED": "true", "OLLAMA_BASE_URL": fake.base_url,
                "OLLAMA_MODEL": "qwen3:8b", "OLLAMA_TIMEOUT": "10",
                "CONSULT_DEADLINE_S": "30", "OLLAMA_THINKING": "off"})
    return env


def _run(fake, *args, timeout=240):
    return subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, env=_env(fake),
                          capture_output=True, text=True, encoding="utf-8", timeout=timeout)


@pytest.fixture
def deciding(fake_ollama):
    fake_ollama.script(deciding_script("Take the first: its way is clear."))
    return fake_ollama


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _claims_nothing(text):
    """No output may say the run was real or was made against the real Ollama."""
    low = text.lower()
    assert "real ollama" not in low and "real run" not in low, text


def test_run_normal_writes_the_six_files_and_the_report(deciding, tmp_path):
    done = _run(deciding, "tools/run_normal.py", "--ticks", TICKS, "--seed", 1,
                "--out", tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    out = tmp_path / "s1"
    for name in FILES:
        assert (out / name).is_file(), name
    consultations = _load(out / "consultations.json")
    assert isinstance(consultations, list) and consultations
    calls = _load(out / "llm_calls.json")
    assert isinstance(calls, list) and {c["served_model"] for c in calls} == {"qwen3:8b"}
    verify = _load(out / "verify.json")
    assert verify["mode"] == "model" and verify["ok"] is True
    assert verify["identity"]["model"] == "qwen3:8b"
    assert verify["base_url"] == deciding.base_url
    assert verify["served_models"] == {"qwen3:8b": len(calls)}
    summary = _load(out / "summary.json")
    assert summary["ticks"] == TICKS and summary["decision_paths"]
    assert set(summary["brains"]) == set(EXPERTS)
    dkrmm = _load(out / "dkrmm.json")
    assert dkrmm["state"]["assessments"] == len(dkrmm["record"]["state_series"]) > 0
    events = (out / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(line)["topic"] == "consult_closed" for line in events)

    report = done.stdout
    assert report.startswith("MODEL-MODE RUN EVIDENCE\n")
    assert "does not establish which server answered" in report.splitlines()[1]
    assert f"base_url: {deciding.base_url}" in report
    first = next(c for c in consultations if c["outcome"] == "decided"
                 and c["request"] and c["response"])
    assert "first complete consultation (decided, with a request and a response)" in report
    with_exchange = sum(1 for c in consultations if c["request"])
    assert (f"model decisions by owner → peer ({len(consultations)} in all, "
            f"{with_exchange} with an exchange)") in report
    totals = {k: sum(b[k] for b in summary["brains"].values()) for k in ("calls", "consultations")}
    assert totals["calls"] == len(consultations)
    assert f"model decisions: {totals['calls']}   exchanges: {totals['consultations']}" in report
    for line in (f"consultation_id: {first['id']}", f"sender: {first['owner']}",
                 f"request: {first['request']}", f"response: {first['response']}",
                 "decision paths", "DK-RMM state history", "RCT ticks",
                 "fallbacks", "retries"):
        assert line in report, line
    # The tool reports what it saw; it never says which server that was.
    _claims_nothing(report)
    assert done.stderr.strip() == ""


def test_run_normal_rules_mode_asks_no_model(fake_ollama, tmp_path):
    done = _run(fake_ollama, "tools/run_normal.py", "--ticks", 40, "--rules",
                "--out", tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    for name in FILES:
        assert (tmp_path / "s1" / name).is_file(), name
    assert _load(tmp_path / "s1" / "verify.json")["mode"] == "rules"
    assert _load(tmp_path / "s1" / "consultations.json") == []
    assert fake_ollama.calls == []
    assert done.stdout.startswith("RULES-ONLY RUN EVIDENCE\n")
    _claims_nothing(done.stdout)


def test_the_evidence_of_an_interrupted_run_says_so(tmp_path):
    """`write_evidence` with `interrupted=True`: the five files, both flags set."""
    from tools import run_normal

    written = run_normal.write_evidence(
        tmp_path, consultations=[], calls=[], state={"state": "STABLE"},
        record={"state_series": []}, summary={"ticks": 7}, stats={},
        verify={"mode": "rules", "ok": None}, interrupted=True)
    for name in FILES[1:]:
        assert (tmp_path / name).is_file(), name
    assert _load(tmp_path / "summary.json") == {"ticks": 7, "interrupted": True, "brains": {}}
    assert _load(tmp_path / "verify.json") == {"mode": "rules", "ok": None, "interrupted": True}
    assert written["summary"]["interrupted"] is written["verify"]["interrupted"] is True
    run_normal.write_evidence(tmp_path, [], [], {}, {}, {"ticks": 9}, {}, {"ok": None})
    assert "interrupted" not in _load(tmp_path / "summary.json")
    assert "interrupted" not in _load(tmp_path / "verify.json")


def test_ctrl_c_still_writes_the_six_files(tmp_path, monkeypatch, capsys):
    """A KeyboardInterrupt in the tick loop: every file written, flagged, exit 130."""
    from post_office.simulation.ecosystem import PostOfficeEcosystem
    from tools import run_normal

    step = PostOfficeEcosystem.step
    steps = []

    def interrupted_at_five(self, *args, **kwargs):
        if len(steps) == 5:
            raise KeyboardInterrupt
        steps.append(self.world.tick)
        return step(self, *args, **kwargs)

    monkeypatch.setattr(PostOfficeEcosystem, "step", interrupted_at_five)
    assert run_normal.main(["--rules", "--ticks", "40", "--out", str(tmp_path)]) == 130
    out = tmp_path / "s1"
    for name in FILES:
        assert (out / name).is_file(), name
    summary = _load(out / "summary.json")
    assert summary["interrupted"] is True and summary["ticks"] == 5
    assert _load(out / "verify.json")["interrupted"] is True
    assert capsys.readouterr().out.rstrip().endswith("INTERRUPTED at tick 5")


def test_run_normal_fails_when_another_model_answers(deciding, tmp_path):
    # The configured model is installed, but the replies name another one.
    deciding.serve_models(["qwen3:4b", "qwen3:8b"])
    # 70 ticks: the first model call is at tick 51 on seed 1, after the idle
    # start of the run (`simulation.activity`).
    done = _run(deciding, "tools/run_normal.py", "--ticks", 70, "--out", tmp_path)
    assert done.returncode == 1, done.stdout + done.stderr
    verify = _load(tmp_path / "s1" / "verify.json")
    assert verify["ok"] is False and "qwen3:4b" in verify["served_models"]


def test_run_normal_stops_before_running_when_the_model_is_missing(fake_ollama, tmp_path):
    fake_ollama.serve_models(["qwen3:4b"])
    done = _run(fake_ollama, "tools/run_normal.py", "--ticks", 30, "--out", tmp_path)
    assert done.returncode == 2
    assert "qwen3:4b" in done.stderr
    assert _load(tmp_path / "s1" / "verify.json")["ok"] is False
    assert fake_ollama.requests == []


def test_main_exits_when_model_missing(fake_ollama):
    fake_ollama.serve_models(["qwen3:4b"])
    done = _run(fake_ollama, "main.py", "--ticks", 1)
    assert done.returncode == 2
    assert "qwen3:4b" in done.stderr
    assert fake_ollama.requests == []


def test_main_model_mode_runs_and_prints_a_complete_consultation(deciding):
    # 70 ticks: the first consultation is at tick 51 on seed 1, after the idle
    # start of the run (`simulation.activity`).
    done = _run(deciding, "main.py", "--ticks", 70)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "first complete consultation (decided, with a request and a response):" in done.stdout
    assert "model decisions: " in done.stdout and "exchanges (the owner asked its peer): " in (
        done.stdout)
    first = json.loads(done.stdout.split("a request and a response):\n", 1)[1])
    assert first["outcome"] == "decided" and first["request"] and first["response"]
    assert done.stderr.strip() == ""
    _claims_nothing(done.stdout)


def test_main_reports_the_first_complete_consultation_however_short_the_window(
        deciding, monkeypatch, capsys, quiet_crewai_console):
    """The first complete consultation is kept during the run, not read back at the end."""
    import main
    from post_office.config.settings import llm_brains
    from post_office.crew.consultation import ConsultationService

    whole = ConsultationService.recent
    # The service as if it kept only its ten latest consultations (a run has more).
    monkeypatch.setattr(ConsultationService, "recent",
                        lambda self, limit=50: whole(self, min(limit, 10)))
    assert main.run(60, 1, None, brains=llm_brains(settings=deciding.settings,
                                                   verify=False)) == 0
    printed = capsys.readouterr().out
    first = json.loads(printed.split("a request and a response):\n", 1)[1])
    assert first["id"] == "CSL-0001" and first["outcome"] == "decided"
    assert first["request"] and first["response"]


def test_main_rules_mode_never_calls_the_server(fake_ollama):
    done = _run(fake_ollama, "main.py", "--rules", "--ticks", 20)
    assert done.returncode == 0, done.stdout + done.stderr
    assert fake_ollama.calls == []


def test_verify_ollama_prints_seven_rows_and_exits_zero(fake_ollama):
    done = _run(fake_ollama, "tools/verify_ollama.py")
    assert done.returncode == 0, done.stdout + done.stderr
    rows = [line for line in done.stdout.splitlines() if "→ Ollama(" in line]
    assert len(rows) == 7
    for agent_id, row in zip(EXPERTS, rows):
        assert row.startswith(f"{role_of(agent_id):<12} → Ollama({fake_ollama.base_url}) → "
                              f"qwen3:8b   served=qwen3:8b  ")
        assert row.endswith(" ms  ok")
    assert "digest: fake-qwen3:8b" in done.stdout
    _claims_nothing(done.stdout)
    assert "<think>" in done.stdout  # the thinking line names what it looked for
    probes = [r for r in fake_ollama.requests if "Decision: probe" in json.dumps(r)]
    assert len(probes) == 7
    assert done.stderr.strip() == ""


def test_verify_ollama_exits_one_when_the_model_is_missing(fake_ollama):
    fake_ollama.serve_models(["qwen3:4b"])
    done = _run(fake_ollama, "tools/verify_ollama.py")
    assert done.returncode == 1
    assert "qwen3:4b" in done.stdout
    assert fake_ollama.requests == []


def test_verify_ollama_exits_one_when_another_model_answers(fake_ollama):
    fake_ollama.serve_models(["qwen3:4b", "qwen3:8b"])
    done = _run(fake_ollama, "tools/verify_ollama.py")
    assert done.returncode == 1
    rows = [line for line in done.stdout.splitlines() if "→ Ollama(" in line]
    assert len(rows) == 7 and all("served=qwen3:4b" in r for r in rows)


def test_verify_ollama_reports_think_tags(fake_ollama):
    fake_ollama.script(lambda body: "<think>hmm</think>\nA")
    done = _run(fake_ollama, "tools/verify_ollama.py")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "7 of 7 replies contained <think>" in done.stdout


def test_verify_ollama_puts_an_unanswered_call_on_its_own_row(fake_ollama):
    # Every reply arrives after the client's one-second timeout: no response at all.
    fake_ollama.delay(2.5)
    env_timeout = {"OLLAMA_TIMEOUT": "1"}
    done = subprocess.run([sys.executable, "tools/verify_ollama.py"], cwd=ROOT,
                          env={**_env(fake_ollama), **env_timeout}, capture_output=True,
                          text=True, encoding="utf-8", timeout=240)
    assert done.returncode == 1, done.stdout + done.stderr
    rows = [line for line in done.stdout.splitlines() if "→ Ollama(" in line]
    assert len(rows) == 7
    for row in rows:
        assert "served=-" in row and "FAILED: " in row, row
