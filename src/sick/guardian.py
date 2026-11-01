"""Repo guardian (`sick watch`) — Sick as the repo's immune system.

Polls the workspace (stdlib mtimes, no new dependency), re-runs the
verification command on change, and on red makes ONE bounded,
checkpointed fix attempt through the normal SDLC-gated agent turn.
Hard limits, aftermath-faithful: max 2 attempts per failure signature,
then it stops and reports; it never commits or pushes.

The core (`Guardian.check_once`) takes verify/fix callbacks so the
daemon logic is testable without real timing or an LLM.
"""

import hashlib
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

IGNORED_DIRS = {".git", ".sick", ".venv", "__pycache__", "node_modules", "dist", "build", ".pytest_cache", "vendor"}
IGNORED_FILES = {"AFTERMATH.log"}


@dataclass
class Guardian:
    workspace: Path
    verify_fn: Callable[[], tuple[bool, str]] | None = None
    fix_fn: Callable[[str, str], bool] | None = None
    max_attempts: int = 2
    attempts: Counter = field(default_factory=Counter)
    _snapshot: dict[str, tuple[int, int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).resolve()
        if self.verify_fn is None:
            self.verify_fn = self._default_verify
        self._snapshot = self.snapshot()

    # ── change detection ──

    def snapshot(self) -> dict[str, tuple[int, int]]:
        snap: dict[str, tuple[int, int]] = {}
        for p in self.workspace.rglob("*"):
            if not p.is_file() or p.name in IGNORED_FILES:
                continue
            rel = p.relative_to(self.workspace)
            if any(part in IGNORED_DIRS or part.startswith(".") and part not in {".sick"} for part in rel.parts[:-1]):
                continue
            if any(part in IGNORED_DIRS for part in rel.parts):
                continue
            try:
                st = p.stat()
                snap[str(rel)] = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue
        return snap

    def changed(self) -> list[str]:
        now = self.snapshot()
        diff = [k for k in set(now) | set(self._snapshot) if now.get(k) != self._snapshot.get(k)]
        self._snapshot = now
        return sorted(diff)

    # ── verification ──

    def _verify_command(self) -> list[str] | None:
        import json

        cfg = self.workspace / ".aftermath" / "config.json"
        try:
            data = json.loads(cfg.read_text())
            cmds = data.get("testCommands") or []
            if cmds:
                return ["bash", "-c", str(cmds[0])]
        except (OSError, ValueError):
            pass
        if list(self.workspace.glob("test_*.py")) or (self.workspace / "tests").is_dir():
            return ["python", "-m", "pytest", "-q"]
        return None

    def _default_verify(self) -> tuple[bool, str]:
        cmd = self._verify_command()
        if cmd is None:
            return True, "no verification command (no tests found)"
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=self.workspace)
            return r.returncode == 0, (r.stdout + r.stderr)[-2000:]
        except (subprocess.TimeoutExpired, OSError) as e:
            return False, f"verification error: {e}"

    # ── core ──

    def log(self, line: str) -> None:
        try:
            with (self.workspace / "AFTERMATH.log").open("a") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M')} guardian: {line}\n")
        except OSError:
            pass

    def check_once(self, changed_files: list[str] | None = None) -> str:
        """One guardian cycle. Returns green|fixed|blocked|failed."""
        ok, output = self.verify_fn()  # type: ignore[misc]
        if ok:
            return "green"
        signature = hashlib.sha256(output.encode()).hexdigest()[:12]
        self.attempts[signature] += 1
        if self.attempts[signature] > self.max_attempts:
            self.log(f"BLOCKED after {self.max_attempts} attempts (sig {signature}): {output.splitlines()[-1][:160] if output else 'no output'}")
            return "blocked"
        if self.fix_fn is None:
            self.log(f"red, no fixer configured (sig {signature})")
            return "failed"
        self.log(f"red (sig {signature}, attempt {self.attempts[signature]}) — attempting bounded fix")
        try:
            delivered = bool(self.fix_fn(signature, output))
        except Exception as e:
            self.log(f"fix attempt raised: {e}")
            return "failed"
        ok2, _ = self.verify_fn()  # type: ignore[misc]
        if delivered and ok2:
            self.attempts.pop(signature, None)
            self.log(f"fixed (sig {signature})")
            return "fixed"
        self.log(f"fix did not verify (sig {signature})")
        return "failed"

    # ── daemon loop ──

    def acquire_lock(self):
        """Single-instance lock via portalocker; returns the lock handle."""
        import portalocker

        lock_path = self.workspace / ".sick" / "guardian.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = portalocker.Lock(str(lock_path), "a", timeout=0)
        lock.acquire()
        return lock

    def run_forever(self, poll_seconds: float = 2.0, debounce_seconds: float = 3.0) -> None:
        lock = self.acquire_lock()
        self.log("watch started")
        pending_since: float | None = None
        try:
            while True:
                changed = self.changed()
                now = time.monotonic()
                if changed:
                    pending_since = pending_since or now
                if pending_since and now - pending_since >= debounce_seconds:
                    result = self.check_once(changed)
                    print(f"guardian: {result}", flush=True)
                    pending_since = None
                    self._snapshot = self.snapshot()
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            self.log("watch stopped")
        finally:
            try:
                lock.release()
            except Exception:
                pass
