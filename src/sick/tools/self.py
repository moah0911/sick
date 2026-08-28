from pathlib import Path

from sick.tools.files import ReadFile, WriteFile

SOURCE_ROOT = Path(__file__).resolve().parents[1]


class SelfRead(ReadFile):
    name = "self_read"
    description = "Read sick's own source code. Path relative to src/sick/."

    def __init__(self, source_root: str | Path = SOURCE_ROOT) -> None:
        super().__init__(source_root)


class SelfWrite(WriteFile):
    name = "self_write"
    description = "Write to sick's own source code. Path relative to src/sick/."

    def __init__(self, source_root: str | Path = SOURCE_ROOT) -> None:
        super().__init__(source_root)
