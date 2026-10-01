"""
DK-RMM consumes the event stream and nothing else (spec 14).

Two checks. Importing `post_office.dkrmm` in a fresh interpreter loads neither
CrewAI nor the model layer, nor the Ollama settings. And no module of the model
layer (`post_office/crew/`) or of the agents (`post_office/agents/`) imports
`dkrmm`, so no prompt, tool or context can be built from the monitor's state.
"""

import ast
import json
import os
import pathlib
import subprocess
import sys

import post_office

ROOT = pathlib.Path(post_office.__file__).resolve().parent
PROJECT = ROOT.parent

PROBE = """
import json, sys
import post_office.dkrmm
import post_office.dkrmm.indicators, post_office.dkrmm.monitor, post_office.dkrmm.record
import post_office.dkrmm.signals, post_office.dkrmm.states
print(json.dumps(sorted(m for m in sys.modules
                        if m == "crewai" or m.startswith("crewai.")
                        or m.startswith("post_office."))))
"""


def _imports(path: pathlib.Path):
    """Every module a file imports, with relative imports resolved against the package."""
    package = path.relative_to(PROJECT).with_suffix("").parts[:-1]
    out = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = list(package[:len(package) - node.level + 1]) if node.level else []
            module = ".".join(base + ([node.module] if node.module else []))
            out.append(module)
            out.extend(f"{module}.{alias.name}" for alias in node.names)
    return out


def test_importing_dkrmm_loads_no_model_layer():
    env = dict(os.environ, PYTHONHASHSEED="0")
    result = subprocess.run([sys.executable, "-c", PROBE], cwd=PROJECT, env=env,
                            capture_output=True, text=True, timeout=120, check=True)
    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    assert "crewai" not in loaded and not [m for m in loaded if m.startswith("crewai.")]
    assert not [m for m in loaded if m == "post_office.crew" or m.startswith("post_office.crew.")]
    assert "post_office.config.ollama" not in loaded
    assert not [m for m in loaded if m.startswith("post_office.agents")]
    assert "post_office.dkrmm.monitor" in loaded


def test_dkrmm_itself_imports_no_model_layer_and_no_agent():
    for path in sorted((ROOT / "dkrmm").glob("*.py")):
        for module in _imports(path):
            assert not module.startswith(("crewai", "post_office.crew", "post_office.agents",
                                          "post_office.config.ollama")), (path.name, module)


def test_no_agent_or_model_layer_module_imports_dkrmm():
    scanned = 0
    for folder in ("crew", "agents"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            scanned += 1
            for module in _imports(path):
                assert "dkrmm" not in module.split("."), (str(path.relative_to(ROOT)), module)
    assert scanned >= 20
