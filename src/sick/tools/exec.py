import os
import shutil
import subprocess
from pathlib import Path

from sick.tools.base import WorkspaceTool


MAX_TIMEOUT_SECONDS = 300
MAX_OUTPUT_CHARS = 20_000


def _sandbox_prefix(root) -> list[str] | None:
    if shutil.which("bwrap") is None:
        return None
    home = os.path.expanduser("~")
    binds: list[str] = [
        "bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--proc", "/proc",
        "--dev", "/dev",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/etc", "/etc",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/sbin", "/sbin",
        "--bind", str(root), str(root),
        "--ro-bind", f"{home}/.cache/uv", f"{home}/.cache/uv",
        "--ro-bind", f"{home}/.local", f"{home}/.local",
        "--ro-bind", f"{home}/.npm", f"{home}/.npm",
        "--chdir", str(root),
    ]
    # optional extra binds — ponytail: add only if present
    for extra in ["/usr/local", "/opt", f"{home}/.cargo", "/tmp"]:
        if Path(extra).exists():
            if extra == "/tmp":
                binds.extend(["--bind", extra, extra])
            else:
                binds.extend(["--ro-bind", extra, extra])
    binds.extend(["bash", "-c"])
    return binds


class Bash(WorkspaceTool):
    name = "bash"
    description = "Execute a shell command from the workspace with a bounded timeout and output"

    def __init__(self, root: str | Path = ".", sandboxed: bool = False) -> None:
        super().__init__(root)
        self.sandboxed = sandboxed

    def execute(self, command: str, timeout: int = 60) -> str:
        if not command.strip():
            return "[error: command must not be empty]"
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
            return f"[error: timeout must be between 1 and {MAX_TIMEOUT_SECONDS} seconds]"
        prefix = None
        if self.sandboxed:
            prefix = _sandbox_prefix(self.root)
            if prefix is None:
                return "[error: sandbox requested but bwrap is not installed]"
            argv = prefix + [command]
        else:
            argv = command
        try:
            r = subprocess.run(
                argv,
                shell=not self.sandboxed,
                capture_output=True,
                text=False,
                timeout=timeout,
                cwd=self.root,
            )
            out = r.stdout.decode("utf-8", errors="replace")
            if r.stderr:
                out += r.stderr.decode("utf-8", errors="replace")
            if r.returncode != 0:
                out += f"\n[exit code {r.returncode}]"
            if len(out) > MAX_OUTPUT_CHARS:
                out = out[:MAX_OUTPUT_CHARS] + f"\n[truncated after {MAX_OUTPUT_CHARS} characters]"
            return out
        except subprocess.TimeoutExpired:
            return f"[timed out after {timeout}s]"
        except OSError as e:
            return f"[error: {e}]"
