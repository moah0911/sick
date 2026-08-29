import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    import portalocker  # type: ignore
except Exception:  # pragma: no cover
    portalocker = None  # type: ignore

MEMORY_DIR = Path(os.environ.get("SICK_MEMORY_DIR", Path.home() / ".sick"))
MEMORY_PATH = MEMORY_DIR / "memory.jsonl"

MAX_MEMORY_BYTES = 5_000_000


@dataclass
class Experience:
    task: str
    outcome: str
    pattern: str
    tools: list[str]
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


class ExperienceMemory:
    def __init__(self, path: str | Path = MEMORY_PATH):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _rotate_if_needed(self) -> None:
        try:
            if self._path.exists() and self._path.stat().st_size > MAX_MEMORY_BYTES:
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

    def record(self, exp: Experience) -> None:
        self._rotate_if_needed()
        line = json.dumps(asdict(exp), default=str) + "\n"
        self._path.parent.mkdir(parents=True, exist_ok=True)
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

    def recall(self, task_type: str, top_k: int = 3) -> list[Experience]:
        if not self._path.exists():
            return []
        results = []
        lines: list[str] = []
        if portalocker:
            try:
                with portalocker.Lock(str(self._path), "r", flags=portalocker.LOCK_SH) as f:  # type: ignore
                    lines = f.read().splitlines()
            except Exception:
                lines = []
        if not lines:
            try:
                with open(self._path) as f:
                    lines = f.read().splitlines()
            except OSError:
                return []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                exp = Experience(**d)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if task_type.lower() in exp.task.lower() or task_type.lower() in exp.pattern.lower():
                results.append(exp)
        results.sort(key=lambda e: e.timestamp, reverse=True)
        return results[:top_k]
