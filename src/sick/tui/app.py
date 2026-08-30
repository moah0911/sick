from __future__ import annotations

import asyncio
import re
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, LoadingIndicator

from sick.tui.chat import ChatView
from sick.tui.commands import SlashCommandRegistry
from sick.tui.host import TurnHost
from sick.tui.inputbar import SickInput

MAX_ATTACH_BYTES = 100_000
MAX_BASH_CHARS = 4_000
MAX_TOTAL_ATTACH = 300_000


class SickApp(App):
    """Sick coding agent TUI — complete."""

    TITLE = "sick"
    CSS = """
    Screen { layout: vertical; }
    ChatView {
        height: 1fr;
        border: round $primary;
        margin: 0 1;
        overflow-y: auto;
    }
    SickInput {
        margin: 0 1 1 1;
        height: 3;
    }
    LoadingIndicator {
        display: none;
        height: 1;
        margin: 0 1;
    }
    LoadingIndicator.-visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("ctrl+x,q", "quit", "quit"),
        Binding("ctrl+q", "quit", "quit", show=False),
        Binding("ctrl+c", "interrupt", "interrupt"),
        Binding("ctrl+x,c", "clear", "clear"),
        Binding("ctrl+l", "clear", "clear", show=False),
        Binding("ctrl+x,h", "help", "help"),
        Binding("f1", "help", "help", show=False),
        Binding("ctrl+x,space", "focus_input", "focus input"),
        Binding("pageup", "page_up", "page up", show=False),
        Binding("pagedown", "page_down", "page down", show=False),
        Binding("home", "scroll_home", "top", show=False),
        Binding("end", "scroll_end", "bottom", show=False),
        Binding("up", "history_up", "history up", show=False),
        Binding("down", "history_down", "history down", show=False),
    ]

    def __init__(self, agent, **kwargs) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self.commands = SlashCommandRegistry(workspace=getattr(agent, "workspace", Path.cwd()))
        self.pending_task: str | None = None
        self.chat_view: ChatView | None = None
        self.sick_input: SickInput | None = None
        self.loading: LoadingIndicator | None = None
        self.host = TurnHost(agent, None)  # type: ignore[arg-type]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ChatView()
        yield LoadingIndicator()
        yield SickInput(self._on_submit, agent=self.agent, commands=self.commands)
        yield Footer()

    def on_mount(self) -> None:
        self.chat_view = self.query_one(ChatView)
        self.sick_input = self.query_one(SickInput)
        self.loading = self.query_one(LoadingIndicator)
        self.host.chat = self.chat_view
        # patch busy to also control input + loading
        orig_set_busy = self.chat_view.set_busy

        def _busy(busy: bool) -> None:
            orig_set_busy(busy)
            if self.sick_input:
                self.sick_input.set_busy(busy)
            if self.loading:
                self.loading.display = busy
            # footer clock already shows time

        self.chat_view.set_busy = _busy  # type: ignore
        self.host.chat.set_busy = _busy  # type: ignore
        # safe markdown
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
        self.chat_view.add_tool("ready — type a message, /help for commands | @file attach | !cmd bash")
        self.chat_view.add_tool(f"workspace: {self.agent.workspace} | model: {self._model_str()}")
        self.set_focus(self.sick_input)

    def _model_str(self) -> str:
        try:
            from sick.providers import detect

            p = detect()
            return f"{p.model_id} ({p.name})"
        except Exception:
            llm = getattr(self.agent, "_llm", None)
            return getattr(llm, "model", "no llm") if llm else "no llm"

    def on_unmount(self) -> None:
        self.host.stop()

    # ── actions ──
    def action_quit(self) -> None:
        # ponytail: no modal confirm unless dirty? keep simple confirm via chat
        if self.chat_view and "dirty" in str(self.agent.workspace):
            self.chat_view.add_tool("quit — use ctrl+q again to confirm")
            return
        self.exit()

    def action_clear(self) -> None:
        if self.chat_view:
            self.chat_view.clear()
        self.agent.context["user_request"] = ""
        if self.chat_view:
            self.chat_view.add_tool("conversation cleared (history kept in audit)")

    def action_help(self) -> None:
        asyncio.create_task(self._handle_input("/help"))

    def action_focus_input(self) -> None:
        if self.sick_input:
            self.set_focus(self.sick_input)

    def action_interrupt(self) -> None:
        self.chat_view.add_tool("interrupt requested")
        self.host.stop()
        # restart host
        try:
            self.host.start()
        except Exception:
            pass
        if self.sick_input:
            self.sick_input.set_busy(False)
        if self.chat_view:
            self.chat_view.set_busy(False)
        if self.loading:
            self.loading.display = False

    def action_page_up(self) -> None:
        if self.chat_view:
            self.chat_view.scroll_page_up()

    def action_page_down(self) -> None:
        if self.chat_view:
            self.chat_view.scroll_page_down()

    def action_scroll_home(self) -> None:
        if self.chat_view:
            self.chat_view.scroll_home(animate=False)

    def action_scroll_end(self) -> None:
        if self.chat_view:
            self.chat_view.scroll_end(animate=False)

    def action_history_up(self) -> None:
        if self.sick_input:
            self.sick_input.action_history_up()

    def action_history_down(self) -> None:
        if self.sick_input:
            self.sick_input.action_history_down()

    # ── input handling ──
    def _on_submit(self, raw: str) -> None:
        task = asyncio.create_task(self._handle_input(raw))
        task.add_done_callback(lambda t: self._on_task_done(t))

    def _on_task_done(self, task: asyncio.Task) -> None:
        try:
            exc = task.exception()
            if exc:
                if self.chat_view:
                    self.chat_view.add_error(f"task failed: {exc}")
        except asyncio.CancelledError:
            pass

    async def _handle_input(self, raw: str) -> None:
        try:
            if raw.startswith("/"):
                result = await self.commands.dispatch(self, raw)
                if result and self.chat_view:
                    self.chat_view.add_agent(result)
                return
            if raw.startswith("!"):
                cmd = raw[1:].strip()
                if not cmd:
                    if self.chat_view:
                        self.chat_view.add_tool("usage: !<command> e.g. !ls -la")
                    return
                await self._run_bash(cmd)
                return
            await self._send(raw)
        except Exception as e:
            if self.chat_view:
                self.chat_view.add_error(f"handle failed: {e}")

    async def _run_bash(self, command: str) -> None:
        if not command:
            return
        if self.chat_view:
            self.chat_view.add_tool(f"$ {command}")
        # destructive guard
        dangerous = any(x in command for x in ["rm -rf /", "mkfs", ":(){"])
        if dangerous and self.chat_view:
            self.chat_view.add_tool("[warn: dangerous command — use --sandbox for isolation]")
        output = await asyncio.to_thread(self.agent.bash, command)
        truncated = len(output) > MAX_BASH_CHARS
        display = output.strip()[:MAX_BASH_CHARS] or "(no output)"
        if truncated and self.chat_view:
            display += f"\n[truncated after {MAX_BASH_CHARS} chars, full {len(output)}]"
        if self.chat_view:
            # color by exit code
            if "[exit code" in output or "[timed out" in output or "[error" in output:
                self.chat_view.add_error(display)
            else:
                self.chat_view.add_tool(display)
        await self._send(
            f"[you ran a shell command] `{command}`\n\noutput:\n```\n{output[:MAX_BASH_CHARS]}\n```",
            show=False,
        )

    async def _send(self, text: str, show: bool = True) -> None:
        expanded = self._expand_attachments(text)
        if show and self.chat_view:
            self.chat_view.add_user(text)
        await self.host.submit(expanded)

    def _expand_attachments(self, text: str) -> str:
        # dedupe and total cap
        seen: set[str] = set()
        total = 0
        # ignore @ in code blocks and emails: negative lookbehind for word char
        for m in re.finditer(r"(?<!\w)@([^\s,;`]+)", text):
            raw = m.group(1).rstrip(",.;: )]`'\"")
            if not raw or raw in seen:
                continue
            # handle quoted paths with spaces: @"my file.txt" handled via broader regex fallback
            # expanduser and resolve against workspace
            try:
                p = Path(raw).expanduser()
                if not p.is_absolute():
                    # try workspace relative first
                    ws = Path(self.agent.workspace)
                    cand = (ws / p).resolve()
                    # if cand exists use it, else try cwd
                    if cand.exists():
                        p = cand
                    else:
                        # fallback to cwd resolve
                        p = (Path.cwd() / p).resolve() if not p.exists() else p.resolve()
                else:
                    p = p.resolve()
            except Exception:
                p = Path(raw)
            if not p.exists() or p.is_dir():
                if self.chat_view:
                    self.chat_view.add_tool(f"[attach missing: {raw}]")
                continue
            # check binary
            try:
                if p.stat().st_size > MAX_ATTACH_BYTES * 3:
                    if self.chat_view:
                        self.chat_view.add_tool(f"[attach large: {p} {p.stat().st_size} bytes, truncating]")
            except OSError:
                pass
            seen.add(raw)
            if total > MAX_TOTAL_ATTACH:
                text += f"\n\n--- attached: {p} ---\n[skipped: total attach cap {MAX_TOTAL_ATTACH} reached]"
                continue
            try:
                if p.suffix.lower() == ".pdf":
                    content = self.agent.parse_pdf(str(p))
                else:
                    # workspace check: allow user-initiated outside, but still bound
                    raw_content = p.read_text(errors="replace")
                    truncated = len(raw_content) > MAX_ATTACH_BYTES
                    content = raw_content[:MAX_ATTACH_BYTES]
                    if truncated:
                        content += f"\n[truncated after {MAX_ATTACH_BYTES} bytes]"
                total += len(content)
                text += f"\n\n--- attached: {p} ---\n{content}"
            except Exception as exc:
                text += f"\n\n--- attached: {p} ---\n[unreadable: {exc}]"
        # also handle @"..." quoted with spaces
        for m in re.finditer(r'@\"([^\"]+)\"', text):
            raw = m.group(1)
            if raw in seen:
                continue
            p = Path(raw).expanduser()
            if not p.is_absolute():
                p = (Path(self.agent.workspace) / p).resolve()
            if not p.exists() or p.is_dir():
                continue
            try:
                content = p.read_text(errors="replace")[:MAX_ATTACH_BYTES]
                text += f"\n\n--- attached: {p} ---\n{content}"
                seen.add(raw)
            except Exception as exc:
                text += f"\n\n--- attached: {p} ---\n[unreadable: {exc}]"
        return text
