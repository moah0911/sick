from __future__ import annotations

from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import RichLog


class ChatView(RichLog):
    """Chat history: user/agent messages, tool activity, errors."""

    def add_user(self, text: str) -> None:
        self.write(Text("  you", style="bold cyan"))
        self.write(Text(text))

    def add_agent(self, text: str) -> None:
        self.write(Text("  sick", style="bold magenta"))
        self.write(Markdown(text))

    def add_tool(self, text: str) -> None:
        self.write(Text(f"  \u2502 {text}", style="dim italic"))

    def add_error(self, text: str) -> None:
        self.write(Text(f"  \u2717 {text}", style="bold red"))

    def set_busy(self, busy: bool) -> None:
        self.border_title = "thinking..." if busy else "sick"