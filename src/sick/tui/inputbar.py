from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from textual.suggester import Suggester
from textual.widgets import Input


class CombinedSuggester(Suggester):
    """Complete @path and /commands."""

    def __init__(self, agent=None, commands=None):
        super().__init__()
        self.agent = agent
        self.commands = commands

    async def get_suggestion(self, value: str) -> str | None:
        v = value.strip()
        # slash commands: /...
        if v.startswith("/"):
            token = v[1:].split()[0].lower() if v[1:] else ""
            if not token:
                return None
            if self.commands:
                candidates = [n for n in self.commands.commands.keys() if n.startswith(token)]
                # dedupe via canonical
                uniq = []
                seen = set()
                for c in candidates:
                    if c not in seen:
                        uniq.append(c)
                        seen.add(c)
                if len(uniq) == 1:
                    return "/" + uniq[0] + (" " if " " not in v else "")
            return None
        # @file
        marker = value.rfind("@")
        if marker == -1:
            return None
        token = value[marker + 1 :]
        if not token:
            return None
        try:
            # workspace-aware: use agent workspace if available
            root = Path(".")
            if self.agent and hasattr(self.agent, "workspace"):
                try:
                    root = Path(self.agent.workspace)
                except Exception:
                    root = Path(".")
            p = Path(token).expanduser()
            # handle nested
            if "/" in token:
                base = p.parent if p.parent != Path("") else root
                # resolve relative to root if not absolute
                if not base.is_absolute():
                    base = (root / base).resolve()
                    # allow outside root for suggester? keep within workspace for now
                prefix = p.name
                if not base.exists():
                    return None
                # filter excluded
                candidates = []
                for c in base.glob(f"{prefix}*"):
                    if c.name.startswith(".") or c.name in {"__pycache__", ".sick", ".git", "node_modules"}:
                        continue
                    candidates.append(c.name)
                if len(candidates) == 1:
                    return value[: marker + 1] + candidates[0]
            else:
                # top-level
                candidates = []
                for c in root.glob(f"{token}*"):
                    if c.name.startswith("."):
                        continue
                    candidates.append(c.name)
                if len(candidates) == 1:
                    return value[: marker + 1] + candidates[0]
        except Exception:
            return None
        return None


class SickInput(Input):
    """Chat input. Enter submits; disabled while the agent is working."""

    def __init__(
        self, on_submit: Callable[[str], None] | None = None, agent=None, commands=None, **kwargs
    ) -> None:
        super().__init__(
            suggester=CombinedSuggester(agent=agent, commands=commands),
            placeholder="ask sick — @file to attach, !cmd for bash, /help for commands",
            **kwargs,
        )
        self._on_submit_cb = on_submit
        self._history: list[str] = []
        self._hidx: int = -1

    def action_submit(self) -> None:
        value = self.value.strip()
        if not value:
            return
        # history ring
        if not self._history or self._history[-1] != value:
            self._history.append(value)
            if len(self._history) > 200:
                self._history = self._history[-200:]
        self._hidx = len(self._history)
        if self._on_submit_cb:
            self._on_submit_cb(value)
        self.value = ""

    def action_history_up(self) -> None:
        if not self._history:
            return
        self._hidx = max(0, self._hidx - 1)
        self.value = self._history[self._hidx]
        self.cursor_position = len(self.value)

    def action_history_down(self) -> None:
        if not self._history:
            return
        self._hidx = min(len(self._history), self._hidx + 1)
        if self._hidx >= len(self._history):
            self.value = ""
        else:
            self.value = self._history[self._hidx]
        self.cursor_position = len(self.value)

    def set_busy(self, busy: bool) -> None:
        self.disabled = busy
        self.placeholder = "thinking... (input disabled)" if busy else "ask sick — @file to attach, !cmd for bash, /help for commands"
