from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


EXCLUDED_DIRS = {"node_modules", "dist", "build", "__pycache__", ".sick"}


class Tool(ABC):
    name: str
    description: str

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any: ...


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
