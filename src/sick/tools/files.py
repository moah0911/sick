import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from sick.tools.base import WorkspaceTool


MAX_READ_BYTES = 500_000


def _read_text(path: Path) -> tuple[str, bool]:
    """Read a bounded text file, returning its contents and truncation state."""
    with path.open("rb") as stream:
        data = stream.read(MAX_READ_BYTES + 1)
    if b"\0" in data:
        raise ValueError("binary files cannot be read as text")
    truncated = len(data) > MAX_READ_BYTES
    return data[:MAX_READ_BYTES].decode("utf-8", errors="replace"), truncated


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            stream.write(content)
            temp_name = stream.name
        os.replace(temp_name, path)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


class ReadFile(WorkspaceTool):
    name = "read_file"
    description = "Read a file from the filesystem with optional line range"

    def execute(self, path: str, offset: int = 0, limit: int | None = None) -> str:
        if offset < 0 or limit is not None and limit < 0:
            return "Error: offset and limit must be non-negative"
        try:
            p = self.resolve_path(path)
            if not p.is_file():
                return f"Error: {path} not found or is not a file"
            text, truncated = _read_text(p)
        except (OSError, ValueError) as exc:
            return f"Error: {exc}"
        lines = text.splitlines(keepends=True)[offset:]
        if limit is not None:
            lines = lines[:limit]
        result = "".join(lines)
        if truncated:
            result += "\n[truncated after 500000 bytes]"
        return result


class WriteFile(WorkspaceTool):
    name = "write_file"
    description = "Write content to a file, creating directories if needed"

    def execute(self, path: str, content: str) -> str:
        try:
            p = self.resolve_path(path)
            _atomic_write(p, content)
        except (OSError, ValueError) as exc:
            return f"Error: {exc}"
        return f"Wrote {len(content.encode('utf-8'))} bytes to {path}"


class EditFile(WorkspaceTool):
    name = "edit_file"
    description = "Search and replace text in an existing file"

    def execute(self, path: str, old: str, new: str) -> bool:
        if not old:
            return False
        try:
            p = self.resolve_path(path)
            if not p.is_file():
                return False
            content, truncated = _read_text(p)
            if truncated or content.count(old) != 1:
                return False
            _atomic_write(p, content.replace(old, new, 1))
        except (OSError, ValueError):
            return False
        return True
