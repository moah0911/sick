#!/usr/bin/env python3
"""Real demo: /visual scaffolding check (no live LLM, exercises tool path).

Verifies SickApp slash dispatch and that bash + glob can scaffold a fake
remotion project (real filesystem ops, no npx required).

Run: uv run python demos/visual_demo.py
"""
import asyncio
import tempfile
from pathlib import Path

from sick.agent import SickAgent


class FakeAgent(SickAgent):
    def __init__(self, workspace="."):
        super().__init__(workspace=workspace)
        self.received = []

    async def respond(self):
        self.received.append(self.context.get("user_request"))


async def main() -> None:
    ws = Path(tempfile.mkdtemp(prefix="sick-visual-"))
    agent = FakeAgent(str(ws))
    from sick.tui.app import SickApp
    from sick.tui.host import TurnHost

    # minimal chat stub
    class DummyChat:
        def set_busy(self, busy): pass
        def add_error(self, text): print(text)

    chat = DummyChat()
    host = TurnHost(agent, chat)  # type: ignore
    host.start()
    app = SickApp(agent)
    # dispatch /visual without needing full TUI mount
    result = await app.commands.dispatch(app, "/visual how a hash table works")
    print(result)
    assert "hash table" in result.lower() or "making a video" in result.lower()
    # wait for host to deliver the hidden prompt
    import time
    deadline = time.time() + 3
    while not agent.received and time.time() < deadline:
        await asyncio.sleep(0.05)
    host.stop()
    assert agent.received and "Remotion" in agent.received[0]
    # simulate scaffold via bash (real file ops)
    agent.write_file("remotion-demo/src/Root.tsx", "export const Root=()=>null")
    assert "Root.tsx" in agent.glob("*.tsx", path="remotion-demo")
    print("demo passed: visual_demo")


if __name__ == "__main__":
    asyncio.run(main())
