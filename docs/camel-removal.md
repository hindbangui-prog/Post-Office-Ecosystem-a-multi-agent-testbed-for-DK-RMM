# Removal of the source's model framework (CAMEL-AI)

The source project's model layer was built on CAMEL-AI (`camel-ai==0.2.90`, with an `mcp<2`
pin). Prototype II replaces it with CrewAI on Ollama, and nothing of it was copied: not
`agents/camel_brain.py`, `agents/response_cache.py` (with its `camel_version()`),
`config/providers.py::create_model`, `observability/instrumentation.py`, the `camel-ai` and
`mcp<2` pins, the `PO_MODEL_*` environment variables, or the tests that asserted
`brain.name == "camel"` or `source.startswith("camel:")`. Comments and docstrings that named it
in copied files were rewritten, and the `DISCUSS_*` message types it used were removed from the
enum. Every file of the source tree that has no counterpart in this project (its `post_office/`
package, `tests/`, `tools/`, `scripts/`, `docs/` and top-level files) is listed with its reason
class in the "Removed" section of [provenance.md](provenance.md).

This file records the check, performed on the delivered tree on 2026-10-01 after the
documentation and the provenance record were written. It is itself one of the files allowed to
name the framework, as are `docs/provenance.md` and `docs/provenance.json` (they name the
removed source files), `docs/superpowers/` (the specification and the plan) and
`tests/test_no_camel.py` (the test, whose file name carries it).

## The grep

Run from the project root, over every text file, case-insensitively, skipping only the
directories that are not part of the project (`.venv`, `results`, `.git`, `__pycache__`,
pytest's `.pytest_cache`, and `.superpowers`, the build's working notes). The removal records
are deliberately not excluded, so the reader can see that they are the only matches.

```
grep -rliI camel --exclude-dir=.venv --exclude-dir=results --exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=.pytest_cache --exclude-dir=.superpowers . | sort
```

Output:

```
./docs/camel-removal.md
./docs/provenance.json
./docs/provenance.md
./docs/superpowers/plans/2026-10-01-prototype-ii-implementation-plan.md
./docs/superpowers/specs/2026-10-01-prototype-ii-crewai-ollama-design.md
./tests/test_no_camel.py
```

Every line is a removal record: this file, the two provenance records, the specification and
the plan, and the test. No source file, configuration file, other document or other test
matches.

## The dependency audit

```
.venv/bin/pip list | grep -i -E "camel|litellm|langchain"
```

Output: none (grep exit status 1). The same pattern finds nothing in `pyproject.toml` or
`requirements.txt`, whose model dependency is `crewai>=1.15,<2`; the environment has
`crewai 1.15.23` and `openai 2.54.0`. On Windows the equivalent is `.venv\Scripts\pip list |
findstr /i "camel litellm langchain"`.

## The test that keeps it so

`tests/test_no_camel.py` walks every `.py`, `.md`, `.html`, `.toml`, `.txt`, `.ini`, `.json`,
`.cfg` and `.example` file and `.gitignore`, outside the same non-project directories, and
asserts that no file other than the removal records contains `camel` in any case (which covers
`camel-ai`, `camelbrain`, `camel_brain` and `camel_agent`) and that no other project path
contains it. A second test reads the tree with nothing excused and asserts that the matching
files are all removal records, so an exclusion cannot hide anything else.
