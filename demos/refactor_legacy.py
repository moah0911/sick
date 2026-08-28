#!/usr/bin/env python3
"""Real demo: refactor legacy codebase — rename symbol across files using grep/edit_file.

Run: uv run python demos/refactor_legacy.py
"""
import tempfile
from pathlib import Path

from sick.agent import SickAgent


def main() -> None:
    ws = Path(tempfile.mkdtemp(prefix="sick-refactor-"))
    agent = SickAgent(workspace=ws)

    # create legacy project
    agent.write_file("utils.py", "def getCwd():\n    return \"/tmp\"\n")
    agent.write_file("main.py", "from utils import getCwd\nprint(getCwd())\n")
    agent.write_file("tests/test_utils.py", "from utils import getCwd\ndef test_cwd():\n    assert getCwd() == \"/tmp\"\n")

    # find all occurrences
    hits = agent.grep("getCwd")
    print("grep hits:", hits)
    assert len(hits) == 3

    # rename with edit_file (requires unique per file)
    assert agent.edit_file("utils.py", "getCwd", "getCurrentWorkingDirectory")
    assert agent.edit_file("main.py", "getCwd", "getCurrentWorkingDirectory")
    assert agent.edit_file("tests/test_utils.py", "getCwd", "getCurrentWorkingDirectory")

    # verify no old hits, grep now finds new
    assert agent.grep("getCwd") == []
    assert len(agent.grep("getCurrentWorkingDirectory")) == 3

    # run tests via bash (real pytest if installed, else plain python)
    out = agent.bash("uv run pytest -q 2>&1 | head -20")
    print(out)
    # fallback run with python
    out2 = agent.bash("uv run python -c \"from utils import getCurrentWorkingDirectory; assert getCurrentWorkingDirectory()=='/tmp'; print('rename ok')\"")
    print(out2)
    assert "rename ok" in out2
    print("demo passed: refactor_legacy")


if __name__ == "__main__":
    main()
