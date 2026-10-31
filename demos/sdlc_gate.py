#!/usr/bin/env python3
"""Demo: the SDLC gate blocks unverified work, then delivers verified work.

No LLM needed — respond() is scripted. Run: uv run python demos/sdlc_gate.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path

from sick.agent import SickAgent


class Unverified(SickAgent):
    async def respond(self):
        self.write_file("mod.py", "x = 1\n")


class Verified(SickAgent):
    async def respond(self):
        self.read_file("mod.py")
        self.write_file("mod.py", "x = 1\n")
        self.write_file("test_mod.py", "from mod import x\n\ndef test_x():\n    assert x == 1\n")
        self.bash(f"{sys.executable} -m pytest -q")


async def main():
    ws = Path(tempfile.mkdtemp())
    (ws / "mod.py").write_text("x = 0\n")

    agent = Unverified(workspace=ws)
    await agent.handle({"user_messages": ["create mod.py"]})
    run = agent.current_run
    print(f"unverified edit -> phase={run.phase.value} tier={run.tier.value}")
    print(f"  gate: {agent.context['sdlc_result']}")

    agent2 = Verified(workspace=ws)
    await agent2.handle({"user_messages": ["create mod.py and test it"]})
    run2 = agent2.current_run
    print(f"verified edit   -> phase={run2.phase.value} tier={run2.tier.value}")
    print(f"  gate: {agent2.context['sdlc_result']}")
    print(f"  artifacts: {sorted(p.name for p in run2.dir.iterdir())}")
    assert run.phase.value == "blocked" and run2.phase.value == "deliver"
    print("OK: unverified work was blocked, verified work delivered")


if __name__ == "__main__":
    asyncio.run(main())
