import fnmatch
import re

from sick.tools.base import ToolResult, WorkspaceTool, max_read_bytes

MAX_GREP_RESULTS = 200


def _get_max_results() -> int:
    import os
    try:
        v = int(os.environ.get("SICK_GREP_MAX_RESULTS", str(MAX_GREP_RESULTS)))
        return max(1, min(500, v))
    except ValueError:
        return MAX_GREP_RESULTS


class Grep(WorkspaceTool):
    name = "grep"
    description = "Search file contents for a regex pattern"

    def execute(self, pattern: str, include: str | None = None, path: str = ".") -> ToolResult:
        try:
            regex = re.compile(pattern)
            search_root = self.resolve_path(path)
        except (re.error, ValueError) as exc:
            return ToolResult.failure(f"Error: {exc}", output=[f"Error: {exc}"], tool=self.name)
        if not search_root.is_dir():
            return ToolResult.failure(f"Error: {path} is not a directory", output=[f"Error: {path} is not a directory"], tool=self.name)

        results: list[str] = []
        max_bytes = max_read_bytes()
        max_res = _get_max_results()
        for p in search_root.rglob("*"):
            if not p.is_file() or self.is_ignored(p):
                continue
            if include and not fnmatch.fnmatch(p.name, include) and not fnmatch.fnmatch(str(p.relative_to(self.root)), include):
                continue
            try:
                if p.stat().st_size > max_bytes:
                    continue
                data = p.read_bytes()
                if b"\0" in data:
                    continue
                for i, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                    if regex.search(line):
                        results.append(f"{p.relative_to(self.root)}:{i}: {line}")
                        if len(results) >= max_res:
                            results.append(f"[truncated after {max_res} results]")
                            return ToolResult.success(results, tool=self.name)
            except OSError:
                continue
        return ToolResult.success(results, tool=self.name)


class Glob(WorkspaceTool):
    name = "glob"
    description = "Find files matching a glob pattern"

    def execute(self, pattern: str, path: str = ".") -> ToolResult:
        try:
            search_root = self.resolve_path(path)
        except ValueError as exc:
            return ToolResult.failure(f"Error: {exc}", output=[f"Error: {exc}"], tool=self.name)
        if not search_root.is_dir():
            return ToolResult.failure(f"Error: {path} is not a directory", output=[f"Error: {path} is not a directory"], tool=self.name)
        try:
            matches = search_root.rglob(pattern)
            return ToolResult.success(sorted(
                str(p.relative_to(self.root))
                for p in matches
                if p.is_file() and not self.is_ignored(p)
            ), tool=self.name)
        except (OSError, ValueError) as exc:
            return ToolResult.failure(f"Error: {exc}", output=[f"Error: {exc}"], tool=self.name)
