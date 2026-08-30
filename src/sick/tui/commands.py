from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sick.tui.app import SickApp


class SlashCommand:
    """A `/name` command. `run` returns chat lines, or None for silent."""

    name: str = ""
    aliases: list[str] = []
    hint: str = ""

    async def run(self, app: SickApp, args: str) -> str | None:
        return None


class HelpCommand(SlashCommand):
    name = "help"
    hint = "show this help"

    async def run(self, app: SickApp, args: str) -> str | None:
        lines = ["## commands"]
        for cmd in app.commands.canonical:
            names = " ".join([f"/{cmd.name}"] + [f"/{a}" for a in cmd.aliases])
            lines.append(f"- `{names}` — {cmd.hint}")
        return "\n".join(lines)


class ClearCommand(SlashCommand):
    name = "clear"
    aliases = ["new"]
    hint = "clear the conversation"

    async def run(self, app: SickApp, args: str) -> str | None:
        app.chat_view.clear()
        app.agent.context["user_request"] = ""
        return "conversation cleared"


class ExitCommand(SlashCommand):
    name = "exit"
    aliases = ["quit", "q"]
    hint = "quit sick"

    async def run(self, app: SickApp, args: str) -> str | None:
        app.exit()
        return None


class ModelsCommand(SlashCommand):
    name = "models"
    hint = "show the active model/provider"

    async def run(self, app: SickApp, args: str) -> str | None:
        # try provider model_id first, then llm internals
        try:
            from sick.providers import detect

            prov = detect()
            return f"model: `{prov.model_id}` (provider: {prov.name})"
        except Exception:
            pass
        llm = getattr(app.agent, "_llm", None) or getattr(app.agent, "llm", None)
        name = getattr(llm, "model", None) or getattr(llm, "model_id", None) or type(llm).__name__ if llm else "no llm"
        return f"model: `{name}`"


class AuditCommand(SlashCommand):
    name = "audit"
    hint = "show the last N tool calls (/audit [n])"

    async def run(self, app: SickApp, args: str) -> str | None:
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
            arg_str = ", ".join(f"{k}={str(v)[:60]}" for k, v in (e.get("args") or {}).items())
            if arg_str:
                lines.append(f"- [{ok}] {e['tool']} ({e['duration_ms']}ms) {arg_str}")
            else:
                lines.append(f"- [{ok}] {e['tool']} ({e['duration_ms']}ms)")
        return "\n".join(lines)


class StatsCommand(SlashCommand):
    name = "stats"
    hint = "show turn and tool-call counts for this session"

    async def run(self, app: SickApp, args: str) -> str | None:
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

    async def run(self, app: SickApp, args: str) -> str | None:
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

    async def run(self, app: SickApp, args: str) -> str | None:
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

    async def run(self, app: SickApp, args: str) -> str | None:
        if not app.pending_task:
            return "nothing pending"
        app.pending_task = None
        return "plan discarded"


class VisualCommand(SlashCommand):
    name = "visual"
    hint = "make an explanatory video with Remotion (/visual <topic>)"

    async def run(self, app: SickApp, args: str) -> str | None:
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


class PromptCommand(SlashCommand):
    """User-defined prompt from .sick/commands/*.md — ponytail: text only, no exec."""

    def __init__(self, name: str, hint: str, template: str):
        self.name = name
        self.hint = hint
        self.template = template

    async def run(self, app: SickApp, args: str) -> str | None:
        prompt = self.template.replace("$ARGUMENTS", args).replace("{{args}}", args).replace("$1", args)
        if not prompt.strip():
            return "prompt is empty"
        await app._send(prompt, show=True)
        return None


def _load_prompt_commands(workspace) -> list[SlashCommand]:
    from pathlib import Path

    cmds: list[SlashCommand] = []
    search_dirs = []
    try:
        if workspace:
            search_dirs.append(Path(workspace) / ".sick" / "commands")
    except Exception:
        pass
    try:
        search_dirs.append(Path.home() / ".sick" / "commands")
    except Exception:
        pass
    for base in search_dirs:
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*.md")):
            try:
                raw = p.read_text(errors="replace")
            except OSError:
                continue
            hint = p.stem
            body = raw.strip()
            if raw.startswith("---"):
                try:
                    _, fm, rest = raw.split("---", 2)
                    for line in fm.splitlines():
                        if line.strip().lower().startswith("description:"):
                            hint = line.split(":", 1)[1].strip().strip('"').strip("'")
                            break
                    body = rest.strip()
                except ValueError:
                    pass
            if not body:
                continue
            # avoid collision with builtins
            if p.stem in {"help", "clear", "exit", "quit", "q", "models", "audit", "stats", "plan", "approve", "reject", "visual", "checkpoint", "restore", "checkpoints", "version", "theme", "copy", "save"}:
                continue
            cmds.append(PromptCommand(p.stem, hint or p.stem, body))
    return cmds


class CheckpointCommand(SlashCommand):
    name = "checkpoint"
    hint = "snapshot workspace to sick-checkpoints branch"

    async def run(self, app: SickApp, args: str) -> str | None:
        return app.agent.checkpoint(args.strip() or "checkpoint")


class RestoreCommand(SlashCommand):
    name = "restore"
    hint = "restore workspace n checkpoints back (/restore [n])"

    async def run(self, app: SickApp, args: str) -> str | None:
        try:
            n = int(args.strip()) if args.strip() else 1
        except ValueError:
            return "usage: /restore [n]"
        return app.agent.restore(max(1, n))


class CheckpointsCommand(SlashCommand):
    name = "checkpoints"
    hint = "list sick-checkpoints"

    async def run(self, app: SickApp, args: str) -> str | None:
        return app.agent.checkpoints()


class VersionCommand(SlashCommand):
    name = "version"
    hint = "show sick version"

    async def run(self, app: SickApp, args: str) -> str | None:
        try:
            from importlib.metadata import version as _v

            v = _v("sick")
        except Exception:
            v = "0.1.0"
        return f"sick {v}"


class SlashCommandRegistry:
    """Registry of slash commands, dispatchable by name or alias."""

    def __init__(self, workspace: str | Path | None = None) -> None:
        from pathlib import Path as _P

        self.commands: dict[str, SlashCommand] = {}
        self.canonical: list[SlashCommand] = []
        for cmd in (
            HelpCommand(), ClearCommand(), ExitCommand(), ModelsCommand(), VisualCommand(),
            AuditCommand(), StatsCommand(), PlanCommand(), ApproveCommand(), RejectCommand(),
            CheckpointCommand(), RestoreCommand(), CheckpointsCommand(), VersionCommand(),
        ):
            self.commands[cmd.name] = cmd
            self.canonical.append(cmd)
            for alias in cmd.aliases:
                self.commands[alias] = cmd
        # custom prompt commands from .sick/commands/*.md (workspace + home)
        try:
            ws = _P(workspace) if workspace else _P.cwd()
            for pc in _load_prompt_commands(ws):
                if pc.name in self.commands:
                    continue
                self.commands[pc.name] = pc
                self.canonical.append(pc)
        except Exception:
            pass

    async def dispatch(self, app: SickApp, line: str) -> str | None:
        parts = line[1:].strip().split(maxsplit=1)
        if not parts or not parts[0]:
            return "unknown command — try `/help`"
        name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        cmd = self.commands.get(name)
        if not cmd:
            # fuzzy suggest
            try:
                import difflib

                sug = difflib.get_close_matches(name, self.commands.keys(), n=1, cutoff=0.6)
                if sug:
                    return f"unknown command `/{name}` — did you mean `/{sug[0]}`? try `/help`"
            except Exception:
                pass
            return f"unknown command `/{name}` — try `/help`"
        try:
            return await cmd.run(app, args)
        except Exception as e:
            return f"[error: {e}]"