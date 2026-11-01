import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EXCLUDED_DIRS = {"node_modules", "dist", "build", "__pycache__", ".sick", ".venv", ".git", ".pytest_cache", "vendor"}

MAX_READ_BYTES = 500_000


def max_read_bytes() -> int:
    """Bounded file-read size, overridable via SICK_MAX_READ_BYTES."""
    try:
        v = int(os.environ.get("SICK_MAX_READ_BYTES", str(MAX_READ_BYTES)))
        return max(10_000, min(10_000_000, v))
    except ValueError:
        return MAX_READ_BYTES


@dataclass
class ToolResult:
    """The single return type of every tool.

    `output` is the value rendered to the LLM / caller (str, bool, list, ...).
    `ok` is authoritative — callers never sniff output strings for errors.
    """

    ok: bool
    output: Any = ""
    error: str | None = None
    tool: str = ""
    duration_ms: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, output: Any = "", *, tool: str = "", **meta: Any) -> "ToolResult":
        return cls(ok=True, output=output, tool=tool, meta=dict(meta))

    @classmethod
    def failure(cls, error: str, *, output: Any = None, tool: str = "", **meta: Any) -> "ToolResult":
        return cls(ok=False, output=error if output is None else output, error=error, tool=tool, meta=dict(meta))

    def render(self) -> Any:
        return self.output

    def __str__(self) -> str:
        return self.output if isinstance(self.output, str) else str(self.output)


class Tool(ABC):
    name: str
    description: str

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult: ...


class WorkspaceTool(Tool):
    """A tool whose file operations are confined to one project directory."""

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()
        self.excluded = set(EXCLUDED_DIRS)

    def resolve_path(self, path: str | Path) -> Path:
        """Resolve a path and reject paths outside ``self.root``."""
        if not str(path):
            raise ValueError("path must not be empty")
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"path escapes workspace: {path}") from exc
        return resolved

    def is_ignored(self, path: Path) -> bool:
        """Return whether a workspace-relative path belongs to generated content."""
        try:
            parts = path.relative_to(self.root).parts
        except ValueError:
            return True
        return any(part.startswith(".") or part in self.excluded for part in parts)
