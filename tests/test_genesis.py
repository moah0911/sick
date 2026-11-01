"""Tests for tool genesis: the agent grows its own tools."""

UPPER_CODE = '''
from sick.tools.base import Tool, ToolResult

class Upper(Tool):
    name = "upper"
    description = "Uppercase text"

    def execute(self, text: str = ""):
        return ToolResult.success(text.upper(), tool=self.name)
'''

BAD_CODE = '''
from sick.tools.base import Tool, ToolResult

class Boom(Tool):
    name = "boom"
    description = "explodes"

    def execute(self, text: str = ""):
        raise RuntimeError("kaboom")
'''


def test_create_tool_registers_live_and_persists(tmp_path):
    from sick.agent import SickAgent

    agent = SickAgent(workspace=tmp_path)
    out = agent.create_tool("upper", UPPER_CODE, {"text": "hi"}, "HI")
    assert out.startswith("tool 'upper' created"), out
    assert agent.use_tool("upper", text="abc") == "ABC"
    assert "grown_tools" in agent.context
    manifest = tmp_path / ".sick" / "tools" / "MANIFEST.json"
    assert manifest.is_file() and "upper" in manifest.read_text()
    # a fresh agent in the same workspace has the grown tool loaded
    agent2 = SickAgent(workspace=tmp_path)
    assert "upper" in agent2.grown_tools
    assert agent2.use_tool("upper", text="xy") == "XY"


def test_create_tool_rejects_bad_code_and_shadowing(tmp_path):
    from sick.agent import SickAgent

    agent = SickAgent(workspace=tmp_path)
    out = agent.create_tool("boom_tool", BAD_CODE, {"text": "hi"})
    assert out.startswith("Error: smoke test failed"), out
    assert not (tmp_path / ".sick" / "tools" / "boom_tool.py").exists()
    assert "boom_tool" not in agent.registry.tools
    # grown tools never shadow builtins
    out = agent.create_tool("read_file", UPPER_CODE.replace('"upper"', '"read_file"'), {"text": "hi"})
    assert "already exists" in out


def test_genesis_can_be_disabled(tmp_path, monkeypatch):
    from sick.agent import SickAgent

    monkeypatch.setenv("SICK_TOOL_GENESIS", "off")
    agent = SickAgent(workspace=tmp_path)
    assert "create_tool" not in agent.registry.tools
    assert agent.grown_tools == []
