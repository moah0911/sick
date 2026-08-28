from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from textual.suggester import Suggester
from textual.widgets import Input


class FileSuggester(Suggester):
    """Complete `@path` tokens against the filesystem."""

    async def get_suggestion(self, value: str) -> str | None:
        marker = value.rfind("@")
        if marker == -1:
            return None
        token = value[marker + 1 :]
        if not token:
            return None
        # expand ~ and handle nested paths
        try:
            p = Path(token).expanduser()
            if "/" in token:
                base = p.parent if p.parent != Path("") else Path(".")
                prefix = p.name
                if not base.exists():
                    return None
                candidates = [str(base / c.name) if str(base) != "." else c.name for c in base.glob(f"{prefix}*")]
            else:
                candidates = [c.name for c in Path(".").glob(f"{token}*")]
            if len(candidates) == 1:
                return value[: marker + 1] + candidates[0]
            if 1 < len(candidates) <= 5 and token:
                # ponytail: don't guess when many; wait for more chars
                return None
        except Exception:
            return None
        return None


class SickInput(Input):
    """Chat input. Enter submits; disabled while the agent is working."""

    def __init__(
        self, on_submit: Callable[[str], None] | None = None, **kwargs
    ) -> None:
        super().__init__(
            suggester=FileSuggester(),
            placeholder="ask sick — @file to attach, !cmd for bash, /help for commands",
            **kwargs,
        )
        self._on_submit_cb = on_submit

    def action_submit(self) -> None:
        value = self.value.strip()
        if not value:
            return
        if self._on_submit_cb:
            self._on_submit_cb(value)
        self.value = ""

    def set_busy(self, busy: bool) -> None:
        self.disabled = busy