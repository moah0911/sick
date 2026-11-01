"""Tests for skills-from-success: /distill draft -> approve -> active."""


def test_distill_draft_then_approve(tmp_path):
    import sys

    from sick.agent import SickAgent

    agent = SickAgent(workspace=tmp_path)
    agent.begin_run("add a hello module")
    agent.write_file("hello.py", "def hello():\n    return 'hi'\n")
    agent.write_file("test_hello.py", "from hello import hello\n\ndef test_hello():\n    assert hello() == 'hi'\n")
    agent.bash(f"{sys.executable} -m pytest -q")
    verdict = agent.finish_run("done")
    assert verdict.allowed
    out = agent.distill_skill()
    assert "draft skill written" in out
    slug = out.split("approve ")[-1].strip()
    draft = tmp_path / ".sick" / "skills-draft" / slug / "SKILL.md"
    assert draft.is_file()
    body = draft.read_text()
    assert "write_file" in body and "pytest" in body and "hello.py" in body
    # drafts are invisible to discovery + loading
    assert all(s.name != slug for s in agent.discovered_skills)
    assert "unknown skill" in agent.load_skill(slug)
    # approve activates it
    approved = agent.approve_skill(slug)
    assert "approved and active" in approved
    assert any(s.name == slug for s in agent.discovered_skills)
    loaded = agent.load_skill(slug)
    assert "Tool sequence that worked" in loaded or "hello" in loaded


def test_distill_requires_a_delivered_change(tmp_path):
    from sick.agent import SickAgent

    agent = SickAgent(workspace=tmp_path)
    assert "nothing to distill" in agent.distill_skill()
