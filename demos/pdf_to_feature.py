#!/usr/bin/env python3
"""Real demo: PDF spec → feature → checkpoint, using sick tools directly (no LLM mock).

Flow:
- creates a mini spec markdown (simulating parsed PDF)
- writes auth.py via WriteFile tool (as agent would)
- validates with grep + bash pytest, checkpoints, restores on failure

Run: uv run python demos/pdf_to_feature.py
"""
import tempfile
import subprocess
from pathlib import Path

from sick.agent import SickAgent


def main() -> None:
    workspace = Path(tempfile.mkdtemp(prefix="sick-pdf-demo-"))
    # init git so checkpoint works
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.email", "demo@sick"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "sick"], cwd=workspace, check=True)
    (workspace / "README.md").write_text("# demo\n")
    subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=workspace, check=True)

    agent = SickAgent(workspace=workspace)
    # simulate PDF attachment: agent already supports --attach *.pdf via parse_pdf,
    # here we exercise the tool pipeline explicitly
    spec = """# Auth spec\n\n- function `authenticate(token)` validates session token\n- returns True iff token == \"secret\"\n"""
    # pretend parse_pdf gave us this spec in context
    agent.context["attachment_spec"] = spec

    # agent would now research, but we exercise code_research + write_file
    agent.write_file("auth.py", "def authenticate(token):\n    \"\"\"Validate token.\"\"\"\n    return token == \"secret\"\n")
    print("write_file -> auth.py created")
    assert "authenticate" in agent.read_file("auth.py")
    hits = agent.code_research("token validation")
    print(hits)
    assert "authenticate" in hits or "auth.py" in hits

    # verify
    out = agent.bash("uv run python -c \"import auth; assert auth.authenticate('secret'); assert not auth.authenticate('bad'); print('auth ok')\"")
    print(out)
    assert "auth ok" in out

    # checkpoint success path
    cp = agent.checkpoint("pdf feature done")
    print(cp)
    assert "checkpoint created" in cp

    # prove restore works: break file then restore
    agent.write_file("auth.py", "broken")
    agent.checkpoint("broken")
    print(agent.restore(n=1))
    assert "secret" in agent.read_file("auth.py")
    print("demo passed: pdf_to_feature")


if __name__ == "__main__":
    main()
