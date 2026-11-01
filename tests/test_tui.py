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


def test_host_skips_session_checkpoint_outside_git(tmp_path):
    from sick.tui.host import TurnHost

    async def scenario():
        agent = FakeAgent(str(tmp_path))
        host = TurnHost(agent, DummyChat())
        host.start()
        await host.submit("hello")
        deadline = time.time() + 10
        while not agent.received and time.time() < deadline:
            await asyncio.sleep(0.05)
        host.stop()
        tools = [e["tool"] for e in agent.audit.entries()]
        assert "checkpoint" not in tools  # non-git: no doomed session-start call

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


def test_plan_lifecycle_phases(tmp_path):
    from sick.lifecycle import Phase
    from sick.tui.app import SickApp

    async def scenario():
        agent = FakeAgent(str(tmp_path))
        app = SickApp(agent)
        await app.commands.dispatch(app, "/plan add tests")
        assert agent.current_run is not None
        assert agent.current_run.phase == Phase.DESIGN
        assert (tmp_path / ".sick" / "runs" / agent.current_run.id / "plan.md").is_file()
        await app.commands.dispatch(app, "/approve")
        assert agent.current_run.phase == Phase.IMPLEMENT
        out = await app.commands.dispatch(app, "/run")
        assert "implement" in out and agent.current_run.id in out
        await app.commands.dispatch(app, "/plan redo it")
        await app.commands.dispatch(app, "/reject")
        assert agent.current_run.phase == Phase.CANCELLED

    asyncio.run(scenario())


def test_connect_switches_provider_live(tmp_path, monkeypatch):
    from sick.tui.app import SickApp

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.delenv("SICK_BASE_URL", raising=False)
    monkeypatch.delenv("SICK_MODEL", raising=False)

    async def scenario():
        agent = FakeAgent(str(tmp_path))
        app = SickApp(agent)
        out = await app.commands.dispatch(app, "/connect groq")
        assert "switched to groq" in out and "openai/gpt-oss-120b" in out
        assert agent._llm is not None
        # header + /models must show the live client, not a re-detected default
        assert "groq/openai/gpt-oss-120b" in app._model_str()
        models_out = await app.commands.dispatch(app, "/models")
        assert "groq/openai/gpt-oss-120b" in models_out
        out = await app.commands.dispatch(app, "/connect setup")
        assert "--setup" in out
        out = await app.commands.dispatch(app, "/connect bogus")
        assert "unknown provider" in out
        status = await app.commands.dispatch(app, "/connect")
        assert "GROQ_API_KEY (groq): set" in status
        assert "gsk-test" not in status  # key values never shown

    asyncio.run(scenario())


def test_thinking_renders_llm_reasoning(tmp_path):
    """LLMComplete.reasoning_content must reach the chat when visible."""
    from types import SimpleNamespace

    from sick.tui.app import SickApp

    async def scenario():
        agent = FakeAgent(str(tmp_path))
        app = SickApp(agent)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.show_thinking is True
            app._on_llm_complete(SimpleNamespace(reasoning_content="weighing options"))
            await pilot.pause()
            assert any("weighing options" in str(line) for line in app.chat_view.lines)
            assert ("thinking", "weighing options") in app.transcript
            # hidden mode renders nothing
            app.show_thinking = False
            app._on_llm_complete(SimpleNamespace(reasoning_content="secret thoughts"))
            await pilot.pause()
            assert not any("secret thoughts" in str(line) for line in app.chat_view.lines)

    asyncio.run(scenario())


def test_live_feed_streams_tools_thinking_and_stays_visible(tmp_path):
    """OpenCode-style live feed: user line, tool lines, thinking — in flight."""
    from types import SimpleNamespace

    from sick.tui.app import SickApp
    from sick.tui.host import TurnHost

    class WorkingAgent(FakeAgent):
        async def respond(self):
            self.write_file("hello.py", "print('hello')\n")
            self.bash("echo done")

    async def scenario():
        agent = WorkingAgent(str(tmp_path))
        app = SickApp(agent)
        host = TurnHost(agent, DummyChat())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            host.start()
            await host.submit("write hello")
            deadline = time.time() + 10
            while agent.turns < 1 and time.time() < deadline:
                await asyncio.sleep(0.05)
                await pilot.pause()
            # let the turn drain through the host loop
            for _ in range(40):
                await asyncio.sleep(0.05)
                await pilot.pause()
                if any("hello.py" in str(ln) for ln in app.chat_view.lines):
                    break
            host.stop()
            lines = [str(ln) for ln in app.chat_view.lines]
            assert any("write_file" in ln for ln in lines), lines[-8:]
            assert any("✓" in ln and "write_file" in ln for ln in lines)
            assert (tmp_path / "hello.py").is_file()
            # busy must never cover the chat with RichLog's loading overlay
            app.chat_view.set_busy(True)
            assert app.chat_view.loading is False
            # status bar carries the compact SDLC segment; /status has the stepper
            app.refresh_status()
            assert "sdlc" in str(app.status_bar.content) and "gate" in str(app.status_bar.content)
            status_out = await app.commands.dispatch(app, "/status")
            assert "SDLC" in status_out and "requirements" in status_out
            # messages are distinct: turn separator renders a boundary line
            app.chat_view.add_turn_separator(2, "10:42")
            await pilot.pause()
            assert any("turn 2" in str(ln) for ln in app.chat_view.lines)
            app._on_llm_output(SimpleNamespace(content="print('x')\nprint('y')"))
            await pilot.pause()
            assert any("▸ code:" in str(ln) for ln in app.chat_view.lines)

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


def test_new_commands_registered(tmp_path):
    from sick.tui.app import SickApp

    app = SickApp(FakeAgent(str(tmp_path)))
    for name in (
        "learn", "undo", "redo", "compact", "summarize", "export", "init",
        "sessions", "resume", "continue", "details", "thinking", "editor",
        "connect", "themes", "update",
    ):
        assert name in app.commands.commands, name
    help_names = [c.name for c in app.commands.canonical]
    assert "learn" in help_names and "undo" in help_names


def test_learn_command_sends_improvement_prompt(tmp_path):
    from sick.tui.app import SickApp
    from sick.tui.host import TurnHost

    async def scenario():
        agent = FakeAgent(str(tmp_path))
        host = TurnHost(agent, DummyChat())
        host.start()
        app = SickApp(agent)
        result = await app.commands.dispatch(app, "/learn fix bash timeouts")
        deadline = time.time() + 5
        while not agent.received and time.time() < deadline:
            await asyncio.sleep(0.05)
        host.stop()
        assert "learn" in result and "self-improvement started" in result
        assert agent.received and "checkpoint('pre-learn')" in agent.received[0]
        assert "fix bash timeouts" in agent.received[0]

    asyncio.run(scenario())


def test_compact_export_init_sessions(tmp_path):
    from sick.tui.app import SickApp

    async def scenario():
        agent = FakeAgent(str(tmp_path))
        app = SickApp(agent)
        app.transcript = [("you", "hello"), ("sick", "hi there")]
        out = await app.commands.dispatch(app, "/export out.md")
        assert "exported" in out
        exported = (tmp_path / "out.md").read_text()
        assert "hello" in exported and "hi there" in exported
        out = await app.commands.dispatch(app, "/compact")
        assert "compacted" in out and "compact_summary" in agent.context
        out = await app.commands.dispatch(app, "/init")
        assert "AGENTS.md" in out and (tmp_path / "AGENTS.md").is_file()
        out = await app.commands.dispatch(app, "/init")
        assert "already exists" in out
        out = await app.commands.dispatch(app, "/sessions")
        assert "sessions" in out and "turns" in out

    asyncio.run(scenario())


def test_details_thinking_connect_themes_update(tmp_path, monkeypatch):
    from sick.tui.app import SickApp

    async def scenario():
        app = SickApp(FakeAgent(str(tmp_path)))
        out = await app.commands.dispatch(app, "/details")
        assert "on" in out and app.show_details is True
        out = await app.commands.dispatch(app, "/details")
        assert "off" in out and app.show_details is False
        # thinking defaults to visible; /thinking toggles it off and back on
        assert app.show_thinking is True
        out = await app.commands.dispatch(app, "/thinking")
        assert "hidden" in out and app.show_thinking is False
        out = await app.commands.dispatch(app, "/thinking")
        assert "visible" in out and app.show_thinking is True
        out = await app.commands.dispatch(app, "/connect")
        assert "providers" in out and "API_KEY" in out
        assert "sk-" not in out  # never leak key values
        out = await app.commands.dispatch(app, "/themes")
        assert "available:" in out
        out = await app.commands.dispatch(app, "/themes textual-light")
        assert "textual-light" in out
        out = await app.commands.dispatch(app, "/themes nope-theme")
        assert "unknown theme" in out
        out = await app.commands.dispatch(app, "/update")
        assert "sick" in out and "install.sh" in out

    asyncio.run(scenario())


def test_undo_redo_roundtrip(tmp_path, monkeypatch):
    import subprocess

    from sick.tui.app import SickApp

    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("v1")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    async def scenario():
        agent = FakeAgent(str(tmp_path))
        app = SickApp(agent)
        agent.checkpoint("base")
        agent.write_file("f.txt", "v2")
        out = await app.commands.dispatch(app, "/undo")
        assert "undid" in out, out
        assert (tmp_path / "f.txt").read_text() == "v1"
        out = await app.commands.dispatch(app, "/redo")
        assert "redone" in out, out
        assert (tmp_path / "f.txt").read_text() == "v2"
        out = await app.commands.dispatch(app, "/redo")
        assert "nothing to redo" in out

    asyncio.run(scenario())


def test_editor_command(tmp_path, monkeypatch):
    from sick.tui.app import SickApp

    script = tmp_path / "fake-editor.sh"
    script.write_text('#!/bin/sh\nprintf "hello from editor" > "$1"\n')
    script.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(script))

    async def scenario():
        app = SickApp(FakeAgent(str(tmp_path)))
        return await app.commands.dispatch(app, "/editor")

    out = asyncio.run(scenario())
    assert "sent message composed in editor" in out


def test_editor_without_editor_env(tmp_path, monkeypatch):
    from sick.tui.app import SickApp

    monkeypatch.delenv("EDITOR", raising=False)

    async def scenario():
        app = SickApp(FakeAgent(str(tmp_path)))
        return await app.commands.dispatch(app, "/editor")

    assert "EDITOR is not set" in asyncio.run(scenario())


def test_leader_keys_dispatch_not_typed(tmp_path):
    """ctrl+x leader: the second key runs a command, never enters the input."""
    from sick.tui.app import SickApp

    async def scenario():
        agent = FakeAgent(str(tmp_path))
        app = SickApp(agent)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            before = len(app.transcript)
            await pilot.press("ctrl+x", "s")  # sessions
            await pilot.pause()
            await asyncio.sleep(0.2)
            await pilot.pause()
            assert len(app.transcript) > before  # command ran
            assert app.sick_input.value == ""  # 's' was not typed
            await pilot.press("ctrl+x", "l")  # learn
            deadline = time.time() + 5
            while not agent.received and time.time() < deadline:
                await asyncio.sleep(0.05)
                await pilot.pause()
            assert agent.received and "checkpoint('pre-learn')" in agent.received[0]
            assert app.sick_input.value == ""

    asyncio.run(scenario())


def test_tui_design_layout_theme_and_keys(tmp_path):
    """Design check: sick theme, full-width canvas (no sidebar), status bar, keys."""
    from sick.tui.app import SickApp

    async def scenario():
        agent = FakeAgent(str(tmp_path))
        app = SickApp(agent)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.theme == "sick"
            assert app.status_bar is not None
            # no sidebar: nothing competes with the chat for width
            assert not list(app.query("#status-panel"))
            assert app.chat_view.size.width >= 110  # nearly full 120-col canvas
            assert "turns" in str(app.status_bar.content)
            assert "sdlc" in str(app.status_bar.content)  # compact tracker segment
            assert app.chat_view.border_title.startswith("sick")
            assert app.sick_input.border_title == "message"
            # scrollbars hidden (no stock-blue bars), scrolling still works
            assert app.chat_view.scrollbar_size_vertical == 0
            # /status carries the full detail the sidebar used to show
            status_out = await app.commands.dispatch(app, "/status")
            assert "SDLC" in status_out and "gate" in status_out and "ponytail" in status_out
            # /help is grouped + carries the keymap
            help_out = await app.commands.dispatch(app, "/help")
            assert "### session" in help_out and "### work" in help_out
            assert "ctrl+x l" in help_out and "/learn" in help_out
            # footer advertises the everyday keys; leader map covers the rest
            footer_keys = {b.description for b in app.BINDINGS}
            assert {"quit", "clear", "help", "theme"} <= footer_keys
            assert {"h", "n", "c", "l", "s", "u", "q"} <= set(app.LEADER_KEYS)
            # real keypresses: ctrl+x h opens help, ctrl+t cycles theme
            await pilot.press("ctrl+x", "h")
            await pilot.pause()
            before = app.theme
            await pilot.press("ctrl+t")
            await pilot.pause()
            assert app.theme != before
            # /details still flips view state, visible via /status
            out = await app.commands.dispatch(app, "/details")
            assert "on" in out
            assert "details on" in await app.commands.dispatch(app, "/status")
            # narrow terminal: chat still fits, nothing clipped by a panel
            await pilot.resize_terminal(70, 24)
            await pilot.pause()
            assert app.chat_view.size.width >= 60

    asyncio.run(scenario())


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
