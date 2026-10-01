import hashlib
import json
import pathlib
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.provenance import record, tree_sha  # noqa: E402


def test_dependencies_are_crewai_not_removed_stack():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())
    deps = " ".join(meta["project"]["dependencies"] + meta["project"]["optional-dependencies"]["dev"])
    assert "crewai" in deps and "fastapi" in deps and "uvicorn" in deps
    # the removed framework name is assembled so that this file stays free of it
    for banned in ("cam" + "el", "litellm", "langchain"):
        assert banned not in deps.lower()
    assert meta["project"]["requires-python"] == ">=3.10,<3.14"


def test_env_example_pins_the_baseline_model():
    text = (ROOT / ".env.example").read_text()
    assert "OLLAMA_MODEL=qwen3:8b" in text and "OLLAMA_BASE_URL=http://localhost:11434" in text


def _fake_source(tmp_path):
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "a.txt").write_bytes(b"alpha")
    (src / "pkg" / "b.txt").write_bytes(b"beta")
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "junk.pyc").write_bytes(b"junk")
    return src


def test_tree_sha_is_deterministic_and_content_sensitive(tmp_path):
    src = _fake_source(tmp_path)
    first = tree_sha(src)
    assert first == tree_sha(src)
    assert len(first) == 64
    # ignored directories do not influence the hash
    (src / "__pycache__" / "more.pyc").write_bytes(b"more")
    assert tree_sha(src) == first
    # file bytes do
    (src / "a.txt").write_bytes(b"alpha2")
    assert tree_sha(src) != first


def test_tree_sha_matches_documented_algorithm(tmp_path):
    src = _fake_source(tmp_path)
    h = hashlib.sha256()
    for rel in ("a.txt", "pkg/b.txt"):
        h.update(rel.encode())
        h.update((src / rel).read_bytes())
    assert tree_sha(src) == h.hexdigest()


def test_record_writes_markdown_and_json(tmp_path):
    src = _fake_source(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    cls = {"x/a.py": "adapted", "x/new.py": "new"}
    # the classified files map to a source path by identical relative path when present
    (src / "x").mkdir()
    (src / "x" / "a.py").write_bytes(b"print(1)")

    data = record(src, target, cls)
    md = (target / "docs" / "provenance.md").read_text()
    js = json.loads((target / "docs" / "provenance.json").read_text())

    assert js == data
    assert js["source_tree_sha256"] == tree_sha(src)
    assert js["source_tree_sha256_at_start"] == tree_sha(src)
    assert js["source_commit"] == "no git repository"
    assert "no git repository" in md and tree_sha(src) in md
    rows = {r["path"]: r for r in js["files"]}
    assert rows["x/a.py"]["class"] == "adapted"
    assert rows["x/a.py"]["source_sha256"] == hashlib.sha256(b"print(1)").hexdigest()
    assert rows["x/new.py"]["class"] == "new"
    assert rows["x/new.py"]["source_path"] == ""
    assert "| x/a.py | adapted |" in md


def test_record_keeps_source_tree_sha_at_start(tmp_path):
    src = _fake_source(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    first = record(src, target, {})["source_tree_sha256_at_start"]
    (src / "a.txt").write_bytes(b"changed")
    second = record(src, target, {})
    assert second["source_tree_sha256_at_start"] == first
    assert second["source_tree_sha256"] != first


def test_record_uses_git_commit_when_repo_present(tmp_path):
    import subprocess

    src = _fake_source(tmp_path)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]}
    subprocess.run(["git", "init", "-q"], cwd=src, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=src, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=src, check=True, env=env)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, check=True, capture_output=True,
                          text=True).stdout.strip()
    target = tmp_path / "target"
    target.mkdir()
    assert record(src, target, {})["source_commit"] == head
