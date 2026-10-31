"""ToolRegistry — the seam through which every tool call flows.

Deep module: registration, dispatch, timing, audit, counts, and lifecycle
recording sit behind ``call(name, **kwargs) -> ToolResult``. Callers never
sniff raw return values; legacy tools returning str/bool/list are wrapped
once, here.
"""

import time
from collections.abc import Callable, Iterable
from typing import Any

from sick.tools.base import Tool, ToolResult


def wrap_result(tool: str, raw: Any) -> ToolResult:
    if isinstance(raw, ToolResult):
        if not raw.tool:
            raw.tool = tool
        return raw
    if isinstance(raw, bool):
        return ToolResult(ok=raw, output=raw, error=None if raw else "tool returned False", tool=tool)
    if isinstance(raw, list):
        ok = not (raw and isinstance(raw[0], str) and raw[0].startswith("Error:"))
        return ToolResult(ok=ok, output=raw, error=raw[0] if not ok else None, tool=tool)
    if isinstance(raw, str):
        head = raw.strip()[:12]
        ok = not head.startswith(("Error", "[error", "[timed out", "[exit code"))
        return ToolResult(ok=ok, output=raw, error=None if ok else raw[:200], tool=tool)
    return ToolResult(ok=True, output=raw, tool=tool)


class ToolRegistry:
    def __init__(self, audit: Any = None, on_result: Callable[[ToolResult, dict], None] | None = None) -> None:
        self.tools: dict[str, Tool] = {}
        self._counts: dict[str, int] = {}
        self.audit = audit
        self.on_result = on_result

    def register(self, tool: Tool) -> Tool:
        self.tools[tool.name] = tool
        return tool

    def register_all(self, tools: Iterable[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def __contains__(self, name: str) -> bool:
        return name in self.tools

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def counts(self) -> dict[str, int]:
        return self._counts

    def set_sandboxed(self, value: bool = True) -> bool:
        bash = self.tools.get("bash")
        if bash is None:
            return False
        bash.sandboxed = value  # type: ignore[attr-defined]
        return True

    def call(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult.failure(f"unknown tool: {name}", tool=name)
        start = time.monotonic()
        try:
            result = wrap_result(name, tool.execute(**kwargs))
        except Exception as e:  # tool raised instead of returning a result
            result = ToolResult.failure(f"{type(e).__name__}: {e}", tool=name)
        result.tool = name
        result.duration_ms = round((time.monotonic() - start) * 1000)
        self._counts[name] = self._counts.get(name, 0) + 1
        if self.audit is not None:
            try:
                self.audit.record(name, ok=result.ok, duration_ms=result.duration_ms, **kwargs)
            except Exception:
                pass
        if self.on_result is not None:
            try:
                self.on_result(result, kwargs)
            except Exception:
                pass
        return result
