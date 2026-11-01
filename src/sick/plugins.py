"""Bundled default plugins: ponytail + aftermath (vendored, pinned).

Sick has no host plugin runtime, so plugins are expressed through the
mechanisms Sick does have: always-on context skills (ponytail body,
aftermath ladder), discovered SKILL.md playbooks (bundled dirs at the
lowest precedence), slash commands, and — for aftermath — real
enforcement in the ToolRegistry (see sick.guard).
"""

from pathlib import Path

BUNDLED_ROOT = Path(__file__).resolve().parent / "bundled"

PONYTAIL_MODES = ("lite", "full", "ultra", "off")
AFTERMATH_MODES = ("lite", "full", "ultra", "off")


def _body(rel: str) -> str:
    """Read a bundled file with YAML frontmatter stripped, or ""."""
    try:
        raw = (BUNDLED_ROOT / rel).read_text(errors="replace")
    except OSError:
        return ""
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return raw.strip()


def ponytail_body() -> str:
    return _body("ponytail/ponytail/SKILL.md")


def ponytail_skill_body(name: str) -> str:
    return _body(f"ponytail/{name}/SKILL.md")


def aftermath_ladder() -> str:
    return _body("aftermath/AFTERMATH.md")


def aftermath_skill_body(name: str) -> str:
    return _body(f"aftermath/{name}/SKILL.md")


def bundled_skills_dirs() -> list[Path]:
    """Dirs whose */SKILL.md become discoverable skills (lowest precedence)."""
    return [BUNDLED_ROOT / "ponytail", BUNDLED_ROOT / "aftermath"]
