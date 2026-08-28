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
            val = data[key]
            # validate types — ponytail: don't crash, just ignore bad types
            if key == "excluded":
                if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                    continue
            elif key == "model":
                if not isinstance(val, str):
                    continue
            cfg[key] = val
    return cfg