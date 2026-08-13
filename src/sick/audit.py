import json
import time
from pathlib import Path


class AuditLog:
    """Append-only JSONL record of every tool call for a workspace."""

    def __init__(self, workspace: str | Path) -> None:
        self._path = Path(workspace).resolve() / ".sick" / "audit.jsonl"

    def record(
        self,
        tool: str,
        ok: bool,
        duration_ms: int,
        **args: object,
    ) -> None:
        entry = {
            "t": time.time(),
            "tool": tool,
            "ok": ok,
            "duration_ms": duration_ms,
            "args": args,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def entries(self, n: int | None = None) -> list[dict]:
        if not self._path.exists():
            return []
        rows = []
        with open(self._path) as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if n is not None:
            rows = rows[-n:]
        return rows