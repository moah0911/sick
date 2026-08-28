from __future__ import annotations

import asyncio
import re
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header

from sick.tui.chat import ChatView
from sick.tui.commands import SlashCommandRegistry
from sick.tui.host import TurnHost
from sick.tui.inputbar import SickInput

MAX_ATTACH_BYTES = 100_000
MAX_BASH_CHARS = 4_000


class SickApp(App):
    """Sick coding agent TUI."""

    TITLE = "sick"
    CSS = """
    ChatView {
        border: round $primary;
        margin: 0 1;
    }
    SickInput {
        margin: 0 1 1 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+x,q", "quit", "quit"),
        Binding("ctrl+x,c", "clear", "clear conversation"),
        Binding("ctrl+x,h", "help", "commands"),
        Binding("ctrl+x,space", "focus_input", "focus input"),
    ]

    def __init__(self, agent, **kwargs) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self.commands = SlashCommandRegistry()
        self.pending_task: str | None = None
        self.chat_view: ChatView | None = None
        self.host = TurnHost(agent, None)  # type: ignore[arg-type]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield ChatView()
        yield SickInput(self._on_submit)

    def on_mount(self) -> None:
        self.chat_view = self.query_one(ChatView)
        self.input = self.query_one(SickInput)
        self.host.chat = self.chat_view
        # ponytail: guard markdown errors from LLM output
        orig_add = self.chat_view.add_agent

        def _safe_add(text: str) -> None:
            try:
                orig_add(text)
            except Exception as e:
                self.chat_view.add_tool(f"[render error: {e}]")
                try:
                    self.chat_view.write(f"  sick: {text[:4000]}")
                except Exception:
                    pass

        self.agent._render_message = _safe_add
        self.host.start()
        self.chat_view.add_tool("ready — type a message, /help for commands")
        self.set_focus(self.input)

    def on_unmount(self) -> None:
        self.host.stop()

    # ── key actions ──

    def action_quit(self) -> None:
        self.exit()

    def action_clear(self) -> None:
        if self.chat_view:
            self.chat_view.clear()
        self.agent.context["user_request"] = ""
        self.chat_view.add_tool("conversation cleared")

    def action_help(self) -> None:
        asyncio.create_task(self._handle_input("/help"))

    def action_focus_input(self) -> None:
        self.set_focus(self.input)

    # ── input handling ──

    def _on_submit(self, raw: str) -> None:
        asyncio.create_task(self._handle_input(raw))

    async def _handle_input(self, raw: str) -> None:
        if raw.startswith("/"):
            result = await self.commands.dispatch(self, raw)
            if result and self.chat_view:
                self.chat_view.add_agent(result)
            return
        if raw.startswith("!"):
            await self._run_bash(raw[1:].strip())
            return
        await self._send(raw)

    async def _run_bash(self, command: str) -> None:
        if not command:
            return
        self.chat_view.add_tool(f"$ {command}")
        output = await asyncio.to_thread(self.agent.bash, command)
        self.chat_view.add_tool(output.strip()[:MAX_BASH_CHARS] or "(no output)")
        await self._send(
            f"[you ran a shell command] `{command}`\n\noutput:\n```\n{output[:MAX_BASH_CHARS]}\n```",
            show=False,
        )

    async def _send(self, text: str, show: bool = True) -> None:
        expanded = self._expand_attachments(text)
        if show:
            self.chat_view.add_user(text)
        await self.host.submit(expanded)

    def _expand_attachments(self, text: str) -> str:
        for m in re.finditer(r"@([^\s,;]+)", text):
            raw = m.group(1).rstrip(",.;: )]")
            if not raw:
                continue
            p = Path(raw)
            if not p.exists() or p.is_dir():
                continue
            try:
                # Enforce workspace boundary for non-PDF; PDFs already do resolve_path
                if p.suffix.lower() != ".pdf":
                    try:
                        # reuse agent's read_file workspace check
                        self.agent._tools["read_file"].resolve_path(str(p))
                    except ValueError as e:
                        content = f"[blocked: {e}]"
                        text += f"\n\n--- attached: {p} ---\n{content}"
                        continue
                if p.suffix.lower() == ".pdf":
                    content = self.agent.parse_pdf(str(p))
                else:
                    raw_content = p.read_text(errors="replace")
                    truncated = len(raw_content) > MAX_ATTACH_BYTES
                    content = raw_content[:MAX_ATTACH_BYTES]
                    if truncated:
                        content += f"\n[truncated after {MAX_ATTACH_BYTES} bytes]"
            except Exception as exc:
                content = f"[unreadable: {exc}]"
            text += f"\n\n--- attached: {p} ---\n{content}"
        return text