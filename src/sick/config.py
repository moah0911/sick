import tomllib
from pathlib import Path

DEFAULTS = {"workspace": ".", "model": "", "excluded": []}


def load_config(workspace: str | Path) -> dict:
    """Read {workspace}/.sick/config.toml, ignoring unknown keys and bad syntax."""
    path = Path(workspace).resolve() / ".sick" / "config.toml"
    cfg = dict(DEFAULTS)
    if not path.exists():
        return cfg
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        return cfg
    for key in DEFAULTS:
        if key in data:
            cfg[key] = data[key]
    return cfg