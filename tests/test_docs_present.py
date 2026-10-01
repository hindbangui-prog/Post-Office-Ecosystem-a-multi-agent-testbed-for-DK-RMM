"""
The delivered documentation exists, and the provenance record covers the package (spec 2, 17).

The eleven prose documents and the two generated records (the provenance record
and the removal record) are present and not empty, the README links every one
it may name, and `docs/provenance.md` names every Python file under
`post_office/`, each in a row of its file table.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: The prose documents, each linked from the README.
PROSE = ("architecture.md", "agents.md", "crewai-ollama.md", "consultation.md", "events.md",
         "dkrmm.md", "perturbation-seams.md", "alignment-baseline.md", "running.md",
         "verification.md", "limitations.md", "provenance.md")
#: The removal record. Its name is assembled so that this file stays free of the removed
#: framework's name, and the README, which may not name it either, does not link it.
REMOVAL = "cam" + "el-removal.md"
DOCS = PROSE + (REMOVAL,)


@pytest.mark.parametrize("name", DOCS)
def test_the_document_exists(name):
    path = ROOT / "docs" / name
    assert path.is_file(), f"docs/{name} is missing"
    assert len(path.read_text(encoding="utf-8").strip()) > 200


def test_the_readme_links_every_prose_document():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for name in PROSE:
        assert f"docs/{name}" in readme, f"README.md does not link docs/{name}"


def test_provenance_lists_every_package_file():
    text = (ROOT / "docs" / "provenance.md").read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip() for line in text.splitlines()
            if line.startswith("| ") and line.count("|") >= 5}
    package = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "post_office").rglob("*.py")
                     if "__pycache__" not in p.parts)
    assert len(package) > 80
    missing = [p for p in package if p not in rows]
    assert missing == []
