"""Tests for skill discovery (sick.skills) and the empty-env regressions."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _make_skill(base: Path, name: str, description: str, body: str = "do the thing") -> Path:
    d = base / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}\n")
    return d


def test_discover_skills_reads_frontmatter(tmp_path, monkeypatch):
    from sick.skills import discover_skills

    _make_skill(tmp_path, "alpha", "Alpha skill")
    _make_skill(tmp_path, "beta", "Beta skill")
    monkeypatch.setenv("SICK_SKILLS_DIR", str(tmp_path))
    monkeypatch.delenv("SICK_REMOTION_DIR", raising=False)
    skills = discover_skills()
    by_name = {s.name: s for s in skills}
    assert by_name["alpha"].description == "Alpha skill"
    assert by_name["beta"].path == tmp_path / "beta"


def test_workspace_skills_override_global(tmp_path, monkeypatch):
    from sick.skills import discover_skills

    global_dir = tmp_path / "global"
    ws = tmp_path / "ws"
    _make_skill(global_dir, "shared", "global version")
    _make_skill(ws / ".sick" / "skills", "shared", "workspace version")
    monkeypatch.setenv("SICK_SKILLS_DIR", str(global_dir))
    skills = discover_skills(ws)
    shared = [s for s in skills if s.name == "shared"]
    assert len(shared) == 1
    assert shared[0].description == "workspace version"


def test_skills_index_and_load_body(tmp_path, monkeypatch):
    from sick.skills import discover_skills, load_skill_body, skills_index_prompt

    _make_skill(tmp_path, "alpha", "Alpha skill", body="ALPHA BODY")
    monkeypatch.setenv("SICK_SKILLS_DIR", str(tmp_path))
    idx = skills_index_prompt(discover_skills())
    assert "alpha" in idx and "Alpha skill" in idx and "SKILL.md" in idx
    assert load_skill_body("alpha") == "ALPHA BODY"
    assert load_skill_body("nope") is None


def test_skills_index_is_capped(tmp_path, monkeypatch):
    from sick.skills import discover_skills, skills_index_prompt

    for i in range(30):
        _make_skill(tmp_path, f"skill-{i:02d}", "x" * 120)
    monkeypatch.setenv("SICK_SKILLS_DIR", str(tmp_path))
    idx = skills_index_prompt(discover_skills(tmp_path), max_chars=1500)
    assert len(idx) <= 2200  # cap + header + omission line
    assert "more installed skills" in idx
    assert "load_skill(name)" in idx


def test_rank_skills_by_relevance():
    from sick.skills import SkillInfo, rank_skills

    skills = [
        SkillInfo("alpha", "generic helper", Path("/x/alpha")),
        SkillInfo("pytest-coverage", "run tests with coverage", Path("/x/pytest-coverage")),
        SkillInfo("zeta", "unrelated", Path("/x/zeta")),
    ]
    ranked = rank_skills(skills, "run the tests and check coverage")
    assert ranked[0].name == "pytest-coverage"


def test_load_skill_goes_through_registry(tmp_path, monkeypatch):
    from sick.agent import SickAgent

    _make_skill(tmp_path, "alpha", "Alpha skill", body="ALPHA BODY")
    monkeypatch.setenv("SICK_SKILLS_DIR", str(tmp_path))
    agent = SickAgent(workspace=tmp_path)
    assert "load_skill" in agent.registry.tools
    assert agent.load_skill("alpha") == "ALPHA BODY"
    assert agent.registry.counts().get("load_skill") == 1
    entries = agent.audit.entries()
    assert any(e["tool"] == "load_skill" and e["ok"] for e in entries)
    assert "unknown skill" in agent.load_skill("nope")


def test_agent_indexes_discovered_skills(tmp_path, monkeypatch):
    from sick.agent import SickAgent

    _make_skill(tmp_path, "alpha", "Alpha skill", body="ALPHA BODY")
    monkeypatch.setenv("SICK_SKILLS_DIR", str(tmp_path))
    agent = SickAgent(workspace=tmp_path)
    assert any(s.name == "alpha" for s in agent.discovered_skills)
    assert "alpha" in agent.context["skills"]
    assert agent.load_skill("alpha") == "ALPHA BODY"
    assert "unknown skill" in agent.load_skill("nope")


def test_empty_skills_dir_env_means_unset(monkeypatch, tmp_path):
    from sick.skills import skills_dirs

    monkeypatch.setenv("SICK_SKILLS_DIR", "")
    monkeypatch.setenv("SICK_REMOTION_DIR", "")
    dirs = skills_dirs(tmp_path)
    assert all(str(d) for d in dirs)  # no Path(".") sneaking in
    assert dirs[0] != Path(".")


def test_empty_memory_env_does_not_leak_into_cwd():
    code = (
        "import os; os.environ['SICK_MEMORY_DIR']='';"
        "from sick.memory import MEMORY_PATH;"
        "print(MEMORY_PATH)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith(".sick/memory.jsonl"), r.stdout


def test_empty_remotion_env_does_not_resolve_to_dot(tmp_path):
    fake = tmp_path / "skills"
    _make_skill(fake, "remotion-create", "create", body="CREATE BODY")
    _make_skill(fake, "remotion-best-practices", "practices", body="PRACTICES BODY")
    code = (
        "import os; os.environ['SICK_REMOTION_DIR']=os.environ['FAKE_SKILLS'];"
        "from sick.agent import _load_remotion_skill;"
        "print(_load_remotion_skill())"
    )
    env = {"FAKE_SKILLS": str(fake), "PATH": "/usr/bin:/bin"}
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
        env={**__import__("os").environ, **env},
    )
    assert "CREATE BODY" in r.stdout and "PRACTICES BODY" in r.stdout, r.stdout + r.stderr
