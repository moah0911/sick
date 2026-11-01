"""Tool genesis — the agent grows its own tools, safely.

`create_tool` writes a new Tool subclass into `.sick/tools/`, validates
it in a subprocess (import + smoke run), and only then registers it
live in the running registry. Workspace tools persist across sessions
and are reloaded at startup; they may extend Sick but never shadow a
builtin. Provenance lands in `.sick/tools/MANIFEST.json`.

Trust model: a workspace tool is code, with the same trust as the
existing `bash` tool. Disable everything with SICK_TOOL_GENESIS=off
or `tool_genesis = false` in .sick/config.toml.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from sick.tools.base import Tool, ToolResult

_NAME_OK = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


def genesis_enabled(config: dict | None = None) -> bool:
    if os.environ.get("SICK_TOOL_GENESIS", "").lower() == "off":
        return False
    if config is not None and config.get("tool_genesis") is False:
        return False
    return True


def tools_dir(workspace: str | Path) -> Path:
    return Path(workspace).resolve() / ".sick" / "tools"


def load_tool_class(path: Path) -> type[Tool] | None:
    """Import a tool file and return its Tool subclass (or None)."""
    spec = importlib.util.spec_from_file_location(f"sick_grown_{path.stem}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for value in vars(module).values():
        if isinstance(value, type) and issubclass(value, Tool) and value is not Tool:
            return value
    return None


def instantiate(cls: type[Tool], workspace: Path) -> Tool:
    try:
        return cls(workspace)  # type: ignore[call-arg]
    except TypeError:
        return cls()  # type: ignore[call-arg]


_SMOKE_SCRIPT = """
import importlib.util, json, sys
from pathlib import Path
path, workspace, kwargs = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
spec = importlib.util.spec_from_file_location("smoke_tool", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
from sick.tools.base import Tool
cls = next(v for v in vars(mod).values() if isinstance(v, type) and issubclass(v, Tool) and v is not Tool)
try:
    tool = cls(workspace)
except TypeError:
    tool = cls()
result = tool.execute(**kwargs)
print("OK:" + str(result.output)[:500])
"""


class CreateTool(Tool):
    name = "create_tool"
    description = (
        "Create a NEW persistent tool for this workspace: write a Tool subclass, "
        "smoke-test it, and register it live. Use when no existing tool fits."
    )

    def __init__(self, workspace: str | Path = ".", registry: Any = None) -> None:
        self.workspace = Path(workspace).resolve()
        self.registry = registry

    def execute(  # type: ignore[override]
        self,
        name: str,
        code: str,
        example_kwargs: dict | None = None,
        expected_contains: str = "",
    ) -> ToolResult:
        if not _NAME_OK.match(name or ""):
            return ToolResult.failure("Error: name must be snake_case (3-41 chars)", tool=self.name)
        if self.registry is not None and name in self.registry.tools:
            return ToolResult.failure(f"Error: tool '{name}' already exists — grown tools never shadow existing ones", tool=self.name)
        if "class " not in code or "Tool" not in code:
            return ToolResult.failure("Error: code must define a Tool subclass", tool=self.name)
        directory = tools_dir(self.workspace)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.py"
        if path.exists():
            return ToolResult.failure(f"Error: {path} already exists", tool=self.name)
        path.write_text(code)
        try:
            smoke = subprocess.run(
                [sys.executable, "-c", _SMOKE_SCRIPT, str(path), str(self.workspace), json.dumps(example_kwargs or {})],
                capture_output=True, text=True, timeout=30, cwd=self.workspace,
            )
        except subprocess.TimeoutExpired:
            path.unlink(missing_ok=True)
            return ToolResult.failure("Error: smoke test timed out (30s) — tool not registered", tool=self.name)
        out = (smoke.stdout or "") + (smoke.stderr or "")
        if smoke.returncode != 0 or not out.startswith("OK:"):
            path.unlink(missing_ok=True)
            return ToolResult.failure(f"Error: smoke test failed — tool not registered:\n{out[-800:]}", tool=self.name)
        if expected_contains and expected_contains not in out:
            path.unlink(missing_ok=True)
            return ToolResult.failure(f"Error: smoke output missing {expected_contains!r} — tool not registered", tool=self.name)
        try:
            cls = load_tool_class(path)
            if cls is None:
                path.unlink(missing_ok=True)
                return ToolResult.failure("Error: no Tool subclass found after smoke — tool not registered", tool=self.name)
            tool = instantiate(cls, self.workspace)
        except Exception as e:
            path.unlink(missing_ok=True)
            return ToolResult.failure(f"Error: load failed ({e}) — tool not registered", tool=self.name)
        if self.registry is not None:
            self.registry.register(tool)
        self._record_manifest(name, example_kwargs or {})
        return ToolResult.success(
            f"tool '{tool.name}' created, smoke-tested, and registered live (persisted at {path})",
            tool=self.name,
        )

    def _record_manifest(self, name: str, example_kwargs: dict) -> None:
        manifest_path = tools_dir(self.workspace) / "MANIFEST.json"
        try:
            data = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
        except ValueError:
            data = {}
        data[name] = {"file": f"{name}.py", "created_at": time.time(), "smoke_kwargs": example_kwargs}
        try:
            manifest_path.write_text(json.dumps(data, indent=2))
        except OSError:
            pass


def load_workspace_tools(registry: Any, workspace: str | Path) -> tuple[list[str], list[str]]:
    """Load persisted grown tools into a registry. Returns (loaded, skipped)."""
    loaded: list[str] = []
    skipped: list[str] = []
    directory = tools_dir(workspace)
    if not directory.is_dir():
        return loaded, skipped
    for path in sorted(directory.glob("*.py")):
        try:
            cls = load_tool_class(path)
            if cls is None:
                skipped.append(path.stem)
                continue
            tool = instantiate(cls, Path(workspace))
            if tool.name in registry.tools:
                skipped.append(tool.name)  # never shadow builtins/existing
                continue
            registry.register(tool)
            loaded.append(tool.name)
        except Exception:
            skipped.append(path.stem)
    return loaded, skipped
