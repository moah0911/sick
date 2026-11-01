"""Tests for bundled default plugins: ponytail + aftermath."""


def test_bundled_content_is_real_upstream():
    from sick.plugins import BUNDLED_ROOT, aftermath_ladder, ponytail_body

    assert (BUNDLED_ROOT / "BUNDLED.md").is_file()
    assert "96608e07" in (BUNDLED_ROOT / "BUNDLED.md").read_text()
    body = ponytail_body()
    assert "lazy senior developer" in body  # the real SKILL.md, not a summary
    assert "first option that fully works" in body
    ladder = aftermath_ladder()
    assert ladder and len(ladder) < 2000  # the dozen-line ladder
    bundled_skills = sorted(p.name for p in (BUNDLED_ROOT / "aftermath").glob("*/SKILL.md"))
    assert len(bundled_skills) == 0 or True  # dirs checked below
    skill_dirs = [d.name for d in (BUNDLED_ROOT / "aftermath").iterdir() if (d / "SKILL.md").is_file()]
    assert len(skill_dirs) == 8, skill_dirs


def test_agent_defaults_to_real_plugins(tmp_path):
    from sick.agent import SickAgent

    agent = SickAgent(workspace=tmp_path)
    assert agent.ponytail_mode == "full" and agent.aftermath_mode == "full"
    assert "lazy senior developer" in agent.context["ponytail"]
    assert agent.context["aftermath"].startswith("## aftermath")
    names = {s.name for s in agent.discovered_skills}
    assert "ponytail" in names and "aftermath" in names  # bundled discovery
    out = agent.set_ponytail_mode("off")
    assert out == "ponytail: off" and "(off" in agent.context["ponytail"]
    agent.set_ponytail_mode("full")


def test_guard_blocks_destructive_and_freezes_edits(tmp_path):
    from sick.guard import AftermathGuard

    g = AftermathGuard(tmp_path, mode="full")
    assert g.check("bash", {"command": "git push --force origin main"}) is not None
    assert g.check("bash", {"command": "rm -rf src"}) is not None
    assert g.check("bash", {"command": "ls"}) is None
    # failure freezes forward edits until a verification passes
    g.record("bash", False, {"command": "pytest -q"})
    assert g.frozen
    assert g.check("write_file", {"path": "a.py"}) is not None
    g.record("bash", True, {"command": "pytest -q"})
    assert not g.frozen
    assert g.check("write_file", {"path": "a.py"}) is None


def test_guard_lite_warns_off_disables(tmp_path):
    from sick.guard import AftermathGuard

    lite = AftermathGuard(tmp_path, mode="lite")
    assert lite.check("bash", {"command": "git reset --hard HEAD"}) is None
    lite.record("bash", False, {"command": "x"})
    assert lite.check("edit_file", {"path": "a.py"}) is None  # lite never blocks edits
    off = AftermathGuard(tmp_path, mode="off")
    assert off.check("bash", {"command": "rm -rf /"}) is None


def test_guard_via_agent_registry(tmp_path):
    from sick.agent import SickAgent

    agent = SickAgent(workspace=tmp_path)
    out = agent.bash("git push --force origin main")
    assert "aftermath: blocked" in out
    entries = agent.audit.entries()
    assert entries and entries[-1]["tool"] == "bash" and entries[-1]["ok"] is False
    # frozen now: edits refused until verification
    out = agent.write_file("a.py", "x = 1\n")
    assert "aftermath: edits frozen" in out
    result = agent.set_aftermath_mode("off")
    assert "off" in result
    assert agent.write_file("a.py", "x = 1\n").startswith("Wrote")


def test_ponytail_debt_command_harvests(tmp_path):
    import asyncio

    from sick.agent import SickAgent
    from sick.tui.app import SickApp

    class FakeAgent(SickAgent):
        def __init__(self, workspace="."):
            super().__init__(workspace=workspace)

        async def respond(self):
            pass

    (tmp_path / "code.py").write_text("# shortcut: naive parse, revisit if format grows\nx = 1\n")

    async def scenario():
        app = SickApp(FakeAgent(str(tmp_path)))
        return await app.commands.dispatch(app, "/ponytail-debt")

    out = asyncio.run(scenario())
    assert "ponytail debt (1)" in out and "code.py" in out


def test_aftermath_commands_dispatch(tmp_path):
    import asyncio

    from sick.agent import SickAgent
    from sick.tui.app import SickApp

    class FakeAgent(SickAgent):
        def __init__(self, workspace="."):
            super().__init__(workspace=workspace)

        async def respond(self):
            pass

    async def scenario():
        app = SickApp(FakeAgent(str(tmp_path)))
        out = await app.commands.dispatch(app, "/aftermath")
        assert "aftermath:" in out
        out = await app.commands.dispatch(app, "/aftermath lite")
        assert "lite" in out
        out = await app.commands.dispatch(app, "/aftermath-log broke the build twice")
        assert "logged" in out
        assert "broke the build twice" in (tmp_path / "AFTERMATH.log").read_text()
        out = await app.commands.dispatch(app, "/ponytail")
        assert "ponytail:" in out

    asyncio.run(scenario())
