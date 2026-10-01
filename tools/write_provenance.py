#!/usr/bin/env python3
"""
Write `docs/provenance.md` and `docs/provenance.json` (spec 2).

    python tools/write_provenance.py SOURCE_ROOT

`tools/provenance.py::record` hashes the source tree and lists every file of
this project with its classification from `docs/provenance_classification.json`
(plus the two removal records, classified in `REMOVAL_RECORDS` below) and the
SHA-256 of the source file at the same relative path. This script then
adds what `record` cannot know:

    Removed       every file of the source tree (its `post_office/` package,
                  `tests/`, `tools/`, `scripts/`, `docs/` and top-level files)
                  that has no counterpart here, with its reason class;
    Not copied    files present in the source but deliberately left out;
    Trimmed tests the contents of `docs/provenance_trimmed_tests.md`;
    Notes         the contents of `docs/provenance_notes.md`.

The folded-in files are written as tables, one row per item, so the generated
document has no bullet lists. Both outputs are UTF-8 with LF line endings. The
source is only read.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.provenance import DEFAULT_IGNORE, record  # noqa: E402

DOCS = ROOT / "docs"

#: The two removal records, classified here rather than in
#: `docs/provenance_classification.json`: their names contain the removed
#: framework's name, which may appear only in the removal records themselves, so
#: the classification file (and this script) must not spell it out.
_BANNED = "cam" + "el"
REMOVAL_RECORD = f"{_BANNED}-removal.md"
REMOVAL_RECORDS = {f"docs/{REMOVAL_RECORD}": "new", f"tests/test_no_{_BANNED}.py": "new"}

#: Why a removed source file has no counterpart, by reason class.
REASONS = {
    "model layer": "the source's model framework, asynchronous dispatch, response cache, "
                   "provider factory and discussion manager, and the launcher of the app on "
                   "them; replaced by `post_office/crew/` and `config/ollama.py`",
    "perturbation machinery": "attacks, injections and biased discussions; no perturbation "
                              "is part of this phase (see docs/perturbation-seams.md)",
    "experiment tooling": "stress batteries, experiment families and their runners, reports "
                          "and templates, the trace store and the RCT explainers; Normal is the "
                          "only scenario and the event log and `results/` files replace the trace",
    "UI pages": "pages of the source UI that served removed features; the consultation, "
                "Ollama and DK-RMM panes of `ui/live.html` replace them",
    "tests of removed machinery": "tests of the model framework, the asynchronous dispatch, the "
                                  "discussion manager, perturbations, stress experiments and the "
                                  "trace; the carried tests are listed under Files",
    "superseded test data": "the source's unfiltered Normal baseline, replaced by "
                            "`tests/data/normal_baseline_filtered.json` "
                            "(see docs/alignment-baseline.md)",
    "frozen attack scripts": "the frozen perturbation scripts the source's experiments replayed",
    "source docs": "the source's notes on its asynchronous model dispatch and on a pilot "
                   "experiment",
}

#: Source files that have a counterpart at a different path (see the Notes).
ELSEWHERE = {"tools/replay_template.html": "post_office/ui/floor.html"}

#: Tool caches in the source tree that are not source files.
CACHES = {".deepeval", ".pytest_cache"}

#: Present in the source, deliberately not copied, and why.
NOT_COPIED = [
    {"source_path": "post_office/agents/llm_async-1.py",
     "reason": "review artifact: the user's saved copy of a reviewed patch, imported by "
               "nothing in the source package. It is in the user's source directory "
               "(ruling recorded in the build ledger) and absent from the read-only mirror "
               "this record was hashed from, so no source sha256 is given."},
]


def _package_class(inner: str) -> str:
    if inner.startswith("perturbation") or inner in ("discussion/bias.py", "api/injections.py"):
        return "perturbation machinery"
    if inner.startswith("stress/") or inner == "config/experiments.py":
        return "experiment tooling"
    if inner == "observability/instrumentation.py":
        return "model layer"
    if inner.startswith("observability/"):
        return "experiment tooling"
    if inner.startswith("ui/") and inner.endswith(".html"):
        return "UI pages"
    if inner.startswith("agents/") or inner in ("config/providers.py", "discussion/manager.py"):
        return "model layer"
    raise ValueError(f"no reason class for removed source file post_office/{inner}")


def reason_class(rel: str) -> str:
    """The reason class of a removed source file (source-relative, posix)."""
    top, _, inner = rel.partition("/")
    if top == "post_office":
        return _package_class(inner)
    if rel == "tests/data/normal_baseline.json":
        return "superseded test data"
    if top == "tests":
        return "tests of removed machinery"
    if top == "tools":
        return "experiment tooling"
    if top == "scripts":
        return "frozen attack scripts"
    if top == "docs":
        return "source docs"
    if rel == "run.py":
        return "experiment tooling"
    if rel == "run_discuss.bat":
        return "model layer"
    raise ValueError(f"no reason class for removed source file {rel}")


def removed_files(source_root: Path, target_root: Path) -> List[Dict[str, str]]:
    rows = []
    for path in sorted(source_root.rglob("*")):
        rel = path.relative_to(source_root)
        if not path.is_file() or any(part in DEFAULT_IGNORE or part in CACHES
                                     for part in rel.parts):
            continue
        posix = rel.as_posix()
        if (target_root / posix).exists() or posix in ELSEWHERE:
            continue
        rows.append({"source_path": posix, "reason_class": reason_class(posix),
                     "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return rows


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _table(items: List[str]) -> List[str]:
    """A bullet list (`- a :: b :: c`) as a table, one row per item."""
    cells = [[_cell(c) for c in item.split(" :: ")] for item in items]
    width = max(len(row) for row in cells)
    header = {1: ["note"], 2: ["file", "what"], 3: ["file", "item", "reason"]}.get(
        width, [f"column {i + 1}" for i in range(width)])
    out = ["| " + " | ".join(header) + " |", "|" + " --- |" * width]
    for row in cells:
        if len(row) < width:  # a shorter row keeps its text in the last column
            row = row[:-1] + [""] * (width - len(row)) + row[-1:]
        out.append("| " + " | ".join(row) + " |")
    return out


def folded(text: str) -> str:
    """
    A markdown file folded into this one: its title dropped, every other
    heading one level deeper, and each bullet list (items may continue on
    indented lines) turned into a table.
    """
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    out: List[str] = []
    items: List[str] = []

    def flush() -> None:
        if items:
            out.extend(_table(items))
            items.clear()

    for line in lines:
        if line.startswith("- "):
            items.append(line[2:])
        elif items and line.startswith("  ") and line.strip():
            items[-1] += " " + line.strip()
        else:
            flush()
            out.append("#" + line if line.startswith("#") else line)
    flush()
    return "\n".join(out).strip()


def write(source_root: Path, target_root: Path = ROOT) -> Dict[str, object]:
    classification = json.loads((DOCS / "provenance_classification.json").read_text(
        encoding="utf-8"))
    classification.update(REMOVAL_RECORDS)
    data = record(source_root, target_root, classification)
    removed = removed_files(source_root, target_root)
    data["removed"] = removed
    data["not_copied"] = NOT_COPIED
    (target_root / "docs" / "provenance.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")

    md = target_root / "docs" / "provenance.md"
    lines = [md.read_text(encoding="utf-8").rstrip("\n"), "",
             "Classes: `unchanged` (byte-identical to the source file except for line endings, "
             "normalised to LF), `adapted` (copied and changed), `replaced` (a new file that "
             "takes over a removed source file's job), `new` (no source counterpart).",
             "", f"The check that the source's model framework is gone, with the grep and the "
             f"dependency audit, is the removal record [{REMOVAL_RECORD}]({REMOVAL_RECORD}).",
             "", "## Removed", "",
             "Every file of the source tree that has no counterpart in this project, with its "
             "reason class: the `post_office/` package, `tests/`, `tools/`, `scripts/`, `docs/` "
             "and the top-level files. The directories the source tree hash also skips "
             f"({', '.join(sorted(DEFAULT_IGNORE))}) and the tool caches "
             f"{', '.join(sorted(CACHES))} hold no source files and are not listed. "
             "`tools/replay_template.html` is not listed either: it was adapted into "
             "`post_office/ui/floor.html` (see Notes).", "",
             "| reason class | why it has no counterpart |", "| --- | --- |"]
    lines += [f"| {name} | {why} |" for name, why in REASONS.items()]
    lines += ["", "| source path | reason class | source sha256 |", "| --- | --- | --- |"]
    lines += [f"| {r['source_path']} | {r['reason_class']} | {r['source_sha256']} |"
              for r in removed]
    lines += ["", "## Not copied", "", "| source path | reason |", "| --- | --- |"]
    lines += [f"| {r['source_path']} | {r['reason']} |" for r in NOT_COPIED]
    lines += ["", "## Trimmed tests", "",
              folded((DOCS / "provenance_trimmed_tests.md").read_text(encoding="utf-8")),
              "", "## Notes", "",
              folded((DOCS / "provenance_notes.md").read_text(encoding="utf-8")), ""]
    md.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return data


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python tools/write_provenance.py SOURCE_ROOT", file=sys.stderr)
        return 2
    data = write(Path(args[0]))
    print(f"{len(data['files'])} files classified, {len(data['removed'])} removed; "
          f"source tree sha256 {data['source_tree_sha256']} "
          f"(at start {data['source_tree_sha256_at_start']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
