import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from sick.tools.base import MAX_READ_BYTES, ToolResult, WorkspaceTool, max_read_bytes

__all__ = ["MAX_READ_BYTES", "ReadFile", "WriteFile", "EditFile"]


def _read_text(path: Path) -> tuple[str, bool]:
    """Read a bounded text file, returning its contents and truncation state."""
    limit = max_read_bytes()
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if b"\0" in data:
        raise ValueError("binary files cannot be read as text")
    truncated = len(data) > limit
    return data[:limit].decode("utf-8", errors="replace"), truncated


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

    def execute(self, path: str, offset: int = 0, limit: int | None = None) -> ToolResult:
        if offset < 0 or limit is not None and limit < 0:
            return ToolResult.failure("Error: offset and limit must be non-negative", tool=self.name)
        try:
            p = self.resolve_path(path)
            if not p.is_file():
                return ToolResult.failure(f"Error: {path} not found or is not a file", tool=self.name)
            text, truncated = _read_text(p)
        except (OSError, ValueError) as exc:
            return ToolResult.failure(f"Error: {exc}", tool=self.name)
        lines = text.splitlines(keepends=True)[offset:]
        if limit is not None:
            lines = lines[:limit]
        result = "".join(lines)
        if truncated:
            result += f"\n[truncated after {max_read_bytes()} bytes]"
        return ToolResult.success(result, tool=self.name)


class WriteFile(WorkspaceTool):
    name = "write_file"
    description = "Write content to a file, creating directories if needed"

    def execute(self, path: str, content: str) -> ToolResult:
        try:
            p = self.resolve_path(path)
            _atomic_write(p, content)
        except (OSError, ValueError) as exc:
            return ToolResult.failure(f"Error: {exc}", tool=self.name)
        return ToolResult.success(f"Wrote {len(content.encode('utf-8'))} bytes to {path}", tool=self.name)


class EditFile(WorkspaceTool):
    name = "edit_file"
    description = "Search and replace text in an existing file"

    def execute(self, path: str, old: str, new: str) -> ToolResult:
        if not old:
            return ToolResult.failure("empty old string", output=False, tool=self.name)
        try:
            p = self.resolve_path(path)
            if not p.is_file():
                return ToolResult.failure("file not found", output=False, tool=self.name)
            content, truncated = _read_text(p)
            if truncated or content.count(old) != 1:
                return ToolResult.failure("match not unique or file truncated", output=False, tool=self.name)
            _atomic_write(p, content.replace(old, new, 1))
        except (OSError, ValueError) as exc:
            return ToolResult.failure(str(exc), output=False, tool=self.name)
        return ToolResult.success(True, tool=self.name)
