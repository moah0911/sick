import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path


MEMORY_DIR = Path(os.environ.get("SICK_MEMORY_DIR", Path.home() / ".sick"))
MEMORY_PATH = MEMORY_DIR / "memory.jsonl"


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

    def record(self, exp: Experience) -> None:
        with open(self._path, "a") as f:
            f.write(json.dumps(asdict(exp)) + "\n")

    def recall(self, task_type: str, top_k: int = 3) -> list[Experience]:
        if not self._path.exists():
            return []
        results = []
        with open(self._path) as f:
            for line in f:
                d = json.loads(line)
                exp = Experience(**d)
                if task_type.lower() in exp.task.lower() or task_type.lower() in exp.pattern.lower():
                    results.append(exp)
        results.sort(key=lambda e: e.timestamp, reverse=True)
        return results[:top_k]
