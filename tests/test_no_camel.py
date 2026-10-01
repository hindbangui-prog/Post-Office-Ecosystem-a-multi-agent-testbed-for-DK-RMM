"""
The removed model framework is gone from the project (spec 22).

Every text file of the project is read and must not contain `camel` in any
case (which also covers `camel-ai`, `camelbrain`, `camel_brain` and
`camel_agent`), and no project path may contain it either. The only files
excused are the ones whose purpose is to record the removal:

    docs/camel-removal.md          the grep and the dependency audit
    docs/provenance.md, .json      they name the removed source files
    docs/superpowers/**            the specification and the plan
    tests/test_no_camel.py         this file

and the directories that are not part of the project: `.venv`, `results`,
`.git`, `__pycache__`, `.pytest_cache` (pytest's own cache, which records this
file's test ids) and `.superpowers` (the build's working notes).

The second test reads the same tree with nothing excused and checks that the
excused records are the only files that match, so an exclusion cannot hide
anything else.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, List

ROOT = Path(__file__).resolve().parents[1]

PATTERN = re.compile(r"camel", re.IGNORECASE)

#: Directories that are not part of the project, skipped wherever they occur.
NOT_PROJECT = {".venv", "results", ".git", "__pycache__", ".pytest_cache", ".superpowers"}

#: The removal records, which name what was removed (project-relative, posix).
RECORDS = {"docs/camel-removal.md", "docs/provenance.md", "docs/provenance.json",
           "tests/test_no_camel.py"}
RECORD_DIRS = ("docs/superpowers/",)

#: What counts as a text file.
SUFFIXES = {".py", ".md", ".html", ".toml", ".txt", ".ini", ".json", ".cfg", ".example"}
NAMES = {".gitignore"}


def _is_record(rel: str) -> bool:
    return rel in RECORDS or rel.startswith(RECORD_DIRS)


def _text_files() -> Iterator[str]:
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if any(part in NOT_PROJECT for part in rel.parts) or not path.is_file():
            continue
        if path.suffix in SUFFIXES or path.name in NAMES:
            yield rel.as_posix()


def _matching() -> List[str]:
    found = []
    for rel in _text_files():
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if PATTERN.search(text) or PATTERN.search(rel):
            found.append(rel)
    return found


def test_no_project_file_names_the_removed_framework():
    scanned = [rel for rel in _text_files() if not _is_record(rel)]
    assert len(scanned) > 100, "the walk should see the whole project"
    offending = [rel for rel in scanned
                 if PATTERN.search(rel)
                 or PATTERN.search((ROOT / rel).read_text(encoding="utf-8", errors="replace"))]
    assert offending == []


def test_the_removal_records_are_the_only_files_that_match():
    found = _matching()
    print("\nfiles matching, nothing excused:\n  " + "\n  ".join(found))
    assert found, "the removal records themselves should match"
    assert all(_is_record(rel) for rel in found), [r for r in found if not _is_record(r)]
    assert "docs/camel-removal.md" in found and "docs/provenance.md" in found
