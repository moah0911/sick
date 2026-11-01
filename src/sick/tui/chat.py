from __future__ import annotations

from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import RichLog


class ChatView(RichLog):
    """Chat history as structured renderables (see DESIGN.md).

    Print-inspired: left rules + small-caps role labels, tree glyphs for
    tool activity, a hairline THINKING label for reasoning. No bubbles,
    no decoration — hierarchy comes from rules, labels, and value.
    """

    def __init__(self, **kwargs):
        super().__init__(max_lines=2000, auto_scroll=True, wrap=True, highlight=True, markup=True, **kwargs)
        self.can_focus = True

    def add_turn_separator(self, turn: int, clock: str = "") -> None:
        """Hairline boundary so previous turns stay distinct when scrolling."""
        label = f"── turn {turn} · {clock} " if clock else f"── turn {turn} "
        self.write(Text(label + "─" * 48, style="dim #46536a"))

    def add_user(self, text: str) -> None:
        self.write(Text("▌ YOU", style="bold #3fb6a8"))
        # raised ground: user text is yours at a glance, even 200 lines up
        self.write(Text(text[:8000], style="#d8dee9 on #18202e"))

    def add_agent(self, text: str, meta: str = "") -> None:
        header = f"▌ SICK · {meta}" if meta else "▌ SICK"
        self.write(Text(header, style="bold #3ecf8e"))
        try:
            self.write(Markdown(text[:20000], hyperlinks=True, code_theme="github-dark"))
        except Exception:
            try:
                self.write(Markdown(text[:20000], hyperlinks=True))
            except Exception:
                self.write(Text(text[:8000]))

    def add_thinking(self, text: str) -> None:
        """Render model reasoning (LLMComplete.reasoning_content), dimmed."""
        body = text.strip()
        if not body:
            return
        self.write(Text("┄ THINKING", style="bold #8a7f5c"))
        self.write(Text(body[:6000], style="dim italic #9a94a6"))

    def add_activity(self, line: str) -> None:
        """One live tool line with tree glyphs (start ▸ / done ✓✗)."""
        if line.startswith("✓"):
            self.write(Text(f"  ╰─ {line}", style="dim #7d8aa0"))
        elif line.startswith("✗"):
            self.write(Text(f"  ╰─ {line}", style="bold #e5534b"))
        elif line.startswith("▸"):
            self.write(Text(f"  ├─ {line}", style="dim italic #7d8aa0"))
        else:
            self.add_tool(line)

    def add_tool(self, text: str) -> None:
        self.write(Text(f"  │ {text[:4000]}", style="dim italic #7d8aa0"))

    def add_error(self, text: str) -> None:
        self.write(Text(f"  ✗ {text[:4000]}", style="bold #e5534b"))

    def set_busy(self, busy: bool) -> None:
        # NOTE: never self.loading = busy here — RichLog's built-in loading
        # overlay covers the whole chat with a spinner, hiding the user
        # message and all live activity for the entire turn (the "blank
        # screen while working" bug). Busy is shown in the border title,
        # status bar, and the height-1 LoadingIndicator row instead.
        self.border_title = "sick · thinking…" if busy else "sick"
