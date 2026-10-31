"""Tests for the TUI: turn host loop and attachment expansion."""
import asyncio
import tempfile
import time
from pathlib import Path

from sick.agent import SickAgent


class FakeAgent(SickAgent):
    def __init__(self, workspace="."):
        super().__init__(workspace=workspace)
        self.received = []

    async def respond(self):
        self.received.append(self.context.get("user_request"))


class DummyChat:
    def __init__(self):
        self.busy = None
        self.errors = []

    def set_busy(self, busy):
        self.busy = busy

    def add_error(self, text):
        self.errors.append(text)


def test_host_delivers_user_messages(tmp_path):
    from sick.tui.host import TurnHost

    async def scenario():
        agent = FakeAgent(str(tmp_path))
        chat = DummyChat()
        host = TurnHost(agent, chat)
        host.start()
        await host.submit("hello there")
        deadline = time.time() + 10
        while not agent.received and time.time() < deadline:
            await asyncio.sleep(0.05)
        # busy may still be True briefly - wait
        deadline2 = time.time() + 3
        while chat.busy is not False and time.time() < deadline2:
            await asyncio.sleep(0.05)
        host.stop()
        await asyncio.sleep(0.1)
        assert agent.received == ["hello there"]
        # allow busy to be False or None if not yet set, but not True
        assert chat.busy is not True

    asyncio.run(scenario())


def test_expand_attachments():
    from sick.tui.app import SickApp

    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "notes.txt"
        f.write_text("important context")
        app = SickApp(FakeAgent())
        out = app._expand_attachments(f"do the thing @{f}")
        assert "important context" in out
        assert f"--- attached: {f} ---" in out


def test_expand_attachments_ignores_missing():
    from sick.tui.app import SickApp

    app = SickApp(FakeAgent())
    out = app._expand_attachments("fix @does_not_exist.py")
    assert "attached" not in out


def test_slash_dispatch_unknown():
    from sick.tui.app import SickApp

    async def scenario():
        app = SickApp(FakeAgent())
        return await app.commands.dispatch(app, "/nope")

    assert "unknown command" in asyncio.run(scenario())


def test_visual_command_submits_prompt():
    from sick.tui.app import SickApp
    from sick.tui.host import TurnHost

    async def scenario():
        agent = FakeAgent()
        host = TurnHost(agent, DummyChat())
        host.start()
        app = SickApp(agent)
        result = await app.commands.dispatch(app, "/visual how a hash table works")
        deadline = time.time() + 5
        while not agent.received and time.time() < deadline:
            await asyncio.sleep(0.05)
        host.stop()
        assert "hash table works" in result
        assert "Remotion" in agent.received[0]

    asyncio.run(scenario())


def test_visual_command_requires_topic():
    from sick.tui.app import SickApp

    async def scenario():
        app = SickApp(FakeAgent())
        return await app.commands.dispatch(app, "/visual")

    assert "usage" in asyncio.run(scenario())


def test_plan_approve_reject_flow():
    from sick.tui.app import SickApp

    async def scenario():
        app = SickApp(FakeAgent())
        r1 = await app.commands.dispatch(app, "/plan add tests")
        assert "approve" in r1 and app.pending_task == "add tests"
        r2 = await app.commands.dispatch(app, "/approve")
        assert app.pending_task is None and "add tests" in r2
        r3 = await app.commands.dispatch(app, "/reject")
        assert "nothing pending" in r3

    asyncio.run(scenario())


def test_plan_reject_clears_pending():
    from sick.tui.app import SickApp

    async def scenario():
        app = SickApp(FakeAgent())
        await app.commands.dispatch(app, "/plan fix the bug")
        r = await app.commands.dispatch(app, "/reject")
        assert "discarded" in r and app.pending_task is None

    asyncio.run(scenario())


def test_stats_command():
    from sick.tui.app import SickApp

    async def scenario():
        app = SickApp(FakeAgent())
        return await app.commands.dispatch(app, "/stats")

    out = asyncio.run(scenario())
    assert "turns: 0" in out


def test_audit_command(tmp_path):
    from sick.tui.app import SickApp

    async def scenario():
        agent = FakeAgent(str(tmp_path))
        agent.write_file("a.txt", "hi")
        app = SickApp(agent)
        return await app.commands.dispatch(app, "/audit")

    out = asyncio.run(scenario())
    assert "write_file" in out


def test_tui_pilot_mounts_and_runs_commands(tmp_path):
    """Full TUI check: mount, /help, custom command, @attach, !bash."""
    from sick.tui.app import SickApp

    (tmp_path / ".sick" / "commands").mkdir(parents=True)
    (tmp_path / ".sick" / "commands" / "greet.md").write_text(
        "---\ndescription: greet someone\n---\nSay hello to $ARGUMENTS\n"
    )
    (tmp_path / "notes.txt").write_text("pilot context")

    async def scenario():
        agent = FakeAgent(str(tmp_path))
        app = SickApp(agent)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.chat_view is not None
            assert app.sick_input is not None
            help_out = await app.commands.dispatch(app, "/help")
            assert "/greet" in help_out and "/help" in help_out
            fuzzy = await app.commands.dispatch(app, "/hepl")
            assert "did you mean" in fuzzy
            expanded = app._expand_attachments("read @notes.txt please")
            assert "pilot context" in expanded
            await app._handle_input("!echo pilot-bash-ok")
            deadline = time.time() + 5
            while not agent.received and time.time() < deadline:
                await asyncio.sleep(0.05)
            assert any("pilot-bash-ok" in (r or "") for r in agent.received)

    asyncio.run(scenario())