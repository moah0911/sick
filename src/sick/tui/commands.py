from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sick.tui.app import SickApp


class SlashCommand:
    """A `/name` command. `run` returns chat lines, or None for silent."""

    name: str = ""
    aliases: list[str] = []
    hint: str = ""

    async def run(self, app: "SickApp", args: str) -> str | None:
        return None


class HelpCommand(SlashCommand):
    name = "help"
    hint = "show this help"

    async def run(self, app: "SickApp", args: str) -> str | None:
        lines = ["## commands"]
        for cmd in app.commands.canonical:
            names = " ".join([f"/{cmd.name}"] + [f"/{a}" for a in cmd.aliases])
            lines.append(f"- `{names}` — {cmd.hint}")
        return "\n".join(lines)


class ClearCommand(SlashCommand):
    name = "clear"
    aliases = ["new"]
    hint = "clear the conversation"

    async def run(self, app: "SickApp", args: str) -> str | None:
        app.chat_view.clear()
        app.agent.context["user_request"] = ""
        return "conversation cleared"


class ExitCommand(SlashCommand):
    name = "exit"
    aliases = ["quit", "q"]
    hint = "quit sick"

    async def run(self, app: "SickApp", args: str) -> str | None:
        app.exit()
        return None


class ModelsCommand(SlashCommand):
    name = "models"
    hint = "show the active model/provider"

    async def run(self, app: "SickApp", args: str) -> str | None:
        llm = getattr(app.agent, "_llm", None)
        name = getattr(llm, "model", None) or type(llm).__name__
        return f"model: `{name}`"


class AuditCommand(SlashCommand):
    name = "audit"
    hint = "show the last N tool calls (/audit [n])"

    async def run(self, app: "SickApp", args: str) -> str | None:
        try:
            n = int(args) if args.strip() else 10
        except ValueError:
            return "usage: /audit [n]"
        entries = app.agent.audit.entries(max(1, min(n, 100)))
        if not entries:
            return "no tool calls recorded yet"
        lines = []
        for e in entries:
            ok = "ok" if e["ok"] else "FAILED"
            lines.append(f"- [{ok}] {e['tool']} ({e['duration_ms']}ms)")
        return "\n".join(lines)


class StatsCommand(SlashCommand):
    name = "stats"
    hint = "show turn and tool-call counts for this session"

    async def run(self, app: "SickApp", args: str) -> str | None:
        counts = app.agent._tool_counts
        lines = [f"turns: {app.agent.turns}"]
        if counts:
            total = sum(counts.values())
            lines.append(f"tool calls: {total}")
            for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {name}: {count}")
        else:
            lines.append("tool calls: none yet")
        return "\n".join(lines)


class PlanCommand(SlashCommand):
    name = "plan"
    hint = "ask the agent for a plan without executing (/plan <task>)"

    async def run(self, app: "SickApp", args: str) -> str | None:
        if not args.strip():
            return "usage: /plan <task or description>"
        app.pending_task = args
        await app._send(
            f"Produce a plan for this task (no execution yet): {args}\n"
            "List the steps, files to touch, and how you will verify. "
            "The user will approve with /approve or revise with /reject.",
            show=False,
        )
        return f"planned: {args} — approve with `/approve`"


class ApproveCommand(SlashCommand):
    name = "approve"
    hint = "execute the pending /plan task"

    async def run(self, app: "SickApp", args: str) -> str | None:
        if not app.pending_task:
            return "nothing pending — start with `/plan <task>`"
        task = app.pending_task
        app.pending_task = None
        await app._send(
            f"Execute the plan you produced for: {task}",
            show=False,
        )
        return f"executing: {task}"


class RejectCommand(SlashCommand):
    name = "reject"
    hint = "discard the pending /plan task"

    async def run(self, app: "SickApp", args: str) -> str | None:
        if not app.pending_task:
            return "nothing pending"
        app.pending_task = None
        return "plan discarded"


class VisualCommand(SlashCommand):
    name = "visual"
    hint = "make an explanatory video with Remotion (/visual <topic>)"

    async def run(self, app: "SickApp", args: str) -> str | None:
        if not args.strip():
            return "usage: /visual <topic or description>"
        await app._send(
            f"Create an explanatory visualization video about: {args}\n"
            "Follow the remotion skill (always active). Scaffold the Remotion "
            "project inside the workspace, design a video-first composition, "
            "render it with `npx remotion render`, and report the final video path.",
            show=False,
        )
        return f"making a video about: {args}"


class SlashCommandRegistry:
    """Registry of slash commands, dispatchable by name or alias."""

    def __init__(self) -> None:
        self.commands: dict[str, SlashCommand] = {}
        self.canonical: list[SlashCommand] = []
        for cmd in (
            HelpCommand(), ClearCommand(), ExitCommand(), ModelsCommand(), VisualCommand(),
            AuditCommand(), StatsCommand(), PlanCommand(), ApproveCommand(), RejectCommand(),
        ):
            self.commands[cmd.name] = cmd
            self.canonical.append(cmd)
            for alias in cmd.aliases:
                self.commands[alias] = cmd

    async def dispatch(self, app: "SickApp", line: str) -> str | None:
        parts = line[1:].strip().split(maxsplit=1)
        name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        cmd = self.commands.get(name)
        if not cmd:
            return f"unknown command `/{name}` — try `/help`"
        return await cmd.run(app, args)