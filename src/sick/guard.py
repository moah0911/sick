"""Aftermath guard — post-failure recovery enforcement at the registry seam.

Faithful subset of upstream aftermath at `full`:
- destructive commands blocked (force push, reset --hard, clean -f,
  rm -rf on non-safe targets, DROP/destroy), path-aware via
  .aftermath/config.json safePaths/protectedPaths/allowlist when present
- forward edits frozen while a failure is unresolved; a passing
  verification (or restore) unfreezes
- repeat-attempt ledger keyed by tool+args

`lite` reports instead of blocking; `off` disables. `ultra` = full +
the registry caller may checkpoint before edits (checkpointing itself
lives in the agent's git tools; autoRevert stays opt-in and off).
"""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

MUTATING_TOOLS = {"write_file", "edit_file", "self_write"}
VERIFY_HINT = re.compile(r"(pytest|ruff|mypy|unittest|test_)", re.IGNORECASE)

_DESTRUCTIVE = [
    (re.compile(r"\bgit\s+push\b.*(--force|-f\b)"), "force push"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git reset --hard"),
    (re.compile(r"\bgit\s+clean\s+-[a-z]*f"), "git clean -f"),
    (re.compile(r"\bgit\s+branch\s+-D\b"), "git branch -D"),
    (re.compile(r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r"), "rm -rf"),
    (re.compile(r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b", re.IGNORECASE), "DROP"),
    (re.compile(r"\btruncate\s+table\b", re.IGNORECASE), "TRUNCATE TABLE"),
]


class AftermathGuard:
    def __init__(self, workspace: str | Path = ".", mode: str = "full") -> None:
        self.workspace = Path(workspace).resolve()
        self.mode = mode if mode in ("lite", "full", "ultra", "off") else "full"
        self.frozen = False
        self.last_error = ""
        self.attempts: Counter[str] = Counter()
        self._config = self._load_config()

    def _load_config(self) -> dict:
        path = self.workspace / ".aftermath" / "config.json"
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @property
    def active(self) -> bool:
        return self.mode in ("full", "ultra")

    def state(self) -> str:
        if self.mode == "off":
            return "off"
        return f"{self.mode} · {'FROZEN: ' + self.last_error if self.frozen else 'ready'}"

    def check(self, tool: str, kwargs: dict[str, Any]) -> str | None:
        """Return a block reason, or None to let the call proceed."""
        if self.mode == "off":
            return None
        if tool == "bash":
            reason = self._destructive_reason(str(kwargs.get("command", "")))
            if reason:
                if self.active:
                    return f"[aftermath: blocked {reason} at mode {self.mode} — /aftermath lite|off to override]"
                return None  # lite: registry caller surfaces failures, guard does not block
        if tool in MUTATING_TOOLS and self.frozen and self.active:
            return (
                f"[aftermath: edits frozen — unresolved failure ({self.last_error}). "
                "Get a verification green, /aftermath-revert, or /aftermath lite|off]"
            )
        return None

    def _destructive_reason(self, command: str) -> str | None:
        if not command.strip():
            return None
        for allow in self._config.get("destructiveAllowlist", []) or []:
            if str(allow) and str(allow) in command:
                return None
        for pattern, label in _DESTRUCTIVE:
            if pattern.search(command):
                if label == "rm -rf" and self._rm_targets_safe(command):
                    return None
                return label
        return None

    def _rm_targets_safe(self, command: str) -> bool:
        safe = [str(s) for s in self._config.get("safePaths", []) or []]
        protected = [str(s) for s in self._config.get("protectedPaths", []) or []]
        if not safe:
            return False
        targets = re.findall(r"\brm\s+-[a-zA-Z]+\s+([^\n;|&]+)", command)
        if not targets:
            return False
        for chunk in targets:
            for token in chunk.split():
                if token.startswith("-"):
                    continue
                if any(token == p or token.startswith(p.rstrip("/") + "/") for p in protected):
                    return False
                if not any(token == s or token.startswith(s.rstrip("/") + "/") for s in safe):
                    return False
        return True

    def record(self, tool: str, ok: bool, kwargs: dict[str, Any]) -> None:
        """Observe a tool result: freeze on failure, thaw on verification."""
        if self.mode == "off":
            return
        key = f"{tool}:{str(kwargs)[:80]}"
        if not ok:
            self.attempts[key] += 1
            self.frozen = True
            self.last_error = key
            return
        if tool == "restore":
            self.frozen = False
            self.last_error = ""
        elif tool == "bash" and VERIFY_HINT.search(str(kwargs.get("command", ""))):
            self.frozen = False
            self.last_error = ""
