from __future__ import annotations

from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import RichLog


class ChatView(RichLog):
    """Chat history: user/agent messages, tool activity, errors.

    Role headers use distinct glyphs + colors (green = sick, teal = you,
    amber/red reserved for warnings/errors) so a long transcript stays
    scannable without reading every line.
    """

    def __init__(self, **kwargs):
        super().__init__(max_lines=2000, auto_scroll=True, wrap=True, highlight=True, markup=True, **kwargs)
        self.can_focus = True

    def add_user(self, text: str) -> None:
        self.write(Text("› you", style="bold #3fb6a8"))
        self.write(Text(text[:8000]))

    def add_agent(self, text: str) -> None:
        self.write(Text("● sick", style="bold #2fbf71"))
        try:
            self.write(Markdown(text[:20000], hyperlinks=True))
        except Exception:
            self.write(Text(text[:8000]))

    def add_thinking(self, text: str) -> None:
        """Render model reasoning (LLMComplete.reasoning_content), dimmed."""
        body = text.strip()
        if not body:
            return
        self.write(Text("◌ thinking", style="bold #8a7f5c"))
        self.write(Text(body[:6000], style="dim italic #9a94a6"))

    def add_tool(self, text: str) -> None:
        self.write(Text(f"  │ {text[:4000]}", style="dim italic"))

    def add_error(self, text: str) -> None:
        self.write(Text(f"  ✗ {text[:4000]}", style="bold #e5534b"))

    def set_busy(self, busy: bool) -> None:
        self.border_title = "sick · thinking…" if busy else "sick"
        self.loading = busy
