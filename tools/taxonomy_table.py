#!/usr/bin/env python3
"""
Print the interaction type table of `docs/events.md` from `taxonomy.table()`.

    python tools/taxonomy_table.py

The output is the markdown table that sits between the markers
`<!-- taxonomy:begin -->` and `<!-- taxonomy:end -->` in `docs/events.md`, one
row per interaction type in the taxonomy's own order, with the channel, the
description and the three hints (`has_receiver`, `latency`, `model`) exactly as
`GET /taxonomy` serves them. `tests/test_docs_present.py` regenerates the table
and asserts that the document's block equals it, so the document can never
say something the served table does not. Nothing is written; the taxonomy
module is the only input.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from post_office.communication import taxonomy  # noqa: E402

BEGIN = "<!-- taxonomy:begin -->"
END = "<!-- taxonomy:end -->"

HEADER = ("| Channel | `interaction_type` | Realised by | `has_receiver` | `latency` | `model` |",
          "|---|---|---|---|---|---|")


def _cell(text: object) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def type_table(table: dict | None = None) -> str:
    """The markdown table of `table()["types"]`, without the markers."""
    table = taxonomy.table() if table is None else table
    lines: List[str] = list(HEADER)
    for row in table["types"]:
        lines.append("| " + " | ".join((
            _cell(row["channel"]), f"`{_cell(row['interaction_type'])}`",
            _cell(row["description"]), _cell(row["has_receiver"]), _cell(row["latency"]),
            "yes" if row["model"] else "no",
        )) + " |")
    return "\n".join(lines)


def block_of(text: str) -> str:
    """The table between the markers of a document, or "" when absent."""
    start, stop = text.find(BEGIN), text.find(END)
    if start < 0 or stop < 0 or stop < start:
        return ""
    return text[start + len(BEGIN):stop].strip()


def main() -> int:
    print(type_table())
    return 0


if __name__ == "__main__":
    sys.exit(main())
