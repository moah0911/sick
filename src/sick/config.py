import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator


class SickConfig(BaseModel):
    model_config = {"extra": "ignore"}

    workspace: str = "."
    model: str = ""
    excluded: list[str] = Field(default_factory=list)
    provider: str = ""
    embedding_model: str = ""
    embedding_provider: str = "auto"
    hybrid_alpha: float = 0.7

    @field_validator("excluded", mode="before")
    @classmethod
    def validate_excluded(cls, v):
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ValueError("excluded must be list[str]")
        return v


DEFAULTS = SickConfig().model_dump()


def _max_bytes() -> int:
    try:
        v = int(os.environ.get("SICK_MAX_READ_BYTES", "500000"))
        return max(10_000, min(10_000_000, v))
    except ValueError:
        return 500_000


def load_config(workspace: str | Path) -> dict:
    """Read {workspace}/.sick/config.toml, ignoring unknown keys and bad syntax."""
    path = Path(workspace).resolve() / ".sick" / "config.toml"
    cfg = dict(DEFAULTS)
    if not path.exists():
        return cfg
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        try:
            import structlog  # type: ignore

            structlog.get_logger("sick.config").warning("config_toml_parse_failed", path=str(path))
        except Exception:
            pass
        return cfg
    try:
        validated = SickConfig.model_validate(raw)
        return validated.model_dump()
    except ValidationError as e:
        try:
            import structlog  # type: ignore

            structlog.get_logger("sick.config").warning("config_validation_failed", errors=str(e.errors()))
        except Exception:
            pass
        for key in DEFAULTS:
            if key in raw:
                try:
                    SickConfig.model_validate({**cfg, key: raw[key]})
                    cfg[key] = raw[key]
                except ValidationError:
                    continue
        return cfg
