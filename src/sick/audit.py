import json
import os
import time
from pathlib import Path

try:
    import portalocker  # type: ignore
except Exception:  # pragma: no cover
    portalocker = None  # type: ignore

MAX_AUDIT_BYTES = 5_000_000


class AuditLog:
    """Append-only JSONL record of every tool call for a workspace."""

    def __init__(self, workspace: str | Path) -> None:
        self._path = Path(workspace).resolve() / ".sick" / "audit.jsonl"

    def _rotate_if_needed(self) -> None:
        try:
            if self._path.exists() and self._path.stat().st_size > MAX_AUDIT_BYTES:
                ts = int(time.time())
                rot = self._path.with_suffix(f".{ts}.jsonl")
                self._path.rename(rot)
                olds = sorted(self._path.parent.glob(self._path.name + ".*.jsonl"))
                for p in olds[:-3]:
                    try:
                        p.unlink()
                    except OSError:
                        pass
        except OSError:
            pass

    def record(
        self,
        tool: str,
        ok: bool,
        duration_ms: int,
        **args: object,
    ) -> None:
        import re

        redacted = {}
        for k, v in args.items():
            s = str(v) if not isinstance(v, str) else v
            s = re.sub(r"(?i)(api[_-]?key\s*[:=]\s*)([^\s\"']+)", r"\1[REDACTED]", s)
            s = re.sub(r"(?i)(sk-[a-z0-9\-]{10,})", "[REDACTED]", s)
            redacted[k] = s
        entry = {
            "t": time.time(),
            "tool": tool,
            "ok": ok,
            "duration_ms": duration_ms,
            "args": redacted,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_if_needed()
        line = json.dumps(entry, default=str) + "\n"
        if portalocker:
            try:
                with portalocker.Lock(str(self._path), "a", timeout=5) as f:  # type: ignore
                    f.write(line)
                    try:
                        f.flush()
                        os.fsync(f.fileno())
                    except OSError:
                        pass
                return
            except Exception:
                pass
        with open(self._path, "a") as f:
            f.write(line)

    def entries(self, n: int | None = None) -> list[dict]:
        if not self._path.exists():
            return []
        rows = []
        data = ""
        if portalocker:
            try:
                with portalocker.Lock(str(self._path), "r", flags=portalocker.LOCK_SH) as f:  # type: ignore
                    data = f.read()
            except Exception:
                data = ""
        if not data:
            try:
                with open(self._path) as f:
                    data = f.read()
            except OSError:
                return []
        for line in data.splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if n is not None:
            rows = rows[-n:]
        return rows
