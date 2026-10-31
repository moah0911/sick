"""Skill discovery — every installed SKILL.md becomes usable by the agent.

Built-in skills (ponytail/pdf/sdlc/remotion) are always in context. Skills
installed on disk (``~/.agents/skills``, ``~/.sick/skills``, workspace
``.sick/skills``) are indexed by name + description only, so dozens of skills
cost a few hundred tokens; the agent reads the full ``SKILL.md`` body on
demand when a skill matches the task.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

MAX_SKILL_BODY = 50_000


@dataclass
class SkillInfo:
    name: str
    description: str
    path: Path  # directory containing SKILL.md


def skills_dirs(workspace: str | Path | None = None) -> list[Path]:
    """Skill search dirs, lowest precedence first (later wins on name clash)."""
    # ponytail: empty env var means unset, same rule as memory/remotion dirs
    base = Path(
        os.environ.get("SICK_SKILLS_DIR")
        or os.environ.get("SICK_REMOTION_DIR")
        or (Path.home() / ".agents" / "skills")
    )
    dirs = [base, Path.home() / ".sick" / "skills"]
    if workspace is not None:
        dirs.append(Path(workspace) / ".sick" / "skills")
    return dirs


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---"):
        return {}, raw.strip()
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw.strip()
    _, fm, body = parts
    meta: dict = {}
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(fm)
        if isinstance(loaded, dict):
            meta = {str(k).lower(): v for k, v in loaded.items()}
    except Exception:
        for line in fm.splitlines():
            m = re.match(r"^([a-zA-Z][a-zA-Z0-9_-]*):\s*(.+)$", line.strip())
            if m:
                meta[m.group(1).lower()] = m.group(2).strip().strip('"').strip("'")
    return meta, body.strip()


def discover_skills(workspace: str | Path | None = None) -> list[SkillInfo]:
    """Find every SKILL.md under the search dirs (deduped by name)."""
    found: dict[str, SkillInfo] = {}
    for base in skills_dirs(workspace):
        if not base.is_dir():
            continue
        for skill_md in sorted(base.glob("*/SKILL.md")):
            try:
                meta, _ = _parse_frontmatter(skill_md.read_text(errors="replace"))
            except OSError:
                continue
            name = str(meta.get("name") or skill_md.parent.name).strip()
            if not name:
                continue
            found[name] = SkillInfo(
                name=name,
                description=str(meta.get("description") or name).strip(),
                path=skill_md.parent,
            )
    return sorted(found.values(), key=lambda s: s.name)


def skills_index_prompt(skills: list[SkillInfo]) -> str:
    """Compact index block: one line per skill, full body read on demand."""
    lines = [
        "## skills (installed)",
        "When a task matches a skill below, read its full instructions first "
        "with `read_file` on the given SKILL.md path, then follow them.",
    ]
    for s in skills:
        lines.append(f"- **{s.name}** — {s.description} (`{s.path / 'SKILL.md'}`)")
    return "\n".join(lines)


def load_skill_body(name: str, workspace: str | Path | None = None) -> str | None:
    """Return the full SKILL.md body for one skill, bounded, or None."""
    for s in discover_skills(workspace):
        if s.name == name:
            try:
                _, body = _parse_frontmatter((s.path / "SKILL.md").read_text(errors="replace"))
            except OSError:
                return None
            if len(body) > MAX_SKILL_BODY:
                body = body[:MAX_SKILL_BODY] + f"\n[truncated after {MAX_SKILL_BODY} bytes]"
            return body
    return None
