"""load_skill tool — full SKILL.md bodies on demand, through the registry.

Previously agent.load_skill bypassed ToolRegistry entirely: uncounted,
unaudited, invisible in the live feed. As a registered tool it gets all
three for free, like every other capability.
"""

from pathlib import Path

from sick.tools.base import Tool, ToolResult


class LoadSkill(Tool):
    name = "load_skill"
    description = "Load the full instructions of an installed skill by name (see the skills index)"

    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace)

    def execute(self, name: str) -> ToolResult:
        from sick.skills import load_skill_body

        body = load_skill_body(name, self.workspace)
        if body is None:
            return ToolResult.failure(f"Error: unknown skill: {name}", tool=self.name)
        return ToolResult.success(body, tool=self.name)
