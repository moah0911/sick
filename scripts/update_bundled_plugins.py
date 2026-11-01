#!/usr/bin/env python3
"""Refresh the vendored ponytail + aftermath plugin content (pinned).

Clones both upstream repos at their current HEAD, copies the skill
files Sick vendors, and rewrites the pins in bundled/BUNDLED.md.
Review the resulting diff like any other dependency change.

Run: uv run python scripts/update_bundled_plugins.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLED = ROOT / "src" / "sick" / "bundled"
REPOS = {
    "ponytail": "https://github.com/DietrichGebert/ponytail.git",
    "aftermath": "https://github.com/moah0911/aftermath.git",
}


def clone(url: str, dest: Path) -> str:
    subprocess.run(["git", "clone", "-q", "--depth", "1", url, str(dest)], check=True)
    return subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> None:
    pins: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, url in REPOS.items():
            src = Path(tmp) / name
            pins[name] = clone(url, src)
            out = BUNDLED / name
            if name == "ponytail":
                for skill_md in sorted((src / "skills").glob("*/SKILL.md")):
                    target = out / skill_md.parent.name
                    target.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(skill_md, target / "SKILL.md")
            else:
                for skill_md in sorted((src / "skills").glob("*/SKILL.md")):
                    target = out / skill_md.parent.name
                    target.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(skill_md, target / "SKILL.md")
                shutil.copyfile(src / "AFTERMATH.md", out / "AFTERMATH.md")
                shutil.copyfile(src / "SKILL.md", out / "SKILL.md")
            shutil.copyfile(src / "LICENSE", out / "LICENSE")
            print(f"{name}: {pins[name]}")
    manifest = (BUNDLED / "BUNDLED.md").read_text()
    import re

    for name, sha in pins.items():
        manifest = re.sub(rf"(\| {name} \| [^|]+) `[^`]+`", rf"\1 `{sha}`", manifest)
    (BUNDLED / "BUNDLED.md").write_text(manifest)
    print("updated src/sick/bundled — review with `git diff`")


if __name__ == "__main__":
    sys.exit(main())
