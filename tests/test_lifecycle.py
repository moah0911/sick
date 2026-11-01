"""Tests for the evidence-gated SDLC lifecycle (sick.lifecycle) + registry seam."""

import asyncio

from sick.lifecycle import Lifecycle, Phase, RiskTier
from sick.tools.base import Tool, ToolResult
from sick.tools.registry import ToolRegistry


def test_trivial_run_delivers_without_evidence(tmp_path):
    lc = Lifecycle(tmp_path)
    run = lc.start("answer a question")
    assert run.phase == Phase.REQUIREMENTS
    assert (tmp_path / ".sick" / "runs" / run.id / "requirements.md").is_file()
    verdict = lc.can_deliver(run)
    assert verdict.allowed and verdict.reasons == []
    lc.finish(run, "answered")
    assert run.phase == Phase.DELIVER
    assert run.tier == RiskTier.TRIVIAL
    assert (tmp_path / ".sick" / "runs" / run.id / "summary.md").is_file()
    assert (tmp_path / ".sick" / "runs" / run.id / "verification.json").is_file()


def test_standard_run_blocked_without_post_edit_evidence(tmp_path):
    lc = Lifecycle(tmp_path)
    run = lc.start("fix the parser")
    lc.record(run, ToolResult.success("found it", tool="read_file"), {"path": "a.py"})
    assert run.phase == Phase.DESIGN
    lc.record(run, ToolResult.success("Wrote 10 bytes", tool="write_file"), {"path": "a.py"})
    assert run.phase == Phase.IMPLEMENT
    verdict = lc.can_deliver(run)
    assert not verdict.allowed
    assert any("no verification evidence after last edit" in r for r in verdict.reasons)
    lc.finish(run, "done")
    assert run.phase == Phase.BLOCKED


def test_evidence_before_last_edit_does_not_unblock(tmp_path):
    lc = Lifecycle(tmp_path)
    run = lc.start("fix the parser")
    lc.record(run, ToolResult.success("ok", tool="bash"), {"command": "pytest -q"})
    lc.record(run, ToolResult.success("Wrote", tool="write_file"), {"path": "a.py"})
    assert not lc.can_deliver(run).allowed
    lc.record(run, ToolResult.success("3 passed", tool="bash"), {"command": "pytest -q"})
    assert run.phase == Phase.VERIFY
    assert lc.can_deliver(run).allowed


def test_risky_run_needs_approval_checkpoint_and_evidence(tmp_path):
    lc = Lifecycle(tmp_path)
    run = lc.start("change auth handling")
    lc.record(run, ToolResult.success("Wrote", tool="self_write"), {"path": "agent.py"})
    assert lc.classify(run) == RiskTier.RISKY
    verdict = lc.can_deliver(run)
    assert not verdict.allowed
    assert any("approval" in r for r in verdict.reasons)
    assert any("checkpoint" in r for r in verdict.reasons)
    lc.approve(run)
    lc.record(run, ToolResult.success("checkpoint created: abc1234", tool="checkpoint"), {})
    lc.record(run, ToolResult.success("ok", tool="bash"), {"command": "pytest -q"})
    assert lc.can_deliver(run).allowed


def test_design_check_blocks_duplicate_definitions(tmp_path):
    (tmp_path / "bad.py").write_text("def f():\n    pass\n\ndef f():\n    pass\n")
    lc = Lifecycle(tmp_path)
    run = lc.start("edit bad module")
    lc.record(run, ToolResult.success("Wrote", tool="write_file"), {"path": "bad.py"})
    lc.record(run, ToolResult.success("ok", tool="bash"), {"command": "pytest -q"})
    verdict = lc.finish(run, "done")
    assert not verdict.allowed
    assert run.phase == Phase.BLOCKED
    assert any("duplicate" in r for r in verdict.reasons)


def test_skill_routing_finds_installed_skill(tmp_path):
    skills = tmp_path / "skills-home"
    (skills / "codebase-design").mkdir(parents=True)
    (skills / "codebase-design" / "SKILL.md").write_text(
        "---\nname: codebase-design\ndescription: deep modules\n---\nDesign deep modules.\n"
    )
    lc = Lifecycle(tmp_path, skills_home=skills)
    routed = lc.skill_for_phase(Phase.DESIGN)
    assert routed is not None and routed.name == "codebase-design"
    run = lc.start("design a module")
    name, body = lc.route_skill(run, Phase.DESIGN)
    assert name == "codebase-design" and "deep modules" in body
    assert run.skills["design"] == "codebase-design"


class _FakeTool(Tool):
    name = "fake"
    description = "fake"

    def __init__(self, raw):
        self.raw = raw

    def execute(self, **kwargs):
        return self.raw


def test_registry_returns_typed_result_and_counts():
    reg = ToolRegistry()
    reg.register(_FakeTool(ToolResult.success("hi", tool="fake")))
    result = reg.call("fake")
    assert isinstance(result, ToolResult) and result.ok and result.output == "hi"
    assert reg.counts() == {"fake": 1}
    missing = reg.call("nope")
    assert not missing.ok and "unknown tool" in (missing.error or "")


def test_registry_activity_streams_start_done():
    events = []
    reg = ToolRegistry()
    reg.activity = events.append
    reg.register(_FakeTool(ToolResult.success("hi", tool="fake")))
    reg.call("fake", path="a.py")
    assert [e["phase"] for e in events] == ["start", "done"]
    assert events[0]["summary"] == "path=a.py"
    assert events[1]["ok"] is True and events[1]["duration_ms"] >= 0


def test_registry_wraps_legacy_returns():
    reg = ToolRegistry()
    reg.register(_FakeTool("Error: boom"))
    result = reg.call("fake")
    assert not result.ok


def test_agent_handle_blocks_unverified_mutation(tmp_path):
    from sick.agent import SickAgent

    class EditingAgent(SickAgent):
        async def respond(self):
            self.write_file("a.py", "x = 1\n")

    async def scenario():
        agent = EditingAgent(workspace=tmp_path)
        await agent.handle({"user_messages": ["create a module"]})
        return agent

    agent = asyncio.run(scenario())
    assert agent.current_run is not None
    assert agent.current_run.phase == Phase.BLOCKED
    remembered = agent.memory.recall("create a module")
    assert remembered and remembered[0].outcome == "blocked"


def test_agent_handle_delivers_verified_mutation(tmp_path):
    from sick.agent import SickAgent

    class VerifiedAgent(SickAgent):
        async def respond(self):
            self.read_file("a.py")
            self.write_file("a.py", "x = 1\n")
            self.write_file("test_a.py", "from a import x\n\ndef test_x():\n    assert x == 1\n")
            self.bash(f"{__import__('sys').executable} -m pytest -q")

    (tmp_path / "a.py").write_text("x = 0\n")

    async def scenario():
        agent = VerifiedAgent(workspace=tmp_path)
        await agent.handle({"user_messages": ["update the module"]})
        return agent

    agent = asyncio.run(scenario())
    assert agent.current_run is not None
    assert agent.current_run.phase == Phase.DELIVER
    remembered = agent.memory.recall("update the module")
    assert remembered and remembered[0].outcome == "success"
