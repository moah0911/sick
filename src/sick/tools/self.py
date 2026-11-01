import os
from pathlib import Path

from sick.tools.files import ReadFile, WriteFile

SOURCE_ROOT = Path(__file__).resolve().parents[1]


def resolve_source_root() -> Path:
    """Where self_read/self_write operate.

    Prefer a real checkout via $SICK_ROOT (so self-improvements survive
    reinstalls and can be committed); fall back to the installed package
    directory. Without this, `uv tool` installs edited site-packages —
    learning that evaporates on the next upgrade.
    """
    env = os.environ.get("SICK_ROOT")
    if env:
        base = Path(env).expanduser()
        for candidate in (base / "src" / "sick", base):
            if (candidate / "agent.py").is_file():
                return candidate
    return SOURCE_ROOT


class SelfRead(ReadFile):
    name = "self_read"
    description = "Read sick's own source code. Path relative to src/sick/."

    def __init__(self, source_root: str | Path | None = None) -> None:
        super().__init__(source_root or resolve_source_root())


class SelfWrite(WriteFile):
    name = "self_write"
    description = "Write to sick's own source code. Path relative to src/sick/."

    def __init__(self, source_root: str | Path | None = None) -> None:
        super().__init__(source_root or resolve_source_root())
