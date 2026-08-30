from __future__ import annotations

from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import RichLog


class ChatView(RichLog):
    """Chat history: user/agent messages, tool activity, errors."""

    def __init__(self, **kwargs):
        super().__init__(max_lines=2000, auto_scroll=True, wrap=True, highlight=True, markup=True, **kwargs)
        self.can_focus = True

    def add_user(self, text: str) -> None:
        self.write(Text("  you", style="bold cyan"))
        self.write(Text(text[:8000]))

    def add_agent(self, text: str) -> None:
        self.write(Text("  sick", style="bold magenta"))
        try:
            self.write(Markdown(text[:20000], hyperlinks=True))
        except Exception:
            self.write(Text(text[:8000]))

    def add_tool(self, text: str) -> None:
        self.write(Text(f"  │ {text[:4000]}", style="dim italic"))

    def add_error(self, text: str) -> None:
        self.write(Text(f"  ✗ {text[:4000]}", style="bold red"))

    def set_busy(self, busy: bool) -> None:
        self.border_title = "thinking..." if busy else "sick"
        self.loading = busy
