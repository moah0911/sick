from __future__ import annotations

import asyncio
import re
import threading
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.theme import Theme
from textual.widgets import Footer, Header, LoadingIndicator, Static

from sick.tui.chat import ChatView
from sick.tui.commands import SlashCommandRegistry
from sick.tui.host import TurnHost
from sick.tui.inputbar import SickInput

MAX_ATTACH_BYTES = 100_000
MAX_BASH_CHARS = 4_000
MAX_TOTAL_ATTACH = 300_000

# sick's own theme: calm dark slate, green = go/healthy, amber = attention.
# (deliberately no purple/blue gradients or magenta accents)
SICK_THEME = Theme(
    name="sick",
    primary="#2fbf71",
    secondary="#e0b341",
    accent="#3fb6a8",
    foreground="#d7dee8",
    background="#101418",
    surface="#171d24",
    panel="#1d242e",
    success="#2fbf71",
    warning="#e0b341",
    error="#e5534b",
    dark=True,
)


class SickApp(App):
    """Sick coding agent TUI — complete."""

    TITLE = "sick"
    SUB_TITLE = "self-improving coding agent"
    CSS = """
    Screen { layout: vertical; background: $background; }
    Header { background: $panel; color: $foreground; }
    Footer { background: $panel; }
    #body { height: 1fr; }
    ChatView {
        width: 1fr;
        height: 1fr;
        border: round $surface-lighten-2;
        border-title-color: $accent;
        margin: 0 0 0 1;
        padding: 0 1;
        overflow-y: auto;
        background: $surface;
    }
    ChatView:focus { border: round $accent; }
    #status-panel {
        width: 30;
        height: 1fr;
        margin: 0 1 0 1;
        padding: 1 2;
        background: $panel;
        border: round $surface-lighten-2;
        color: $foreground;
    }
    #status-bar {
        height: 1;
        margin: 0 1;
        padding: 0 1;
        background: $panel;
        color: $text-muted;
    }
    SickInput {
        margin: 0 1;
        height: 3;
        border: tall $surface-lighten-2;
        background: $surface;
    }
    SickInput:focus { border: tall $primary; }
    SickInput:disabled { border: tall $warning; }
    LoadingIndicator {
        display: none;
        height: 1;
        margin: 0 1;
        color: $primary;
    }
    LoadingIndicator.-visible { display: block; }
    """

    # keymap: ctrl+x is a LEADER key (handled in handle_leader_key, since
    # Textual Binding commas mean alternative keys, not chord sequences),
    # plus a few direct keys shown in the footer. /help lists them all.
    LEADER_KEYS = {
        "h": "help", "n": "clear", "c": "compact", "l": "learn",
        "s": "sessions", "u": "undo", "r": "redo", "e": "editor",
        "x": "export", "m": "models", "t": "themes", "d": "details",
        "q": "quit", "space": "focus_input",
    }

    BINDINGS = [
        Binding("ctrl+q", "quit", "quit"),
        Binding("ctrl+c", "interrupt", "interrupt", show=False),
        Binding("ctrl+l", "clear", "clear"),
        Binding("f1", "help", "help"),
        Binding("ctrl+t", "cycle_theme", "theme"),
        Binding("escape", "focus_input", "focus input", show=False),
        Binding("pageup", "page_up", "page up", show=False),
        Binding("pagedown", "page_down", "page down", show=False),
        Binding("home", "scroll_home", "top", show=False),
        Binding("end", "scroll_end", "bottom", show=False),
        Binding("up", "history_up", "history up", show=False),
        Binding("down", "history_down", "history down", show=False),
    ]

    def __init__(self, agent, **kwargs) -> None:
        super().__init__(**kwargs)
        self.register_theme(SICK_THEME)
        self.theme = "sick"
        self.agent = agent
        self.commands = SlashCommandRegistry(workspace=getattr(agent, "workspace", Path.cwd()))
        self.pending_task: str | None = None
        self.chat_view: ChatView | None = None
        self.sick_input: SickInput | None = None
        self.loading: LoadingIndicator | None = None
        self.status_panel: Static | None = None
        self.status_bar: Static | None = None
        self.host = TurnHost(agent, None)  # type: ignore[arg-type]
        # conversation transcript for /export and /compact (role, text)
        self.transcript: list[tuple[str, str]] = []
        self.show_details = False
        self.show_thinking = True
        self._can_redo = False
        self._busy_state = False
        self._work_started = 0.0
        self._last_tool = "—"
        self._llm_calls = 0
        self._ui_thread = 0
        self._branch = ""
        self._leader = False

    def handle_leader_key(self, key: str) -> bool:
        """ctrl+x leader: first press arms it, second key runs the action.

        Returns True when the key was consumed. Called from SickInput (which
        has focus while typing) and from App.on_key (chat focused).
        """
        if key == "ctrl+x":
            self._leader = True
            if self.sick_input:
                self.sick_input.border_subtitle = "ctrl+x — h help · n new · c compact · l learn · s sessions · u undo · q quit"
            return True
        if not self._leader:
            return False
        self._leader = False
        if self.sick_input:
            self.sick_input.border_subtitle = "enter send · /help · @file · !cmd"
        action = self.LEADER_KEYS.get(key)
        if action is not None:
            getattr(self, f"action_{action}")()
        return True

    def on_key(self, event) -> None:  # chat-focused keys bubble here
        if self.handle_leader_key(event.key):
            event.stop()
            event.prevent_default()

    def _note(self, role: str, text: str) -> None:
        self.transcript.append((role, text))
        if len(self.transcript) > 500:
            self.transcript = self.transcript[-500:]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield ChatView(id="chat")
            yield Static("", id="status-panel")
        yield LoadingIndicator()
        yield Static("", id="status-bar")
        yield SickInput(self._on_submit, agent=self.agent, commands=self.commands)
        yield Footer()

    def _git_branch(self) -> str:
        try:
            import subprocess

            r = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, cwd=self.agent.workspace, timeout=2,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    def refresh_status(self) -> None:
        """Re-render the sidebar + status bar from live session state."""
        if self.status_panel is None or self.status_bar is None:
            return
        ws = Path(self.agent.workspace)
        turns = getattr(self.agent, "turns", 0)
        registry = getattr(self.agent, "registry", None)
        tools = sum(registry.counts().values()) if registry is not None else 0
        run = getattr(self.agent, "current_run", None)
        sdlc_line = f"  sdlc    {run.phase.value}/{run.tier.value}" if run is not None else "  sdlc    —"
        skills = len(getattr(self.agent, "discovered_skills", []) or [])
        if self._busy_state:
            elapsed = int(time.monotonic() - self._work_started) if self._work_started else 0
            state = f"working {elapsed}s · last: {self._last_tool} · llm calls {self._llm_calls}"
        else:
            state = "ready"
        panel = "\n".join([
            "WORKSPACE",
            f"  {ws.name or ws}",
            f"  branch  {self._branch or '—'}",
            "",
            "MODEL",
            f"  {self._model_str()}",
            "",
            "SESSION",
            f"  turns   {turns}",
            f"  tools   {tools}",
            sdlc_line,
            f"  pending {self.pending_task or '—'}",
            "",
            "VIEW",
            f"  details  {'on' if self.show_details else 'off'}  (/details)",
            f"  thinking {'shown' if self.show_thinking else 'hidden'}  (/thinking)",
            f"  theme    {self.theme}  (ctrl+t)",
            "",
            "SKILLS",
            f"  {skills} discovered  (/learn improves sick)",
            "",
            "KEYS",
            "  ctrl+x h  help      ctrl+x l  learn",
            "  ctrl+x u  undo      ctrl+x n  new",
            "  ctrl+x c  compact   ctrl+x s  sessions",
        ])
        self.status_panel.update(panel)
        self.status_bar.update(
            f" {ws.name} · {self._branch or 'no git'} · {state} · "
            f"{turns} turns · {tools} tools · @file attach · !bash · /help"
        )
        if self.chat_view:
            self.chat_view.border_title = f"sick — {ws.name}" + (" · thinking…" if self._busy_state else "")

    def on_resize(self, event) -> None:  # type: ignore[override]
        if self.status_panel is not None:
            self.status_panel.display = event.size.width >= 90

    def on_mount(self) -> None:
        self.chat_view = self.query_one(ChatView)
        self.sick_input = self.query_one(SickInput)
        self.loading = self.query_one(LoadingIndicator)
        self.status_panel = self.query_one("#status-panel", Static)
        self.status_bar = self.query_one("#status-bar", Static)
        self._branch = self._git_branch()
        if self.sick_input:
            self.sick_input.border_title = "message"
            self.sick_input.border_subtitle = "enter send · /help · @file · !cmd"
        self.host.chat = self.chat_view
        # patch busy to also control input + loading
        orig_set_busy = self.chat_view.set_busy

        def _busy(busy: bool) -> None:
            orig_set_busy(busy)
            if busy and not self._busy_state:
                self._work_started = time.monotonic()
                self._llm_calls = 0
            self._busy_state = busy
            if self.sick_input:
                self.sick_input.set_busy(busy)
            if self.loading:
                self.loading.display = busy
            self.refresh_status()

        self.chat_view.set_busy = _busy  # type: ignore
        self.host.chat.set_busy = _busy  # type: ignore
        # safe markdown
        orig_add = self.chat_view.add_agent

        def _safe_add(text: str) -> None:
            self._note("sick", text)
            try:
                orig_add(text)
            except Exception as e:
                self.chat_view.add_tool(f"[render error: {e}]")
                try:
                    self.chat_view.write(f"  sick: {text[:4000]}")
                except Exception:
                    pass

        self.agent._render_message = _safe_add
        # Live thinking: NOOA emits LLMComplete after every LLM round-trip
        # with the model's reasoning_content. Nothing subscribed before, so
        # reasoning models (gpt-oss, o-series, ...) appeared to hang in
        # silence while they thought. Render it (dimmed) when enabled.
        try:
            self.agent.event_manager.on("LLMComplete", self._on_llm_complete)
            self.agent.event_manager.on("LLMOutput", self._on_llm_output)
        except Exception:
            pass
        # Live tool activity: every Sick tool call streams start/done lines
        # to the chat as it executes (the registry is the single seam all
        # tool calls already flow through).
        self._ui_thread = threading.get_ident()
        try:
            if getattr(self.agent, "registry", None) is not None:
                self.agent.registry.activity = self._on_tool_activity
        except Exception:
            pass
        try:
            self.set_interval(1.0, self._tick_work_status)
        except Exception:
            pass
        self.host.start()
        self.chat_view.add_tool("ready — /help for commands and keys · @file attach · !cmd bash · /learn improves sick")
        self.chat_view.add_tool(f"workspace: {self.agent.workspace} | model: {self._model_str()}")
        self.refresh_status()
        self.set_focus(self.sick_input)

    def _on_llm_complete(self, event) -> None:
        """Render one LLM round-trip's reasoning when thinking is visible."""
        self._llm_calls += 1
        if not self.show_thinking or self.chat_view is None:
            return
        reasoning = getattr(event, "reasoning_content", "") or ""
        if reasoning.strip():
            self._note("thinking", reasoning)
            try:
                self.chat_view.add_thinking(reasoning)
            except Exception:
                pass

    def _on_llm_output(self, event) -> None:
        """Preview the code/output the model just produced (per iteration)."""
        if not self.show_thinking or self.chat_view is None:
            return
        content = (getattr(event, "content", "") or "").strip()
        if not content:
            return
        first = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
        if first:
            self._render_live(f"▸ code: {first[:140]}")

    def _on_tool_activity(self, event: dict) -> None:
        """Stream one tool start/done line to the chat (registry hook)."""
        tool = event.get("tool", "?")
        summary = event.get("summary", "")
        if event.get("phase") == "start":
            self._last_tool = f"{tool} {summary}".strip()
            self._render_live(f"▸ {tool}({summary})" if summary else f"▸ {tool}")
        else:
            ms = int(event.get("duration_ms") or 0)
            dur = f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms}ms"
            mark = "✓" if event.get("ok") else "✗"
            self._render_live(f"{mark} {tool} · {dur}")

    def _render_live(self, line: str) -> None:
        """Write a live-activity line, hopping to the UI thread if needed."""
        def render() -> None:
            if self.chat_view is None:
                return
            self._note("tool", line)
            try:
                self.chat_view.add_tool(line)
            except Exception:
                pass

        if self._ui_thread and threading.get_ident() != self._ui_thread:
            try:
                self.call_from_thread(render)
                return
            except Exception:
                pass
        render()

    def _tick_work_status(self) -> None:
        if self._busy_state:
            self.refresh_status()

    def _model_str(self) -> str:
        from sick.providers import client_model_name

        live = client_model_name(self.agent)
        if live:
            return str(live)
        try:
            from sick.providers import detect

            p = detect()
            return f"{p.model_id} ({p.name})"
        except Exception:
            return "no llm"

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

    def action_undo(self) -> None:
        asyncio.create_task(self._handle_input("/undo"))

    def action_redo(self) -> None:
        asyncio.create_task(self._handle_input("/redo"))

    def action_sessions(self) -> None:
        asyncio.create_task(self._handle_input("/sessions"))

    def action_compact(self) -> None:
        asyncio.create_task(self._handle_input("/compact"))

    def action_learn(self) -> None:
        asyncio.create_task(self._handle_input("/learn"))

    def action_editor(self) -> None:
        asyncio.create_task(self._handle_input("/editor"))

    def action_export(self) -> None:
        asyncio.create_task(self._handle_input("/export"))

    def action_models(self) -> None:
        asyncio.create_task(self._handle_input("/models"))

    def action_themes(self) -> None:
        asyncio.create_task(self._handle_input("/themes"))

    def action_details(self) -> None:
        asyncio.create_task(self._handle_input("/details"))

    def action_cycle_theme(self) -> None:
        names = sorted(self.available_themes)
        if not names:
            return
        idx = names.index(self.theme) if self.theme in names else -1
        self.theme = names[(idx + 1) % len(names)]
        self.refresh_status()
        if self.chat_view:
            self.chat_view.add_tool(f"theme → {self.theme}")

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
                if result:
                    self._note("command", result)
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
        finally:
            self.refresh_status()

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
        cap = MAX_BASH_CHARS * 5 if self.show_details else MAX_BASH_CHARS
        truncated = len(output) > cap
        display = output.strip()[:cap] or "(no output)"
        if truncated and self.chat_view:
            display += f"\n[truncated after {cap} chars, full {len(output)} — /details for more]"
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
        if show:
            self._note("you", text)
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
                    if content.startswith(("Error:", "[error")):
                        # parse_pdf is workspace-confined; a user-attached PDF
                        # outside the workspace lands here — say so, don't
                        # embed the tool error as if it were the document
                        text += f"\n\n--- attached: {p} ---\n[unreadable: {content}]"
                        total += len(content)
                        continue
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
