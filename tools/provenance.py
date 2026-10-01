"""Provenance recording: hash a source tree and classify every target file against it."""
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
from pathlib import Path

CLASSES = ("unchanged", "adapted", "replaced", "new")
DEFAULT_IGNORE = (".venv", "results", ".git", "__pycache__", ".pytest_cache", "logs", ".model_cache")
NO_GIT = "no git repository"


def tree_sha(root: Path, ignore=DEFAULT_IGNORE) -> str:
    """Deterministic sha256 of a tree: sorted relative paths, each path then its bytes."""
    root = Path(root)
    files = []
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if any(part in ignore for part in rel.parts) or not p.is_file():
            continue
        files.append(rel.as_posix())
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode())
        h.update((root / rel).read_bytes())
    return h.hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit(source_root: Path) -> str:
    if not (source_root / ".git").exists():
        return NO_GIT
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source_root, capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else NO_GIT


def record(source_root: Path, target_root: Path, classification: dict[str, str]) -> dict:
    """Write docs/provenance.md and docs/provenance.json under target_root and return the data.

    classification maps a target-relative path to unchanged|adapted|replaced|new. The source
    path of a file is the same relative path under source_root when that file exists there,
    otherwise empty. source_tree_sha256_at_start is written on the first run and kept after.
    """
    source_root, target_root = Path(source_root), Path(target_root)
    bad = {p: c for p, c in classification.items() if c not in CLASSES}
    if bad:
        raise ValueError(f"unknown classification values: {bad}")

    docs = target_root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    json_path = docs / "provenance.json"

    current = tree_sha(source_root)
    at_start = current
    if json_path.exists():
        at_start = json.loads(json_path.read_text()).get("source_tree_sha256_at_start", current)

    files = []
    for path in sorted(classification):
        src = source_root / path
        has_src = src.is_file()
        files.append({
            "path": path,
            "class": classification[path],
            "source_path": path if has_src else "",
            "source_sha256": _file_sha(src) if has_src else "",
        })

    data = {
        "source_commit": _git_commit(source_root),
        "source_tree_sha256": current,
        "source_tree_sha256_at_start": at_start,
        "date": datetime.date.today().isoformat(),
        "files": files,
    }
    json_path.write_text(json.dumps(data, indent=2) + "\n")

    lines = [
        "# Provenance",
        "",
        "## Source identity",
        "",
        f"- Source commit: {data['source_commit']}",
        f"- source_tree_sha256: {data['source_tree_sha256']}",
        f"- source_tree_sha256_at_start: {data['source_tree_sha256_at_start']}",
        f"- Date: {data['date']}",
        "",
        "## Files",
        "",
        "| path | class | source path | source sha256 |",
        "| --- | --- | --- | --- |",
    ]
    for f in files:
        lines.append(f"| {f['path']} | {f['class']} | {f['source_path']} | {f['source_sha256']} |")
    (docs / "provenance.md").write_text("\n".join(lines) + "\n")
    return data
